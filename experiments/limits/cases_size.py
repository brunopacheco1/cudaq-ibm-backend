# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""Width and depth. Wide circuits are Clifford, so the probe server can
sample them with Stim; the others go to the fixed-samples backend, which
checks every gate and link but returns canned samples (compile only)."""
import random
import time

from lib import *


def timed_sample(kernel, *args, shots=200, backend="ibm_fake"):
    ibm(backend=backend)
    t = time.monotonic()
    got = counts(cudaq.sample(kernel, *args, shots_count=shots))
    return got, round(time.monotonic() - t, 2)


# ---- width: no two-qubit gate ---------------------------------------------
@cudaq.kernel
def k_pattern(n: int):
    q = cudaq.qvector(n)
    for i in range(n):
        if i % 3 == 0:
            x(q[i])


def pattern(n):
    want = "".join("1" if i % 3 == 0 else "0" for i in range(n))
    got, took = timed_sample(k_pattern, n)
    ok = got == {want: 200}
    return {"outcome": "same" if ok else "WRONG", "seconds": took,
            "detail": "the pattern 100100... in every shot" if ok else f"wanted {want[:20]}..., got {top(got, 2)[:200]}"}


def s_x_pattern_024(): return pattern(24)
def s_x_pattern_025(): return pattern(25)
def s_x_pattern_064(): return pattern(64)
def s_x_pattern_065(): return pattern(65)
def s_x_pattern_100(): return pattern(100)
def s_x_pattern_128(): return pattern(128)
def s_x_pattern_150(): return pattern(150)
def s_x_pattern_153(): return pattern(153)
def s_x_pattern_154(): return pattern(154)
def s_x_pattern_156(): return pattern(156)
def s_x_pattern_157(): return pattern(157)
def s_x_pattern_300(): return pattern(300)


# ---- width: GHZ ---------------------------------------------------------------
@cudaq.kernel
def k_ghz(n: int):
    q = cudaq.qvector(n)
    h(q[0])
    for i in range(n - 1):
        x.ctrl(q[i], q[i + 1])


@cudaq.kernel
def k_star(n: int):
    q = cudaq.qvector(n)
    h(q[0])
    for i in range(1, n):
        x.ctrl(q[0], q[i])


def ghz(kernel, n, shots=2000):
    got, took = timed_sample(kernel, n, shots=shots)
    zeros, ones = got.get("0" * n, 0), got.get("1" * n, 0)
    ok = zeros + ones == shots and abs(zeros - shots / 2) < 0.08 * shots
    return {"outcome": "same" if ok else "WRONG", "seconds": took,
            "detail": f"{zeros} x 00..0, {ones} x 11..1" if ok else f"got {top(got, 3)[:300]}"}


def s_ghz_chain_010(): return ghz(k_ghz, 10)
def s_ghz_chain_024(): return ghz(k_ghz, 24)
def s_ghz_chain_030(): return ghz(k_ghz, 30)
def s_ghz_chain_050(): return ghz(k_ghz, 50)
def s_ghz_chain_075(): return ghz(k_ghz, 75)
def s_ghz_chain_100(): return ghz(k_ghz, 100)
def s_ghz_chain_120(): return ghz(k_ghz, 120)
def s_ghz_chain_140(): return ghz(k_ghz, 140)
def s_ghz_chain_153(): return ghz(k_ghz, 153)
def s_ghz_star_010(): return ghz(k_star, 10)
def s_ghz_star_024(): return ghz(k_star, 24)
def s_ghz_star_050(): return ghz(k_star, 50)
def s_ghz_star_100(): return ghz(k_star, 100)
def s_ghz_star_153(): return ghz(k_star, 153)


# ---- width: random x/cx, one right answer ------------------------------------
def random_xcx(n, gates, seed, local=0):
    rng = random.Random(seed)
    kernel = cudaq.make_kernel()
    q = kernel.qalloc(n)
    bits = [0] * n
    for _ in range(gates):
        if rng.random() < 0.6:
            a = rng.randrange(n)
            if local:
                b = min(n - 1, max(0, a + rng.choice([-1, 1]) * rng.randint(1, local)))
                if b == a:
                    continue
            else:
                b = rng.choice([k for k in range(n) if k != a])
            kernel.cx(q[a], q[b]); bits[b] ^= bits[a]
        else:
            a = rng.randrange(n)
            kernel.x(q[a]); bits[a] ^= 1
    want = "".join(map(str, bits))
    got, took = timed_sample(kernel)
    ok = got == {want: 200}
    return {"outcome": "same" if ok else "WRONG", "seconds": took,
            "detail": "the one right answer in every shot" if ok else f"wanted {want[:30]}..., got {top(got, 2)[:200]}"}


def s_random_cx_any_pair_020(): return random_xcx(20, 60, 1)
def s_random_cx_any_pair_040(): return random_xcx(40, 120, 2)
def s_random_cx_any_pair_060(): return random_xcx(60, 180, 3)
def s_random_cx_any_pair_080(): return random_xcx(80, 240, 4)
def s_random_cx_any_pair_100(): return random_xcx(100, 300, 5)
def s_random_cx_any_pair_130(): return random_xcx(130, 390, 6)
def s_random_cx_any_pair_153(): return random_xcx(153, 459, 7)
def s_random_cx_neighbours_100(): return random_xcx(100, 300, 8, local=2)
def s_random_cx_neighbours_153(): return random_xcx(153, 459, 9, local=2)
def s_random_cx_any_pair_040_deep(): return random_xcx(40, 2000, 10)


# ---- width: not Clifford, compile only -----------------------------------------
@cudaq.kernel
def k_layers(n: int, layers: int):
    q = cudaq.qvector(n)
    for l in range(layers):
        for i in range(n):
            ry(0.1 + 0.01 * i + 0.3 * l, q[i])
        for i in range(l % 2, n - 1, 2):
            x.ctrl(q[i], q[i + 1])


@cudaq.kernel
def k_qft_only(n: int):
    q = cudaq.qvector(n)
    for i in range(n):
        h(q[i])
        angle = 3.141592653589793
        for j in range(i + 1, n):
            angle = angle / 2.0
            r1.ctrl(angle, q[j], q[i])


def compile_only(kernel, *args):
    got, took = timed_sample(kernel, *args, shots=3, backend="ibm_fixed_samples")
    return {"outcome": "accepted", "seconds": took,
            "detail": "every gate native and on a working link (result not checked)"}


def s_layers_050_x_10_compile(): return compile_only(k_layers, 50, 10)
def s_layers_100_x_10_compile(): return compile_only(k_layers, 100, 10)
def s_layers_153_x_10_compile(): return compile_only(k_layers, 153, 10)
def s_qft_016_compile(): return compile_only(k_qft_only, 16)
def s_qft_032_compile(): return compile_only(k_qft_only, 32)
def s_qft_064_compile(): return compile_only(k_qft_only, 64)
def s_qft_100_compile(): return compile_only(k_qft_only, 100)


# ---- depth ---------------------------------------------------------------------
@cudaq.kernel
def k_deep_one(outer: int, inner: int):
    q = cudaq.qvector(1)
    for i in range(outer):
        for j in range(inner):
            h(q[0]); t(q[0])


def deep_one(outer, inner):
    """The right answer comes from 2x2 matrices here: CUDA-Q's simulator needs
    a quarter of an hour for 200 000 gates."""
    import numpy as np
    h_gate = np.array([[1, 1], [1, -1]]) / np.sqrt(2)
    t_gate = np.diag([1, np.exp(1j * np.pi / 4)])
    state = np.linalg.matrix_power(t_gate @ h_gate, outer * inner) @ np.array([1, 0])
    p_one = float(abs(state[1]) ** 2)
    shots = 4000
    got, took = timed_sample(k_deep_one, outer, inner, shots=shots)
    ones = got.get("1", 0)
    sigma = (p_one * (1 - p_one) / shots) ** 0.5
    ok = sum(got.values()) == shots and abs(ones / shots - p_one) < 5 * sigma + 1e-3
    return {"outcome": "same" if ok else "WRONG", "seconds": took,
            "detail": f"1 in {ones / shots:.3f} of the shots; exact value {p_one:.3f}"}


# Two loops, because one loop of 1024 rounds or more does not compile (below).
def d_one_qubit_200_gates(): return deep_one(1, 100)
def d_one_qubit_2000_gates(): return deep_one(10, 100)
def d_one_qubit_20000_gates(): return deep_one(100, 100)
def d_one_qubit_200000_gates(): return deep_one(1000, 100)


def d_layers_10_qubits_x_10(): return compare(k_layers, 10, 10, shots=20000, ref_shots=200000, limit=0.2)
def d_layers_10_qubits_x_100(): return compare(k_layers, 10, 100, shots=20000, ref_shots=200000, limit=0.2)
def d_layers_10_qubits_x_1000(): return compare(k_layers, 10, 1000, shots=20000, ref_shots=200000, limit=0.2)


@cudaq.kernel
def k_many_cx(n: int):
    q = cudaq.qvector(2)
    x(q[0])
    for i in range(n):
        x.ctrl(q[0], q[1])


def cx_count(kernel, *args, count):
    """x on q0, then `count` cx: q1 ends in 1 exactly when count is odd."""
    want = "11" if count % 2 else "10"
    got, took = timed_sample(kernel, *args)
    ok = got == {want: 200}
    return {"outcome": "same" if ok else "WRONG", "seconds": took,
            "detail": f"{want} in every shot" if ok else f"wanted {want}, got {top(got)}"}


def d_one_loop_of_1023_rounds(): return cx_count(k_many_cx, 1023, count=1023)
def d_one_loop_of_1024_rounds(): return cx_count(k_many_cx, 1024, count=1024)


@cudaq.kernel
def k_nested_cx(outer: int, inner: int):
    q = cudaq.qvector(2)
    x(q[0])
    for i in range(outer):
        for j in range(inner):
            x.ctrl(q[0], q[1])


def d_nested_loops_101_x_101_cx(): return cx_count(k_nested_cx, 101, 101, count=101 * 101)
def d_nested_loops_1001_x_101_cx(): return cx_count(k_nested_cx, 1001, 101, count=1001 * 101)


def d_builder_kernel_100001_cx():
    kernel = cudaq.make_kernel()
    q = kernel.qalloc(2)
    kernel.x(q[0])
    for _ in range(100001):
        kernel.cx(q[0], q[1])
    return cx_count(kernel, count=100001)
s_x_pattern_024.server_env = {}
s_x_pattern_025.server_env = {}
s_x_pattern_064.server_env = {}
s_x_pattern_065.server_env = {}
s_x_pattern_100.server_env = {}
s_x_pattern_128.server_env = {}
s_x_pattern_150.server_env = {}
s_x_pattern_153.server_env = {}
s_x_pattern_154.server_env = {}
s_x_pattern_156.server_env = {}
s_x_pattern_157.server_env = {}
s_x_pattern_300.server_env = {}
s_ghz_chain_010.server_env = {}
s_ghz_chain_024.server_env = {}
s_ghz_chain_030.server_env = {}
s_ghz_chain_050.server_env = {}
s_ghz_chain_075.server_env = {}
s_ghz_chain_100.server_env = {}
s_ghz_chain_120.server_env = {}
s_ghz_chain_140.server_env = {}
s_ghz_chain_153.server_env = {}
s_ghz_star_010.server_env = {}
s_ghz_star_024.server_env = {}
s_ghz_star_050.server_env = {}
s_ghz_star_100.server_env = {}
s_ghz_star_153.server_env = {}
s_random_cx_any_pair_020.server_env = {}
s_random_cx_any_pair_040.server_env = {}
s_random_cx_any_pair_060.server_env = {}
s_random_cx_any_pair_080.server_env = {}
s_random_cx_any_pair_100.server_env = {}
s_random_cx_any_pair_130.server_env = {}
s_random_cx_any_pair_153.server_env = {}
s_random_cx_neighbours_100.server_env = {}
s_random_cx_neighbours_153.server_env = {}
s_random_cx_any_pair_040_deep.server_env = {}
s_layers_050_x_10_compile.server_env = {}
s_layers_100_x_10_compile.server_env = {}
s_layers_153_x_10_compile.server_env = {}
s_qft_016_compile.server_env = {}
s_qft_032_compile.server_env = {}
s_qft_064_compile.server_env = {}
s_qft_100_compile.server_env = {}
d_one_qubit_200_gates.server_env = {}
d_one_qubit_2000_gates.server_env = {}
d_one_qubit_20000_gates.server_env = {}
d_one_qubit_200000_gates.server_env = {}
d_layers_10_qubits_x_10.server_env = {}
d_layers_10_qubits_x_100.server_env = {}
d_layers_10_qubits_x_1000.server_env = {}
d_one_loop_of_1023_rounds.server_env = {}
d_one_loop_of_1024_rounds.server_env = {}
d_nested_loops_101_x_101_cx.server_env = {}
d_nested_loops_1001_x_101_cx.server_env = {}
d_builder_kernel_100001_cx.server_env = {}
d_layers_10_qubits_x_1000.timeout = 600
d_one_qubit_200000_gates.timeout = 900
d_nested_loops_1001_x_101_cx.timeout = 900
d_builder_kernel_100001_cx.timeout = 900
