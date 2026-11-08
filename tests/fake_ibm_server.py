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

import sys
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request

API_KEY = "test-key"
CRN = "test-crn"
TOKEN = "fake-token"
GRANT_TYPE = "urn:ibm:params:oauth:grant-type:apikey"
POLLS_BEFORE_DONE = 2
# Two qubits, three shots. IBM is little-endian: "0x1" means qubit 0 = 1.
SAMPLES = ["0x1", "0x1", "0x2"]

app = FastAPI()
jobs: dict[str, dict[str, Any]] = {}


def check_auth(request: Request) -> None:
    if request.headers.get("authorization") != f"Bearer {TOKEN}":
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
    return {"access_token": TOKEN, "expires_in": 3600}


@app.post("/api/v1/jobs")
async def submit_job(request: Request):
    check_auth(request)
    body = await request.json()
    if body.get("program_id") != "sampler":
        raise HTTPException(400, "program_id must be 'sampler'")
    pubs = body.get("params", {}).get("pubs")
    if not isinstance(pubs, list) or not pubs:
        raise HTTPException(400, "params.pubs must be a non-empty list")
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"polls": 0, "body": body}
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
    print(f"[fake-ibm] poll {jobs[job_id]['polls']} -> {status}")
    return {"id": job_id, "state": {"status": status}}


@app.get("/api/v1/jobs/{job_id}/results")
async def job_results(job_id: str, request: Request):
    check_auth(request)
    if job_id not in jobs:
        raise HTTPException(404, "job not found")
    return {"results": [{"data": {"c": {"samples": SAMPLES}}}]}


if __name__ == "__main__":
    import uvicorn
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 62455
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
