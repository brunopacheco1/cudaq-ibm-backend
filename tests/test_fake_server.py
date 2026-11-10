# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""The fake IBM server must behave like IBM where the C++ plugin depends on
it (M3: /configuration, /properties, and refusing cz on unwired pairs)."""

from fastapi.testclient import TestClient

from tests import fake_ibm_server as fake

AUTH = {"Authorization": f"Bearer {fake.TOKEN}", "Service-CRN": fake.CRN}
client = TestClient(fake.app)


def job(lines: list[str]) -> dict:
    qasm = "\n".join(['OPENQASM 3.0;', 'include "stdgates.inc";', "bit[1] c;",
                      *lines, "c[0] = measure $0;"])
    return {"program_id": "sampler", "backend": "ibm_fez",
            "params": {"pubs": [[qasm, None, 3]], "version": 2}}


def test_coupling_data_matches_qiskit_fake_fez(fez_configuration):
    real = {tuple(p) for p in fez_configuration["coupling_map"]}
    assert fake.N_QUBITS == fez_configuration["n_qubits"] == 156
    assert fake.LINKS == real


def test_configuration_lists_links_both_ways():
    r = client.get("/api/v1/backends/ibm_fez/configuration", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    pairs = {tuple(p) for p in body["coupling_map"]}
    assert body["n_qubits"] == 156
    assert all((b, a) in pairs for a, b in pairs)


def test_properties_mark_broken_link_and_down_qubit():
    body = client.get("/api/v1/backends/ibm_fez/properties", headers=AUTH).json()
    errors = {tuple(g["qubits"]): g["parameters"][0]["value"]
              for g in body["gates"] if g["gate"] == "cz"}
    assert errors[fake.BROKEN_LINK] == 1.0
    down = body["qubits"][fake.DOWN_QUBIT]
    assert {"name": "operational", "value": 0} == {
        k: v for k, v in down[-1].items() if k in ("name", "value")}
    # One direction of one link has a value the plugin cannot read.
    a, b = fake.UNREADABLE_LINK
    assert errors[(a, b)] is None and errors[(b, a)] == 0.01


def test_obstacles_leave_the_best_qubit_connected():
    """The best qubit must keep working links into the rest of the chip,
    or the plugin would (rightly) never start its numbering there."""
    adj = {}
    for a, b in fake.LINKS:
        if fake.usable(a, b):
            adj.setdefault(a, set()).add(b)
    seen, stack = {fake.BEST_QUBIT}, [fake.BEST_QUBIT]
    while stack:
        for v in adj.get(stack.pop(), ()):
            if v not in seen:
                seen.add(v)
                stack.append(v)
    assert len(adj[fake.BEST_QUBIT]) == 2
    assert len(seen) > 140


def test_properties_fail_for_the_no_properties_backend():
    r = client.get(f"/api/v1/backends/{fake.NO_PROPERTIES_BACKEND}/properties",
                   headers=AUTH)
    assert r.status_code == 503
    assert client.get(
        f"/api/v1/backends/{fake.NO_PROPERTIES_BACKEND}/configuration",
        headers=AUTH).status_code == 200


def test_backend_endpoints_need_auth():
    assert client.get("/api/v1/backends/ibm_fez/configuration").status_code == 401


def test_cz_on_wired_pair_is_accepted():
    assert client.post("/api/v1/jobs", headers=AUTH,
                       json=job(["cz $0, $1;"])).status_code == 200


def test_cz_on_unwired_pair_is_rejected():
    r = client.post("/api/v1/jobs", headers=AUTH, json=job(["cz $0, $2;"]))
    assert r.status_code == 400 and "unwired" in r.json()["detail"]


def test_cz_on_broken_pair_is_rejected():
    for a, b in (fake.BROKEN_LINK, fake.UNREADABLE_LINK):
        r = client.post("/api/v1/jobs", headers=AUTH,
                        json=job([f"cz ${a}, ${b};"]))
        assert r.status_code == 400 and "broken" in r.json()["detail"]


def test_down_qubit_is_rejected():
    r = client.post("/api/v1/jobs", headers=AUTH, json=job([f"x ${fake.DOWN_QUBIT};"]))
    assert r.status_code == 400 and "not usable" in r.json()["detail"]


def test_properties_report_a_stale_sx_error_as_one():
    body = client.get("/api/v1/backends/ibm_fez/properties", headers=AUTH).json()
    sx = {g["qubits"][0]: g["parameters"][0]["value"]
          for g in body["gates"] if g["gate"] == "sx"}
    assert len(sx) == 156 and sx[fake.STALE_QUBIT] == 1
    assert all(v < 0.01 for q, v in sx.items() if q != fake.STALE_QUBIT)


def test_qubit_with_stale_sx_error_is_rejected():
    for line in (f"sx ${fake.STALE_QUBIT};", f"cz ${fake.STALE_QUBIT}, $85;"):
        r = client.post("/api/v1/jobs", headers=AUTH, json=job([line]))
        assert r.status_code == 400 and "not usable" in r.json()["detail"]


def test_results_report_num_bits_of_the_circuit():
    job_id = client.post("/api/v1/jobs", headers=AUTH,
                         json=job(["x $0;"])).json()["id"]
    reg = client.get(f"/api/v1/jobs/{job_id}/results",
                     headers=AUTH).json()["results"][0]["data"]["c"]
    assert reg["num_bits"] == 1 and reg["samples"] == fake.SAMPLES
