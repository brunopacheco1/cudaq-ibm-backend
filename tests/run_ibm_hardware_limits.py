# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""Limits on real hardware: how wide, how deep, and what IBM answers to bad
input. SPENDS QPU TIME: 10 jobs with the default parts.

The limit probes (experiments/limits) run against a fake chip without noise.
This run asks what only a real chip can answer. It measures; there is no pass
mark. Write down what you expect BEFORE the run, then compare.

width       GHZ as a chain on 5, 10, 20, 40 and 80 qubits: h on the first
            qubit, then cx from each qubit to the next. Without noise every
            shot is all 0 or all 1. Printed: the share of such shots, and how
            often two neighbours of the chain agree (the mean over all pairs
            and the weakest pair), which shows where a chain breaks.
depth       Two qubits: x on the first, then 1, 11, 101 and 1001 cx in a
            row. An odd number of cx always gives 11. Printed: the share of
            11. Noise that hits all four answers alike gives 25%; qubits
            that lose their energy on the way end in 00, which gives less.
bad-input   An angle that is NaN (10 shots): the plugin sends it
            (docs/architecture.md, section 8 item 9); printed: what IBM
            answers. And shots_count=0, for which CUDA-Q sends no job and
            returns an empty result.
rate-limit  Only when named in --parts. Six jobs of one shot without a pause.
            IBM documents 5 jobs per minute per user; printed: what happens
            to the sixth.

A rough expectation for width and depth: every cz and every readout succeeds
or fails on its own, so the share is about
(1 - cz error)^(number of cz) * (1 - readout error)^(number of qubits).

Between two jobs the script waits until 13 s have passed, to stay below
IBM's 5 jobs per minute. A job that fails does not stop the run.

Run it only after tests/run_fake_ibm_results.py passes. From the repository
root, with a local build (plugin/build_against_wheel.sh):

    python3 tests/run_ibm_hardware_limits.py --yes-spend-qpu-time

With the installed wheel, set CUDAQ_IBM_PLUGIN=installed first. Fewer jobs:
--parts depth, --widths 5,20, --depths 1,101.

A free rehearsal against the fake IBM server instead of IBM (needs fastapi,
uvicorn and python-multipart; no noise, so every share is 100%, the NaN
angle is refused and no job is refused for coming too fast):

    python3 tests/run_ibm_hardware_limits.py --fake

--trace (width part only) also says where each chain ran: for every job,
the links and qubits with the highest errors in IBM's calibration data, what
that data alone predicts for the circuit, and the IBM qubits of every weak
pair. It costs one login and one GET more, no extra job (hardware_trace.py).
To look at one width again:

    python3 tests/run_ibm_hardware_limits.py --parts width --widths 40 \
        --trace --yes-spend-qpu-time

The rehearsal samples chains of more than 24 qubits with Stim (pip install
stim; on Linux aarch64 pip builds it and needs g++). Without Stim it skips
them and says so.

Credentials: IBM_QUANTUM_API_KEY and IBM_QUANTUM_CRN from the environment,
or from the git-ignored .env at the repository root. They are never printed.
"""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import hardware_trace  # noqa: E402
import plugin_under_test  # noqa: E402
from run_ibm_hardware import ROOT, load_env_file  # noqa: E402

FAKE_PORT = 62459
PARTS = ("width", "depth", "bad-input", "rate-limit")
SECONDS_BETWEEN_JOBS = 13.0   # IBM: 5 jobs per minute per user
WIDEST_WITHOUT_STIM = 24      # the fake server's own simulator stops there
WEAK_PAIR = 0.90              # neighbours that agree less often are listed


def ghz_chain(cudaq, n: int):
    """No `mz`: `sample` then measures every qubit, in allocation order. With
    the wheel v0.1.0rc1 a kernel with `mz` on 50 or more qubits does not
    compile (docs/architecture.md, section 8 item 9)."""
    kernel = cudaq.make_kernel()
    q = kernel.qalloc(n)
    kernel.h(q[0])
    for i in range(n - 1):
        kernel.cx(q[i], q[i + 1])
    return kernel


def many_cx(cudaq, n: int):
    kernel = cudaq.make_kernel()
    q = kernel.qalloc(2)
    kernel.x(q[0])
    for _ in range(n):
        kernel.cx(q[0], q[1])
    kernel.mz(q)
    return kernel


def one_rx(cudaq, angle: float):
    kernel = cudaq.make_kernel()
    q = kernel.qalloc(1)
    kernel.rx(angle, q[0])
    kernel.mz(q)
    return kernel


def one_x(cudaq):
    kernel = cudaq.make_kernel()
    q = kernel.qalloc(1)
    kernel.x(q[0])
    kernel.mz(q)
    return kernel


def neighbours_agree(counts: dict[str, int]) -> list[float]:
    """For each pair (i, i+1) of the chain, the share of shots in which the
    two bits are equal."""
    shots = sum(counts.values())
    width = len(next(iter(counts)))
    return [sum(n for bits, n in counts.items() if bits[i] == bits[i + 1])
            / shots for i in range(width - 1)]


def most_frequent(counts: dict[str, int], many: int = 3) -> str:
    def short(bits):
        return bits if len(bits) <= 12 else f"{bits[:5]}..{bits[-5:]}"
    top = sorted(counts.items(), key=lambda item: -item[1])[:many]
    return ", ".join(f"{short(bits)}:{n}" for bits, n in top)


class Jobs:
    """Sends one job at a time, keeps IBM's pace, and never raises."""

    def __init__(self, cudaq, pause: float):
        self.cudaq, self.pause = cudaq, pause
        self.last, self.sent, self.failed = None, 0, 0

    def wait_for_pace(self):
        if self.last is not None:
            left = self.pause - (time.monotonic() - self.last)
            if left > 0:
                time.sleep(left)
        self.last = time.monotonic()

    def sample(self, kernel, shots: int):
        """(counts, seconds, None) or (None, seconds, the error text)."""
        self.wait_for_pace()
        self.sent += 1
        started = time.monotonic()
        try:
            counts = dict(self.cudaq.sample(kernel, shots_count=shots).items())
            return counts, time.monotonic() - started, None
        except Exception as error:  # the message is the result of the probe
            self.failed += 1
            text = " ".join(str(error).split())[:300]
            return None, time.monotonic() - started, text


def child(n: int, shots: int, target: dict) -> int:
    """One GHZ job in a process of its own, so that the parent can read the
    plugin's info log of exactly this job. Prints one line for the parent."""
    import cudaq
    try:
        plugin_under_test.register(cudaq)
        cudaq.set_target("ibm", **target)
        counts = dict(cudaq.sample(ghz_chain(cudaq, n),
                                   shots_count=shots).items())
        print("\nCHILD-COUNTS " + json.dumps(counts), flush=True)
    except Exception as error:
        print("\nCHILD-ERROR " + " ".join(str(error).split())[:300],
              flush=True)
    return 0


def traced_sample(jobs, n: int, shots: int, target: dict):
    """(counts, seconds, error text, the job's info log)."""
    jobs.wait_for_pace()
    jobs.sent += 1
    started = time.monotonic()
    done = subprocess.run(
        [sys.executable, "-W", "ignore", __file__, "--child",
         json.dumps({"n": n, "shots": shots, "target": target})],
        env=dict(os.environ, CUDAQ_LOG_LEVEL="info"),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    seconds = time.monotonic() - started
    counts = error = None
    for line in done.stdout.splitlines():
        if line.startswith("CHILD-COUNTS "):
            counts = json.loads(line[len("CHILD-COUNTS "):])
        elif line.startswith("CHILD-ERROR "):
            error = line[len("CHILD-ERROR "):]
    if counts is None:
        jobs.failed += 1
        error = error or f"the job's process ended with code {done.returncode}"
    return counts, seconds, error, done.stdout


def width_part(jobs, cudaq, widths, shots, widest, trace=None):
    """`trace`: None, or (target, readout errors, link errors)."""
    for n in widths:
        if n > widest:
            print(f"LIMIT width {n:>4}: skipped in this rehearsal: the fake "
                  f"server needs Stim above {widest} qubits (pip install "
                  "stim). The real run does not need it.")
            continue
        log = None
        if trace:
            counts, seconds, error, log = traced_sample(jobs, n, shots,
                                                        trace[0])
        else:
            counts, seconds, error = jobs.sample(ghz_chain(cudaq, n), shots)
        if error:
            print(f"LIMIT width {n:>4}: ERROR after {seconds:.0f} s: {error}")
            continue
        total = sum(counts.values())
        whole = (counts.get("0" * n, 0) + counts.get("1" * n, 0)) / total
        pairs = neighbours_agree(counts)
        weakest = min(range(n - 1), key=lambda i: pairs[i])
        print(f"LIMIT width {n:>4}: all 0 or all 1 in {whole:6.1%} of "
              f"{total} shots; neighbours agree: mean "
              f"{sum(pairs) / len(pairs):.1%}, weakest pair "
              f"({weakest},{weakest + 1}) {pairs[weakest]:.1%}; "
              f"{seconds:.0f} s; most frequent: {most_frequent(counts)}")
        weak = [(i, share) for i, share in enumerate(pairs)
                if share < WEAK_PAIR]
        if weak:
            # One weak pair: the chain broke between two qubits. Two weak
            # pairs side by side, (i-1,i) and (i,i+1): qubit i itself.
            print(f"LIMIT width {n:>4}: pairs that agree in less than "
                  f"{WEAK_PAIR:.0%} of the shots: "
                  + ", ".join(f"({i},{i + 1}) {share:.1%}"
                              for i, share in weak[:20])
                  + (f" and {len(weak) - 20} more" if len(weak) > 20 else ""))
        if trace:
            try:
                for line in hardware_trace.report(
                        f"TRACE width {n:>4}", hardware_trace.parse_log(log),
                        trace[1], trace[2], [i for i, _ in weak]):
                    print(line)
            except ValueError as problem:
                print(f"TRACE width {n:>4}: no trace: {problem}")


def depth_part(jobs, cudaq, depths, shots):
    for n in depths:
        counts, seconds, error = jobs.sample(many_cx(cudaq, n), shots)
        if error:
            print(f"LIMIT depth {n:>4} cx: ERROR after {seconds:.0f} s: "
                  f"{error}")
            continue
        total = sum(counts.values())
        print(f"LIMIT depth {n:>4} cx: 11 in {counts.get('11', 0) / total:6.1%}"
              f" of {total} shots; {seconds:.0f} s; "
              f"most frequent: {most_frequent(counts, 4)}")


def bad_input_part(jobs, cudaq):
    counts, seconds, error = jobs.sample(one_rx(cudaq, float("nan")), 10)
    if error:
        print(f"LIMIT bad input, angle NaN, 10 shots: refused after "
              f"{seconds:.0f} s: {error}")
    else:
        print(f"LIMIT bad input, angle NaN, 10 shots: ACCEPTED, "
              f"{sum(counts.values())} samples back after {seconds:.0f} s: "
              f"{most_frequent(counts) or 'nothing'}")
    # No job: cudaq.sample runs the kernel until it has shots_count shots,
    # so with 0 it never sends one (sample.py:174, tag 0.16.0). Not counted
    # as a job and not paced.
    try:
        counts = dict(cudaq.sample(one_x(cudaq), shots_count=0).items())
        print(f"LIMIT bad input, shots_count=0: no job is sent; "
              f"{sum(counts.values())} samples and no error")
    except Exception as error:
        print("LIMIT bad input, shots_count=0: "
              f"{' '.join(str(error).split())[:300]}")


def rate_limit_part(jobs, cudaq):
    """Six jobs without a pause. sample_async returns once the job is sent,
    so the six POSTs follow each other within seconds."""
    kernel = one_x(cudaq)
    futures = []
    for k in range(1, 7):
        jobs.sent += 1
        try:
            futures.append((k, cudaq.sample_async(kernel, shots_count=1)))
        except Exception as error:
            jobs.failed += 1
            print(f"LIMIT rate limit, job {k}: refused when sent: "
                  f"{' '.join(str(error).split())[:300]}")
    for k, future in futures:
        try:
            counts = dict(future.get().items())
            print(f"LIMIT rate limit, job {k}: ran, {most_frequent(counts)}")
        except Exception as error:
            jobs.failed += 1
            print(f"LIMIT rate limit, job {k}: failed: "
                  f"{' '.join(str(error).split())[:300]}")
    jobs.last = time.monotonic()


def numbers(text: str) -> list[int]:
    return [int(part) for part in text.split(",") if part]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backend", default="ibm_fez")
    parser.add_argument("--parts", default="width,depth,bad-input",
                        help=f"comma-separated, some of: {', '.join(PARTS)}")
    parser.add_argument("--widths", type=numbers, default=[5, 10, 20, 40, 80])
    parser.add_argument("--depths", type=numbers, default=[1, 11, 101, 1001],
                        help="numbers of cx; use odd numbers")
    parser.add_argument("--shots", type=int, default=1000)
    parser.add_argument("--trace", action="store_true",
                        help="width part: also print the IBM links and "
                             "qubits each job used, with their errors in "
                             "IBM's calibration data")
    parser.add_argument("--child", help=argparse.SUPPRESS)
    parser.add_argument("--yes-spend-qpu-time", action="store_true",
                        help="confirms that real jobs may be sent")
    parser.add_argument("--fake", action="store_true",
                        help="rehearsal against the fake IBM server: free, "
                             "never touches IBM")
    args = parser.parse_args()
    if args.child:      # started by traced_sample(), never by hand
        job = json.loads(args.child)
        return child(job["n"], job["shots"], job["target"])
    parts = [part for part in args.parts.split(",") if part]
    if args.fake == args.yes_spend_qpu_time:
        print("Refusing to run: add --yes-spend-qpu-time to send real jobs, "
              "or --fake for a free rehearsal (not both).")
        return 2
    if not parts or any(part not in PARTS for part in parts):
        print(f"--parts takes some of: {', '.join(PARTS)}")
        return 2
    if any(n < 2 for n in args.widths) or any(n % 2 == 0 for n in args.depths):
        print("--widths needs numbers from 2 up; --depths needs odd numbers "
              "(an even number of cx gives 10, not 11).")
        return 2

    planned = ((len(args.widths) if "width" in parts else 0)
               + (len(args.depths) if "depth" in parts else 0)
               + (1 if "bad-input" in parts else 0)
               + (6 if "rate-limit" in parts else 0))
    server = None
    if args.fake:
        # Test credentials replace any real ones: the real key must never be
        # sent to another server, not even to localhost.
        os.environ["IBM_QUANTUM_API_KEY"] = "test-key"
        os.environ["IBM_QUANTUM_CRN"] = "test-crn"
        from run_token_expiry import start_server, stop_server
        # The probe server is the fake server plus Stim, which samples the
        # GHZ circuits that are too wide for the fake server's own simulator.
        server = start_server(
            ttl=0, polls=0, port=FAKE_PORT,
            server=ROOT / "experiments" / "limits" / "probe_server.py")
        target = dict(backend="ibm_fake",
                      url=f"http://localhost:{FAKE_PORT}/api",
                      iam_url=f"http://localhost:{FAKE_PORT}/identity/token")
        pause = 0.0
        widest = (max(args.widths) if importlib.util.find_spec("stim")
                  else WIDEST_WITHOUT_STIM)
    else:
        load_env_file()
        for name in ("IBM_QUANTUM_API_KEY", "IBM_QUANTUM_CRN"):
            if not os.environ.get(name):
                print(f"Set {name} (environment or .env).")
                return 2
        target = dict(backend=args.backend)
        pause = SECONDS_BETWEEN_JOBS
        widest = max(args.widths)

    import cudaq

    print(f"Limits on {target['backend']}: parts {', '.join(parts)}; up to "
          f"{planned} jobs, {args.shots} shots each for width and depth.")
    try:
        plugin_under_test.register(cudaq)
        cudaq.set_target("ibm", **target)
        jobs = Jobs(cudaq, pause)
        trace = None
        if args.trace and "width" in parts:
            # Now, and not after the jobs: the plugin reads the same data
            # when it compiles, and IBM renews it a few times a day.
            properties = hardware_trace.fetch_properties(
                target["backend"], os.environ["IBM_QUANTUM_API_KEY"],
                os.environ["IBM_QUANTUM_CRN"],
                **({"url": target["url"], "iam_url": target["iam_url"]}
                   if args.fake else {}))
            trace = (target, *hardware_trace.chip_errors(properties))
        if "width" in parts:
            width_part(jobs, cudaq, args.widths, args.shots, widest, trace)
        if "depth" in parts:
            depth_part(jobs, cudaq, args.depths, args.shots)
        if "bad-input" in parts:
            bad_input_part(jobs, cudaq)
        if "rate-limit" in parts:
            jobs.wait_for_pace()
            rate_limit_part(jobs, cudaq)
    finally:
        if server:
            stop_server(*server)
    print(f"RESULT: {jobs.sent} jobs sent, {jobs.failed} refused or failed. "
          "Compare the lines above with what you wrote down before the run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
