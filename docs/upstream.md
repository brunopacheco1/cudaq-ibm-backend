# Upstream contributions to CUDA-Q

Date: 2026-11-09. Status: living list. Nothing opened yet.
Reader: Bruno, before opening an issue or PR on NVIDIA/cuda-quantum.
Tags: **[V]** verified (source given), **[U]** unverified.
File references are in the CUDA-Q `0.16.0` tag.

Each item is a gap we hit while building this plugin. A fix upstream removes a workaround here
and helps every other backend too.

Rules before opening anything:

- Search existing issues and PRs first. On 2026-11-06 there were none about IBM support **[V]**.
- Contributions need a DCO sign-off (`git commit -s`) **[V]** `Contributing.md:38-79`.
- NVIDIA expects backends to stay external plugins (`backend.rst:6-9`) **[V]**, so we propose
  generic fixes, not an in-tree `ibm` target.

| # | Change | Why (evidence) | Removes here | Status |
|---|---|---|---|---|
| 1 | Call `getHeaders()` inside the poll loop in `Future::get`, like `getCookies()` | Headers are built once per job, so tokens expire during long queue waits **[V]** `runtime/common/Future.cpp` | Limit in [decision 0004](decisions/0004-accept-token-expiry-in-v1.md) | Not started. First PR to open. |
| 2 | `RestClient`: verify TLS by default (`enableSsl = true`), including the Executor's job POST | Today the default turns certificate checks off **[V]** `runtime/common/RestClient.cpp` | Nothing in our code, but a security gap for all REST backends | Not started. Report as an issue first. |
| 3 | `RestClient`: allow form bodies and a way to turn off body logging | `post()` always JSON-dumps and logs the body at INFO **[V]** `runtime/common/RestClient.cpp` | libcurl IAM call ([decision 0005](decisions/0005-iam-login-with-libcurl.md)) | Idea; lower priority |
| 4 | Decomposition patterns to IBM's basis `{rz, sx, x, cz}` | `basis-conversion` fails on `quake.h` for that basis **[V]** experiment, `DecompositionPatterns.cpp` | Most of `plugin/Qasm2ToIsa.h` | After M2, using our proven rules |
| 5 | Keep physical qubit ids through `regtomem`, or export the final layout (`mapping_v2p`) into `KernelExecution` | `regtomem` packs the used device qubits into 0..m-1 and the layout is not passed to the helper **[V]** `RegToMem.cpp:560-590`, `KernelExecution.h:23-32`, `experiments/m3_qubit_ids.py`. IQM, OQC and Anyon also run `regtomem` after routing (`iqm.yml`, `oqc.yml`, `anyon.yml`) and IQM names allocas in order (`TranslateToIQMJson.cpp`), so they likely send wrong qubits when routing borrows one **[U]** not run on their targets. Related: issue #3080 (closed as not an issue). | Assignment search in `Layout.h` (M3) | Issue draft in progress |
| 6 | Share the fake IBM server as a mock QPU under `python/tests/utils/mock_qpu/` | In-tree backends test this way **[V]** `python/tests/backends/test_IQM.py` | Nothing; helps reviewers | Only if an in-tree IBM test makes sense |
