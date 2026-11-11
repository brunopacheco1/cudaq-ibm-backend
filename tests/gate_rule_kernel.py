# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""A kernel with ONE certain answer that shows a wrong gate rule.

Ten qubits, no two-qubit gate. Each qubit runs a few one-qubit gates that
must end in a known bit, so the whole kernel has exactly one right answer.
A wrong rewrite rule for rx, ry, z or y (plugin/Qasm2ToIsa.h) turns at least
one of these bits into a coin flip or flips it. On real hardware that is
easy to tell from noise: noise costs a qubit a few percent, a wrong rule
costs it half of its shots or all of them.

Why two qubits per gate: one input state cannot show every mistake. A gate
that is wrong by a Z does nothing visible to a qubit in 0, and one that is
wrong by an X does nothing visible to a qubit in + (the state after h). So
each gate is used once on 0 and once on a state on the equator.

The helper gates h, x and sdg already ran on hardware (M2, M3, M4). u3 does
not reach the plugin as u3 from a builder kernel: CUDA-Q splits it into
rz, rx, rz first, so the two u3 qubits check that split and the rx rule
again.

How the sequences were found, and the proof that they catch wrong rules:
experiments/hardware_gate_kernel_search.py and
experiments/plant_rule_faults.py.

Used by tests/run_fake_ibm_results.py (free, in CI) and by
tests/run_ibm_hardware_gates.py (real hardware). This file has no side
effects, so both can import it.
"""

import math

PI = math.pi

# (what the qubit checks, the bit it must give, its gates in circuit order)
CASES = [
    # Two quarter turns around X make a half turn: 0 -> 1.
    ("rx, twice a quarter turn", 1, [("rx", PI / 2), ("rx", PI / 2)]),
    # h, sdg puts the qubit on the -Y axis; three quarter turns around X
    # bring it up to 0. With the sign of the angle wrong it ends in 1.
    ("rx, from the Y axis", 0, [("h",), ("sdg",), ("rx", 3 * PI / 2)]),
    ("ry, twice a quarter turn", 1, [("ry", PI / 2), ("ry", PI / 2)]),
    # Three quarter turns around Y end on the -X axis, which h reads as 1.
    # With the sign wrong it is +X, read as 0.
    ("ry, then h", 1, [("ry", 3 * PI / 2), ("h",)]),
    # z must leave 0 alone ...
    ("z on 0", 0, [("z",)]),
    # ... and turn + into -: h, z, h is an x.
    ("z on +", 1, [("h",), ("z",), ("h",)]),
    ("y on 0", 1, [("y",)]),
    ("y on +", 1, [("h",), ("y",), ("h",)]),
    ("u3, twice", 1, [("u3", PI / 2, PI / 4, PI / 2), ("sdg",),
                      ("u3", PI / 2, PI / 2, PI / 4)]),
    ("u3, from +", 0, [("h",), ("u3", 3 * PI / 4, PI / 2, PI / 2), ("sdg",),
                       ("x",), ("u3", 3 * PI / 2, PI / 4, PI / 2)]),
]

EXPECTED = "".join(str(bit) for _, bit, _ in CASES)   # qubit 0 first


def ops() -> list[tuple]:
    """The kernel as data, in the form tests/run_fake_ibm_results.py uses:
    (gate, angles..., qubit)."""
    return [(gate[0], *gate[1:], k)
            for k, (_, _, gates) in enumerate(CASES) for gate in gates]


def build(cudaq):
    """The CUDA-Q kernel: one qubit per entry of CASES, then mz on all."""
    kernel = cudaq.make_kernel()
    q = kernel.qalloc(len(CASES))
    for name, *args in ops():
        *angles, k = args
        getattr(kernel, name)(*angles, q[k])
    kernel.mz(q)
    return kernel


def share_per_qubit(counts: dict[str, int]) -> list[float]:
    """For each qubit, the share of shots that gave its expected bit."""
    shots = sum(counts.values())
    return [sum(n for bits, n in counts.items() if bits[k] == want) / shots
            for k, want in enumerate(EXPECTED)]
