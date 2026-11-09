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


def test_backend_endpoints_need_auth():
    assert client.get("/api/v1/backends/ibm_fez/configuration").status_code == 401


def test_cz_on_wired_pair_is_accepted():
    assert client.post("/api/v1/jobs", headers=AUTH,
                       json=job(["cz $0, $1;"])).status_code == 200


def test_cz_on_unwired_pair_is_rejected():
    r = client.post("/api/v1/jobs", headers=AUTH, json=job(["cz $0, $2;"]))
    assert r.status_code == 400 and "unwired" in r.json()["detail"]


def test_cz_on_broken_pair_is_rejected():
    r = client.post("/api/v1/jobs", headers=AUTH, json=job(["cz $62, $63;"]))
    assert r.status_code == 400 and "broken" in r.json()["detail"]


def test_down_qubit_is_rejected():
    r = client.post("/api/v1/jobs", headers=AUTH, json=job(["x $61;"]))
    assert r.status_code == 400 and "not usable" in r.json()["detail"]
