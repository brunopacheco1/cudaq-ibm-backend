# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""Random kernels, each compared with CUDA-Q's simulator. A wrong result here
is the worst kind of limit: nothing warns the user."""
import math
import random

from lib import *

ONE = ("h", "x", "y", "z", "s", "t", "sdg", "tdg")
ROT = ("rx", "ry", "rz", "r1")
TWO = ("cx", "cy", "cz", "ch", "swap")
CROT = ("crx", "cry", "crz", "cr1")


def random_kernel(rng, n, gates):
    kernel = cudaq.make_kernel()
    q = kernel.qalloc(n)
    text = []
    for _ in range(gates):
        kind = rng.random()
        if kind < 0.25 or n == 1:
            g, a = rng.choice(ONE), rng.randrange(n)
            getattr(kernel, g)(q[a]); text.append(f"{g} {a}")
        elif kind < 0.5:
            g, a, angle = rng.choice(ROT), rng.randrange(n), rng.uniform(-math.pi, math.pi)
            getattr(kernel, g)(angle, q[a]); text.append(f"{g}({angle:.3f}) {a}")
        elif kind < 0.55:
            a = rng.randrange(n)
            angles = [rng.uniform(-math.pi, math.pi) for _ in range(3)]
            kernel.u3(*angles, q[a]); text.append(f"u3 {a}")
        elif kind < 0.8:
            g = rng.choice(TWO)
            a, b = rng.sample(range(n), 2)
            getattr(kernel, g)(q[a], q[b]); text.append(f"{g} {a},{b}")
        elif kind < 0.92:
            g, angle = rng.choice(CROT), rng.uniform(-math.pi, math.pi)
            a, b = rng.sample(range(n), 2)
            getattr(kernel, g)(angle, q[a], q[b]); text.append(f"{g}({angle:.3f}) {a},{b}")
        elif n >= 3:
            a, b, c = rng.sample(range(n), 3)
            if rng.random() < 0.6:
                kernel.cx([q[a], q[b]], q[c]); text.append(f"ccx {a},{b},{c}")
            else:
                kernel.cswap(q[a], q[b], q[c]); text.append(f"cswap {a},{b},{c}")
    how = rng.choice(("all", "none", "part", "part"))
    if how == "all":
        kernel.mz(q)
    elif how == "part" and n > 1:
        picked = rng.sample(range(n), rng.randint(1, n - 1))
        for k in picked:
            kernel.mz(q[k])
        how = "mz on " + ",".join(map(str, picked))
    return kernel, "; ".join(text) + f" | {how}"


def fuzz(seed, count, max_qubits, max_gates):
    rng = random.Random(seed)
    made = [(*random_kernel(rng, rng.randint(1, max_qubits), rng.randint(3, max_gates)),) for _ in range(count)]
    cudaq.set_target("qpp-cpu")
    cudaq.set_random_seed(seed)
    refs = [counts(cudaq.sample(k, shots_count=200000)) for k, _ in made]
    ibm()
    bad, worst = [], 0.0
    for (kernel, text), ref in zip(made, refs):
        got = counts(cudaq.sample(kernel, shots_count=20000))
        d = distance(ref, got)
        # Shot noise grows with the number of outcomes; ask again with more
        # shots before calling a difference real.
        if d > 0.03 + 0.02 * math.sqrt(len(ref) / 16):
            got = counts(cudaq.sample(kernel, shots_count=400000))
            d = distance(ref, got)
            if d > 0.03 + 0.01 * math.sqrt(len(ref) / 16):
                bad.append(f"distance {d:.3f}: {text[:400]} || simulator {top(ref, 3)} | plugin {top(got, 3)}")
                continue
        worst = max(worst, d)
    if bad:
        return {"outcome": "WRONG", "detail": f"{len(bad)} of {count} kernels differ. First: {bad[0]}"}
    return {"outcome": "same", "detail": f"{count} random kernels, up to {max_qubits} qubits and {max_gates} gates; largest distance {worst:.3f}"}


def f_100_small_kernels(): return fuzz(11, 100, 4, 15)
def f_100_medium_kernels(): return fuzz(12, 100, 7, 40)
def f_100_medium_kernels_other_seed(): return fuzz(13, 100, 7, 40)
def f_40_larger_kernels(): return fuzz(14, 40, 10, 80)


f_100_small_kernels.server_env = {}
f_100_medium_kernels.server_env = {}
f_100_medium_kernels_other_seed.server_env = {}
f_40_larger_kernels.server_env = {}
f_100_small_kernels.timeout = 900
f_100_medium_kernels.timeout = 900
f_100_medium_kernels_other_seed.timeout = 900
f_40_larger_kernels.timeout = 900
