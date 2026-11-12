# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""The repository's fake IBM server plus two things the limit probes need:

- Clifford circuits (every rz a multiple of pi/2) on more than 16 qubits are
  sampled with Stim, an independent stabilizer simulator. The fake server's
  own simulator stops at 24 qubits and is slow long before that;
- PROBE_FAULT=<name> makes one endpoint misbehave.
"""
import asyncio
import math
import os
import re
import sys

REPO = os.environ.get("PROBE_REPO", os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tests"))
import fake_ibm_server as fake  # noqa: E402
from fastapi import Request  # noqa: E402
from fastapi.responses import JSONResponse, PlainTextResponse  # noqa: E402

FAULT = os.environ.get("PROBE_FAULT", "")
# The fake server's own simulator takes minutes at 24 qubits. Wider Clifford
# circuits than this go to Stim, which takes milliseconds at any width.
STIM_ABOVE = 16
state = {"polls": 0, "posts": 0}

RZ = re.compile(r"^rz\(([-+0-9.eE]+)\) \$(\d+);$")
ONE = re.compile(r"^(sx|x) \$(\d+);$")
CZ = re.compile(r"^cz \$(\d+), \$(\d+);$")
MEAS = re.compile(r"^c\[(\d+)\] = measure \$(\d+);$")
BITS = re.compile(r"^bit\[(\d+)\] c;$")


def stim_samples(qasm3: str, shots: int, seed: int):
    """Samples of a Clifford ISA circuit, in IBM's hex format; None if the
    circuit is not Clifford, or if Stim is not installed (it has no ready
    wheel for every platform: on Linux aarch64 pip builds it and needs g++).
    The fake server's own simulator then answers, up to its 24 qubits."""
    try:
        import stim
    except ImportError:
        return None
    circuit = stim.Circuit()
    measured = {}
    n_bits = 0
    for line in qasm3.strip().splitlines():
        line = line.strip()
        if m := RZ.match(line):
            turns = float(m[1]) / (math.pi / 2)
            k = round(turns)
            if abs(turns - k) > 1e-5:
                return None
            gate = ("I", "S", "Z", "S_DAG")[k % 4]
            if gate != "I":
                circuit.append(gate, [int(m[2])])
        elif m := ONE.match(line):
            circuit.append("SQRT_X" if m[1] == "sx" else "X", [int(m[2])])
        elif m := CZ.match(line):
            circuit.append("CZ", [int(m[1]), int(m[2])])
        elif m := MEAS.match(line):
            measured[int(m[1])] = len(measured)
            circuit.append("M", [int(m[2])])
        elif m := BITS.match(line):
            n_bits = int(m[1])
    sampler = circuit.compile_sampler(seed=seed)
    out = []
    for shot in sampler.sample(shots):
        value = 0
        for bit, column in measured.items():
            if shot[column]:
                value |= 1 << bit
        out.append(hex(value))
    return out


original_answer = fake.answer


def answer(backend, qasm3, shots, job_number):
    touched = {int(q) for q in fake.QUBIT.findall(qasm3)}
    if backend != fake.FIXED_SAMPLES_BACKEND and len(touched) > STIM_ABOVE:
        samples = stim_samples(qasm3, shots, fake.SEED + job_number)
        if samples is not None:
            print(f"[probe] {len(touched)} qubits: sampled with Stim")
            return samples
    samples = original_answer(backend, qasm3, shots, job_number)
    if FAULT == "results_fewer_samples":
        return samples[: max(1, len(samples) // 2)]
    return samples


def chip(kind, config):
    """Small chips in IBM's format. kind: chip_line5, chip_line5_dead_middle,
    chip_all_links_broken, chip_no_readout_errors, chip_single_qubit,
    chip_ecr (a 2-qubit gate other than cz, as on IBM's Eagle chips)."""
    two = "ecr" if kind == "chip_ecr" else "cz"
    n = 1 if kind == "chip_single_qubit" else 5
    pairs = [(a, a + 1) for a in range(n - 1)]
    links = sorted([a, b] for a, b in pairs) + sorted([b, a] for a, b in pairs)
    if config:
        return {"backend_name": "tiny", "n_qubits": n, "basis_gates": [two, "id", "rz", "sx", "x"],
                "coupling_map": links}
    date = "2026-11-09T00:00:00Z"
    qubits = []
    for q in range(n):
        entry = [] if kind == "chip_no_readout_errors" else [
            {"date": date, "name": "readout_error", "unit": "", "value": 0.01}]
        qubits.append(entry)
    gates = []
    for a, b in links:
        error = 0.01
        if kind == "chip_all_links_broken" or (kind == "chip_line5_dead_middle" and 2 in (a, b)):
            error = 1
        gates.append({"gate": two, "qubits": [a, b], "name": f"{two}{a}_{b}",
                      "parameters": [{"date": date, "name": "gate_error", "unit": "", "value": error}]})
    gates += [{"gate": g, "qubits": [q], "name": f"{g}{q}",
               "parameters": [{"date": date, "name": "gate_error", "unit": "", "value": 0.0003}]}
              for q in range(n) for g in ("sx", "x")]
    return {"backend_name": "tiny", "qubits": qubits, "gates": gates, "general": []}


fake.answer = answer
app = fake.app


@app.middleware("http")
async def faults(request: Request, call_next):
    path, method = request.url.path, request.method
    is_post = method == "POST" and path.endswith("/jobs")
    is_poll = method == "GET" and re.search(r"/jobs/[^/]+$", path)
    is_results = path.endswith("/results")
    is_config = path.endswith("/configuration")
    is_props = path.endswith("/properties")
    is_login = path.endswith("/identity/token")
    if is_post:
        state["posts"] += 1
        size = int(request.headers.get("content-length", 0))
        print(f"[probe] job POST body: {size} bytes")
    if is_poll:
        state["polls"] += 1
    f = FAULT
    if f == "login_500" and is_login:
        return PlainTextResponse("IAM is down", 500)
    if f == "login_html" and is_login:
        return PlainTextResponse("<html>maintenance</html>", 200, media_type="text/html")
    if f == "login_no_token" and is_login:
        return JSONResponse({"expires_in": 3600})
    if f == "login_slow" and is_login:
        await asyncio.sleep(45)
    if f == "config_500" and is_config:
        return JSONResponse({"errors": [{"message": "boom"}]}, 500)
    if f == "config_html" and is_config:
        return PlainTextResponse("<html>bad gateway</html>", 200, media_type="text/html")
    if f == "config_404" and is_config:
        return JSONResponse({"errors": [{"code": 1211, "message": "Backend not found."}]}, 404)
    if f == "props_empty" and is_props:
        return JSONResponse({})
    if f == "post_429_after_5" and is_post and state["posts"] > 5:
        return JSONResponse({"errors": [{"message": "rate limit: 5 jobs per minute"}]}, 429)
    if f.startswith("chip_") and (is_config or is_props):
        return JSONResponse(chip(f, is_config))
    if f == "post_401" and is_post:
        return JSONResponse({"errors": [{"message": "token rejected"}]}, 401)
    if f == "post_429" and is_post:
        return JSONResponse({"errors": [{"message": "too many requests"}]}, 429)
    if f == "post_500" and is_post:
        return JSONResponse({"errors": [{"message": "internal error"}]}, 500)
    if f == "post_500_once" and is_post and state["posts"] == 1:
        return JSONResponse({"errors": [{"message": "internal error"}]}, 500)
    if f == "post_no_id" and is_post:
        return JSONResponse({"backend": "ibm_fake"})
    if f == "post_html" and is_post:
        return PlainTextResponse("<html>bad gateway</html>", 200, media_type="text/html")
    if f == "post_slow" and is_post:
        await asyncio.sleep(75)
    if f == "poll_500_once" and is_poll and state["polls"] == 1:
        return JSONResponse({"errors": [{"message": "internal error"}]}, 500)
    if f == "poll_500" and is_poll:
        return JSONResponse({"errors": [{"message": "internal error"}]}, 500)
    if f == "poll_404" and is_poll:
        return JSONResponse({"errors": [{"message": "job not found"}]}, 404)
    if f == "poll_html" and is_poll:
        return PlainTextResponse("<html>bad gateway</html>", 200, media_type="text/html")
    if f in ("status_failed", "status_cancelled", "status_weird", "status_none",
             "never_done", "status_lower") and is_poll:
        job = path.rsplit("/", 1)[1]
        body = {"status_failed": {"status": "Failed", "reason": "Qubit 3 is faulty",
                                  "reason_code": 1517},
                "status_cancelled": {"status": "Cancelled"},
                "status_weird": {"status": "Paused"},
                "never_done": {"status": "Queued"},
                "status_lower": {"status": "completed"}}.get(f)
        if f == "status_none":
            return JSONResponse({"id": job})
        return JSONResponse({"id": job, "state": body})
    if is_results and f.startswith("results_") and f != "results_fewer_samples":
        if f == "results_500":
            return JSONResponse({"errors": [{"message": "internal error"}]}, 500)
        if f == "results_empty":
            return JSONResponse({"results": [{"data": {"c": {"samples": [], "num_bits": 2}}}]})
        if f == "results_two_registers":
            return JSONResponse({"results": [{"data": {
                "c": {"samples": ["0x1"], "num_bits": 2},
                "d": {"samples": ["0x1"], "num_bits": 2}}}]})
        if f == "results_no_num_bits":
            return JSONResponse({"results": [{"data": {"c": {"samples": ["0x0", "0x0", "0x0"]}}}]})
        if f == "results_bad_hex":
            return JSONResponse({"results": [{"data": {"c": {"samples": ["zz", "0x1"], "num_bits": 2}}}]})
        if f == "results_too_wide":
            return JSONResponse({"results": [{"data": {"c": {"samples": ["0xff", "0x1"], "num_bits": 2}}}]})
        if f == "results_no_results":
            return JSONResponse({"metadata": {}})
        if f == "results_meas_name":
            return JSONResponse({"results": [{"data": {"meas": {"samples": ["0x3", "0x3"], "num_bits": 2}}}]})
    return await call_next(request)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
