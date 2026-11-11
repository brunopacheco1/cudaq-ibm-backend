# 0018. Refuse `emulate=True` with a clear error

Date: 2026-11-10. Status: accepted.
Tags: **[V]** verified (source given), **[U]** unverified.

## Context

`cudaq.set_target("ibm", emulate=True)` asks CUDA-Q to simulate the kernel locally with
the target's compiler pipeline. Before M4 it failed inside CUDA-Q with "Multiple qalloc
statements found". One more pass at the end of the pipeline (`combine-quantum-alloc`)
removes the error, but then the **bit order is wrong without any warning**: `1110` instead
of `1011`. Cause: in emulation CUDA-Q sorts the bits with its own `reorderIdx`, which is
wrong with our router options `placement=auto search=sabre`
([upstream.md](../upstream.md) #8). With CUDA-Q's default start layout the emulated
results were right in 3 sample kernels and 16 observe operators **[V]** experiments
`e1_emulate.py`, `e3_observe.py`, `e7_observe_idle.py`, 2026-11-10, pip `cudaq` 0.16.0.

CUDA-Q announces that `sample` and `observe` "will change in a future release" **[V]**
`FutureWarning` at `import cudaq`. NVIDIA/cuda-quantum PR 5875 (open on 2026-11-10, by a
maintainer) would remove `mapping_reorder_idx` and require an explicit `cudaq.record(...)`.

The experiment scripts named here were throwaway and are not in the repository; the
lasting cases are in `tests/run_fake_ibm.py` and `tests/run_fake_ibm_results.py`.

## Options

- **A.** Refuse it with a clear sentence. The helper's `initialize` receives the `emulate`
  setting **[V]** `qpu_utils.cpp:166`, `BaseRemoteRESTQPU.h:203` (tag `0.16.0`).
- **B.** Support it: in emulation switch the router to CUDA-Q's default start layout.
  About a day, with a random-kernel test in CI.
- **C.** Leave the compiler error.

## Decision (Bruno, 2026-11-10)

**A for this release.**

## Consequences

- In emulation CUDA-Q simulates its own IR and never calls our gate rewrite, qubit
  assignment or result decoding. So emulation would test CUDA-Q, not this plugin, and
  nothing is lost for testing: the fake server covers the real path.
- A silent wrong bit order is the worst failure this plugin can have; A rules it out.
- The error is raised when the target is set, before any job
  ([architecture.md](../architecture.md) §8 item 7).

## Revisit when

CUDA-Q's announced change to `sample` and `observe` is released. Read PR 5875 before any
design.
