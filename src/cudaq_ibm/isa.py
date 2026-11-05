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

from qiskit import QuantumCircuit, transpile
from qiskit.transpiler import CouplingMap, Target


def target_from_configuration(configuration: Mapping[str, Any]) -> Target:
    """Build a minimal ``Target`` from an IBM backend configuration dict.

    Only gate set, qubit count and wiring are used. Error rates (from the
    ``/properties`` endpoint) are ignored for now; using them would let the
    transpiler pick the best qubits. That is a good next learning step.
    """
    basis = [g for g in configuration["basis_gates"] if g != "id"]
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
