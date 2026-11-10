# ============================================================================ #
# Copyright (c) 2022 - 2026 NVIDIA Corporation & Affiliates.                   #
# All rights reserved.                                                         #
#                                                                              #
# Modifications copyright (c) 2026 Bruno Pacheco.                              #
# Adapted from the CUDA-Q mock_rest plugin example for IBM Quantum.            #
#                                                                              #
# This source code and the accompanying materials are made available under     #
# the terms of the Apache License 2.0 which accompanies this distribution.     #
# ============================================================================ #

import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request

API_KEY = "test-key"
CRN = "test-crn"
TOKEN = "fake-token"
GRANT_TYPE = "urn:ibm:params:oauth:grant-type:apikey"
POLLS_BEFORE_DONE = int(os.environ.get("FAKE_IBM_POLLS_BEFORE_DONE", "2"))
# Expiring-token mode (tests/run_token_expiry.py). 0 = off: one token, valid
# for ever. With N > 0 every login gets a new token that stops working after
# N seconds, as IBM's IAM tokens do after about an hour.
TOKEN_TTL = float(os.environ.get("FAKE_IBM_TOKEN_TTL", "0"))
# Two qubits, three shots. IBM is little-endian: "0x1" means qubit 0 = 1.
SAMPLES = ["0x1", "0x1", "0x2"]

# IBM accepts only "ISA" circuits: native gates on physical qubits ($k).
NATIVE_LINE = re.compile(
    r"^(rz\([-+0-9.eE]+\) \$\d+|sx \$\d+|x \$\d+|cz \$\d+, \$\d+"
    r"|c\[\d+\] = measure \$\d+);$")
HEADER_LINES = ("OPENQASM 3.0;", 'include "stdgates.inc";')
CZ_LINE = re.compile(r"^cz \$(\d+), \$(\d+);$")
QUBIT = re.compile(r"\$(\d+)")


def load_chip() -> tuple[int, set[tuple[int, int]]]:
    """ibm_fez wiring (156 qubits) from tests/data, links in both directions."""
    n, links = 0, set()
    path = Path(__file__).parent / "data" / "ibm_fez_coupling.txt"
    for line in path.read_text().splitlines():
        if line.startswith("qubits"):
            n = int(line.split()[1])
        elif line and line[0].isdigit():
            a, b = map(int, line.split())
            links |= {(a, b), (b, a)}
    return n, links


N_QUBITS, LINKS = load_chip()
# Calibration data for /properties. Qubit 62 and its two links (61-62, 62-63)
# are the best, so the plugin should start its numbering there. Around it:
# - link 63-64 is broken (gate_error 1, as IBM reports it);
# - qubit 56 is marked not operational;
# - link 60-61 has a gate_error the plugin cannot read (null) in one
#   direction: the plugin must treat it as broken (decision 0009, item 3).
# - qubit 84 has an sx error of 1: IBM reports that when the benchmark of a
#   gate failed for days ("undefined, proceed with caution"). Seen on the
#   real ibm_fez on 2026-11-10. The plugin must not use such a qubit.
# The plugin must route around all four; check_isa rejects a gate on them.
BEST_QUBIT = 62
BROKEN_LINK = (63, 64)
DOWN_QUBIT = 56
UNREADABLE_LINK = (60, 61)
STALE_QUBIT = 84
UNUSABLE_QUBITS = (DOWN_QUBIT, STALE_QUBIT)
# A backend whose /properties request fails: the plugin must stop.
NO_PROPERTIES_BACKEND = "ibm_no_properties"


def link_error(a: int, b: int) -> float:
    if {a, b} == set(BROKEN_LINK):
        return 1.0
    if BEST_QUBIT in (a, b):
        return 0.001
    return 0.01


def usable(a: int, b: int) -> bool:
    return (link_error(a, b) < 1.0
            and not {a, b} & set(UNUSABLE_QUBITS)
            and {a, b} != set(UNREADABLE_LINK))


app = FastAPI()


def check_isa(qasm3: str) -> None:
    """Reject anything a real IBM chip would reject: non-native gates, qubits
    that do not exist or are down, and cz on pairs that are not wired or are
    broken (M3)."""
    for line in qasm3.strip().splitlines():
        line = line.strip()
        if not line or line in HEADER_LINES or line.startswith("bit["):
            continue
        if not NATIVE_LINE.match(line):
            raise HTTPException(400, f"not an ISA instruction: {line!r}")
        for q in map(int, QUBIT.findall(line)):
            if q >= N_QUBITS or q in UNUSABLE_QUBITS:
                raise HTTPException(400, f"qubit {q} is not usable: {line!r}")
        cz = CZ_LINE.match(line)
        if cz:
            a, b = int(cz[1]), int(cz[2])
            if (a, b) not in LINKS:
                raise HTTPException(400, f"cz on unwired pair: {line!r}")
            if not usable(a, b):
                raise HTTPException(400, f"cz on broken pair: {line!r}")
jobs: dict[str, dict[str, Any]] = {}
# Expiring-token mode: token -> the time.monotonic() at which it stops working.
issued: dict[str, float] = {}


def bearer(request: Request) -> str:
    return request.headers.get("authorization", "").removeprefix("Bearer ")


def check_auth(request: Request) -> None:
    if TOKEN_TTL > 0:
        token = bearer(request)
        if token not in issued:
            raise HTTPException(401, "missing or wrong Bearer token")
        late = time.monotonic() - issued[token]
        if late > 0:
            print(f"[fake-ibm] 401 for {request.url.path}: {token} expired "
                  f"{late:.1f} s ago")
            raise HTTPException(401, f"token expired {late:.1f} s ago")
    elif request.headers.get("authorization") != f"Bearer {TOKEN}":
        raise HTTPException(401, "missing or wrong Bearer token")
    if request.headers.get("service-crn") != CRN:
        raise HTTPException(401, "missing or wrong Service-CRN header")


@app.post("/identity/token")
async def iam_token(request: Request):
    """IAM login. The real one only accepts a form body, so we do too."""
    if not request.headers.get("content-type", "").startswith(
            "application/x-www-form-urlencoded"):
        raise HTTPException(400, "IAM expects a form-encoded body")
    form = await request.form()
    if form.get("grant_type") != GRANT_TYPE:
        raise HTTPException(400, f"bad grant_type: {form.get('grant_type')}")
    if form.get("apikey") != API_KEY:
        raise HTTPException(400, "bad apikey")
    if TOKEN_TTL > 0:
        token = f"{TOKEN}-{len(issued) + 1}"
        issued[token] = time.monotonic() + TOKEN_TTL
        print(f"[fake-ibm] login: issued {token}, valid for {TOKEN_TTL:g} s")
        return {"access_token": token, "expires_in": max(1, round(TOKEN_TTL))}
    return {"access_token": TOKEN, "expires_in": 3600}


@app.get("/api/v1/backends/{name}/configuration")
async def backend_configuration(name: str, request: Request):
    """Wiring, in IBM's format: every link listed in both directions."""
    check_auth(request)
    return {"backend_name": name, "n_qubits": N_QUBITS,
            "basis_gates": ["cz", "id", "rz", "sx", "x"],
            "coupling_map": sorted([a, b] for a, b in LINKS)}


@app.get("/api/v1/backends/{name}/properties")
async def backend_properties(name: str, request: Request):
    """Calibration data, in IBM's format (see props_fez.json in
    qiskit-ibm-runtime's fake provider)."""
    check_auth(request)
    if name == NO_PROPERTIES_BACKEND:
        raise HTTPException(503, "properties are not available")
    date = "2026-11-09T00:00:00Z"
    qubits = []
    for q in range(N_QUBITS):
        entry = [{"date": date, "name": "readout_error", "unit": "",
                  "value": 0.001 if q == BEST_QUBIT else 0.02}]
        if q == DOWN_QUBIT:
            entry.append({"date": date, "name": "operational", "unit": "",
                          "value": 0})
        qubits.append(entry)
    gates = [{"gate": "cz", "qubits": [a, b], "name": f"cz{a}_{b}",
              "parameters": [{"date": date, "name": "gate_error", "unit": "",
                              "value": (None if (a, b) == UNREADABLE_LINK
                                        else link_error(a, b))}]}
             for a, b in sorted(LINKS)]
    gates += [{"gate": g, "qubits": [q], "name": f"{g}{q}",
               "parameters": [{"date": date, "name": "gate_error", "unit": "",
                               "value": 1 if q == STALE_QUBIT else 0.0003},
                              {"date": date, "name": "gate_length",
                               "unit": "ns", "value": 24}]}
              for q in range(N_QUBITS) for g in ("sx", "x")]
    return {"backend_name": name, "qubits": qubits, "gates": gates,
            "general": []}


@app.post("/api/v1/jobs")
async def submit_job(request: Request):
    check_auth(request)
    body = await request.json()
    if body.get("program_id") != "sampler":
        raise HTTPException(400, "program_id must be 'sampler'")
    pubs = body.get("params", {}).get("pubs")
    if not isinstance(pubs, list) or not pubs:
        raise HTTPException(400, "params.pubs must be a non-empty list")
    for pub in pubs:
        check_isa(pub[0])
        used = sorted({int(q) for q in QUBIT.findall(pub[0])})
        print(f"[fake-ibm] circuit uses qubits {used}, "
              f"{pub[0].count('cz ')} cz, all on working links")
    job_id = str(uuid.uuid4())
    # IBM reports the register size as num_bits (architecture.md §3.5).
    bits = re.search(r"^bit\[(\d+)\] c;$", pubs[0][0], re.MULTILINE)
    jobs[job_id] = {"polls": 0, "body": body,
                    "num_bits": int(bits.group(1)) if bits else 0}
    print(f"[fake-ibm] job {job_id}: backend={body.get('backend')} "
          f"shots={pubs[0][2]}")
    return {"id": job_id, "backend": body.get("backend")}


@app.get("/api/v1/jobs/{job_id}")
async def job_status(job_id: str, request: Request):
    check_auth(request)
    if job_id not in jobs:
        raise HTTPException(404, "job not found")
    jobs[job_id]["polls"] += 1
    done = jobs[job_id]["polls"] > POLLS_BEFORE_DONE
    status = "Completed" if done else "Running"
    who = f" with {bearer(request)}" if TOKEN_TTL > 0 else ""
    print(f"[fake-ibm] poll {jobs[job_id]['polls']}{who} -> {status}")
    return {"id": job_id, "state": {"status": status}}


@app.get("/api/v1/jobs/{job_id}/results")
async def job_results(job_id: str, request: Request):
    check_auth(request)
    if job_id not in jobs:
        raise HTTPException(404, "job not found")
    return {"results": [{"data": {"c": {
        "samples": SAMPLES, "num_bits": jobs[job_id]["num_bits"]}}}]}


if __name__ == "__main__":
    import uvicorn
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 62455
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
