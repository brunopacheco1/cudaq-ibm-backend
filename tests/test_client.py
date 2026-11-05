"""End-to-end test of run_on_ibm against a fake IBM REST server."""

import json

import pytest
import responses

from cudaq_ibm import IBMJobError, IBMQuantumClient, kernel_to_circuit, run_on_ibm
from cudaq_ibm.client import DEFAULT_API_URL as API, DEFAULT_IAM_URL as IAM

from .conftest import x_on_first


@pytest.fixture
def client():
    return IBMQuantumClient(api_key="fake-key", crn="crn:fake")


def _mock_common(rsps, configuration, statuses):
    rsps.post(IAM, json={"access_token": "tok", "expires_in": 3600})
    rsps.get(f"{API}/backends/ibm_fez/configuration", json=configuration)
    rsps.post(f"{API}/jobs", json={"id": "job-1"})
    for status in statuses:
        rsps.get(f"{API}/jobs/job-1", json={"state": {"status": status}})


@responses.activate
def test_run_on_ibm_end_to_end(client, fez_configuration):
    _mock_common(responses, fez_configuration, ["Queued", "Running", "Completed"])
    # x(q[0]) on 3 qubits. IBM reports bit 0 set as 0x1. The register name
    # is whatever CUDA-Q chose when exporting OpenQASM.
    creg = kernel_to_circuit(x_on_first).cregs[0].name
    responses.get(
        f"{API}/jobs/job-1/results",
        json={"results": [{"data": {creg: {"samples": ["0x1"] * 9 + ["0x0"]}}}]},
    )
    result = run_on_ibm(x_on_first, backend="ibm_fez", shots=10, client=client, poll_seconds=0)

    assert result.counts == {"100": 9, "000": 1}
    assert result.job_id == "job-1"

    submit = next(c.request for c in responses.calls if c.request.url == f"{API}/jobs")
    assert submit.headers["Authorization"] == "Bearer tok"
    assert submit.headers["Service-CRN"] == "crn:fake"
    body = json.loads(submit.body)
    assert body["program_id"] == "sampler"
    assert body["backend"] == "ibm_fez"
    qasm, params, shots = body["params"]["pubs"][0]
    assert qasm.startswith("OPENQASM 3")
    assert params is None and shots == 10


@responses.activate
def test_failed_job_raises(client, fez_configuration):
    _mock_common(responses, fez_configuration, ["Failed"])
    with pytest.raises(IBMJobError):
        run_on_ibm(x_on_first, backend="ibm_fez", client=client, poll_seconds=0)


@responses.activate
def test_token_is_cached(client):
    responses.post(IAM, json={"access_token": "tok", "expires_in": 3600})
    responses.get(f"{API}/jobs/a", json={"state": {"status": "Running"}})
    client.job_status("a")
    client.job_status("a")
    assert sum(1 for c in responses.calls if c.request.url == IAM) == 1
