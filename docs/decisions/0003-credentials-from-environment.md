# 0003. Read IBM credentials from the environment only

Date: 2026-11-08. Status: accepted.

## Context

The plugin needs an IBM Cloud API key and an instance CRN. CUDA-Q target arguments end up in
`backendConfig`, which CUDA-Q copies around and may log. `RestClient::post` also logs request
bodies at INFO **[V]** `runtime/common/RestClient.cpp`.

## Options

- **A.** Target arguments (`cudaq.set_target("ibm", api_key=...)`), like some other backends.
- **B.** Environment variables only: `IBM_QUANTUM_API_KEY`, `IBM_QUANTUM_CRN`.

## Decision

B. The key lives in one private member of `IBMServerHelper` and only goes to IAM through
libcurl ([0005](0005-iam-login-with-libcurl.md)), which logs nothing.

## Consequences

- Users must export two variables (or use a git-ignored `.env`) before `set_target`.
- `initialize` throws a clear error if either is missing.
- Same variable names as the Python prototype, so one `.env` serves both.

## Revisit when

We add QRMI as a transport (it has its own `QRMI_IBM_QCS_*` configuration), or users ask for
a credentials file like `qiskit-ibm-runtime`'s.
