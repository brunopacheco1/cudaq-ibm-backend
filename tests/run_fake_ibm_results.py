# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""Check the RESULTS the C++ 'ibm' plugin returns, not only that IBM would
accept its circuits (docs/m4-spec.md, step 2).

Every kernel below runs twice:

    reference:  on CUDA-Q's own simulator (target qpp-cpu), untouched;
    plugin:     through the 'ibm' target against the fake IBM server, which
                simulates the native-gate circuit the plugin sent with
                tests/isa_simulator.py (no noise) and answers with samples.

The two must agree. So this checks, end to end and for physics: the gate
rewrite rules of M2, the routing and qubit choice of M3, and the bit order of
the answer. The two simulators share no code.

Three kinds of kernels:

- x and cx only, at random. Such a circuit has exactly one right answer, and
  it can also be computed with plain bit logic, which this script does as a
  third opinion. Measured in full, in part and out of order, and not at all.
  Some have qubits that no gate touches: each must still give its bit.
- GHZ states: only 00...0 and 11...1 may come out, about half each.
- kernels with rotations: the two outcome distributions must be close.

Run from the repository root, after plugin/build_against_wheel.sh:

    python3 tests/run_fake_ibm_results.py

It starts its own fake server on port 62457 (jobs finish at the first poll,
so a job takes well under a second) and stops it at the end. Nothing here
touches IBM.
"""

import os
import random
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run_token_expiry import start_server, stop_server  # noqa: E402

PORT = 62457
SEED = 2026
SHOTS_EXACT = 200          # for kernels with one right answer
SHOTS = 20000              # for kernels with a distribution
SHOTS_REFERENCE = 200000
# Largest allowed distance between the two distributions (half the sum of the
# differences in probability; 0 = equal, 1 = nothing in common). Pure shot
# noise at these shot counts is about 0.01 for 16 outcomes. A wrong gate rule
# or a wrong bit order moves it far above the limit; each such kernel is
# checked to be far from its own mirror image, so a reversed answer cannot
# pass by symmetry.
MAX_DISTANCE = 0.03
MIN_DISTANCE_FROM_MIRROR = 0.1

os.environ["IBM_QUANTUM_API_KEY"] = "test-key"
os.environ["IBM_QUANTUM_CRN"] = "test-crn"


# ---- kernels --------------------------------------------------------------
# A kernel is described as data, so the same description builds the CUDA-Q
# kernel and, for x/cx circuits, feeds the bit-logic calculation.
# ops: ("x", q), ("cx", control, target), ("h", q), ("rx", angle, q), ...
# measure: None = mz on all qubits; a list = mz on these qubits in this
# order; "none" = no mz in the kernel at all (CUDA-Q then measures all).


def build(cudaq, n: int, ops: list[tuple], measure):
    kernel = cudaq.make_kernel()
    q = kernel.qalloc(n)
    for name, *args in ops:
        if name in ("x", "y", "z", "h", "s", "t", "sdg", "tdg"):
            getattr(kernel, name)(q[args[0]])
        elif name in ("rx", "ry", "rz", "r1"):
            getattr(kernel, name)(args[0], q[args[1]])
        elif name == "u3":
            kernel.u3(args[0], args[1], args[2], q[args[3]])
        elif name in ("cx", "cz", "swap"):
            getattr(kernel, name)(q[args[0]], q[args[1]])
        else:
            raise ValueError(f"unknown gate in a test kernel: {name}")
    if measure is None:
        kernel.mz(q)
    elif measure != "none":
        for k in measure:
            kernel.mz(q[k])
    return kernel


def bit_logic(n: int, ops: list[tuple], measure) -> str:
    """The one right answer of an x/cx circuit, by flipping bits. CUDA-Q
    lists the measured qubits in allocation order, qubit 0 first, whatever
    order mz ran in (decision 0010)."""
    bits = [0] * n
    for name, *args in ops:
        if name == "x":
            bits[args[0]] ^= 1
        else:
            bits[args[1]] ^= bits[args[0]]
    kept = range(n) if measure in (None, "none") else sorted(measure)
    return "".join(str(bits[k]) for k in kept)


def random_x_cx(rng: random.Random, n: int) -> list[tuple]:
    """About 3n gates, and at least one on every qubit (IDLE_CASES has the
    kernels with untouched qubits)."""
    ops: list[tuple] = []
    for _ in range(3 * n):
        if n > 1 and rng.random() < 0.6:
            ops.append(("cx", *rng.sample(range(n), 2)))
        else:
            ops.append(("x", rng.randrange(n)))
    touched = {q for op in ops for q in op[1:]}
    ops += [("x", q) for q in range(n) if q not in touched]
    rng.shuffle(ops)
    return ops


def exact_cases() -> list[tuple]:
    rng = random.Random(SEED)
    cases = []
    for number in range(1, 13):
        n = rng.randint(2, 7)
        ops = random_x_cx(rng, n)
        how = (None, "part", "none")[number % 3]
        if how == "part":
            measure = rng.sample(range(n), rng.randint(1, n - 1))
            label = "mz on q" + ",q".join(map(str, measure))
        else:
            measure = how
            label = "mz on all" if how is None else "no mz"
        cases.append((f"random x/cx {number} ({n} qubits, {label})",
                      n, ops, measure))
    return cases


def ghz(n: int) -> list[tuple]:
    return [("h", 0)] + [("cx", k, k + 1) for k in range(n - 1)]


# Two kernels with rotations.
# GATE_RULES is the second kernel of tests/run_fake_ibm.py: one gate per M2
# rule. EVERY_GATE has every gate CUDA-Q's kernel builder offers for one and
# two qubits. It was picked by a search (experiments/m4_test_kernel_search.py)
# so that a mistake in any single kind of gate shows: a missing gate, a
# wrong sign or half the angle, or an extra x, y or z next to it moves the
# outcome distribution by 0.117 or more, four times MAX_DISTANCE. A kernel
# written by hand did not have that property: two wrong ry gates cancelled
# each other and the result looked right.
GATE_RULES = [("rx", 0.7, 0), ("ry", -2.3, 1), ("z", 0), ("y", 1), ("s", 0),
              ("t", 1), ("u3", 0.3, -1.1, 2.0, 0), ("cx", 1, 0)]
EVERY_GATE = [("ry", 1.1, 0), ("rx", 0.7, 1), ("ry", -1.9, 2), ("tdg", 1),
              ("sdg", 0), ("swap", 0, 1), ("ry", -2.5, 1), ("rz", -1.2, 1),
              ("y", 1), ("z", 1), ("s", 0), ("u3", 0.7, 0.6, 0.9, 1),
              ("cx", 1, 0), ("h", 1), ("cz", 1, 2), ("t", 0),
              ("r1", -1.5, 2), ("x", 2), ("rx", 0.6, 0), ("ry", 1.0, 2),
              ("r1", 1.2, 0), ("rx", -1.7, 1), ("cz", 2, 1)]
DISTRIBUTION_CASES = [
    ("GHZ on q0,q2,q3 with q1 idle", 4,
     [("h", 0), ("cx", 0, 2), ("cx", 2, 3)], None),
    ("every M2 gate rule (2 qubits)", 2, GATE_RULES, None),
    ("every gate of the kernel builder (3 qubits)", 3, EVERY_GATE, None),
    ("every gate, mz on q2,q0 only", 3, EVERY_GATE, [2, 0]),
    ("every gate, no mz", 3, EVERY_GATE, "none"),
]
GHZ_SIZES = (3, 8, 16)
# Qubits no gate touches. With the `dqe` pass in the pipeline (until M4
# step 3) CUDA-Q removed such a qubit and the answer had one bit too few:
# the first kernel below returned 111 instead of 1011 (docs/m4-spec.md F4,
# decision D5).
IDLE_CASES = [
    ("idle q1 (4 qubits, no mz)", 4,
     [("x", 0), ("cx", 0, 2), ("x", 3)], "none"),
    ("idle q1 (4 qubits, mz on all)", 4,
     [("x", 0), ("cx", 0, 2), ("x", 3)], None),
    ("idle q0 and q3 (4 qubits, mz on q3,q1)", 4,
     [("x", 1), ("cx", 1, 2)], [3, 1]),
    ("idle last qubit (3 qubits, no mz)", 3, [("x", 0), ("cx", 0, 1)], "none"),
    ("no gate at all (2 qubits, mz on all)", 2, [], None),
]


# ---- comparing ------------------------------------------------------------


def as_dict(counts) -> dict[str, int]:
    return {bits: count for bits, count in counts.items()}


def distance(a: dict[str, int], b: dict[str, int]) -> float:
    """Total variation distance between two tables of counts."""
    total_a, total_b = sum(a.values()), sum(b.values())
    return 0.5 * sum(abs(a.get(k, 0) / total_a - b.get(k, 0) / total_b)
                     for k in set(a) | set(b))


def mirrored(counts: dict[str, int]) -> dict[str, int]:
    return {bits[::-1]: count for bits, count in counts.items()}


def main() -> int:
    warnings.simplefilter("ignore")
    import cudaq

    exact = exact_cases() + IDLE_CASES
    ghz_cases = [(f"GHZ-{n}", n, ghz(n), None) for n in GHZ_SIZES]
    everything = exact + ghz_cases + DISTRIBUTION_CASES
    kernels = {name: build(cudaq, n, ops, measure)
               for name, n, ops, measure in everything}

    # 1. The reference answers, on CUDA-Q's simulator.
    cudaq.set_target("qpp-cpu")
    cudaq.set_random_seed(SEED)
    reference = {}
    for name, *_ in exact:
        reference[name] = as_dict(cudaq.sample(kernels[name],
                                               shots_count=SHOTS_EXACT))
    for name, *_ in ghz_cases + DISTRIBUTION_CASES:
        reference[name] = as_dict(cudaq.sample(kernels[name],
                                               shots_count=SHOTS_REFERENCE))

    # 2. The same kernels through the plugin and the simulating fake server.
    process, log = start_server(ttl=0, polls=0, port=PORT)
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str) -> None:
        print(("OK:   " if ok else "FAIL: ") + f"{name}: {detail}")
        if not ok:
            failures.append(name)

    try:
        cudaq.register_backend_path("build/external/ibm")
        # Always the localhost urls: without them the plugin talks to IBM.
        cudaq.set_target("ibm",
                         backend="ibm_fake",
                         url=f"http://localhost:{PORT}/api",
                         iam_url=f"http://localhost:{PORT}/identity/token")

        for name, n, ops, measure in exact:
            want = bit_logic(n, ops, measure)
            got = as_dict(cudaq.sample(kernels[name], shots_count=SHOTS_EXACT))
            ok = got == {want: SHOTS_EXACT} == reference[name]
            check(name, ok, f"{want} in every shot" if ok else
                  f"bit logic says {want}, CUDA-Q's simulator "
                  f"{reference[name]}, the plugin {got}")

        for name, n, _, _ in ghz_cases:
            got = as_dict(cudaq.sample(kernels[name], shots_count=SHOTS))
            zeros, ones = got.get("0" * n, 0), got.get("1" * n, 0)
            ok = (zeros + ones == SHOTS and set(reference[name]) == set(got)
                  and abs(zeros - SHOTS / 2) < 0.03 * SHOTS)
            check(name, ok, f"{zeros} x {'0' * n}, {ones} x {'1' * n}" if ok
                  else f"the plugin returned {got}")

        for name, _, _, _ in DISTRIBUTION_CASES:
            got = as_dict(cudaq.sample(kernels[name], shots_count=SHOTS))
            d = distance(got, reference[name])
            from_mirror = distance(reference[name], mirrored(reference[name]))
            if from_mirror < MIN_DISTANCE_FROM_MIRROR:
                check(name, False, "the kernel is too symmetric to show a "
                      f"reversed answer (distance {from_mirror:.3f})")
                continue
            check(name, d <= MAX_DISTANCE,
                  f"distance {d:.4f} from CUDA-Q's simulator (limit "
                  f"{MAX_DISTANCE}; a reversed answer would be "
                  f"{from_mirror:.2f})")
    finally:
        lines = stop_server(process, log)

    if failures:
        print("\nFake server log (last 40 lines):")
        for line in lines[-40:]:
            print("  " + line)
        print(f"\nRESULT: {len(failures)} of {len(everything)} kernels gave "
              "a wrong result.")
        return 1
    print(f"\nRESULT: all {len(everything)} kernels give the same result "
          "through the plugin as on CUDA-Q's simulator.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
