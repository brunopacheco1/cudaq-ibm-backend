# 0019. No `cudaq.observe` in the first release; expectation values from `sample`

Date: 2026-11-10. Status: accepted.
Tags: **[V]** verified (source given), **[U]** unverified.

## Context

`cudaq.observe` returns expectation values. On the `ibm` target before M4 it failed with
"Multiple qalloc statements found" for 2 qubits, and with a **segmentation fault** (Python
dies) for a 5-qubit star. With one more pass (`combine-quantum-alloc`) the circuit reaches
our helper as one register-wide `measure`, which the helper does not read; with
`placement=auto` the 5-qubit star still crashes inside CUDA-Q before our code runs **[V]**
experiments `e3_observe.py`, `e5_observe_small.py`, `e8_dump.py`, 2026-11-10, pip `cudaq`
0.16.0. The crash has the same root as
[NVIDIA/cuda-quantum#5882](https://github.com/NVIDIA/cuda-quantum/issues/5882), and it
also happens on a target NVIDIA ships (`anyon`, `emulate=True`, 3-qubit kernel) **[V]**
pip `cudaq` 0.16.0 and 0.16.0.post1.

The experiment scripts named here were throwaway and are not in the repository; the
lasting cases are in `tests/run_fake_ibm.py` and `tests/run_fake_ibm_results.py`.

## Options

- **A.** Not in this release. Document it, stop with a clear error, and add an example
  that computes expectation values from `sample` counts.
- **B.** Implement it now: read the register-wide `measure`, keep the bits of each term.
  Works only while routing stays inside the first qubits; otherwise CUDA-Q crashes before
  our code.
- **C.** Wait for NVIDIA's answer to #5882, then decide.

## Decision (Bruno, 2026-11-10)

**A, then C.**

## Consequences

- `observe` stops with our error for small and large kernels, with no crash:
  `getPipelineSubstitutions` runs before CUDA-Q compiles the kernel, and
  `cudaq::getExecutionContext()` names the call **[V]** 2026-11-10
  ([architecture.md](../architecture.md) §8 item 7).
- `examples/expectation_from_samples.py` (Bruno, 2026-11-11) computes `<ZZ>`, `<XX>` and
  `<YY>` of a Bell pair from `sample` counts and is compared with `cudaq.observe` on the
  simulator in the tests.
- A user needs one job per measurement basis and writes the basis change by hand.

## Revisit when

NVIDIA answers #5882, or CUDA-Q's announced change to `sample` and `observe` is released
([decision 0018](0018-refuse-emulate.md)).
