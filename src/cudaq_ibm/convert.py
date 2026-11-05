"""Step 1: turn a CUDA-Q kernel into a Qiskit circuit.

CUDA-Q compiles kernels with MLIR. It can print a kernel as OpenQASM 2,
which is a plain-text circuit format that Qiskit can read. That text is the
bridge between the two worlds.
"""

from __future__ import annotations

from typing import Any

import cudaq
from qiskit import QuantumCircuit


def kernel_to_qasm2(kernel: Any, *args: Any) -> str:
    """Return the kernel as OpenQASM 2 text.

    A kernel with arguments (for example an angle) must first be
    "synthesized": CUDA-Q bakes the argument values into the circuit,
    because OpenQASM 2 has no concept of runtime parameters.
    """
    if args:
        kernel = cudaq.synthesize(kernel, *args)
    return cudaq.translate(kernel, format="openqasm2")


def qasm2_to_circuit(qasm2: str) -> QuantumCircuit:
    """Parse OpenQASM 2 into a Qiskit circuit.

    ``cudaq.sample`` measures every qubit when a kernel has no ``mz``.
    The exported text then has no measurements, so we add them here to keep
    the same behaviour.
    """
    circuit = QuantumCircuit.from_qasm_str(qasm2)
    if circuit.num_clbits == 0:
        circuit.measure_all()
    return circuit


def kernel_to_circuit(kernel: Any, *args: Any) -> QuantumCircuit:
    """CUDA-Q kernel -> Qiskit ``QuantumCircuit`` (not yet hardware-ready)."""
    return qasm2_to_circuit(kernel_to_qasm2(kernel, *args))
