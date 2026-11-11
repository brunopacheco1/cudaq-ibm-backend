# 0017. Keep idle qubits: remove `dqe` from the pipeline

Date: 2026-11-10. Status: accepted.
Tags: **[V]** verified (source given), **[U]** unverified.

## Context

`dqe` is the CUDA-Q pass that deletes qubits no gate touches; the remaining qubits are
renumbered. With it in our pipeline (inherited from the example target), a kernel with an
idle qubit came back with fewer bits than it has qubits: `111` instead of `1011` **[V]**
experiment `e2_idle.py`, 2026-11-10, now a case in `tests/run_fake_ibm_results.py`.
CUDA-Q's specification allows the shorter string, but a user who allocates four qubits
expects four bits.

The experiment scripts named here were throwaway and are not in the repository; the
lasting cases are in `tests/run_fake_ibm.py` and `tests/run_fake_ibm_results.py`.

## Options

- **A.** Remove `dqe`. Every allocated qubit keeps its place and is measured.
- **B.** Run `add-measurements` early (the earlier plan). Works for `sample`, but breaks
  `observe`: "Cannot observe kernel with non dangling measurements" **[V]** experiment
  `e7_observe_idle.py`.
- **C.** Leave it.

## Decision (Bruno, 2026-11-10)

**A.**

## Consequences

- An idle qubit now occupies a chip qubit and adds one readout.
- Nothing else changed **[V]** 2026-11-10: the result checks and the protocol cases pass
  unchanged without `dqe`, and GHZ-20 keeps its 28 `cz`.
- On targets NVIDIA ships, an idle qubit with `emulate=True` gives a wrong expectation
  value (`<Z1>` = -1 instead of +1 on `anyon` and `oqc`) **[V]** pip `cudaq` 0.16.0 and
  0.16.0.post1. A removes that cause here. Not reported to NVIDIA on this date.

## Revisit when

Idle qubits cost real QPU time for someone, or CUDA-Q changes how `sample` reports
unmeasured qubits.
