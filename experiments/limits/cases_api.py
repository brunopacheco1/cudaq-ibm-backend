# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""The calls around a kernel: shots, async, other CUDA-Q entry points,
target arguments, many jobs."""
import glob
import os
import subprocess
import sys
import threading
import time

from lib import *


@cudaq.kernel
def bell():
    q = cudaq.qvector(2)
    h(q[0]); x.ctrl(q[0], q[1])


@cudaq.kernel
def flip(n: int):
    q = cudaq.qvector(3)
    for i in range(n):
        x(q[i])


@cudaq.kernel
def turn(a: float):
    q = cudaq.qvector(2)
    ry(a, q[0]); x.ctrl(q[0], q[1])


def bell_ok(got, shots):
    return (set(got) <= {"00", "11"} and sum(got.values()) == shots
            and (shots < 50 or abs(got.get("00", 0) - shots / 2) < 0.2 * shots))


def shots_case(shots):
    ibm()
    t = time.monotonic()
    r = cudaq.sample(bell, shots_count=shots) if shots is not None else cudaq.sample(bell)
    got = counts(r)
    took = round(time.monotonic() - t, 2)
    want = 1000 if shots is None else shots
    ok = bell_ok(got, want)
    return {"outcome": "same" if ok else "WRONG", "seconds": took,
            "detail": f"{sum(got.values())} samples back for shots={shots}: {top(got)}"}


def a_shots_default(): return shots_case(None)
def a_shots_1(): return shots_case(1)
def a_shots_0():
    """No job is sent: cudaq.sample loops until it has `shots_count` shots,
    so with 0 it never runs the kernel (python/cudaq/runtime/sample.py:174,
    tag 0.16.0). The private server shows it: no POST, so no `bytes`."""
    ibm()
    got = counts(cudaq.sample(bell, shots_count=0))
    return {"outcome": "empty" if not got else "UNEXPECTED",
            "detail": f"{sum(got.values())} samples and no error for "
                      "shots=0; CUDA-Q sends no job (the Bytes column is "
                      "empty: the server saw no POST)"}
def a_shots_negative(): return shots_case(-5)
def a_shots_100_000(): return shots_case(100_000)
def a_shots_1_000_000(): return shots_case(1_000_000)
def a_shots_10_000_000(): return shots_case(10_000_000)


a_shots_0.server_env = {}


def a_sample_async_one():
    ibm()
    f = cudaq.sample_async(bell, shots_count=500)
    got = counts(f.get())
    return {"outcome": "same" if bell_ok(got, 500) else "WRONG", "detail": top(got)}


def a_sample_async_twenty_at_once():
    ibm()
    t = time.monotonic()
    futures = [cudaq.sample_async(flip, k % 4, shots_count=50) for k in range(20)]
    got = [counts(f.get()) for f in futures]
    want = [{"1" * (k % 4) + "0" * (3 - k % 4): 50} for k in range(20)]
    return {"outcome": "same" if got == want else "WRONG", "seconds": round(time.monotonic() - t, 2),
            "detail": f"20 jobs, each with its own answer; first four: {got[:4]}"}


def a_sample_async_saved_as_text_and_read_back():
    ibm()
    f = cudaq.sample_async(flip, 2, shots_count=50)
    text = str(f)
    again = cudaq.AsyncSampleResult(text)
    got = counts(again.get())
    return {"outcome": "same" if got == {"110": 50} else "WRONG",
            "detail": f"{got}; the saved text has {len(text)} characters"}


def a_sample_list_of_arguments():
    ibm()
    out = cudaq.sample(flip, [0, 1, 2, 3], shots_count=20)
    got = [counts(r) for r in out]
    want = [{"000": 20}, {"100": 20}, {"110": 20}, {"111": 20}]
    return {"outcome": "same" if got == want else "WRONG", "detail": str(got)}


def a_observe():
    ibm()
    from cudaq import spin
    r = cudaq.observe(bell, spin.z(0) * spin.z(1))
    return {"outcome": "UNEXPECTED", "detail": f"observe returned {r.expectation()}"}


def a_observe_async():
    ibm()
    from cudaq import spin
    r = cudaq.observe_async(bell, spin.z(0) * spin.z(1)).get()
    return {"outcome": "UNEXPECTED", "detail": f"observe_async returned {r.expectation()}"}


def a_emulate():
    ibm(emulate=True)
    return {"outcome": "UNEXPECTED", "detail": f"emulate returned {top(counts(cudaq.sample(bell)))}"}


def a_get_state():
    ibm()
    s = cudaq.get_state(bell)
    return {"outcome": "UNEXPECTED", "detail": f"get_state returned {s}"}


def a_get_state_async():
    ibm()
    s = cudaq.get_state_async(bell).get()
    return {"outcome": "UNEXPECTED", "detail": f"get_state_async returned {s}"}


def a_draw_while_ibm_is_the_target():
    ibm()
    drawing = cudaq.draw(bell)
    return {"outcome": "works" if "h" in drawing else "empty",
            "detail": f"cudaq.draw returned {len(drawing)} characters"}


def a_translate_while_ibm_is_the_target():
    ibm()
    qasm = cudaq.translate(bell, format="openqasm2")
    return {"outcome": "works" if "OPENQASM" in qasm else "empty",
            "detail": f"cudaq.translate returned {len(qasm.splitlines())} lines of OpenQASM 2 (textbook gates, not what the plugin sends)"}


def a_estimate_resources():
    ibm()
    r = cudaq.estimate_resources(bell)
    return {"outcome": "works", "detail": str(r).replace("\n", " ")[:200]}


def a_noise_model_argument():
    ibm()
    noise = cudaq.NoiseModel()
    noise.add_all_qubit_channel("x", cudaq.BitFlipChannel(0.5))
    got = counts(cudaq.sample(bell, shots_count=200, noise_model=noise))
    return {"outcome": "ignored" if bell_ok(got, 200) else "WRONG",
            "detail": f"the noise model had no effect, no warning: {top(got)}"}


def a_explicit_measurements():
    ibm()
    got = counts(cudaq.sample(bell, shots_count=20, explicit_measurements=True))
    return {"outcome": "note", "detail": top(got, 6)}


def a_result_methods():
    ibm()
    r = cudaq.sample(turn, 0.9, shots_count=2000)
    seq = r.get_sequential_data()
    cudaq.set_target("qpp-cpu")
    sim_seq = cudaq.sample(turn, 0.9, shots_count=2000).get_sequential_data()
    marg = counts(r.get_marginal_counts([0]))
    detail = (f"most_probable {r.most_probable()}, probability {r.probability('00'):.2f}, "
              f"expectation {r.expectation():.2f}, marginal on q0 {marg}, "
              f"per-shot data: {len(seq)} entries (the simulator gives {len(sim_seq)})")
    return {"outcome": "works" if len(seq) == 2000 else "partly",
            "detail": detail}


# ---- target arguments and environment -----------------------------------------
def a_no_api_key():
    ibm(); return {"outcome": "UNEXPECTED", "detail": top(counts(cudaq.sample(bell)))}


def a_empty_crn():
    ibm(); return {"outcome": "UNEXPECTED", "detail": top(counts(cudaq.sample(bell)))}


def a_wrong_api_key():
    ibm(); return {"outcome": "UNEXPECTED", "detail": top(counts(cudaq.sample(bell)))}


def a_wrong_crn():
    ibm(); return {"outcome": "UNEXPECTED", "detail": top(counts(cudaq.sample(bell)))}


def a_nothing_listens_on_the_url():
    cudaq.set_target("ibm", backend="ibm_fake", url="http://localhost:9/api",
                     iam_url=f"http://localhost:{PORT}/identity/token")
    return {"outcome": "UNEXPECTED", "detail": top(counts(cudaq.sample(bell)))}


def a_nothing_listens_on_the_login_url():
    cudaq.set_target("ibm", backend="ibm_fake", url=f"http://localhost:{PORT}/api",
                     iam_url="http://localhost:9/identity/token")
    return {"outcome": "UNEXPECTED", "detail": top(counts(cudaq.sample(bell)))}


def a_url_with_trailing_slash():
    cudaq.set_target("ibm", backend="ibm_fake", url=f"http://localhost:{PORT}/api/",
                     iam_url=f"http://localhost:{PORT}/identity/token")
    got = counts(cudaq.sample(bell, shots_count=100))
    return {"outcome": "same" if bell_ok(got, 100) else "WRONG", "detail": top(got)}


def a_backend_name_with_a_slash():
    ibm(backend="ibm/fez")
    got = counts(cudaq.sample(bell, shots_count=100))
    return {"outcome": "UNEXPECTED", "detail": top(got)}


def a_backend_name_empty():
    cudaq.set_target("ibm", backend="", url=f"http://localhost:{PORT}/api",
                     iam_url=f"http://localhost:{PORT}/identity/token")
    got = counts(cudaq.sample(bell, shots_count=100))
    return {"outcome": "note", "detail": "an empty backend name falls back to the default ibm_fez: " + top(got)}


def a_unknown_target_argument():
    ibm(colour="blue")
    got = counts(cudaq.sample(bell, shots_count=100))
    return {"outcome": "ignored", "detail": "an unknown target argument is accepted silently: " + top(got)}


def a_mapping_file_missing():
    ibm(mapping_file="/nonexistent/chip.txt")
    return {"outcome": "UNEXPECTED", "detail": top(counts(cudaq.sample(bell)))}


def a_mapping_file_garbage():
    path = "/tmp/probe-garbage-chip.txt"
    open(path, "w").write("this is not a device file\n")
    ibm(mapping_file=path)
    return {"outcome": "UNEXPECTED", "detail": top(counts(cudaq.sample(bell, shots_count=10)))}


def a_mapping_file_two_islands():
    path = "/tmp/probe-islands-chip.txt"
    open(path, "w").write("Number of nodes: 4\nNumber of edges: 2\n0 --> {1}\n1 --> {0}\n2 --> {3}\n3 --> {2}\n")
    ibm(mapping_file=path)
    got = counts(cudaq.sample(flip, 3, shots_count=10))
    return {"outcome": "note", "detail": top(got)}


# ---- many jobs --------------------------------------------------------------------
def a_switch_targets_back_and_forth():
    for _ in range(5):
        cudaq.set_target("qpp-cpu")
        a = counts(cudaq.sample(flip, 1, shots_count=10))
        ibm()
        b = counts(cudaq.sample(flip, 1, shots_count=10))
        if a != b:
            return {"outcome": "WRONG", "detail": f"{a} vs {b}"}
    return {"outcome": "same", "detail": "five round trips qpp-cpu <-> ibm"}


def a_error_then_a_good_job():
    ibm()

    @cudaq.kernel
    def bad():
        q = cudaq.qvector(2)
        x(q[0]); reset(q[0])
    try:
        cudaq.sample(bad)
        return {"outcome": "note", "detail": "reset did not fail"}
    except RuntimeError:
        pass
    got = counts(cudaq.sample(flip, 2, shots_count=10))
    return {"outcome": "same" if got == {"110": 10} else "WRONG", "detail": f"after an error the next job is right: {got}"}


def jobs_in_a_row(count):
    ibm()
    import resource
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    files_before = len(glob.glob("/tmp/cudaq-ibm-device-*"))
    t = time.monotonic()
    for k in range(count):
        got = counts(cudaq.sample(flip, k % 4, shots_count=20))
        if got != {"1" * (k % 4) + "0" * (3 - k % 4): 20}:
            return {"outcome": "WRONG", "detail": f"job {k}: {got}"}
    took = time.monotonic() - t
    after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    files = len(glob.glob("/tmp/cudaq-ibm-device-*")) - files_before
    return {"outcome": "same", "seconds": round(took, 1),
            "detail": f"{took / count * 1000:.0f} ms per job; peak memory grew {(after - before) / 1024:.0f} MB; "
                      f"{files} device file(s) in /tmp while running"}


def a_300_jobs_in_a_row(): return jobs_in_a_row(300)
def a_3000_jobs_in_a_row(): return jobs_in_a_row(3000)


def a_python_threads_8_at_once():
    ibm()
    results, errors = {}, []

    def work(k):
        try:
            results[k] = counts(cudaq.sample(flip, k % 4, shots_count=20))
        except BaseException as error:  # noqa: BLE001
            errors.append(f"{type(error).__name__}: {str(error)[:150]}")
    threads = [threading.Thread(target=work, args=(k,)) for k in range(8)]
    [t.start() for t in threads]; [t.join() for t in threads]
    want = {k: {"1" * (k % 4) + "0" * (3 - k % 4): 20} for k in range(8)}
    if errors:
        return {"outcome": "error", "detail": f"{len(errors)} of 8 threads failed: {errors[0]}"}
    return {"outcome": "same" if results == want else "WRONG", "detail": str(results)[:300]}


def a_6_processes_at_once():
    code = ("import sys\nsys.path.insert(0, '.')\nfrom lib import *\nfrom cases_api import flip\nibm()\n"
            "k=int(sys.argv[1])\n"
            "for i in range(15):\n"
            "    got = counts(cudaq.sample(flip, k % 4, shots_count=20))\n"
            "    assert got == {'1' * (k % 4) + '0' * (3 - k % 4): 20}, got\n"
            "print('fine')\n")
    procs = [subprocess.Popen([sys.executable, "-c", code, str(k)], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, cwd=os.path.dirname(__file__))
             for k in range(6)]
    outs = [p.communicate(timeout=150) for p in procs]
    bad = [e[-300:] for o, e in outs if "fine" not in o]
    left = glob.glob("/tmp/cudaq-ibm-device-*")
    return {"outcome": "same" if not bad else "WRONG",
            "detail": (f"6 processes x 15 jobs, all right; device files left in /tmp afterwards: {len(left)}"
                       if not bad else bad[0])}


def a_secrets_in_the_info_log():
    code = ("import sys\nsys.path.insert(0, '.')\nfrom lib import *\nfrom cases_api import bell\nibm()\ncudaq.sample(bell, shots_count=5)\n")
    env = dict(os.environ, CUDAQ_LOG_LEVEL="info")
    p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                       cwd=os.path.dirname(__file__), timeout=120)
    log = p.stdout + p.stderr
    found = [name for name, secret in (("API key", "test-key"), ("access token", "fake-token"),
                                       ("CRN", "test-crn")) if secret in log]
    return {"outcome": "clean" if not found else "LEAK",
            "detail": f"{len(log.splitlines())} log lines at info level; found in them: {found or 'none of key, token, CRN'}"}


def a_secrets_in_the_debug_log():
    code = ("import sys\nsys.path.insert(0, '.')\nfrom lib import *\nfrom cases_api import bell\nibm()\ncudaq.sample(bell, shots_count=5)\n")
    env = dict(os.environ, CUDAQ_LOG_LEVEL="trace")
    p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                       cwd=os.path.dirname(__file__), timeout=120)
    log = p.stdout + p.stderr
    found = [name for name, secret in (("API key", "test-key"), ("access token", "fake-token"),
                                       ("CRN", "test-crn")) if secret in log]
    return {"outcome": "clean" if not found else "LEAK",
            "detail": f"{len(log.splitlines())} log lines at trace level; found in them: {found or 'none of key, token, CRN'}"}


a_no_api_key.unset = ["IBM_QUANTUM_API_KEY"]
a_empty_crn.env = {"IBM_QUANTUM_CRN": ""}
a_wrong_api_key.env = {"IBM_QUANTUM_API_KEY": "not-the-key"}
a_wrong_crn.env = {"IBM_QUANTUM_CRN": "not-the-crn"}
a_shots_10_000_000.timeout = 400
a_300_jobs_in_a_row.timeout = 400
a_3000_jobs_in_a_row.timeout = 600
