# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""A small statevector simulator for the circuits the plugin sends to IBM.

The fake IBM server (tests/fake_ibm_server.py) uses it to answer a job with
real samples, so the tests can check results and not only that the gates are
allowed (docs/m4-spec.md, decision D4).

It only knows what an IBM Heron chip knows: the gates rz, sx, x and cz, and
measurements at the end. No noise.

Conventions, used by every function below and by the tests:

- The simulator only keeps the qubits a circuit touches. A circuit on IBM
  qubits $61, $62 and $76 has 3 simulator qubits, numbered 0, 1, 2 in that
  order (`Circuit.qubits` remembers the IBM numbers).
- The state of n qubits is a numpy array of 2**n complex numbers, the
  amplitudes. Amplitude number i belongs to the basis state whose bits are
  the binary digits of i, and **bit k of i is the value of qubit k**
  (`(i >> k) & 1`). So with 3 qubits, i = 1 = 0b001 means "qubit 0 is 1, the
  others are 0". This is the order Qiskit and IBM use.
- A measurement `c[j] = measure $q;` copies the value of that qubit into
  classical bit j. IBM returns each shot as one hex number whose bit j is
  c[j] (docs/architecture.md, section 3.5).

The file has two parts. The plumbing (reading the OpenQASM 3 text) is done.
The quantum part is yours, Bruno: eight small functions, in the order the
tests in tests/test_isa_simulator.py check them. Run one group at a time:

    pytest tests/test_isa_simulator.py -k step1
"""

import re
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class Gate:
    """One gate. `qubits` are simulator qubits (not IBM numbers)."""
    name: str                    # "rz", "sx", "x" or "cz"
    qubits: tuple[int, ...]      # one qubit, or two for cz
    angle: float | None = None   # only for rz, in radians


@dataclass(frozen=True)
class Circuit:
    """A circuit as the plugin sends it, with qubits renumbered from 0."""
    qubits: tuple[int, ...]              # qubits[k] = IBM number of simulator qubit k
    gates: tuple[Gate, ...]
    measures: dict[int, int] = field(default_factory=dict)  # classical bit j -> simulator qubit
    n_bits: int = 0                      # size of the classical register c

    @property
    def n_qubits(self) -> int:
        return len(self.qubits)


# --------------------------------------------------------------------------
# Plumbing: OpenQASM 3 text -> Circuit. Done; nothing to fill in here.
# --------------------------------------------------------------------------

_RZ = re.compile(r"^rz\(([-+0-9.eE]+)\) \$(\d+);$")
_ONE = re.compile(r"^(sx|x) \$(\d+);$")
_CZ = re.compile(r"^cz \$(\d+), \$(\d+);$")
_MEASURE = re.compile(r"^c\[(\d+)\] = measure \$(\d+);$")
_BITS = re.compile(r"^bit\[(\d+)\] c;$")
_QUBIT = re.compile(r"\$(\d+)")
_HEADER = ("OPENQASM 3.0;", 'include "stdgates.inc";')


def parse(qasm3: str) -> Circuit:
    """Read the OpenQASM 3 the plugin sends. Raises ValueError on any line
    that is not a native gate, a measurement or the header, and on a gate
    after a measurement of the same qubit (the simulator measures at the
    end)."""
    lines = [line.strip() for line in qasm3.strip().splitlines() if line.strip()]
    ibm_qubits = sorted({int(q) for line in lines for q in _QUBIT.findall(line)})
    index = {q: k for k, q in enumerate(ibm_qubits)}
    gates: list[Gate] = []
    measures: dict[int, int] = {}
    n_bits = 0
    for line in lines:
        if line in _HEADER:
            continue
        if found := _BITS.match(line):
            n_bits = int(found[1])
            continue
        if found := _MEASURE.match(line):
            measures[int(found[1])] = index[int(found[2])]
            continue
        if found := _RZ.match(line):
            gate = Gate("rz", (index[int(found[2])],), float(found[1]))
        elif found := _ONE.match(line):
            gate = Gate(found[1], (index[int(found[2])],))
        elif found := _CZ.match(line):
            gate = Gate("cz", (index[int(found[1])], index[int(found[2])]))
        else:
            raise ValueError(f"cannot simulate this line: {line!r}")
        if set(gate.qubits) & set(measures.values()):
            raise ValueError(f"gate after a measurement: {line!r}")
        gates.append(gate)
    if any(bit >= n_bits for bit in measures):
        raise ValueError("a measurement writes outside the register c")
    return Circuit(tuple(ibm_qubits), tuple(gates), measures, n_bits)


# --------------------------------------------------------------------------
# The quantum part: yours, Bruno. Replace each `raise NotImplementedError`.
# --------------------------------------------------------------------------


def zero_state(n_qubits: int) -> np.ndarray:
    """Step 1. The state "every qubit is 0": 2**n complex amplitudes, all 0
    except one.

    Question to answer first: which index i is the basis state 00...0?
    """
    raise NotImplementedError


def gate_matrix(name: str, angle: float | None = None) -> np.ndarray:
    """Step 2. The 2x2 complex matrix of a one-qubit native gate.

    `name` is "x", "sx" or "rz"; `angle` (radians) is used by rz only.
    Raise ValueError for any other name.

    You know these matrices from M2: they are in
    plugin/tests/test_qasm2_to_isa.cpp (xM, sxM, rzM) and in the Bloch Gate
    Stepper. Rows and columns are in the order |0>, |1>.

    Check you can explain: why does sx applied twice equal x?
    """
    raise NotImplementedError


def apply_gate(state: np.ndarray, matrix: np.ndarray, qubit: int) -> np.ndarray:
    """Step 3. Apply a one-qubit gate to `qubit`; return the new state.

    The idea: a gate on qubit k never mixes amplitudes whose other bits
    differ. The amplitudes come in pairs (i0, i1) that are equal in every
    bit except bit k, where i0 has 0 and i1 has 1. For each pair:

        new[i0], new[i1] = matrix @ (old[i0], old[i1])

    There are 2**(n-1) such pairs. A loop over them is fine (the circuits
    are small); numpy's reshape can do it without a loop if you like.
    Do not change `state` in place: return a new array.
    """
    raise NotImplementedError


def apply_cz(state: np.ndarray, a: int, b: int) -> np.ndarray:
    """Step 4. Apply cz to qubits `a` and `b`; return the new state.

    cz does one thing: it multiplies by -1 every amplitude whose index has
    both bit a and bit b set. Nothing else changes.

    Check you can explain: why does it not matter which of the two qubits
    is called the control?
    """
    raise NotImplementedError


def run(circuit: Circuit) -> np.ndarray:
    """Step 5. Start from zero_state and apply every gate of the circuit in
    order. Return the final state (measurements are not applied here)."""
    raise NotImplementedError


def probabilities(state: np.ndarray) -> np.ndarray:
    """Step 6. The Born rule: the probability of finding basis state i is
    the squared size of amplitude i. Returns 2**n real numbers that sum
    to 1."""
    raise NotImplementedError


def classical_value(index: int, measures: dict[int, int]) -> int:
    """Step 7. What the classical register c holds when the qubits were
    found in basis state `index`.

    `measures[j] = k` means "classical bit j is the value of qubit k".
    Bit j of the result is c[j]. A classical bit no measurement writes
    stays 0, and a qubit nobody measures does not appear.

    Example: 3 qubits found as index 0b011 (qubits 0 and 1 are 1), with
    measures {0: 2, 1: 0}: c[0] = qubit 2 = 0, c[1] = qubit 0 = 1, so the
    result is 0b10 = 2.
    """
    raise NotImplementedError


def sample(circuit: Circuit, shots: int, rng: np.random.Generator) -> list[str]:
    """Step 8. Run the circuit and measure it `shots` times.

    Each shot: pick a basis state at random with the probabilities of the
    final state (rng.choice can do all shots at once), then turn it into
    the register value with classical_value.

    Returns one string per shot in IBM's format: Python's hex(), such as
    "0x0", "0x3", "0x1f".
    """
    raise NotImplementedError
