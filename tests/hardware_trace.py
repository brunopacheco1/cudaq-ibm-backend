# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""Which IBM qubits and links did a job use, and how good are they?

Used by tests/run_ibm_hardware_limits.py --trace. Three steps:

1. parse_log()   reads the plugin's own info log of one job
                 (CUDAQ_LOG_LEVEL=info): the cz gates of the circuit it sent
                 and the IBM qubit each result bit is measured on.
2. fetch_properties() / chip_errors()
                 reads IBM's calibration data for the backend: the readout
                 error of each qubit and the cz error of each link. One login
                 and one GET, no job, no QPU time.
3. report()      puts the two together: the links and qubits with the highest
                 errors, and what the calibration data alone would predict.

The log is parsed and never printed: at info level it holds the whole
circuit and every sample. The API key goes to IBM's login only, over
verified TLS, as in experiments/fetch_chip_data.py; it is never printed.
"""

import re

API_URL = "https://quantum.cloud.ibm.com/api"
IAM_URL = "https://iam.cloud.ibm.com/identity/token"

ISA_START = "IBM: ISA circuit for"
CZ = re.compile(r"^cz \$(\d+), \$(\d+);$")
MEASURE = re.compile(r"^c\[(\d+)\] = measure \$(\d+);$")


def parse_log(text: str) -> dict:
    """{"cz": [(a, b), ...], "measured": {bit: IBM qubit}} for the last
    circuit in the log. Bit i is the kernel's qubit i (plugin/ResultBits.h).
    Raises ValueError when the log holds no circuit."""
    start = text.rfind(ISA_START)
    if start < 0:
        raise ValueError("no ISA circuit in the log; is CUDAQ_LOG_LEVEL=info "
                         "set, and did the job get as far as the rewrite?")
    cz, measured = [], {}
    for line in text[start:].splitlines()[1:]:
        line = line.strip()
        if line.startswith("["):       # the next log message
            break
        if m := CZ.match(line):
            cz.append((int(m[1]), int(m[2])))
        elif m := MEASURE.match(line):
            measured[int(m[1])] = int(m[2])
    return {"cz": cz, "measured": measured}


def chip_errors(properties: dict) -> tuple[dict, dict]:
    """(readout error per qubit, cz error per link) from IBM's /properties.
    A link is a sorted pair; IBM lists it once per direction and the worse
    error counts, as in plugin/ChipData.h. A value IBM does not give is
    None."""
    readout = {}
    for q, entries in enumerate(properties.get("qubits", [])):
        for entry in entries:
            if entry.get("name") == "readout_error":
                readout[q] = entry.get("value")
    links = {}
    for gate in properties.get("gates", []):
        if gate.get("gate") != "cz" or len(gate.get("qubits", [])) != 2:
            continue
        link = tuple(sorted(gate["qubits"]))
        error = None
        for parameter in gate.get("parameters", []):
            if parameter.get("name") == "gate_error":
                error = parameter.get("value")
        if link not in links:
            links[link] = error
        elif error is not None and (links[link] is None
                                    or error > links[link]):
            links[link] = error
    return readout, links


def fetch_properties(backend: str, key: str, crn: str, url: str = API_URL,
                     iam_url: str = IAM_URL) -> dict:
    """IBM's calibration data for `backend`. Two requests, no job.

    With `requests`, as in experiments/fetch_chip_data.py: IBM answered a GET
    from Python's built-in urllib with HTTP 403 (2026-11-12). CUDA-Q installs
    `requests`. Raises RuntimeError with the HTTP status when IBM refuses."""
    import requests

    login = requests.post(
        iam_url,
        data={"grant_type": "urn:ibm:params:oauth:grant-type:apikey",
              "apikey": key},
        headers={"Accept": "application/json"}, timeout=30)
    if not login.ok:
        # Not the body: a login reply is no place to print from.
        raise RuntimeError(f"IBM login failed: HTTP {login.status_code}")
    reply = requests.get(
        f"{url}/v1/backends/{backend}/properties",
        headers={"Authorization": f"Bearer {login.json()['access_token']}",
                 "Service-CRN": crn, "Accept": "application/json"},
        timeout=60)
    if not reply.ok:
        raise RuntimeError(
            f"GET /v1/backends/{backend}/properties failed: HTTP "
            f"{reply.status_code}: {reply.text[:200]!r}")
    return reply.json()


def percent(value) -> str:
    return "unknown" if value is None else f"{value:.2%}"


def report(label: str, circuit: dict, readout: dict, links: dict,
           weak_pairs: list[int], many: int = 5) -> list[str]:
    """The lines to print for one traced job. `weak_pairs` holds each i for
    which the neighbours (i, i+1) of the chain agree too rarely."""
    lines = []
    used = {}
    for a, b in circuit["cz"]:
        link = tuple(sorted((a, b)))
        used[link] = used.get(link, 0) + 1
    measured = circuit["measured"]

    survive_cz, unknown_cz = 1.0, 0
    for link, count in used.items():
        error = links.get(link)
        if error is None:
            unknown_cz += count
        else:
            survive_cz *= (1.0 - error) ** count
    survive_readout, unknown_readout = 1.0, 0
    for qubit in measured.values():
        error = readout.get(qubit)
        if error is None:
            unknown_readout += 1
        else:
            survive_readout *= 1.0 - error
    unknown = ""
    if unknown_cz or unknown_readout:
        unknown = (f" ({unknown_cz} cz and {unknown_readout} readouts have "
                   "no error in IBM's data and count as perfect)")
    lines.append(
        f"{label}: {len(circuit['cz'])} cz on {len(used)} links, "
        f"{len(measured)} qubits measured. IBM's calibration alone predicts: "
        f"every cz right {survive_cz:.1%}, every readout right "
        f"{survive_readout:.1%}, both {survive_cz * survive_readout:.1%}"
        f"{unknown}")

    def worst_first(item):
        return -1.0 if item[1] is None else -item[1]

    by_link = sorted(((link, links.get(link)) for link in used),
                     key=worst_first)[:many]
    lines.append(f"{label}: links used with the highest cz error: " + ", ".join(
        f"{a}-{b} {percent(error)} ({used[(a, b)]} cz)"
        for (a, b), error in by_link))
    by_qubit = sorted(((bit, readout.get(qubit)) for bit, qubit
                       in measured.items()), key=worst_first)[:many]
    lines.append(f"{label}: highest readout errors: " + ", ".join(
        f"chain qubit {bit} on IBM qubit {measured[bit]} {percent(error)}"
        for bit, error in by_qubit))
    for i in weak_pairs:
        if i not in measured or i + 1 not in measured:
            continue
        a, b = measured[i], measured[i + 1]
        link = tuple(sorted((a, b)))
        if link in links:
            how = (f"linked, cz error {percent(links[link])}, used by "
                   f"{used.get(link, 0)} cz")
        else:
            how = "not linked on the chip at the end of the circuit"
        lines.append(
            f"{label}: weak pair ({i},{i + 1}) is measured on IBM qubits "
            f"{a} and {b}: readout errors {percent(readout.get(a))} and "
            f"{percent(readout.get(b))}; {how}")
    return lines


def main() -> int:
    """Free check of step 2: read the calibration data, print a summary."""
    import argparse
    import os
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from run_ibm_hardware import load_env_file

    parser = argparse.ArgumentParser(
        description="Read IBM's calibration data of a backend and print a "
                    "summary. One login and one GET: no job, no QPU time.")
    parser.add_argument("backend", nargs="?", default="ibm_fez")
    args = parser.parse_args()
    load_env_file()
    for name in ("IBM_QUANTUM_API_KEY", "IBM_QUANTUM_CRN"):
        if not os.environ.get(name):
            print(f"Set {name} (environment or .env).")
            return 2
    try:
        readout, links = chip_errors(fetch_properties(
            args.backend, os.environ["IBM_QUANTUM_API_KEY"],
            os.environ["IBM_QUANTUM_CRN"]))
    except Exception as error:  # noqa: BLE001 - any failure is the answer
        print(f"TRACE-CHECK: failed: {type(error).__name__}: {error}")
        return 1
    worst = sorted((item for item in links.items() if item[1] is not None),
                   key=lambda item: -item[1])[:5]
    print(f"TRACE-CHECK: {args.backend}: readout error for {len(readout)} "
          f"qubits, cz error for {len(links)} links. Highest cz errors: "
          + ", ".join(f"{a}-{b} {percent(error)}" for (a, b), error in worst))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
