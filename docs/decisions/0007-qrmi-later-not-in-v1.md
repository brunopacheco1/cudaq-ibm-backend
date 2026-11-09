# 0007. QRMI as a later transport, not in v1

Date: 2026-11-06. Status: accepted.
Tags: **[V]** verified (source given), **[U]** unverified.

## Context

QRMI (https://github.com/qiskit-community/qrmi) is IBM's vendor-neutral resource interface.
**[V]** clone and GitHub page, 2026-11-06:

- v0.26.6, Apache-2.0, Rust core with a C API (`qrmi_resource_{new,acquire,task_start,task_status,task_result,target}`, `src/cext.rs`).
- IBM resources: `ibm-quantum-compute-service` and `ibm-quantum-system` (Direct Access).
  Payload is the Sampler V2 schema. `target()` returns the backend configuration and
  properties, which the topology builder (M3) needs.
- CUDA-Q 0.16 already bundles `libqrmi` for its Pasqal connector (Linux only).
- It does **not** transpile, so it does not solve the ISA problem.
- `acquire()` defaults to a dedicated session (`QRMI_IBM_QCS_SESSION_MODE`), which the Open
  plan may not allow **[U]**. The API has churned since v0.23.

## Options

- **A.** Build v1 on QRMI.
- **B.** Plain REST in v1; keep the transport replaceable; add QRMI later.

## Decision

B. Plain REST is what the prototype proved on hardware, and QRMI adds a moving dependency
without solving the hard part.

## Consequences

- Our own IAM and job code ([0005](0005-iam-login-with-libcurl.md)).
- QRMI stays on the roadmap (M5) as a second transport and a place to contribute.

## Revisit when

v1 works end to end on hardware, or QRMI's session defaults and API settle.
