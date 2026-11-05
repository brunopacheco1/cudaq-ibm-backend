"""Step 2: rewrite the circuit so a specific IBM chip can run it ("ISA circuit").

A real chip has two hard limits:

* It runs only a few native gates (for IBM Heron chips: ``cz``, ``rz``,
  ``sx``, ``x``, ``id``). A Hadamard, for example, must be rebuilt from
  ``rz`` and ``sx``.
* A two-qubit gate works only between qubits that are physically wired
  together (the "coupling map"). If the circuit needs qubits 0 and 5 to
  interact and they are not neighbours, the transpiler inserts swaps.

A circuit that respects both limits uses the chip's Instruction Set
Architecture (ISA). IBM rejects jobs whose circuits are not ISA circuits,
so this step is mandatory.

We build the hardware description (a Qiskit ``Target``) from the same JSON
the IBM REST API returns at ``GET /v1/backends/{name}/configuration``.
"""

from __future__ import annotations

from typing import Any, Mapping

import logging

from qiskit import QuantumCircuit, transpile
from qiskit.circuit.library import PhaseGate, RZGate, U1Gate
from qiskit.circuit.library.standard_gates import get_standard_gate_name_mapping
from qiskit.transpiler import CouplingMap, Target

log = logging.getLogger(__name__)


def usable_basis_gates(basis_gates: list[str]) -> list[str]:
    """Keep only the gates we can safely target. This mirrors what IBM's own
    ``qiskit-ibm-runtime`` client does when it builds a Target.

    * **Unknown gates** (for example ``xslow``) are IBM-internal pulse
      variants with no standard Qiskit definition. They are dropped.
    * **Fractional gates** (for example ``rx(θ)``, ``rzz(θ)``) take a
      continuous angle *and* cost real pulse time. IBM accepts them only when
      the job opts in to "fractional gates", and they cannot be mixed with
      dynamic circuits, so they are dropped by default. ``rz`` is kept: IBM
      does it "virtually" (a frame change, zero time), so it is not
      fractional.
    * ``id`` is just "wait one gate length", never needed by the transpiler.
    """
    standard = get_standard_gate_name_mapping()
    keep, dropped = [], []
    for name in basis_gates:
        gate = standard.get(name)
        fractional = gate is not None and gate.params and not isinstance(
            gate, (RZGate, PhaseGate, U1Gate)
        )
        if gate is None or fractional or name == "id":
            dropped.append(name)
        else:
            keep.append(name)
    if dropped:
        log.info("Ignoring backend gates: %s", ", ".join(dropped))
    return keep


def target_from_configuration(configuration: Mapping[str, Any]) -> Target:
    """Build a minimal ``Target`` from an IBM backend configuration dict.

    Only gate set, qubit count and wiring are used. Error rates (from the
    ``/properties`` endpoint) are ignored for now; using them would let the
    transpiler pick the best qubits. That is a good next learning step.
    """
    basis = usable_basis_gates(list(configuration["basis_gates"]))
    edges = configuration.get("coupling_map")
    return Target.from_configuration(
        basis_gates=basis + ["measure"],
        num_qubits=configuration["n_qubits"],
        coupling_map=CouplingMap(edges) if edges else None,
    )


def to_isa(
    circuit: QuantumCircuit, target: Target, optimization_level: int = 1
) -> QuantumCircuit:
    """Transpile ``circuit`` into an ISA circuit for ``target``."""
    return transpile(circuit, target=target, optimization_level=optimization_level)
