# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""Expectation values on the `ibm` target, from sample counts.

`cudaq.observe` is not supported on the `ibm` target yet (docs/architecture.md
§8 item 7). This example shows what `observe` does under the hood, with
`cudaq.sample` only: it measures <ZZ>, <XX> and <YY> of a Bell pair.

Why these three numbers? A Bell pair gives 00 or 11, half each. So does a
coin that is flipped once and copied to both qubits. Measured along Z the two
look the same: <ZZ> = 1. Measured along X they differ: the Bell pair gives
<XX> = 1, the copied coin gives <XX> = 0. Entanglement shows in the second
basis, not in the first.

    python examples/expectation_from_samples.py                # simulator
    python examples/expectation_from_samples.py --target ibm --backend ibm_fez \\
        --yes-spend-qpu-time                                   # real chip

The second form sends three jobs to IBM and spends QPU time. It needs
IBM_QUANTUM_API_KEY and IBM_QUANTUM_CRN in the environment.

The file has two parts. The plumbing (arguments, targets, printing) is done.
The four functions marked "yours" are Bruno's, in the order the tests in
tests/test_expectation_example.py check them:

    pytest tests/test_expectation_example.py -k step1
"""

import argparse
import math

import cudaq

# The terms measured below, and what an ideal Bell pair (|00> + |11>)/sqrt(2)
# gives for each.
IDEAL = {"zz": 1.0, "xx": 1.0, "yy": -1.0}


# --------------------------------------------------------------------------
# The quantum part: yours, Bruno. Replace each `raise NotImplementedError`.
# --------------------------------------------------------------------------


def parity(bits: str) -> int:
    """Step 1. The value one shot gives for a product of Z operators.

    Measuring Z on one qubit gives +1 for the outcome 0 and -1 for the
    outcome 1. A product such as ZZ multiplies the values of its qubits.
    `bits` is one outcome as CUDA-Q prints it, such as "01" or "110".
    Return +1 or -1.

    Question to answer first: why does only the number of 1s matter, and
    not where they are?
    """
    raise NotImplementedError


def expectation(counts: dict[str, int]) -> float:
    """Step 2. The expectation value: the average of `parity` over all shots.

    `counts` maps each outcome to how often it came, such as
    {"00": 495, "11": 449, "01": 39, "10": 17}. The result lies between -1
    and +1.
    """
    raise NotImplementedError


def standard_error(counts: dict[str, int]) -> float:
    """Step 3. How far the measured average can be from the true value just
    because the number of shots is finite (one standard deviation).

    Every shot gives +1 or -1. If the true average is E, the spread of one
    shot is sqrt(1 - E**2), and the average of N shots is sqrt(N) times more
    precise: sqrt((1 - E**2) / N). Use the measured average for E.

    Check you can explain: why is the error 0 when every shot agrees, and
    largest when the average is 0?
    """
    raise NotImplementedError


def measure_in(kernel, qubits, basis: str) -> None:
    """Step 4. Add to `kernel` the measurement of `qubits` in `basis`.

    `basis` has one letter per qubit, "x", "y" or "z": "zz" measures both
    qubits along Z, "xx" both along X, "zx" the first along Z and the second
    along X. Raise ValueError for any other letter.

    The chip can only measure along Z (that is `kernel.mz`). To measure
    along another axis, first turn that axis onto Z with gates, then
    measure. You know which gate turns X into Z from the M2 rules and the
    Bloch Gate Stepper; Y needs one gate more.

    Gates are added with `kernel.h(qubits[k])`, `kernel.sdg(qubits[k])`,
    `kernel.s(qubits[k])` and so on; finish with `kernel.mz(qubits)`.
    """
    raise NotImplementedError


# --------------------------------------------------------------------------
# Plumbing: the Bell pair, the target and the report. Done.
# --------------------------------------------------------------------------


def bell_kernel(basis: str):
    """A kernel that makes (|00> + |11>)/sqrt(2) and measures it in `basis`."""
    kernel = cudaq.make_kernel()
    qubits = kernel.qalloc(2)
    kernel.h(qubits[0])
    kernel.cx(qubits[0], qubits[1])
    measure_in(kernel, qubits, basis)
    return kernel


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", default="qpp-cpu",
                        help="qpp-cpu (simulator, default) or ibm")
    parser.add_argument("--backend", default="ibm_fez",
                        help="IBM backend, with --target ibm")
    parser.add_argument("--shots", type=int, default=1000)
    parser.add_argument("--yes-spend-qpu-time", action="store_true",
                        help="needed with --target ibm: three real jobs")
    args = parser.parse_args()

    if args.target == "ibm":
        if not args.yes_spend_qpu_time:
            raise SystemExit("--target ibm sends three jobs to IBM and "
                             "spends QPU time. Add --yes-spend-qpu-time.")
        cudaq.set_target("ibm", backend=args.backend)
    else:
        cudaq.set_target(args.target)

    print(f"Bell pair on {args.target}, {args.shots} shots per term")
    measured = {}
    for basis, ideal in IDEAL.items():
        counts = dict(cudaq.sample(bell_kernel(basis),
                                   shots_count=args.shots).items())
        measured[basis] = expectation(counts)
        print(f"  <{basis.upper()}> = {measured[basis]:+.3f} "
              f"+- {standard_error(counts):.3f}   (ideal {ideal:+.0f})   "
              f"{counts}")
    # For a Bell pair the three numbers give the fidelity: how much of the
    # measured state is the ideal one (1 = perfect, 0.5 = a copied coin).
    fidelity = (1 + measured["zz"] + measured["xx"] - measured["yy"]) / 4
    error = math.sqrt(sum(1 - value ** 2 for value in measured.values())
                      / args.shots) / 4
    print(f"  fidelity with the ideal Bell pair = {fidelity:.3f} "
          f"+- {error:.3f}")


if __name__ == "__main__":
    main()
