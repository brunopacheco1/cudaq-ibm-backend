# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""Check the plugin's input checks and error messages against the fake IBM
server (quality step 1; docs/architecture.md §8 item 9).

Each case runs in its own Python process, against its own fake server on
port 62461; some cases start that server with FAKE_IBM_FAULT, which makes one
reply wrong. A case passes when the process ends as expected (error or not)
and its output holds the expected text. Cases that must not send a job also
check that the server saw no job.

Run, from the repository root, after plugin/build_against_wheel.sh:
    python3 tests/run_fake_ibm_errors.py
It ends with one RESULT line. About a minute. Nothing here touches IBM.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_token_expiry import start_server, stop_server  # noqa: E402

PORT = 62461
URL = f"http://localhost:{PORT}/api"
IAM_URL = f"http://localhost:{PORT}/identity/token"
SUBMITTED = "answers with"  # the fake server prints this for every job

# name: (FAKE_IBM_FAULT, should the call fail?, text the output must hold,
#        may a job be sent?)
CASES = {
    "nan_angle": ("", True, "has an angle that is not a finite number", False),
    "infinite_angle": ("", True, "has an angle that is not a finite number",
                       False),
    "reset": ("", True, "reset is not supported on the 'ibm' target", False),
    "url_with_trailing_slash": ("", False, "COUNTS { 00:", True),
    "mapping_file_without_qubits": ("", True, "has no qubits", False),
    "login_html": ("login_html", True, "the login reply is not JSON", False),
    "config_html": ("config_html", True,
                    "the reply to GET /backends/ibm_sim/configuration is not "
                    "JSON", False),
    "status_unknown_once": ("status_unknown_once", False,
                            "the job has status 'PAUSED'", True),
    "status_missing": ("status_missing", True,
                       "the reply to GET /jobs/{id} lacks what IBM documents",
                       True),
    "results_missing": ("results_missing", True,
                        "/results lacks what IBM documents", True),
    "results_fewer_samples": ("results_fewer_samples", False,
                              "returned 10 samples for 20 shots", True),
}
# Text no case may print: a check must not warn about a healthy job.
NEVER = {
    "url_with_trailing_slash": "samples for",
    "future_saved_as_text": "samples for",
}
CASES["future_saved_as_text"] = ("", False, "COUNTS { 00:", True)


def run_case(name: str) -> None:
    """Child process: run one case and print COUNTS or raise."""
    os.environ["IBM_QUANTUM_API_KEY"] = "test-key"
    os.environ["IBM_QUANTUM_CRN"] = "test-crn"
    import cudaq
    import plugin_under_test
    plugin_under_test.register(cudaq)

    target = dict(backend="ibm_sim", url=URL, iam_url=IAM_URL)
    if name == "url_with_trailing_slash":
        target.update(url=URL + "/", iam_url=IAM_URL + "/")
    if name == "mapping_file_without_qubits":
        empty = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
        empty.write("this is not a device file\n")
        empty.close()
        target.update(mapping_file=empty.name)
    cudaq.set_target("ibm", **target)

    @cudaq.kernel
    def bell():
        q = cudaq.qvector(2)
        h(q[0])
        x.ctrl(q[0], q[1])
        mz(q)

    @cudaq.kernel
    def turn(a: float):
        q = cudaq.qvector(2)
        rx(a, q[0])
        h(q[1])
        mz(q)

    @cudaq.kernel
    def with_reset():
        q = cudaq.qvector(2)
        x(q[0])
        reset(q[0])
        x(q[1])
        mz(q)

    if name == "nan_angle":
        result = cudaq.sample(turn, float("nan"), shots_count=20)
    elif name == "infinite_angle":
        result = cudaq.sample(turn, float("inf"), shots_count=20)
    elif name == "reset":
        result = cudaq.sample(with_reset, shots_count=20)
    elif name == "future_saved_as_text":
        text = str(cudaq.sample_async(bell, shots_count=20))
        result = cudaq.AsyncSampleResult(text).get()
    else:
        result = cudaq.sample(bell, shots_count=20)
    print("COUNTS", result)


def check(name: str) -> tuple[bool, str]:
    fault, should_fail, expected, may_send = CASES[name]
    os.environ["FAKE_IBM_FAULT"] = fault
    process, log = start_server(ttl=0, polls=1, port=PORT)
    try:
        child = subprocess.run(
            [sys.executable, __file__, "--case", name],
            capture_output=True, text=True, timeout=120,
            env=dict(os.environ, PYTHONUNBUFFERED="1"))
    finally:
        server_lines = stop_server(process, log)
        os.environ.pop("FAKE_IBM_FAULT", None)
    output = child.stdout + child.stderr
    failed = child.returncode != 0
    sent = any(SUBMITTED in line for line in server_lines)
    problems = []
    if failed != should_fail:
        problems.append("failed" if failed else "did not fail")
    if expected not in output:
        problems.append(f"no {expected!r} in the output")
    if sent and not may_send:
        problems.append("a job was sent")
    if name in NEVER and NEVER[name] in output:
        problems.append(f"{NEVER[name]!r} in the output")
    if problems:
        tail = "\n".join(output.strip().splitlines()[-8:])
        return False, f"{'; '.join(problems)}\n      last lines:\n{tail}"
    line = next((l for l in output.splitlines() if expected in l), "")
    return True, line.strip()[:160]


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--case":
        run_case(sys.argv[2])
        return
    wanted = sys.argv[1:] or list(CASES)
    bad = 0
    for name in wanted:
        ok, detail = check(name)
        bad += not ok
        print(f"{'OK:  ' if ok else 'FAIL:'} {name}: {detail}", flush=True)
    print()
    if bad:
        print(f"RESULT: {bad} of {len(wanted)} error cases FAILED.")
        sys.exit(1)
    print(f"RESULT: all {len(wanted)} error cases give the expected answer.")


if __name__ == "__main__":
    main()
