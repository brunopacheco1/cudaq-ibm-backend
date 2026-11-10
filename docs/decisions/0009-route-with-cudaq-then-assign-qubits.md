# 0009. Route with CUDA-Q, then assign IBM qubits to its labels

Date: 2026-11-10. Status: accepted.
Tags: **[V]** verified (source given), **[U]** unverified.
Evidence: [m3-spec.md](../m3-spec.md) §2 (until M3 ends, then [architecture.md](../architecture.md)).

## Context

CUDA-Q's `qubit-mapping` pass routes a kernel on a device graph we give it as a file. After
routing, `regtomem` packs the device qubits the circuit used into labels 0..m-1, and the real
layout (`mapping_v2p`) is not passed to the helper **[V]** `experiments/m3_qubit_ids.py`.
Routing often borrows qubits outside 0..n-1 (20 of 30 test circuits on `ibm_fez` with the
default options) **[V]**. So "label = device qubit" is wrong.

## Options

- **D1-A.** Prefix layout plus a guard that refuses jobs that borrowed a qubit. Refuses too much.
- **D1-A'.** Prefix layout plus an **assignment search**: map each label to a device qubit so
  every 2-qubit gate lands on a link. Any such map gives the same computation; borrowed qubits
  start in |0> wherever they sit.
- **D1-B.** Keep ids with `wireset-to-profile-qir` and translate QIR ourselves (failed in a
  first try).
- **D1-C.** Fix it upstream (pass the layout to helpers). Slow.

## Decision (Bruno, 2026-11-09 and 2026-11-10)

1. **D1-A' now, D1-C in parallel** ([upstream.md](../upstream.md) #5). The search lives in
   `plugin/Layout.h`. It returns a valid map or throws; never a wrong one.
2. **Noise-aware root.** Drop broken links and qubits; keep the largest connected part; root =
   lowest (mean cz error of its links + readout error); number breadth-first from it, so every
   prefix 0..k-1 is connected. The search tries each label's own number first, which keeps the
   circuit near the root.
3. **Fetch `/configuration` and `/properties` per compile**, kept 60 s: CUDA-Q asks for the
   device file twice per `sample` **[V]** `launch.h:83-86`, `RemoteRESTQPU.cpp:33`, so both
   calls share one fetch. `mapping_file` skips the fetch. What happens when `/properties`
   cannot be read: [decision 0011](0011-stop-when-properties-cannot-be-read.md).
4. **Router options `placement=auto search=sabre`**, not CUDA-Q's default identity start:
   GHZ-20 on `ibm_fez` needs 28 two-qubit gates instead of 151. Most of the gain is the
   placement (`auto` alone: 34) **[V]** `experiments/m3_routing.py`, m3-spec §2.9.

Result bit order is a separate choice: [decision 0010](0010-measure-all-then-keep-measured-bits.md).

## Consequences

- Every circuit CUDA-Q can route runs; nothing is refused for borrowing.
- Two GETs per `sample`. The layout at submit time may differ from the one CUDA-Q routed on
  (calibration changed in between); still correct, the search places the circuit on the
  layout it has.
- No hardware target shipped with CUDA-Q uses `placement=auto search=sabre` **[V]** `iqm.yml`,
  `oqc.yml`, `anyon.yml`. If a router bug shows up: `placement=auto search=none`, then the default.
- Known limit: above about 100 qubits the search may run out of steps and refuse the circuit
  with a clear error **[V]** `experiments/m3_search_stress.cpp`.

## Revisit when

Upstream passes the final layout to helpers (then delete the search), or we want a
noise-aware router, not just a noise-aware start.
