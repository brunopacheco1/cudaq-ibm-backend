# 0001. CUDA-Q routes, the ServerHelper rewrites gates (Option A)

Date: 2026-11-06. Status: accepted. Decided by: Bruno.
Tags: **[V]** verified (source given), **[U]** unverified. CUDA-Q file references are in the `0.16.0` tag.

## Context

IBM only accepts ISA circuits: "When submitting a job to an IBM Quantum backend, the circuits
must adhere to the backend's ISA" **[V]** https://quantum.cloud.ibm.com/docs/guides/transpile.
On `ibm_fez` that means gates `{rz, sx, x, cz}`, with 2-qubit gates only on wired qubits.

Nobody else will transpile for us:

- IBM's server-side transpilation is gone; the `transpiled_circuits` endpoint was dropped on
  2026-02-01 **[V]** https://quantum.cloud.ibm.com/docs/api/qiskit-runtime-rest/changelog.
- The Qiskit Transpiler Service is "only available for IBM Quantum Premium Plan members"
  **[V]** https://quantum.cloud.ibm.com/docs/api/qiskit-transpiler-service-rest.

What CUDA-Q 0.16 can do **[V]** experiments with the pip wheel's MLIR bindings, 2026-11-06:

| Capability | Result |
|---|---|
| Route on a 156-qubit heavy-hex graph from a file | Works: `qubit-mapping{device=file(F)}`, SABRE (`Mapping.cpp:812`), 0.01-0.02 s per kernel |
| Load the topology from the vendor at run time | Works: `getPipelineSubstitutions` runs on every compile (`BaseRemoteRESTQPU.h:225-229`); IQM does this (`IQMServerHelper.cpp:457-490`) |
| Decompose to `{cz, rz, sx, x}` | Fails: "failed to legalize operation 'quake.h'"; no patterns for that basis (`DecompositionPatterns.cpp`) |
| Decompose to a textbook basis `{h, rx, ry, rz, x, z, cx}` | Works, but leaves `y` and `u3` as they are (observed QASM2, 2026-11-08) |
| Keep physical qubit ids | Fails: `regtomem` renumbers to 0..n-1 (`RegToMem.cpp:121-140`); the layout `mapping_v2p` is not passed to the helper (`KernelExecution.h:23-32`) |
| Routing quality | Mediocre: GHZ-20 on Fez needed 23 swaps; not noise-aware |
| Topology with isolated qubits | Error "disconnected device topology" (`Mapping.cpp:3189`); prune them first |

## Options

- **A.** CUDA-Q routes; the `ServerHelper` rewrites the textbook gates into `{rz, sx, x, cz}`
  with fixed identities (~400 lines of C++).
- **B.** The `ServerHelper` is a mini-transpiler: layout, routing and rewrite in C++ with live
  error rates. Correct and noise-aware, but ~1-2k lines plus tests, all ours to maintain.
- **C.** Someone else transpiles: IBM's service (Premium only) or a local Qiskit sidecar
  (brings Python and Qiskit back into a C++ plugin).

## Decision

Option A. It is small, every quantum step stays visible in the code, and the two CUDA-Q gaps
become useful upstream contributions ([upstream.md](../upstream.md) #4, #5).

## Consequences

- We depend on CUDA-Q pass names, an internal API ("Contact the CUDA-Q team for help setting
  this up", `backend.rst:172`). Pin `cudaq-version`.
- Physical ids are compacted to 0..n-1. Tolerated: the helper will relabel qubits so 0..m-1
  is a good, connected region (M3).
- Routing is not noise-aware. Fine for learning.
- How the rewrite works today: [architecture.md](../architecture.md) §4.

## Revisit when

Routing quality starts to matter (add B's layout logic), or CUDA-Q gains IBM basis patterns
and layout export upstream (drop the text rewrite).
