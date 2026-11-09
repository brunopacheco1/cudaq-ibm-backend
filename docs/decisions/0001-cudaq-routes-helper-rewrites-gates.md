# 0001. CUDA-Q routes, the ServerHelper rewrites gates (Option A)

Date: 2026-11-06. Status: accepted. Decided by: Bruno.

## Context

IBM only accepts ISA circuits (native gates `{rz, sx, x, cz}` on connected qubits). IBM's
server-side transpilation is gone, and its transpiler service is Premium-only. CUDA-Q 0.16
can route on a topology file, but cannot decompose to IBM's basis and renumbers physical
qubits **[V]** experiments in [research/2026-11-06-phase3-design.md](../research/2026-11-06-phase3-design.md) §3.

## Options

- **A.** CUDA-Q routes; the `ServerHelper` does a small, fixed gate rewrite to IBM's basis.
- **B.** The `ServerHelper` is a full mini-transpiler (layout, routing, rewrite) in C++.
- **C.** Someone else transpiles (IBM service, Premium only; or a Qiskit sidecar).

## Decision

Option A. Small (~400 lines), every quantum step is visible, and the two CUDA-Q gaps are
good upstream contributions ([upstream.md](../upstream.md)).

## Consequences

- We depend on CUDA-Q pass names, an internal API. Pin `cudaq-version`.
- Physical qubit ids are compacted to 0..n-1 by CUDA-Q. Tolerated; the helper will relabel
  qubits so 0..m-1 is a good connected region (M3).
- Routing quality is mediocre (23 swaps for a 20-qubit GHZ on Fez) and not noise-aware.

## Revisit when

Routing quality starts to matter for real experiments (then add B's layout logic), or CUDA-Q
gains native IBM basis patterns and layout export upstream (then drop the text rewrite).
