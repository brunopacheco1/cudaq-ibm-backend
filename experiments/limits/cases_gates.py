# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""Every gate and kernel feature CUDA-Q can send, as decorator kernels."""
import math

import numpy as np

from lib import *


# ---- one-qubit gates ------------------------------------------------------
@cudaq.kernel
def k_clifford_t():
    q = cudaq.qvector(3)
    h(q[0]); s(q[0]); t(q[0]); h(q[0])
    h(q[1]); t.adj(q[1]); s.adj(q[1]); h(q[1]); t(q[1]); h(q[1])
    x(q[2]); y(q[2]); z(q[2]); h(q[2]); t(q[2]); h(q[2])


def g_h_s_t_adjoints(): return compare(k_clifford_t)


@cudaq.kernel
def k_rotations(a: float, b: float, c: float):
    q = cudaq.qvector(3)
    rx(a, q[0]); ry(b, q[0]); rz(c, q[0]); rx(-b, q[0])
    ry(a, q[1]); r1(c, q[1]); rx(b, q[1])
    h(q[2]); r1(a, q[2]); rz(-c, q[2]); h(q[2])


def g_rotations_with_arguments(): return compare(k_rotations, 0.7, -1.9, 2.4)


@cudaq.kernel
def k_u3():
    q = cudaq.qvector(2)
    u3(0.7, 0.6, 0.9, q[0]); u3(2.1, -1.3, 0.4, q[1]); h(q[0]); u3(-0.5, 1.1, 2.2, q[0])


def g_u3(): return compare(k_u3)


# ---- two-qubit gates ------------------------------------------------------
@cudaq.kernel
def k_controlled_paulis():
    q = cudaq.qvector(4)
    h(q[0]); ry(0.9, q[1]); ry(1.7, q[2]); rx(0.4, q[3])
    x.ctrl(q[0], q[1]); y.ctrl(q[1], q[2]); z.ctrl(q[2], q[3]); h(q[3])
    h.ctrl(q[3], q[0]); ry(0.3, q[0])


def g_cx_cy_cz_ch(): return compare(k_controlled_paulis)


@cudaq.kernel
def k_controlled_phases():
    q = cudaq.qvector(3)
    h(q); s.ctrl(q[0], q[1]); t.ctrl(q[1], q[2]); h(q)
    ry(0.8, q[0]); s.adj(q[0]); t.ctrl(q[0], q[2]); h(q[2])


def g_cs_ct(): return compare(k_controlled_phases)


@cudaq.kernel
def k_controlled_rotations():
    q = cudaq.qvector(4)
    h(q[0]); ry(1.2, q[1]); ry(0.5, q[2]); h(q[3])
    rx.ctrl(0.9, q[0], q[1]); ry.ctrl(-1.3, q[1], q[2])
    rz.ctrl(0.7, q[2], q[3]); r1.ctrl(1.9, q[3], q[0]); h(q[3]); h(q[0])


def g_crx_cry_crz_cr1(): return compare(k_controlled_rotations)


@cudaq.kernel
def k_swap():
    q = cudaq.qvector(3)
    x(q[0]); ry(0.8, q[1]); swap(q[0], q[2]); swap(q[1], q[0])


def g_swap(): return compare(k_swap)


# ---- three and more qubits -------------------------------------------------
@cudaq.kernel
def k_ccx():
    q = cudaq.qvector(3)
    h(q[0]); ry(1.0, q[1]); x.ctrl(q[0], q[1], q[2]); ry(0.3, q[2])


def g_ccx_toffoli(): return compare(k_ccx)


@cudaq.kernel
def k_ccz_cswap():
    q = cudaq.qvector(4)
    h(q[0]); h(q[1]); ry(1.1, q[2]); x(q[3])
    z.ctrl(q[0], q[1], q[2]); swap.ctrl(q[0], q[2], q[3]); h(q[1]); ry(-0.4, q[2])


def g_ccz_and_cswap(): return compare(k_ccz_cswap)


@cudaq.kernel
def k_c3x():
    q = cudaq.qvector(4)
    h(q[0]); ry(2.0, q[1]); ry(2.2, q[2]); x.ctrl(q[0], q[1], q[2], q[3])


def g_x_with_3_controls_no_mz(): return compare(k_c3x)


@cudaq.kernel
def k_c3x_mz():
    q = cudaq.qvector(4)
    h(q[0]); ry(2.0, q[1]); ry(2.2, q[2]); x.ctrl(q[0], q[1], q[2], q[3])
    mz(q)


def g_x_with_3_controls_and_mz_on_all(): return compare(k_c3x_mz)


@cudaq.kernel
def k_c5x():
    c = cudaq.qvector(5)
    t = cudaq.qubit()
    ry(2.2, c); x.ctrl(c, t)


def g_x_with_5_controls_no_mz(): return compare(k_c5x)


@cudaq.kernel
def k_c5x_mz():
    c = cudaq.qvector(5)
    t = cudaq.qubit()
    ry(2.2, c); x.ctrl(c, t)
    mz(c); mz(t)


def g_x_with_5_controls_and_mz_on_all(): return compare(k_c5x_mz)


@cudaq.kernel
def k_negated_control():
    q = cudaq.qvector(2)
    ry(0.9, q[0]); x.ctrl(~q[0], q[1])


def g_negated_control(): return compare(k_negated_control)


@cudaq.kernel
def k_mc_rotation():
    q = cudaq.qvector(3)
    h(q[0]); ry(1.3, q[1]); ry.ctrl(0.8, [q[0], q[1]], q[2])


def g_ry_with_2_controls_no_mz(): return compare(k_mc_rotation)


@cudaq.kernel
def k_mc_rotation_mz():
    q = cudaq.qvector(3)
    h(q[0]); ry(1.3, q[1]); ry.ctrl(0.8, [q[0], q[1]], q[2])
    mz(q)


def g_ry_with_2_controls_and_mz_on_all(): return compare(k_mc_rotation_mz)


# ---- composed kernels -----------------------------------------------------
@cudaq.kernel
def sub(q: cudaq.qview, a: float):
    ry(a, q[0]); x.ctrl(q[0], q[1]); rz(a, q[1]); t(q[0])


@cudaq.kernel
def k_calls_sub():
    q = cudaq.qvector(3)
    sub(q, 0.9); h(q[2]); sub(q[1:3], -0.4)


def g_kernel_calls_kernel(): return compare(k_calls_sub)


@cudaq.kernel
def k_adjoint():
    q = cudaq.qvector(2)
    ry(0.5, q[1]); sub(q, 1.1); h(q[1]); cudaq.adjoint(sub, q, 0.6)


def g_adjoint_of_a_kernel(): return compare(k_adjoint)


@cudaq.kernel
def k_control():
    c = cudaq.qubit()
    q = cudaq.qvector(2)
    ry(1.4, c); cudaq.control(sub, c, q, 0.9)


def g_control_of_a_kernel(): return compare(k_control)


@cudaq.kernel
def k_exp_pauli(a: float):
    q = cudaq.qvector(3)
    h(q[0]); ry(0.7, q[1])
    exp_pauli(a, q, "XYZ")
    exp_pauli(-0.4, q, "ZIX")


def g_exp_pauli(): return compare(k_exp_pauli, 0.6)


def g_custom_unitary():
    cudaq.register_operation("my_sqrt_y", np.array(
        [[0.5 + 0.5j, -0.5 - 0.5j], [0.5 + 0.5j, 0.5 + 0.5j]]))

    @cudaq.kernel
    def k():
        q = cudaq.qvector(2)
        my_sqrt_y(q[0]); x.ctrl(q[0], q[1]); my_sqrt_y(q[1])
    return compare(k)


def g_custom_2_qubit_unitary():
    cudaq.register_operation("my_iswap", np.array(
        [[1, 0, 0, 0], [0, 0, 1j, 0], [0, 1j, 0, 0], [0, 0, 0, 1]]))

    @cudaq.kernel
    def k():
        q = cudaq.qvector(2)
        x(q[0]); ry(0.7, q[1]); my_iswap(q[0], q[1]); h(q[0])
    return compare(k)


# ---- state preparation ------------------------------------------------------
@cudaq.kernel
def k_state_literal():
    q = cudaq.qvector([0.6, 0.0, 0.0, 0.8])
    h(q[0])


def g_state_from_amplitudes_in_the_kernel(): return compare(k_state_literal)


@cudaq.kernel
def k_state_arg(v: list[complex]):
    q = cudaq.qvector(v)
    ry(0.4, q[1])


def g_state_from_amplitudes_as_argument():
    v = np.array([0.5, 0.5j, -0.5, 0.5], dtype=complex)
    return compare(k_state_arg, v)


def g_state_from_cudaq_state_object():
    cudaq.set_target("qpp-cpu")
    st = cudaq.State.from_data(np.array([0.6, 0, 0, 0.8], dtype=np.complex128))

    @cudaq.kernel
    def k(s: cudaq.State):
        q = cudaq.qvector(s)
        h(q[0])
    return compare(k, st)


# ---- measurement and reset ---------------------------------------------------
@cudaq.kernel
def k_reset():
    q = cudaq.qvector(2)
    x(q[0]); reset(q[0]); x(q[1])


def g_reset(): return compare(k_reset)


@cudaq.kernel
def k_mid_measure():
    q = cudaq.qvector(2)
    h(q[0]); mz(q[0]); h(q[0]); x(q[1])
    mz(q)


def g_measure_then_more_gates_on_the_same_qubit(): return compare(k_mid_measure)


@cudaq.kernel
def k_branch():
    q = cudaq.qvector(2)
    h(q[0])
    b = mz(q[0])
    if b:
        x(q[1])
    mz(q)


def g_if_on_a_measurement_with_sample(): return compare(k_branch)


@cudaq.kernel
def k_run() -> int:
    q = cudaq.qvector(2)
    h(q[0])
    b = mz(q[0])
    if b:
        x(q[1])
    c = mz(q[1])
    r = 0
    if c:
        r = 1
    return r


def g_if_on_a_measurement_with_cudaq_run():
    cudaq.set_target("qpp-cpu")
    ref = cudaq.run(k_run, shots_count=20)
    ibm()
    got = cudaq.run(k_run, shots_count=20)
    return {"outcome": "same?", "detail": f"simulator {sorted(set(ref))}, plugin {list(got)[:20]}"}


@cudaq.kernel
def k_no_branch_run() -> int:
    q = cudaq.qvector(2)
    x(q[0]); x.ctrl(q[0], q[1])
    r = 0
    if mz(q[1]):
        r = 3
    return r


def g_cudaq_run_returning_a_value():
    ibm()
    got = cudaq.run(k_no_branch_run, shots_count=10)
    return {"outcome": "same" if list(got) == [3] * 10 else "WRONG", "detail": f"plugin {list(got)}"}


@cudaq.kernel
def k_mx():
    q = cudaq.qvector(2)
    h(q[0]); x(q[1])
    mx(q[0]); mz(q[1])


def g_mx(): return compare(k_mx)


@cudaq.kernel
def k_my():
    q = cudaq.qvector(1)
    h(q[0]); s(q[0])
    my(q[0])


def g_my(): return compare(k_my)


@cudaq.kernel
def k_x_basis_by_hand():
    q = cudaq.qvector(2)
    h(q[0]); x(q[1])
    h(q[0])              # what mx does: turn X onto Z, then measure
    mz(q)


def g_x_basis_by_hand_h_then_mz(): return compare(k_x_basis_by_hand)


@cudaq.kernel
def k_named():
    q = cudaq.qvector(3)
    x(q[0]); x(q[2])
    first = mz(q[0])
    rest = mz(q[1:3])


def g_two_named_measurement_registers():
    out = compare(k_named)
    ibm()
    r = cudaq.sample(k_named, shots_count=50)
    names = list(r.register_names)
    out["detail"] += f"; register names from the plugin: {names}"
    cudaq.set_target("qpp-cpu")
    out["detail"] += f"; from the simulator: {list(cudaq.sample(k_named, shots_count=50).register_names)}"
    return out


@cudaq.kernel
def k_measure_twice():
    q = cudaq.qvector(2)
    x(q[0])
    mz(q[0]); mz(q[0]); mz(q[1])


def g_same_qubit_measured_twice(): return compare(k_measure_twice)


# ---- allocation ------------------------------------------------------------
@cudaq.kernel
def k_two_registers():
    a = cudaq.qvector(2)
    b = cudaq.qvector(3)
    x(a[1]); x(b[0]); x.ctrl(a[1], b[2])


def g_two_qvectors(): return compare(k_two_registers)


@cudaq.kernel
def k_measure_registers_reversed():
    a = cudaq.qvector(2)
    b = cudaq.qvector(2)
    x(a[1]); x(b[0])
    mz(b); mz(a)


def g_two_qvectors_measured_in_the_other_order(): return compare(k_measure_registers_reversed)


@cudaq.kernel
def k_single_qubits():
    a = cudaq.qubit()
    b = cudaq.qubit()
    c = cudaq.qvector(2)
    x(a); x.ctrl(a, c[1]); h(b); x.ctrl(b, c[0])


def g_single_qubits_and_a_qvector(): return compare(k_single_qubits)


@cudaq.kernel
def k_one():
    q = cudaq.qubit()
    ry(0.9, q)


def g_one_qubit_kernel(): return compare(k_one)


@cudaq.kernel
def k_none():
    pass


def g_kernel_without_qubits(): return compare(k_none)


@cudaq.kernel
def k_alloc_n(n: int):
    q = cudaq.qvector(n)
    for i in range(n):
        if i % 2 == 0:
            x(q[i])
    for i in range(n - 1):
        x.ctrl(q[i], q[i + 1])


def g_size_and_loops_from_an_argument(): return compare(k_alloc_n, 7)


@cudaq.kernel
def k_list_arg(angles: list[float]):
    q = cudaq.qvector(len(angles))
    for i, a in enumerate(angles):
        ry(a, q[i])
    for i in range(len(angles) - 1):
        x.ctrl(q[i], q[i + 1])


def g_list_of_angles_as_argument(): return compare(k_list_arg, [0.3, 1.1, 2.0, -0.7])


@cudaq.kernel
def k_late_alloc():
    a = cudaq.qvector(2)
    h(a[0]); x.ctrl(a[0], a[1])
    b = cudaq.qvector(2)
    x.ctrl(a[1], b[0]); x(b[1])


def g_qubits_allocated_after_gates(): return compare(k_late_alloc)


# ---- angles -----------------------------------------------------------------
@cudaq.kernel
def k_angle(a: float):
    q = cudaq.qvector(2)
    rx(a, q[0]); h(q[1]); rz(a, q[1]); h(q[1])


def g_angle_very_small(): return compare(k_angle, 1e-9)
# Ten million turns plus half a turn: on the simulator both qubits end in 1.
# CUDA-Q prints the angle in OpenQASM 2 with 7 significant digits, which
# moves it by 3.8 rad.
def g_angle_very_large(): return compare(k_angle, 2 * math.pi * 1e7 + math.pi)
def g_angle_negative_large(): return compare(k_angle, -12345.678)
def g_angle_multiple_of_2pi(): return compare(k_angle, 2 * math.pi * 3)


def plugin_only(kernel, *args):
    """For inputs that crash CUDA-Q's own simulator: no reference run."""
    ibm()
    got = counts(cudaq.sample(kernel, *args, shots_count=100))
    return {"outcome": "UNEXPECTED", "detail": f"an answer came back: {top(got)}"}


def g_angle_nan(): return plugin_only(k_angle, float("nan"))
def g_angle_infinite(): return plugin_only(k_angle, float("inf"))


def g_angle_nan_on_cudaq_simulator():
    cudaq.set_target("qpp-cpu")
    got = counts(cudaq.sample(k_angle, float("nan"), shots_count=100))
    return {"outcome": "note", "detail": f"CUDA-Q's simulator returned {top(got)}"}


@cudaq.kernel
def k_float_power(n: int):
    q = cudaq.qvector(2)
    h(q[0])
    for j in range(n):
        r1.ctrl(3.141592653589793 / 2.0 ** j, q[0], q[1])


def g_float_power_of_a_loop_variable(): return compare(k_float_power, 4)


@cudaq.kernel
def k_int_power(n: int):
    q = cudaq.qvector(2)
    h(q[0])
    for j in range(n):
        r1.ctrl(3.141592653589793 / 2 ** j, q[0], q[1])


def g_int_power_of_a_loop_variable(): return compare(k_int_power, 4)
def g_int_power_past_2_to_the_63(): return plugin_only(k_int_power, 70)
def g_angle_many_digits(): return compare(k_angle, 1.2345678901234567)


# ---- small algorithms ---------------------------------------------------------
@cudaq.kernel
def k_qft(n: int):
    q = cudaq.qvector(n)
    x(q[0]); x(q[2]); ry(0.7, q[1])
    for i in range(n):
        h(q[i])
        for j in range(i + 1, n):
            r1.ctrl(2 * np.pi / 2 ** (j - i + 1), q[j], q[i])
    for i in range(n):
        ry(0.3 * (i + 1), q[i])


def g_qft_5_qubits(): return compare(k_qft, 5, shots=20000, ref_shots=200000)
def g_qft_8_qubits(): return compare(k_qft, 8, shots=40000, ref_shots=400000, limit=0.08)


@cudaq.kernel
def k_grover():
    q = cudaq.qvector(3)
    h(q)
    for _ in range(2):
        z.ctrl(q[0], q[1], q[2])          # oracle marks 111
        h(q); x(q); z.ctrl(q[0], q[1], q[2]); x(q); h(q)


def g_grover_3_qubits(): return compare(k_grover)


@cudaq.kernel
def k_all_pairs(n: int):
    q = cudaq.qvector(n)
    for i in range(n):
        ry(0.4 + 0.3 * i, q[i])
    for i in range(n):
        for j in range(i + 1, n):
            z.ctrl(q[i], q[j])
    for i in range(n):
        ry(0.9 - 0.2 * i, q[i])


def g_cz_between_every_pair_of_8(): return compare(k_all_pairs, 8, shots=40000, ref_shots=400000, limit=0.08)


@cudaq.kernel
def k_ansatz(n: int, layers: int, angles: list[float]):
    q = cudaq.qvector(n)
    k = 0
    for _ in range(layers):
        for i in range(n):
            ry(angles[k], q[i]); k += 1
            rz(angles[k], q[i]); k += 1
        for i in range(n - 1):
            x.ctrl(q[i], q[i + 1])


def g_layered_ansatz_6_qubits_3_layers():
    rng = np.random.default_rng(7)
    return compare(k_ansatz, 6, 3, list(rng.uniform(-3, 3, 36)), shots=20000, ref_shots=200000)


@cudaq.kernel
def k_far_swaps():
    q = cudaq.qvector(12)
    x(q[0]); x(q[5]); ry(1.0, q[11])
    swap(q[0], q[11]); swap(q[5], q[2]); x.ctrl(q[11], q[3]); x.ctrl(q[0], q[6])


def g_gates_between_far_qubits_of_12(): return compare(k_far_swaps)


# ---- the same kernels on the hardware targets CUDA-Q ships -------------------
def g_other_hardware_targets_in_emulation():
    """Which of the findings above are CUDA-Q's and which are this plugin's?
    The shipped targets run without credentials when emulate=True."""
    rows = []
    for target in ("ionq", "quantinuum", "oqc", "anyon"):
        cells = []
        for name, kernel in (("3 controls, no mz", k_c3x), ("mx", k_mx), ("my", k_my),
                             ("reset", k_reset), ("named registers", k_named)):
            try:
                cudaq.set_target(target, emulate=True)
                result = cudaq.sample(kernel, shots_count=500)
                width = len(next(iter(counts(result))))
                extra = ""
                if name == "named registers":
                    extra = f", registers {sorted(result.register_names)}"
                cells.append(f"{name}: {width} bits{extra}")
            except BaseException as error:  # noqa: BLE001
                cells.append(f"{name}: error {str(error)[:60]}")
        rows.append(f"{target}: " + "; ".join(cells))
    return {"outcome": "note", "detail": " || ".join(rows)}
