# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""tests/hardware_trace.py: reading the plugin's log and IBM's calibration
data, and the lines printed from them."""

import sys
from pathlib import Path

import pytest
import responses

sys.path.insert(0, str(Path(__file__).parent))
import hardware_trace  # noqa: E402

LOG = """[2026-11-12 07:25:01.000] [info] [IBMServerHelper.cpp:391] IBM: OpenQASM 2 from CUDA-Q for ghz:
cx var0[0], var0[1];
[2026-11-12 07:25:01.001] [info] [IBMServerHelper.cpp:403] IBM: qubit labels -> IBM qubits for ghz: 0->7 1->8 2->9
[2026-11-12 07:25:01.002] [info] [IBMServerHelper.cpp:409] IBM: ISA circuit for ghz:
OPENQASM 3.0;
include "stdgates.inc";
bit[3] c;
rz(1.5707963267948966) $7;
sx $7;
cz $7, $8;
cz $9, $8;
cz $8, $7;
c[0] = measure $7;
c[1] = measure $8;
c[2] = measure $9;
[2026-11-12 07:25:01.003] [info] [RestClient.cpp:60] Posting to somewhere
cz $1, $2;
"""

PROPERTIES = {
    "qubits": [[{"name": "T1", "value": 100.0},
                {"name": "readout_error", "value": 0.01 * (q + 1)}]
               for q in range(10)],
    "gates": [
        {"gate": "cz", "qubits": [7, 8],
         "parameters": [{"name": "gate_error", "value": 0.004}]},
        {"gate": "cz", "qubits": [8, 7],
         "parameters": [{"name": "gate_error", "value": 0.2}]},
        {"gate": "cz", "qubits": [8, 9],
         "parameters": [{"name": "gate_error", "value": None}]},
        {"gate": "sx", "qubits": [7],
         "parameters": [{"name": "gate_error", "value": 0.0003}]},
    ],
}


def test_the_log_gives_the_cz_gates_and_where_each_bit_is_measured():
    circuit = hardware_trace.parse_log(LOG)
    # The cz after the next log message is not part of the circuit.
    assert circuit["cz"] == [(7, 8), (9, 8), (8, 7)]
    assert circuit["measured"] == {0: 7, 1: 8, 2: 9}


def test_a_log_without_a_circuit_is_an_error():
    with pytest.raises(ValueError):
        hardware_trace.parse_log("[info] IBM: requesting a new IAM token.")


def test_a_link_keeps_the_worse_direction_and_an_unknown_error_stays_unknown():
    readout, links = hardware_trace.chip_errors(PROPERTIES)
    assert readout[7] == pytest.approx(0.08)
    assert links == {(7, 8): 0.2, (8, 9): None}


def test_the_report_names_the_bad_link_and_the_qubits_of_a_weak_pair():
    readout, links = hardware_trace.chip_errors(PROPERTIES)
    lines = hardware_trace.report("T", hardware_trace.parse_log(LOG),
                                  readout, links, weak_pairs=[0, 1])
    # Two cz on the link 7-8 at 20% each: 0.8 * 0.8; the cz on 8-9 has no
    # error in the data and counts as perfect.
    assert "every cz right 64.0%" in lines[0]
    assert "(1 cz and 0 readouts have no error" in lines[0]
    # Readout: 0.92 * 0.91 * 0.90.
    assert "every readout right 75.3%" in lines[0]
    assert "7-8 20.00% (2 cz)" in lines[1]
    assert "8-9 unknown (1 cz)" in lines[1]
    assert lines[2].index("chain qubit 2 on IBM qubit 9") < \
        lines[2].index("chain qubit 0 on IBM qubit 7")
    assert ("weak pair (0,1) is measured on IBM qubits 7 and 8: readout "
            "errors 8.00% and 9.00%; linked, cz error 20.00%, used by 2 cz"
            in lines[3])
    assert "weak pair (1,2)" in lines[4] and "cz error unknown" in lines[4]


@responses.activate
def test_fetch_properties_logs_in_and_sends_token_and_crn():
    responses.post("https://iam.test/identity/token",
                   json={"access_token": "t0k"})
    responses.get("https://api.test/api/v1/backends/ibm_x/properties",
                  json={"qubits": [], "gates": []})
    data = hardware_trace.fetch_properties(
        "ibm_x", "k3y", "crn-1", url="https://api.test/api",
        iam_url="https://iam.test/identity/token")
    assert data == {"qubits": [], "gates": []}
    login, get = responses.calls
    assert "apikey=k3y" in login.request.body
    assert get.request.headers["Authorization"] == "Bearer t0k"
    assert get.request.headers["Service-CRN"] == "crn-1"
    # The key goes to the login only.
    assert "k3y" not in str(get.request.headers)


@responses.activate
def test_fetch_properties_says_the_http_status_when_ibm_refuses():
    responses.post("https://iam.test/identity/token",
                   json={"access_token": "t0k"})
    responses.get("https://api.test/api/v1/backends/ibm_x/properties",
                  body="error code: 1010", status=403)
    with pytest.raises(RuntimeError, match="HTTP 403.*error code: 1010"):
        hardware_trace.fetch_properties(
            "ibm_x", "k3y", "crn-1", url="https://api.test/api",
            iam_url="https://iam.test/identity/token")


@responses.activate
def test_fetch_properties_never_prints_a_failed_login_body():
    responses.post("https://iam.test/identity/token",
                   body="apikey k3y is wrong", status=400)
    with pytest.raises(RuntimeError) as failure:
        hardware_trace.fetch_properties(
            "ibm_x", "k3y", "crn-1", url="https://api.test/api",
            iam_url="https://iam.test/identity/token")
    assert "HTTP 400" in str(failure.value)
    assert "k3y" not in str(failure.value)


def test_report_names_the_ibm_qubits_that_read_1_least_often():
    circuit = {"cz": [(7, 8)], "measured": {0: 7, 1: 8}}
    lines = hardware_trace.report("T", circuit, {7: 0.01, 8: 0.02},
                                  {(7, 8): 0.003}, [], low_qubits=[1])
    assert lines[-1] == ("T: the qubits that read 1 least often: chain qubit "
                         "1 is IBM qubit 8 (readout error 2.00%)")
