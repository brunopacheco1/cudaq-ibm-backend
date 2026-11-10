# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""Show what happens when the IAM token expires while a job is polled.

CUDA-Q asks the plugin for the request headers once per job and reuses them
for every status poll (`Future::get` in runtime/common/Future.cpp,
architecture.md §2.1). A token that expires during a long queue wait is
therefore sent again and again (known limit 1, decision 0004).

This script makes the wait short enough to watch. It starts its own fake IBM
server on port 62456 in expiring-token mode:

    a token lives            12 s
    the plugin polls every    5 s   (nextResultPollingInterval)
    the job is done at poll   5     (about 20 s after the first poll)

So polls 1 to 3 carry a valid token, and poll 4 comes 3 s too late unless the
headers were built again in between.

Run, from /work/cuda-quantum:
    python3 /src/cudaq-ibm-backend/tests/run_token_expiry.py

It prints the server's log and one RESULT line. With CUDA-Q 0.16.0 the
expected result is a failed poll (HTTP 401). With a CUDA-Q that calls
getHeaders() on every poll, the job finishes. Nothing here touches IBM.
"""

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PORT = 62456
TOKEN_TTL_SECONDS = 12
POLLS_BEFORE_DONE = 4
SERVER = Path(__file__).with_name("fake_ibm_server.py")


def start_server(ttl: float = TOKEN_TTL_SECONDS,
                 polls: int = POLLS_BEFORE_DONE, port: int = PORT):
    """Start the fake server in expiring-token mode; return (process, log)."""
    log = tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False)
    env = dict(os.environ,
               FAKE_IBM_TOKEN_TTL=str(ttl),
               FAKE_IBM_POLLS_BEFORE_DONE=str(polls),
               PYTHONUNBUFFERED="1")
    process = subprocess.Popen([sys.executable, str(SERVER), str(port)],
                               env=env, stdout=log, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        with socket.socket() as probe:
            probe.settimeout(0.5)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return process, log
        time.sleep(0.2)
    process.kill()
    log.seek(0)
    raise SystemExit(f"the fake server did not start on port {port}:\n"
                     f"{log.read()}\nIs an older one still running? Are "
                     "fastapi, uvicorn and python-multipart installed?")


def stop_server(process, log) -> list[str]:
    """Stop the server and return the lines it printed."""
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
    log.seek(0)
    lines = log.read().splitlines()
    log.close()
    os.unlink(log.name)
    return lines


def main() -> None:
    os.environ["IBM_QUANTUM_API_KEY"] = "test-key"
    os.environ["IBM_QUANTUM_CRN"] = "test-crn"
    process, log = start_server()
    error = None
    started = time.monotonic()
    try:
        import cudaq

        cudaq.register_backend_path("build/external/ibm")
        # Always the localhost urls: without them the plugin talks to IBM.
        cudaq.set_target("ibm",
                         backend="ibm_fake",
                         url=f"http://localhost:{PORT}/api",
                         iam_url=f"http://localhost:{PORT}/identity/token")
        kernel = cudaq.make_kernel()
        q = kernel.qalloc(2)
        kernel.h(q[0])
        kernel.cx(q[0], q[1])
        kernel.mz(q)
        print(f"Sampling. Tokens live {TOKEN_TTL_SECONDS} s, the job needs "
              f"{POLLS_BEFORE_DONE + 1} polls. This takes up to half a minute.")
        counts = cudaq.sample(kernel, shots_count=3)
    except Exception as e:  # noqa: BLE001
        error = e
    finally:
        elapsed = time.monotonic() - started
        lines = stop_server(process, log)

    print("\nServer log:")
    for line in lines:
        if "login:" in line or "poll " in line or "401" in line:
            print("  " + line)
    tokens = sorted({word for line in lines if "poll " in line
                     for word in line.split() if word.startswith("fake-token-")})
    print(f"\nTokens seen in status polls: {', '.join(tokens) or 'none'}")

    if error is None:
        print(f"RESULT: the job finished after {elapsed:.0f} s: {counts}. "
              "The headers were built again while polling.")
    elif "401" in str(error):
        print(f"RESULT: the poll failed after {elapsed:.0f} s with HTTP 401. "
              "The token from before the poll loop was sent after it had "
              "expired.")
        print("        " + str(error).splitlines()[0][:200])
    else:
        print(f"RESULT: unexpected error after {elapsed:.0f} s (not a 401):")
        raise error


if __name__ == "__main__":
    main()
