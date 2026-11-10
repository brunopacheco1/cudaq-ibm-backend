# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""Tests for tests/isa_simulator.py, in the order its functions are written.

Run one group at a time while you write the simulator:

    pytest tests/test_isa_simulator.py -k parse     # the plumbing, passes already
    pytest tests/test_isa_simulator.py -k step1     # zero_state
    ...
    pytest tests/test_isa_simulator.py -k step8     # sample
    pytest tests/test_isa_simulator.py              # everything

The last group compares the whole simulator with Qiskit on random circuits.
Qiskit numbers basis states the same way (bit k of the index is qubit k).
"""

import math

import numpy as np
import pytest

from tests import isa_simulator as sim
from tests.isa_simulator import Circuit, Gate

HEADER = 'OPENQASM 3.0;\ninclude "stdgates.inc";\n'
SQRT_HALF = 1 / math.sqrt(2)
# Hadamard out of native gates (the rule of M2): rz(pi/2) sx rz(pi/2).
H = (("rz", math.pi / 2), ("sx", None), ("rz", math.pi / 2))


def circuit(n: int, gates: list[Gate], measures: dict[int, int] | None = None,
            n_bits: int | None = None) -> Circuit:
    measures = {k: k for k in range(n)} if measures is None else measures
    n_bits = (max(measures) + 1 if measures else 0) if n_bits is None else n_bits
    return Circuit(tuple(range(n)), tuple(gates), measures, n_bits)


def h_gates(qubit: int) -> list[Gate]:
    return [Gate(name, (qubit,), angle) for name, angle in H]


def same_up_to_phase(a: np.ndarray, b: np.ndarray) -> bool:
    """Two states are the same physics if they differ by one global phase."""
    k = int(np.argmax(np.abs(b)))
    if abs(a[k]) < 1e-9:
        return False
    return np.allclose(a * (b[k] / a[k]), b, atol=1e-9)


# ---- the plumbing ---------------------------------------------------------


def test_parse_renumbers_ibm_qubits_from_zero():
    c = sim.parse(HEADER + "bit[2] c;\nrz(1.5e+00) $62;\nsx $62;\nx $76;\n"
                  "cz $62, $76;\nc[0] = measure $62;\nc[1] = measure $76;\n")
    assert c.qubits == (62, 76) and c.n_qubits == 2 and c.n_bits == 2
    assert c.gates == (Gate("rz", (0,), 1.5), Gate("sx", (0,)), Gate("x", (1,)),
                       Gate("cz", (0, 1)))
    assert c.measures == {0: 0, 1: 1}


def test_parse_refuses_what_ibm_would_not_run():
    with pytest.raises(ValueError, match="cannot simulate"):
        sim.parse(HEADER + "bit[1] c;\nh $0;\nc[0] = measure $0;\n")
    with pytest.raises(ValueError, match="after a measurement"):
        sim.parse(HEADER + "bit[1] c;\nc[0] = measure $0;\nx $0;\n")


# ---- step 1: zero_state ---------------------------------------------------


def test_step1_zero_state_has_one_amplitude():
    for n in (1, 2, 5):
        state = sim.zero_state(n)
        assert state.shape == (2 ** n,)
        assert np.iscomplexobj(state)
        assert state[0] == 1 and np.count_nonzero(state) == 1


# ---- step 2: gate_matrix --------------------------------------------------


def test_step2_x_swaps_zero_and_one():
    assert np.allclose(sim.gate_matrix("x"), [[0, 1], [1, 0]])


def test_step2_sx_twice_is_x():
    sx = sim.gate_matrix("sx")
    assert np.allclose(sx @ sx, sim.gate_matrix("x"))


def test_step2_rz_is_diagonal_with_opposite_phases():
    theta = 0.7
    rz = sim.gate_matrix("rz", theta)
    assert np.allclose(rz, np.diag([np.exp(-0.5j * theta), np.exp(0.5j * theta)]))
    assert np.allclose(sim.gate_matrix("rz", 0.0), np.eye(2))


def test_step2_every_gate_is_unitary():
    for matrix in (sim.gate_matrix("x"), sim.gate_matrix("sx"),
                   sim.gate_matrix("rz", -2.1)):
        assert np.allclose(matrix @ matrix.conj().T, np.eye(2))


def test_step2_unknown_gate_is_refused():
    with pytest.raises(ValueError):
        sim.gate_matrix("h")


# ---- step 3: apply_gate ---------------------------------------------------


def test_step3_x_on_each_qubit_sets_that_bit():
    # Bit k of the index is qubit k: x on qubit k of |000> gives index 2**k.
    for qubit in range(3):
        state = sim.apply_gate(sim.zero_state(3), sim.gate_matrix("x"), qubit)
        assert np.isclose(state[1 << qubit], 1) and np.count_nonzero(state) == 1


def test_step3_does_not_change_its_input():
    start = sim.zero_state(2)
    sim.apply_gate(start, sim.gate_matrix("x"), 0)
    assert start[0] == 1 and np.count_nonzero(start) == 1


def test_step3_gates_on_different_qubits_commute():
    x, sx = sim.gate_matrix("x"), sim.gate_matrix("sx")
    one = sim.apply_gate(sim.apply_gate(sim.zero_state(3), sx, 0), x, 2)
    two = sim.apply_gate(sim.apply_gate(sim.zero_state(3), x, 2), sx, 0)
    assert np.allclose(one, two)


def test_step3_hadamard_from_native_gates():
    state = sim.zero_state(2)
    for name, angle in H:
        state = sim.apply_gate(state, sim.gate_matrix(name, angle), 1)
    # Qubit 1 is in (|0> + |1>)/sqrt(2), qubit 0 still 0: indexes 0b00 and 0b10.
    assert same_up_to_phase(state, np.array([SQRT_HALF, 0, SQRT_HALF, 0]))


# ---- step 4: apply_cz -----------------------------------------------------


def test_step4_cz_flips_the_sign_of_11_only():
    state = np.array([0.5, 0.5, 0.5, 0.5], dtype=complex)
    assert np.allclose(sim.apply_cz(state, 0, 1), [0.5, 0.5, 0.5, -0.5])


def test_step4_cz_is_symmetric_and_picks_the_right_bits():
    rng = np.random.default_rng(1)
    state = rng.normal(size=8) + 1j * rng.normal(size=8)
    out = sim.apply_cz(state, 0, 2)
    assert np.allclose(out, sim.apply_cz(state, 2, 0))
    expected = state.copy()
    expected[[0b101, 0b111]] *= -1    # qubit 0 and qubit 2 are both 1
    assert np.allclose(out, expected)


# ---- step 5: run ----------------------------------------------------------


def test_step5_bell_pair_from_native_gates():
    # cx(0 -> 1) = h on the target, cz, h on the target.
    gates = h_gates(0) + h_gates(1) + [Gate("cz", (0, 1))] + h_gates(1)
    state = sim.run(circuit(2, gates))
    assert same_up_to_phase(state, np.array([SQRT_HALF, 0, 0, SQRT_HALF]))


def test_step5_empty_circuit_stays_zero():
    assert np.allclose(sim.run(circuit(3, [])), sim.zero_state(3))


# ---- step 6: probabilities ------------------------------------------------


def test_step6_born_rule():
    state = np.array([0.6, 0.8j, 0, 0])
    p = sim.probabilities(state)
    assert np.allclose(p, [0.36, 0.64, 0, 0])
    assert not np.iscomplexobj(p)


# ---- step 7: classical_value ----------------------------------------------


def test_step7_measure_all_in_order_is_the_index():
    assert sim.classical_value(0b101, {0: 0, 1: 1, 2: 2}) == 0b101


def test_step7_docstring_example():
    assert sim.classical_value(0b011, {0: 2, 1: 0}) == 0b10


def test_step7_unmeasured_qubits_and_unwritten_bits():
    # Only qubit 1 is measured, into c[3]. Qubit 0 being 1 must not show.
    assert sim.classical_value(0b11, {3: 1}) == 0b1000
    assert sim.classical_value(0b01, {3: 1}) == 0


# ---- step 8: sample -------------------------------------------------------


def test_step8_a_fixed_outcome_comes_back_every_time():
    # x on qubits 0 and 2 of three, all measured in order: c = 0b101 = 0x5.
    c = circuit(3, [Gate("x", (0,)), Gate("x", (2,))])
    assert sim.sample(c, 20, np.random.default_rng(0)) == ["0x5"] * 20


def test_step8_bell_pair_gives_only_00_and_11_about_half_each():
    gates = h_gates(0) + h_gates(1) + [Gate("cz", (0, 1))] + h_gates(1)
    shots = sim.sample(circuit(2, gates), 4000, np.random.default_rng(3))
    assert set(shots) == {"0x0", "0x3"}
    assert 1800 < shots.count("0x3") < 2200


def test_step8_same_seed_same_shots():
    c = circuit(1, h_gates(0))
    assert (sim.sample(c, 50, np.random.default_rng(5))
            == sim.sample(c, 50, np.random.default_rng(5)))


def test_step8_measurements_out_of_order():
    # x on qubit 0 only; c[0] reads qubit 1 and c[1] reads qubit 0.
    c = circuit(2, [Gate("x", (0,))], measures={0: 1, 1: 0})
    assert sim.sample(c, 5, np.random.default_rng(0)) == ["0x2"] * 5


# ---- all together, against Qiskit -----------------------------------------


def random_gates(rng: np.random.Generator, n: int, count: int) -> list[Gate]:
    gates = []
    for _ in range(count):
        kind = rng.choice(["rz", "sx", "x", "cz"])
        if kind == "cz" and n > 1:
            a, b = rng.choice(n, size=2, replace=False)
            gates.append(Gate("cz", (int(a), int(b))))
        elif kind == "rz":
            gates.append(Gate("rz", (int(rng.integers(n)),),
                              float(rng.uniform(-math.pi, math.pi))))
        else:
            gates.append(Gate("sx" if kind == "cz" else str(kind),
                              (int(rng.integers(n)),)))
    return gates


def test_whole_simulator_agrees_with_qiskit_on_random_circuits():
    qiskit = pytest.importorskip("qiskit")
    from qiskit.quantum_info import Statevector

    rng = np.random.default_rng(2026)
    for case in range(40):
        n = int(rng.integers(1, 6))
        gates = random_gates(rng, n, 30)
        reference = qiskit.QuantumCircuit(n)
        for gate in gates:
            if gate.name == "rz":
                reference.rz(gate.angle, gate.qubits[0])
            else:
                getattr(reference, gate.name)(*gate.qubits)
        expected = Statevector(reference).data
        got = sim.run(circuit(n, gates))
        # sx in Qiskit and here are the same matrix, so even the global
        # phase must agree.
        assert np.allclose(got, expected, atol=1e-9), f"case {case}: {gates}"
