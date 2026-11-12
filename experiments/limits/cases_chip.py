# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""Odd chips and IBM's rate limit. The canned chips come from probe_server.py;
jobs go to the fixed-samples backend because the fake server checks circuits
against the real ibm_fez wiring, which these chips do not have."""
from lib import *


@cudaq.kernel
def chain(n: int):
    q = cudaq.qvector(n)
    x(q[0])
    for i in range(n - 1):
        x.ctrl(q[i], q[i + 1])


@cudaq.kernel
def singles(n: int):
    q = cudaq.qvector(n)
    for i in range(n):
        x(q[i])


@cudaq.kernel
def flip(n: int):
    q = cudaq.qvector(3)
    for i in range(n):
        x(q[i])


def attempt(kernel, n):
    ibm(backend="ibm_fixed_samples")
    try:
        cudaq.sample(kernel, n, shots_count=3)
    except RuntimeError as error:
        text = str(error)
        if "is not usable" in text or "unwired" in text or "more than" in text:
            return {"outcome": "sent", "detail": "a job was sent (the fake server then compared it with ibm_fez, which does not apply here)"}
        return {"outcome": "error", "detail": text[:400]}
    return {"outcome": "sent", "detail": "a job was sent"}


def c_5_qubit_chip_kernel_of_5(): return attempt(chain, 5)
def c_5_qubit_chip_kernel_of_6(): return attempt(chain, 6)
def c_5_qubit_chip_dead_middle_kernel_of_2(): return attempt(chain, 2)
def c_5_qubit_chip_dead_middle_kernel_of_3(): return attempt(chain, 3)
def c_chip_with_every_link_broken_no_2q_gate(): return attempt(singles, 1)
def c_chip_with_every_link_broken_2_qubits(): return attempt(chain, 2)
def c_chip_without_readout_errors(): return attempt(chain, 2)
def c_chip_with_one_qubit(): return attempt(singles, 1)
def c_chip_whose_2_qubit_gate_is_ecr(): return attempt(chain, 2)


def c_rate_limit_list_of_8_arguments():
    ibm()
    try:
        out = cudaq.sample(flip, [0, 1, 2, 3, 0, 1, 2, 3], shots_count=20)
        return {"outcome": "answer", "detail": f"{len(out)} results"}
    except RuntimeError as error:
        return {"outcome": "error", "detail": "the 6th job is refused and the answers of the first five are lost: " + str(error)[:200]}


def c_rate_limit_8_async_jobs():
    ibm()
    done, failed = 0, ""
    futures = []
    try:
        for k in range(8):
            futures.append(cudaq.sample_async(flip, k % 4, shots_count=20))
    except RuntimeError as error:
        failed = "sample_async itself raised at job " + str(len(futures) + 1) + ": " + str(error)[:150]
    for f in futures:
        try:
            f.get(); done += 1
        except RuntimeError as error:
            failed = failed or str(error)[:200]
    return {"outcome": "partly", "detail": f"{done} of 8 jobs gave a result; first failure: {failed}"}


c_5_qubit_chip_kernel_of_5.fault = "chip_line5"
c_5_qubit_chip_kernel_of_6.fault = "chip_line5"
c_5_qubit_chip_dead_middle_kernel_of_2.fault = "chip_line5_dead_middle"
c_5_qubit_chip_dead_middle_kernel_of_3.fault = "chip_line5_dead_middle"
c_chip_with_every_link_broken_no_2q_gate.fault = "chip_all_links_broken"
c_chip_with_every_link_broken_2_qubits.fault = "chip_all_links_broken"
c_chip_without_readout_errors.fault = "chip_no_readout_errors"
c_chip_with_one_qubit.fault = "chip_single_qubit"
c_chip_whose_2_qubit_gate_is_ecr.fault = "chip_ecr"
c_rate_limit_list_of_8_arguments.fault = "post_429_after_5"
c_rate_limit_8_async_jobs.fault = "post_429_after_5"
