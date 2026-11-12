# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""Probe the limits of the 'ibm' plugin against the fake IBM server.

    python3 experiments/limits/run.py                  # everything, ~5 min 
    python3 experiments/limits/run.py gates api        # some groups
    python3 experiments/limits/run.py --only ghz       # probes by name
    python3 experiments/limits/run.py --report out.md  # also write a table

Needs the built plugin (plugin/build_against_wheel.sh, or the installed wheel
with CUDAQ_IBM_PLUGIN=installed) and: pip install fastapi uvicorn
python-multipart stim. Nothing here touches IBM: every probe passes the
localhost urls (lib.py).

A probe is a function in cases_<group>.py that returns
{"outcome": ..., "detail": ...}. Each runs in its own process with a time
limit, because finding crashes and hangs is part of the job:

    same        the plugin's answer equals CUDA-Q's simulator (or the one
                answer the kernel can have)
    WRONG       an answer came back and it is not the right one
    error       an exception; the detail is the message the user sees
    CRASH       the Python process died
    HANG        no answer within the time limit
    other words (accepted, works, note, ...) are explained by their detail

A probe function may carry attributes, read here without importing it:
.fault (the PROBE_FAULT of a private probe_server.py), .server_env (a private
server without a fault), .env and .unset (environment of the probe),
.timeout (seconds).
"""

import argparse
import ast
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable
REPO = os.environ.get("PROBE_REPO", str(HERE.parents[1]))
SHARED_PORT = 62460
GROUPS = ("gates", "size", "api", "errors", "chip", "fuzz")
PREFIXES = "gsdaecf"   # g_ates, s_ize, d_epth, a_pi, e_rrors, c_hip, f_uzz


def wait_port(port, process=None, seconds=30.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        with socket.socket() as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        if process is not None and process.poll() is not None:
            return False
        time.sleep(0.2)
    return False


def start_server(port, logs, fault="", extra=None):
    env = dict(os.environ, PROBE_REPO=REPO, PROBE_FAULT=fault,
               PYTHONUNBUFFERED="1", FAKE_IBM_POLLS_BEFORE_DONE="0",
               **(extra or {}))
    log = open(logs / f"server-{port}.log", "w")
    process = subprocess.Popen([PY, str(HERE / "probe_server.py"), str(port)],
                               env=env, stdout=log, stderr=subprocess.STDOUT)
    if not wait_port(port, process):
        raise SystemExit(f"the probe server did not start on port {port}; "
                         f"see {log.name}")
    return process


def probes_of(module):
    """Names and attributes of the probes in a file, from its syntax tree."""
    tree = ast.parse((HERE / f"{module}.py").read_text())
    names, attrs = [], {}
    for node in tree.body:
        if (isinstance(node, ast.FunctionDef) and node.name[1] == "_"
                and node.name[0] in PREFIXES):
            names.append(node.name)
        if (isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Attribute)
                and isinstance(node.targets[0].value, ast.Name)):
            owner = node.targets[0].value.id
            attrs.setdefault(owner, {})[node.targets[0].attr] = \
                ast.literal_eval(node.value)
    return names, attrs


def how_it_ended(code):
    if code is not None and code < 0:
        return f"signal {signal.Signals(-code).name}"
    return f"exit code {code}"


def run_one(module, name, attrs, port, logs, default_timeout):
    a = attrs.get(name, {})
    server = None
    if "fault" in a or "server_env" in a:
        server = start_server(port, logs, a.get("fault", ""),
                              a.get("server_env"))
    else:
        port = SHARED_PORT
    env = dict(os.environ, PROBE_REPO=REPO, PROBE_PORT=str(port),
               IBM_QUANTUM_API_KEY="test-key", IBM_QUANTUM_CRN="test-crn")
    env.update(a.get("env", {}))
    for key in a.get("unset", []):
        env.pop(key, None)
    limit = a.get("timeout", default_timeout)
    started = time.monotonic()
    out_path = logs / f"{name}.out"
    with open(out_path, "w") as out:
        process = subprocess.Popen(
            [PY, str(HERE / "run_case.py"), module, name], env=env, cwd=HERE,
            stdout=out, stderr=subprocess.STDOUT)
        try:
            code, hung = process.wait(timeout=limit), False
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            code, hung = None, True
    took = time.monotonic() - started
    text = out_path.read_text(errors="replace")
    tail = [line for line in text.strip().splitlines()
            if not line.startswith(("[20", "PROBE "))]
    result = None
    for line in text.splitlines():
        if line.startswith("PROBE "):
            result = json.loads(line[6:])
    if hung:
        result = {"outcome": "HANG",
                  "detail": f"no answer after {limit} s"}
    elif result is None:
        result = {"outcome": "CRASH", "detail": f"{how_it_ended(code)}; "
                  "last output: " + " | ".join(tail[-2:])[-500:]}
    elif code != 0:
        result["outcome"] += "+CRASH"
        result["detail"] += f" [then the process ended: {how_it_ended(code)}]"
    result.update(name=name, group=module.removeprefix("cases_"),
                  wall=round(took, 1))
    if server is not None:
        server.terminate()
        server.wait()
        log = (logs / f"server-{port}.log").read_text()
        result["cz"] = [int(n) for n in
                        re.findall(r", (\d+) cz, all on", log)][-1:]
        result["bytes"] = [int(n) for n in
                           re.findall(r"job POST body: (\d+) bytes", log)][-1:]
    return result


def one_line(r):
    extra = "".join(f" {key}={r[key]}" for key in ("seconds", "cz", "bytes")
                    if r.get(key))
    return (f"{r['outcome']:<10} {r['name']:<46} {r['wall']:>6}s{extra} | "
            f"{r.get('detail', '')}")


def write_report(path, results, about):
    lines = [f"# Limit probes of the `ibm` plugin: results", "", about, "",
             "Made by `experiments/limits/run.py --report`. Outcomes are "
             "explained at the top of that file. `cz` and `bytes` are the "
             "two-qubit gates and the size of the last job sent.", ""]
    for group in GROUPS:
        rows = [r for r in results if r["group"] == group]
        if not rows:
            continue
        lines += [f"## {group}", "",
                  "| Probe | Outcome | Seconds | cz | Bytes | Detail |",
                  "|---|---|---|---|---|---|"]
        for r in rows:
            detail = r.get("detail", "").replace("|", "\\|").replace("\n", " ")
            detail = re.sub(r"\s+", " ", detail)[:400]
            lines.append(
                f"| `{r['name']}` | {r['outcome']} | "
                f"{r.get('seconds', r['wall'])} | "
                f"{(r.get('cz') or [''])[0]} | {(r.get('bytes') or [''])[0]} "
                f"| {detail} |")
        lines.append("")
    counts = {}
    for r in results:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    lines += ["## Totals", "",
              ", ".join(f"{n} {word}" for word, n in sorted(counts.items())),
              ""]
    Path(path).write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("groups", nargs="*", help=f"some of: {GROUPS}")
    parser.add_argument("--only", default="", help="substring of probe names")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--logs", default="/tmp/cudaq-ibm-limit-probes")
    parser.add_argument("--report", help="write a Markdown table here")
    parser.add_argument("--about", default="", help="a line for the report")
    args = parser.parse_args()
    logs = Path(args.logs)
    logs.mkdir(parents=True, exist_ok=True)

    todo = []
    for group in args.groups or GROUPS:
        module = f"cases_{group}"
        names, attrs = probes_of(module)
        todo += [(module, name, attrs) for name in names if args.only in name]
    # Our own shared server, always: one left over from another run may be
    # about to stop, or may have a fault switched on.
    free_by = time.monotonic() + 15
    while wait_port(SHARED_PORT, seconds=0.3):
        if time.monotonic() > free_by:
            raise SystemExit(f"port {SHARED_PORT} is in use; stop the other "
                             "run or server first")
        time.sleep(0.5)
    shared = start_server(SHARED_PORT, logs)
    results = []
    try:
        with ThreadPoolExecutor(args.jobs) as pool:
            futures = [pool.submit(run_one, module, name, attrs, 62500 + i,
                                   logs, args.timeout)
                       for i, (module, name, attrs) in enumerate(todo)]
            for future in futures:
                results.append(future.result())
                print(one_line(results[-1])[:700], flush=True)
    finally:
        shared.terminate()
        shared.wait()
    (logs / "results.json").write_text(json.dumps(results, indent=1))
    if args.report:
        write_report(args.report, results, args.about)
    print(f"\n{len(results)} probes; full output of each in {logs}")


if __name__ == "__main__":
    main()
