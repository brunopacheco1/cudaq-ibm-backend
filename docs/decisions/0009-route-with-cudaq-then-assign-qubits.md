# 0009. Route with CUDA-Q, then assign IBM qubits to its labels

Date: 2026-11-09. Status: accepted.
Tags: **[V]** verified (source given), **[U]** unverified.
Evidence: [m3-spec.md](../m3-spec.md) §2 (until M3 ends, then [architecture.md](../architecture.md)).

## Context

CUDA-Q's `qubit-mapping` pass routes a kernel on a device graph we give it as a file. After
routing, `regtomem` packs the device qubits the circuit used into labels 0..m-1, and the real
layout (`mapping_v2p`) is not passed to the helper **[V]** `experiments/m3_qubit_ids.py`.
Routing often borrows qubits outside 0..n-1 (20 of 30 test circuits on `ibm_fez`, including a
20-qubit GHZ chain) **[V]** `experiments/m3_routing.py`. So "label = device qubit" is wrong.

## Options

- **D1-A.** Prefix layout plus a guard that refuses jobs that borrowed a qubit. Refuses too
  much (above).
- **D1-A'.** Prefix layout plus an **assignment search**: map each label to a device qubit so
  every 2-qubit gate lands on a link. Any such map gives the same computation; borrowed qubits
  start in |0> wherever they sit.
- **D1-B.** Keep ids with `wireset-to-profile-qir` and translate QIR ourselves (translation
  failed in a first try).
- **D1-C.** Fix it upstream (keep ids, or pass `mapping_v2p` to helpers). Slow.

## Decision (Bruno, 2026-11-09; items 4 and 5 proposed, waiting for Bruno)

1. **D1-A' now, D1-C in parallel** ([upstream.md](../upstream.md) #5). The search lives in
   `plugin/Layout.h`; it throws only if no valid map exists.
2. **D2-C: noise-aware root.** Drop links with cz `gate_error` = 1 or `operational` = 0 and
   qubits with `operational` = 0; keep the largest connected part; root = lowest (mean cz
   error of its links + readout error). Number breadth-first from it, so every prefix is
   connected and routing stays near the root.
3. **D3-A: fetch `/configuration` and `/properties` on every compile**, like IQM, with a
   `mapping_file` target argument to skip the fetch in tests.
4. **Router options `placement=auto search=sabre`**, not CUDA-Q's default identity start:
   GHZ-20 on `ibm_fez` needs 28 two-qubit gates instead of 151 **[V]** `m3_routing.py`.
5. **Do not apply `reorderIdx`** to IBM results: the QASM2 classical-bit order is already the
   user's order (40/40) **[V]** `experiments/m3_bit_order.py`.

## Consequences

- Every circuit CUDA-Q can route runs; nothing is refused for borrowing.
- Two extra GETs per compiled kernel. If `/properties` fails, we warn and pick the root
  without error rates.
- The layout set at compile time is used at submit time; both happen in one call.

## Revisit when

Upstream passes the final layout to helpers (then drop the search), or we want a
noise-aware router, not just a noise-aware start.
