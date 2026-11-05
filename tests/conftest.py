import json
import warnings

import cudaq
import pytest

warnings.filterwarnings("ignore")


@cudaq.kernel
def bell():
    q = cudaq.qvector(2)
    h(q[0])
    cx(q[0], q[1])
    mz(q)


@cudaq.kernel
def x_on_first():
    # Asymmetric on purpose: exposes bit-order mistakes.
    q = cudaq.qvector(3)
    x(q[0])
    mz(q)


@cudaq.kernel
def rotation(theta: float):
    q = cudaq.qvector(1)
    ry(theta, q[0])  # no mz: cudaq.sample measures all qubits implicitly


@pytest.fixture
def fez_configuration():
    from qiskit_ibm_runtime.fake_provider import FakeFez

    # Round-trip through JSON, as if it came from the REST API.
    return json.loads(json.dumps(FakeFez().configuration().to_dict(), default=str))
