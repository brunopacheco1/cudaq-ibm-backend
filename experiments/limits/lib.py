# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""Helpers shared by the limit probes. One probe = one function that returns
a dict {"outcome": ..., "detail": ...}; run_case.py runs it in its own
process, because a probe may crash or hang."""
import os
import sys
import time
import warnings
from pathlib import Path

# The clone the plugin and the fake server come from. PROBE_REPO points
# somewhere else when a copy with a planted fault is tested.
REPO = os.environ.get("PROBE_REPO", str(Path(__file__).resolve().parents[2]))
PORT = int(os.environ.get("PROBE_PORT", "62460"))
# Credentials for the fake server come from the runner (run.py), so that a
# probe can also run without them.
if "PROBE_PORT" not in os.environ:      # started by hand, not by run.py
    os.environ.setdefault("IBM_QUANTUM_API_KEY", "test-key")
    os.environ.setdefault("IBM_QUANTUM_CRN", "test-crn")
warnings.simplefilter("ignore")
sys.path.insert(0, os.path.join(REPO, "tests"))

import cudaq  # noqa: E402
import plugin_under_test  # noqa: E402

os.chdir(REPO)
plugin_under_test.register(cudaq)
SEED = 2026


def ibm(backend="ibm_fake", **more):
    # Always the localhost urls: without them the plugin talks to IBM.
    cudaq.set_target("ibm", backend=backend,
                     url=f"http://localhost:{PORT}/api",
                     iam_url=f"http://localhost:{PORT}/identity/token", **more)


def counts(result) -> dict:
    return {bits: n for bits, n in result.items()}


def distance(a: dict, b: dict) -> float:
    ta, tb = sum(a.values()), sum(b.values())
    return 0.5 * sum(abs(a.get(k, 0) / ta - b.get(k, 0) / tb) for k in set(a) | set(b))


def top(c: dict, n=4) -> str:
    items = sorted(c.items(), key=lambda kv: -kv[1])[:n]
    return " ".join(f"{k}:{v}" for k, v in items) + (" ..." if len(c) > n else "")


def compare(kernel, *args, shots=4000, ref_shots=40000, limit=0.05, **sample_kw):
    """Run on CUDA-Q's simulator, then through the plugin; say if they agree."""
    cudaq.set_target("qpp-cpu")
    cudaq.set_random_seed(SEED)
    try:
        ref = counts(cudaq.sample(kernel, *args, shots_count=ref_shots, **sample_kw))
    except BaseException as error:  # noqa: BLE001
        return {"outcome": "not-a-plugin-limit",
                "detail": "CUDA-Q's own simulator refuses it too: " + str(error).strip()[:300]}
    ibm()
    t = time.monotonic()
    got = counts(cudaq.sample(kernel, *args, shots_count=shots, **sample_kw))
    took = time.monotonic() - t
    if sum(got.values()) != shots:
        return {"outcome": "WRONG", "detail": f"{sum(got.values())} samples for {shots} shots; plugin {top(got)}"}
    widths = {len(k) for k in ref} | {len(k) for k in got}
    d = distance(ref, got)
    if len(widths) != 1:
        return {"outcome": "WRONG", "detail": f"bit string widths differ: simulator {top(ref)} | plugin {top(got)}"}
    if d > limit:
        return {"outcome": "WRONG", "detail": f"distance {d:.3f}: simulator {top(ref)} | plugin {top(got)}"}
    return {"outcome": "same", "detail": f"distance {d:.3f}; {top(got, 3)}", "seconds": round(took, 2)}
