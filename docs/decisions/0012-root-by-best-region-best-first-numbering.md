# 0012. Root by its best 10-qubit region, best-first numbering

Date: 2026-11-10. Status: accepted. Replaces item 2 of
[decision 0009](0009-route-with-cudaq-then-assign-qubits.md).
Tags: **[V]** verified (source given), **[U]** unverified.
Evidence: [m3-spec.md](../m3-spec.md) §6 step 3.

## Context

Decision 0009 chose the root by its own numbers (mean cz error of its links + readout error)
and numbered the chip breadth-first from it. On the first hardware run (`ibm_fez`,
2026-11-10) that picked qubit 114: readout error 0.1%, but only two neighbours, and one of
them, 113, had a readout error of 11.7% (chip median 1.2%). Breadth-first numbering gave
113 label 1, so GHZ-5 ran through it and scored 81.2% **[V]**.

The run also tested a simple forecast: multiply (1 - readout error) over the qubits used and
(1 - cz error) over the links used. It gave 82.9% for that job; measured 81.2% ± 2.5 **[V]**.
One data point.

## Options

Forecast for the first 5, 10 and 20 numbers, same calibration **[V]** (Python on the saved
`/properties` reply, m3-spec §6 step 3):

| | Rule | Root | 5 | 10 | 20 |
|---|---|---|---|---|---|
| A | Keep: best own score, breadth-first | 114 | 85.3% | 77.6% | 58.7% |
| B | Keep the root rule, number best-first | 114 | 93.3% | 85.6% | 76.5% |
| C | Root by its best 10-qubit region, number best-first | 124 | 96.5% | 91.9% | 79.7% |

(A fourth mix, new root with breadth-first numbering, was worse at 20 qubits: 46.3%.)

## Decision (Bruno, 2026-11-10)

**C.** In `plugin/Layout.h`:

- **Best-first numbering.** Label 0 is the root. The next label goes to the qubit, linked to
  an already numbered one, with the lowest cost = its readout error + the cz error of its
  best link into the numbered set. Ties go to the lowest IBM id. Every prefix 0..k-1 stays
  connected, by the same proof as before.
- **Root.** Grow such a patch of 10 qubits (`ROOT_REGION_SIZE`) from every usable qubit; the
  root is the one whose patch has the best forecast. Roots inside the same patch tie; then
  the lower readout error wins, then the lower IBM id.
- The plugin logs the root and the forecast of its patch at INFO.

## Consequences

- A badly measured qubit next to a good one is numbered late instead of early.
- One fixed setting, the patch size 10. The kernel size is not known when the device file is
  written, so it cannot follow the circuit. A 5-qubit job gets the best start of a good
  10-qubit patch, not necessarily the best 5-qubit patch on the chip.
- The job does not stay strictly inside the first numbers (GHZ-5 used numbers 0, 1, 2, 3 and
  5), so real gains are somewhat below the table. Not measured on hardware yet **[U]**.
- The forecast ignores 1-qubit gate errors, idle time (T1, T2) and crosstalk, and the
  calibration can be a day old (on 2026-11-10 the values were 13 hours old).
- Cost: 156 patches of 10 qubits per compile, well under a millisecond.

## Revisit when

A second hardware run does not show the gain; or CUDA-Q gets a noise-aware router or passes
the final layout to the helper ([upstream.md](../upstream.md) #5), which would let the
placement follow the circuit.
