"""The full pipeline: CUDA-Q kernel -> IBM chip -> CUDA-Q style counts."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from qiskit import QuantumCircuit, qasm3

from .client import IBMQuantumClient
from .convert import kernel_to_circuit
from .isa import target_from_configuration, to_isa
from .results import samples_to_counts


@dataclass
class IBMRunResult:
    """What came back from a run. ``counts`` uses CUDA-Q bit order."""

    counts: dict[str, int]
    isa_circuit: QuantumCircuit
    backend: str
    job_id: str | None = None

    def most_probable(self) -> str:
        return max(self.counts, key=self.counts.get)


def _registers(circuit: QuantumCircuit) -> list[tuple[str, int]]:
    return [(creg.name, creg.size) for creg in circuit.cregs]


def client_from_env() -> IBMQuantumClient:
    """Build a client from ``IBM_QUANTUM_API_KEY`` and ``IBM_QUANTUM_CRN``."""
    try:
        return IBMQuantumClient(
            api_key=os.environ["IBM_QUANTUM_API_KEY"],
            crn=os.environ["IBM_QUANTUM_CRN"],
        )
    except KeyError as missing:
        raise RuntimeError(
            f"Set the {missing} environment variable (see README, 'Credentials')."
        ) from None


def run_on_ibm(
    kernel: Any,
    *args: Any,
    backend: str,
    shots: int = 1000,
    client: IBMQuantumClient | None = None,
    poll_seconds: float = 5.0,
    timeout: float = 3600.0,
) -> IBMRunResult:
    """Run a CUDA-Q kernel on a real IBM Quantum backend.

    This uses real QPU time from your IBM plan. Try ``simulate_locally``
    first.
    """
    client = client or client_from_env()
    circuit = kernel_to_circuit(kernel, *args)
    target = target_from_configuration(client.backend_configuration(backend))
    isa = to_isa(circuit, target)

    job_id = client.submit_sampler(backend, [qasm3.dumps(isa)], shots)
    client.wait(job_id, poll_seconds=poll_seconds, timeout=timeout)
    pub_result = client.results(job_id)["results"][0]

    counts = samples_to_counts(pub_result["data"], _registers(isa))
    return IBMRunResult(counts=counts, isa_circuit=isa, backend=backend, job_id=job_id)


def simulate_locally(
    kernel: Any, *args: Any, fake_backend: Any = None, shots: int = 1000
) -> IBMRunResult:
    """Run the same pipeline on a noisy local simulator. No account needed.

    ``fake_backend`` is a fake IBM device from
    ``qiskit_ibm_runtime.fake_provider`` (default: ``FakeFez``, a 156-qubit
    Heron chip). It copies the real chip's gates, wiring and noise.

    Needs the ``local`` extra: ``pip install "cudaq-ibm-backend[local]"``.
    """
    from qiskit_ibm_runtime import SamplerV2
    from qiskit_ibm_runtime.fake_provider import FakeFez

    fake_backend = fake_backend or FakeFez()
    circuit = kernel_to_circuit(kernel, *args)
    # Same Target-building code as the real path, fed with the fake chip's
    # configuration JSON, so we exercise it here too.
    target = target_from_configuration(fake_backend.configuration().to_dict())
    isa = to_isa(circuit, target)
    qasm3.dumps(isa)  # make sure the circuit can be serialized like a real job

    pub_result = SamplerV2(mode=fake_backend).run([isa], shots=shots).result()[0]
    # Re-shape the local result into the JSON layout IBM's REST API returns
    # (hex strings per register), so both paths share the same decoder.
    data = {
        name: {"samples": [hex(int(b, 2)) for b in getattr(pub_result.data, name).get_bitstrings()]}
        for name, _ in _registers(isa)
    }
    counts = samples_to_counts(data, _registers(isa))
    return IBMRunResult(counts=counts, isa_circuit=isa, backend=fake_backend.name)
