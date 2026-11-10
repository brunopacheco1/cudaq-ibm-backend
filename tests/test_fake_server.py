# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""The fake IBM server must behave like IBM where the C++ plugin depends on
it (M3: /configuration, /properties, and refusing cz on unwired pairs; M4:
answering a job with the samples its circuit really gives)."""

from fastapi.testclient import TestClient

from tests import fake_ibm_server as fake

AUTH = {"Authorization": f"Bearer {fake.TOKEN}", "Service-CRN": fake.CRN}
client = TestClient(fake.app)


def job(lines: list[str], backend: str = "ibm_fez", shots: int = 3,
        bits: int = 1) -> dict:
    """A job as the plugin sends it. With the default arguments `lines` are
    gates and qubit 0 is measured into c[0]; with `bits` > 1 `lines` must
    hold the measurements too."""
    measure = ["c[0] = measure $0;"] if bits == 1 else []
    qasm = "\n".join(['OPENQASM 3.0;', 'include "stdgates.inc";',
                      f"bit[{bits}] c;", *lines, *measure])
    return {"program_id": "sampler", "backend": backend,
            "params": {"pubs": [[qasm, None, shots]], "version": 2}}


def samples_of(body: dict) -> dict:
    """Submit a job and return the register `c` of its result."""
    r = client.post("/api/v1/jobs", headers=AUTH, json=body)
    assert r.status_code == 200, r.json()
    return client.get(f"/api/v1/jobs/{r.json()['id']}/results",
                      headers=AUTH).json()["results"][0]["data"]["c"]


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


def test_fixed_samples_backend_ignores_the_circuit():
    reg = samples_of(job(["x $0;"], backend=fake.FIXED_SAMPLES_BACKEND,
                         shots=50))
    assert reg["num_bits"] == 1 and reg["samples"] == fake.SAMPLES


def test_a_job_is_answered_with_what_its_circuit_gives():
    # x on $0 only: every shot finds qubit 0 in 1, one sample per shot.
    reg = samples_of(job(["x $0;"], shots=50))
    assert reg["num_bits"] == 1 and reg["samples"] == ["0x1"] * 50
    assert samples_of(job([], shots=7))["samples"] == ["0x0"] * 7


def test_samples_follow_the_classical_register_not_the_qubit_numbers():
    # IBM qubits far apart, measured out of order: c[0] reads $76 (0),
    # c[1] reads $62 (1), c[2] is never written. The register holds 0b010.
    reg = samples_of(job(["x $62;", "cz $62, $63;", "c[1] = measure $62;",
                          "c[0] = measure $76;"], shots=5, bits=3))
    assert reg["num_bits"] == 3 and reg["samples"] == ["0x2"] * 5


def test_a_bell_pair_gives_00_and_11_about_half_each():
    h = ["rz(1.5707963267948966) {q};", "sx {q};", "rz(1.5707963267948966) {q};"]
    lines = ([g.format(q="$0") for g in h] + [g.format(q="$1") for g in h]
             + ["cz $0, $1;"] + [g.format(q="$1") for g in h]
             + ["c[0] = measure $0;", "c[1] = measure $1;"])
    got = samples_of(job(lines, shots=2000, bits=2))["samples"]
    assert set(got) == {"0x0", "0x3"}
    assert 900 < got.count("0x3") < 1100


def test_the_same_jobs_in_the_same_order_give_the_same_samples(monkeypatch):
    h = ["rz(1.5707963267948966) $0;", "sx $0;", "rz(1.5707963267948966) $0;"]
    runs = []
    for _ in range(2):
        monkeypatch.setattr(fake, "jobs", {})
        runs.append([samples_of(job(h, shots=40))["samples"]
                     for _ in range(2)])
    assert runs[0] == runs[1]
    # ... and the two jobs of one run do not repeat each other.
    assert runs[0][0] != runs[0][1]


def test_a_circuit_the_simulator_cannot_run_is_refused(monkeypatch):
    # A gate after the measurement of the same qubit.
    r = client.post("/api/v1/jobs", headers=AUTH, json=job(
        ["c[0] = measure $0;", "x $0;", "c[1] = measure $1;"], bits=2))
    assert r.status_code == 400 and "after a measurement" in r.json()["detail"]
    # More qubits than the simulator is allowed to hold.
    monkeypatch.setattr(fake, "MAX_SIMULATED_QUBITS", 2)
    r = client.post("/api/v1/jobs", headers=AUTH,
                    json=job(["x $0;", "x $1;", "x $2;"]))
    assert r.status_code == 400 and "at most 2 qubits" in r.json()["detail"]
    # The fixed-samples backend does not simulate, so it has no such limit.
    assert client.post("/api/v1/jobs", headers=AUTH, json=job(
        ["x $0;", "x $1;", "x $2;"],
        backend=fake.FIXED_SAMPLES_BACKEND)).status_code == 200


def test_expiring_token_mode(monkeypatch):
    """FAKE_IBM_TOKEN_TTL: every login gets a new token, and a token stops
    working once its time is over (tests/run_token_expiry.py)."""
    import time

    monkeypatch.setattr(fake, "TOKEN_TTL", 0.2)
    monkeypatch.setattr(fake, "issued", {})

    def login() -> dict:
        r = client.post("/identity/token",
                        data={"grant_type": fake.GRANT_TYPE,
                              "apikey": fake.API_KEY})
        assert r.status_code == 200
        return r.json()

    def get(token: str):
        return client.get("/api/v1/backends/ibm_fez/configuration",
                          headers={"Authorization": f"Bearer {token}",
                                   "Service-CRN": fake.CRN})

    first = login()
    assert first["access_token"] == "fake-token-1"
    assert first["expires_in"] == 1  # never 0: the plugin would not cache it
    assert get("fake-token-1").status_code == 200
    # The fixed token of the normal mode is not accepted in this mode.
    assert get(fake.TOKEN).status_code == 401

    time.sleep(0.3)
    late = get("fake-token-1")
    assert late.status_code == 401 and "expired" in late.json()["detail"]

    assert login()["access_token"] == "fake-token-2"
    assert get("fake-token-2").status_code == 200


def test_normal_mode_keeps_one_token_for_ever():
    assert fake.TOKEN_TTL == 0
    r = client.post("/identity/token",
                    data={"grant_type": fake.GRANT_TYPE, "apikey": fake.API_KEY})
    assert r.json() == {"access_token": fake.TOKEN, "expires_in": 3600}
