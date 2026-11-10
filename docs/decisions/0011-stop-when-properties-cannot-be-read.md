# 0011. Stop when `/properties` cannot be read (fail closed)

Date: 2026-11-10. Status: accepted.
Tags: **[V]** verified (source given), **[U]** unverified.

## Context

`/properties` tells us which qubits and links are broken (`operational` = 0, cz `gate_error`
= 1) and gives the error rates for the root choice ([decision 0009](0009-route-with-cudaq-then-assign-qubits.md)).
The first M3 code warned and continued when the request failed, and skipped entries it could
not read. Then no broken link is removed and a `cz` can land on one. The FakeFez snapshot has
7 broken links **[V]** m3-spec §2.5. What real IBM does with such a job is **[U]**. The free
plan gives about 10 minutes of QPU time per 28 days.

## Options

- **A.** Warn and continue. Jobs keep flowing during an IBM hiccup, but a wrong guess costs
  QPU time, and a format change (a renamed field) goes unnoticed.
- **B.** Stop with a clear error. A retry is free. IQM does this for its chip data **[V]**
  `IQMServerHelper.cpp:588-590`.
- **C.** Stop by default, with a target argument to continue. More surface, no present need.

## Decision (Bruno, 2026-11-10)

**B**, and what we cannot read, we do not trust (`plugin/ChipData.h`, `Layout.h`
`closeUnknowns`):

- The request fails, or the reply has no `qubits` or `gates` list: error.
- An `operational` or `gate_error` value we cannot read: that qubit or link is broken.
- A link with no cz error in either direction is not used (it must not look perfect).
- A qubit with no readout error gets the worst score: never the root, still usable.
- No cz error for any link: error (not a cz backend).
- Anything skipped is counted in one warning.

**Added 2026-11-10, after the first hardware run** (done by Claude under this decision,
reported to Bruno the same day; he can reverse it):

- A qubit whose `sx` or `x` `gate_error` is 1, or cannot be read, is not used. Real `ibm_fez`
  data had this for qubits 72, 148 and 149 **[V]** (calibration of 2026-11-10), and the first
  M3 code never looked at 1-qubit gates. No `sx` or `x` entry at all changes nothing.

What an error of 1 means **[V]** IBM guide
["QPU information"](https://quantum.cloud.ibm.com/docs/en/guides/qpu-information): when the
benchmark of a gate fails for several days, the value is stale and reported as 1. IBM says
this does not prove the qubit or link is broken; the error is undefined and "you should
proceed with caution". So "broken" in this record means "error unknown, we do not use it",
for links (cz error 1) and for qubits (sx or x error 1) alike.

## Consequences

- If `/properties` is down, nothing runs on that backend. Way around: `mapping_file`.
- A damaged entry shrinks the usable region a little instead of risking a bad job.
- Checked on the FakeFez snapshot (qiskit-ibm-runtime 0.52.0): 0 unreadable entries, 154 of
  156 qubits usable **[V]** `plugin/tests/test_chip_data.cpp` in file mode. Real `ibm_fez`
  data (2026-11-10): 0 unreadable entries **[V]**; one link (32-33) and three qubits (72,
  148, 149) carry an error of 1.

## Revisit when

Real `/properties` turns out to be flaky, or a paid plan makes a bad job cheap.
