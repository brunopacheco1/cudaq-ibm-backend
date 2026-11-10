# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""How the kernel EVERY_GATE of tests/run_fake_ibm_results.py was picked.

The result checks compare the outcome distribution of a kernel on CUDA-Q's
simulator with the one the plugin returns. That only finds a wrong gate rule
if the mistake changes the distribution of that kernel. A first kernel,
written by hand, did not: with a wrong `ry` rule in the plugin (an extra y
before each ry) its two ry gates cancelled the fault and the check passed.

This script scores a kernel by the smallest change any single planted fault
makes, and searches random kernels for a good score. A fault is applied to
every gate of one kind:

    drop        the gate is left out
    X, Y, Z     an extra Pauli gate right before it (on its last qubit)
    neg, half   for gates with angles: the sign flipped, or half the angle

The score also asks that the distribution is far from its own mirror image
(so a reversed bit order shows) and that no outcome is rare (so shot noise
stays small against the changes).

Needs Qiskit (in the Mac .venv, not in the CUDA-Q container):

    python3 experiments/m4_test_kernel_search.py

Run 2026-11-10: the kernel printed at the end has worst fault 0.117
(a dropped t), mirror distance 0.28, rarest outcome 4.2%. The two kernels
used before score 0.0.
"""

import random
import sys
from pathlib import Path

import numpy as np
from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector

sys.path.insert(0, str(Path(__file__).parent.parent / "tests"))
import run_fake_ibm_results as checks  # noqa: E402

ONE = ("x", "y", "z", "h", "s", "t", "sdg", "tdg")
ROTATIONS = ("rx", "ry", "rz", "r1")
TWO = ("cx", "cz", "swap")


def probabilities(n: int, ops: list[tuple], fault=None) -> np.ndarray:
    """Exact outcome probabilities of a kernel, with one kind of gate made
    wrong: fault = (gate name, kind)."""
    circuit = QuantumCircuit(n)
    for name, *args in ops:
        kind = fault[1] if fault is not None and fault[0] == name else None
        if kind == "drop":
            continue
        if kind in ("X", "Y", "Z"):
            getattr(circuit, kind.lower())(args[-1])
        if name in ROTATIONS or name == "u3":
            angles = list(args[:-1])
            if kind == "neg":
                angles = [-a for a in angles]
            if kind == "half":
                angles = [a / 2 for a in angles]
            if name == "r1":
                circuit.p(angles[0], args[-1])
            elif name == "u3":
                circuit.u(*angles, args[-1])
            else:
                getattr(circuit, name)(angles[0], args[-1])
        else:
            getattr(circuit, name)(*args)
    return Statevector(circuit).probabilities()


def distance(a: np.ndarray, b: np.ndarray) -> float:
    return 0.5 * float(np.abs(a - b).sum())


def faults(ops: list[tuple]) -> list[tuple[str, str]]:
    found = []
    for name in sorted({op[0] for op in ops}):
        found += [(name, kind) for kind in ("X", "Y", "Z", "drop")]
        if name in ROTATIONS or name == "u3":
            found += [(name, "neg"), (name, "half")]
    return found


def score(n: int, ops: list[tuple]):
    """(smallest change, the fault that makes it), mirror distance, rarest
    outcome."""
    base = probabilities(n, ops)
    worst = min((distance(base, probabilities(n, ops, f)), f)
                for f in faults(ops))
    mirror = distance(base, base.reshape([2] * n).transpose().reshape(-1))
    return worst, mirror, float(base.min())


def random_kernel(rng: random.Random, n: int) -> list[tuple]:
    def angle() -> float:
        return round(rng.uniform(0.4, 2.6) * rng.choice((1, -1)), 1)

    names = list(ONE + ROTATIONS + TWO) + ["u3"]
    rng.shuffle(names)
    names += [rng.choice(ROTATIONS + TWO) for _ in range(4)]
    # Start with a rotation on every qubit, so that no gate acts on a plain
    # 0, where an extra z would never show.
    ops: list[tuple] = [("ry", 1.1, 0), ("rx", 0.7, 1), ("ry", -1.9, 2)]
    for name in names:
        if name in ONE:
            ops.append((name, rng.randrange(n)))
        elif name in ROTATIONS:
            ops.append((name, angle(), rng.randrange(n)))
        elif name == "u3":
            ops.append(("u3", angle(), angle(), angle(), rng.randrange(n)))
        else:
            ops.append((name, *rng.sample(range(n), 2)))
    return ops


def main() -> None:
    for label, n, ops in (("GATE_RULES", 2, checks.GATE_RULES),
                          ("EVERY_GATE", 3, checks.EVERY_GATE)):
        (change, fault), mirror, rarest = score(n, ops)
        print(f"{label}: worst fault {change:.3f} {fault}, mirror "
              f"{mirror:.3f}, rarest outcome {rarest:.4f}")

    rng = random.Random(7)
    best = None
    for _ in range(4000):
        ops = random_kernel(rng, 3)
        (change, fault), mirror, rarest = score(3, ops)
        value = min(change, mirror / 2, rarest * 5)
        if best is None or value > best[0]:
            best = (value, change, fault, mirror, rarest, ops)
    _, change, fault, mirror, rarest, ops = best
    print(f"best of 4000: worst fault {change:.3f} {fault}, mirror "
          f"{mirror:.3f}, rarest outcome {rarest:.4f}")
    print(ops)


if __name__ == "__main__":
    main()
