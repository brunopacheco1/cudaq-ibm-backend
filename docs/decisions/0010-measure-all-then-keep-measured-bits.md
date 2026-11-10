# 0010. Measure every qubit in allocation order, then keep the measured bits

Date: 2026-11-10. Status: accepted.
Tags: **[V]** verified (source given), **[U]** unverified.
Evidence: [m3-spec.md](../m3-spec.md) §2.8, §2.11, §2.12.

## Context

CUDA-Q promises that a sample lists the measured qubits sorted by allocation order, whatever
order the kernel measured them in. IBM returns bits in the order of the measure statements.
With our first M3 pipeline, kernels that measure out of order (`mz(q[2]); mz(q[0])`) or measure
registers in reverse came back in the wrong bit order: 11 of 120 random kernels **[V]**
`experiments/m3_bit_order.py`. The router options do not matter: the same kernels fail with
the identity start **[V]**.

## Options

- **A.** Run `combine-measurements` before routing (then `expand-measurements`,
  `cc-loop-unroll`), so the circuit measures every qubit in allocation order (`c[i]` = qubit
  i). CUDA-Q records the qubits the kernel measured in `output_names`; `processResults` keeps
  `c[q]` for those q, ascending.
- **B.** Keep statement order and tell users to measure in order. Fails silently.
- **C.** `reorderIdx`, like IQM. It assumes results sorted by physical qubit and a known
  layout; we have neither.
- **D.** Wait for upstream.

## Decision (Bruno, 2026-11-10)

**A.** Code: `plugin/targets/ibm.yml.in`, `plugin/ResultBits.h`. 0 of 120 wrong **[V]**.
Braket, qBraid and Scaleway use the same two pieces **[V]** their YAML files, but none of
them also routes, so this combination is ours to maintain.

## Consequences

- Every qubit is measured, also those the kernel did not measure: a few more readouts.
- `emulate=True` very likely fails: in emulation CUDA-Q runs `combine-measurements` at the
  end, and on a routed circuit that pass stops with "Multiple qalloc statements found" **[V]**
  at pass level (`Compiler.cpp:307-319`), **[U]** in the built plugin
  (`tests/run_fake_ibm.py` probes it). Not supported in M3.
- `cudaq.observe` on this target is untested **[U]**. Not supported in M3.
- If `output_names` is missing for a job, every bit is kept without a warning. That is right
  for a kernel that measures everything.
- A kernel with no `mz` and a qubit it never touches loses that qubit's bit: CUDA-Q removes
  the idle qubit before it adds the measurements **[V]** `Compiler.cpp:421, 467-473`.
  CUDA-Q's specification allows it, and `oqc` and `anyon` do the same
  ([m3-spec.md](../m3-spec.md) §2.11). A fix exists (`add-measurements` early in the
  pipeline); planned for M4 (Bruno, 2026-11-10; [roadmap.md](../roadmap.md)).

## Revisit when

Upstream passes the layout to helpers and fixes `mapping_reorder_idx`, or emulation is needed.
