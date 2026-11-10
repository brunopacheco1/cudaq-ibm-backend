# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""M3 check: which CUDA-Q targets drop idle qubits from `sample` when the
kernel has no `mz`?

On the simulator, and on quantinuum, ionq, infleqtion and braket in
emulation, a 4-qubit kernel gives 4 bits. On oqc and anyon in emulation it
gives 2: the two qubits the kernel never touches are gone. Their pipelines
run `dqe` before routing, as ours does, so the `ibm` target behaves like
them (docs/m3-spec.md, section 2.11).

This is allowed, not a bug: the CUDA-Q specification says a qubit the kernel
allocates but does not use "may not appear in the implicit measurement
results" (docs/sphinx/specification/cudaq/algorithmic_primitives.rst, note
after the `__global__` register rules, tag 0.16.0).

Result with cudaq 0.16.0 and 0.16.0.post1:

    simulator   no mz: { 0101:10 }   with mz: { 0101:10 }
    quantinuum  no mz: { 0101:10 }   with mz: { 0101:10 }
    ionq        no mz: { 0101:10 }   with mz: { 0101:10 }
    infleqtion  no mz: { 0101:10 }   with mz: { 0101:10 }
    braket      no mz: { 0101:10 }   with mz: { 0101:10 }
    oqc         no mz: { 11:10 }     with mz: { 0101:10 }
    anyon       no mz: { 11:10 }     with mz: { 0101:10 }

Needs: pip install cudaq==0.16.0
Run:   python experiments/m3_idle_qubit.py
"""

import warnings

warnings.filterwarnings("ignore")

import cudaq  # noqa: E402


@cudaq.kernel
def no_mz():
    q = cudaq.qvector(4)
    x(q[1])
    x(q[3])  # q[0] and q[2] are never touched


@cudaq.kernel
def with_mz():
    q = cudaq.qvector(4)
    x(q[1])
    x(q[3])
    mz(q)


def counts(kernel) -> str:
    return str(cudaq.sample(kernel, shots_count=10)).strip()


def main() -> None:
    print(f"{'simulator':11s} no mz: {counts(no_mz)}   with mz: {counts(with_mz)}")
    for target in ("quantinuum", "ionq", "infleqtion", "braket", "oqc", "anyon"):
        try:
            cudaq.set_target(target, emulate=True)
            print(f"{target:11s} no mz: {counts(no_mz)}   "
                  f"with mz: {counts(with_mz)}")
        except Exception as e:  # noqa: BLE001
            print(f"{target:11s} failed: {str(e).splitlines()[0][:100]}")
        cudaq.reset_target()


if __name__ == "__main__":
    main()
