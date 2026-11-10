# Upstream contributions to CUDA-Q

Date: 2026-11-10. Status: living list. Opened so far: item 5, as
[NVIDIA/cuda-quantum#5882](https://github.com/NVIDIA/cuda-quantum/issues/5882).
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
| 2 | `RestClient`: verify TLS by default (`enableSsl = true`), including the Executor's job POST | Today the default turns certificate checks off **[V]** `runtime/common/RestClient.h:49-76`, `RestClient.cpp:75` | Nothing in our code, but a security gap for all REST backends | Not started. Not a public issue: NVIDIA's `SECURITY.md` asks for security reports by its form or e-mail **[V]**. Bruno decides whether to report. |
| 3 | `RestClient`: allow form bodies and a way to turn off body logging | `post()` always JSON-dumps and logs the body at INFO **[V]** `runtime/common/RestClient.cpp` | libcurl IAM call ([decision 0005](decisions/0005-iam-login-with-libcurl.md)) | Idea; lower priority |
| 4 | Decomposition patterns to IBM's basis `{rz, sx, x, cz}` | `basis-conversion` fails on `quake.h` for that basis **[V]** experiment, `DecompositionPatterns.cpp` | Most of `plugin/Qasm2ToIsa.h` | After M2, using our proven rules |
| 5 | Give the helper the final layout: the device qubit behind each qubit of the generated code (attach it to `KernelExecution`). Other way: keep device ids through `regtomem` | After routing, `regtomem` turns borrowed device wires into plain allocations, so QASM and QIR number the qubits 0..m-1. Only `mapping_reorder_idx` reaches the helper **[V]** `RegToMem.cpp:569-585`, `KernelExecution.h:29`. Reproduced with a target NVIDIA ships: Anyon's pipeline and `berkeley-25q.txt` route a 3-qubit kernel onto device qubits {0, 1, 2, 6}; the QIR says 0..3 and has a cz on (3, 0), not coupled on that device **[V]** `experiments/upstream_layout_lost.py`. How often: 47 of 150 random kernels on that device, 12 of 150 on OQC `toshiko`, 0 of 150 on Anyon `telegraph-8q` and on IQM's 20-qubit mock graph **[V]** `experiments/upstream_layout_sweep.py`. Whether the vendors' servers then run the wrong qubits: **[U]**, we have no access. Related: #3080 (IQM, closed by its reporter), #5385 | Assignment search in `Layout.h` ([decision 0009](decisions/0009-route-with-cudaq-then-assign-qubits.md)) | **Opened** 2026-11-10 by Bruno: [NVIDIA/cuda-quantum#5882](https://github.com/NVIDIA/cuda-quantum/issues/5882). No answer yet. Before opening: the GHZ-5 runs on `ibm_fez` passed with the workaround, the script was rerun on 0.16.0.post1 (newest release), the tracker was searched again (#763 and #2190 read: other matters). |
| 6 | Share the fake IBM server as a mock QPU under `python/tests/utils/mock_qpu/` | In-tree backends test this way **[V]** `python/tests/backends/test_IQM.py` | Nothing; helps reviewers | Only if an in-tree IBM test makes sense |
| 7 | ~~`sample` on a kernel without `mz` should return one bit per allocated qubit~~ | `oqc` and `anyon` (`emulate=True`) return 2 bits for a 4-qubit kernel that touches 2 qubits; the simulator and four other targets return 4 **[V]** `experiments/m3_idle_qubit.py`. But the specification allows it: an unused qubit "may not appear in the implicit measurement results" **[V]** `algorithmic_primitives.rst`, tag 0.16.0 | - | Dropped 2026-11-10: documented behaviour, not a bug. |
| 8 | `mapping_reorder_idx` with `placement=auto` | With a modelled backend (bits sorted by qubit, then `reorderIdx`) the order is wrong in 32 of 60 kernels with `placement=auto search=sabre`, 0 of 60 with the default **[V]** `experiments/upstream_reorder_idx.py`. No shipped target uses `placement=auto`, and it is a model, not a run | Nothing: we do not use `reorderIdx` ([decision 0010](decisions/0010-measure-all-then-keep-measured-bits.md)) | Draft written, on hold. Mention in #5 only if asked. |

## Issue plan

Drafts, in NVIDIA's bug-report layout, are in the project files (`cudaq-ibm/upstream/`), not
in this repository, so that they can change freely until opened.

| Order | Issue | Open when | Why this order |
|---|---|---|---|
| 1 | #5, final layout | Opened 2026-11-10: [#5882](https://github.com/NVIDIA/cuda-quantum/issues/5882) | The hardware runs show our workaround gives right answers on a real chip, which makes the report stronger. The evidence itself does not depend on them. |
| 2 | #1, `getHeaders()` in the poll loop | With a PR; next, now that M3 is done | Already agreed ([decision 0004](decisions/0004-accept-token-expiry-in-v1.md)). |
| - | #8, `reorderIdx` | Not planned | Weak: modelled, and no shipped target is affected. |
| - | #2, TLS checks off by default | Bruno's call | Security reports do not go through GitHub issues (`SECURITY.md`). |
| - | #7, idle qubits | Dropped | Documented behaviour. |
| - | `emulate=True` fails after routing when the pipeline has `combine-measurements` | Not planned as it stands | Confirmed in the built plugin **[V]** 2026-11-10 ([architecture.md](architecture.md) §8 item 7), but only with our own pipeline. No shipped target is shown to fail **[U]**. To check in M4, where emulation is fixed on our side anyway. |
| - | IBM-side findings of the hardware runs (error reported as 1, readout error that includes preparation, forecast too high) | Not for CUDA-Q | Facts about IBM's data ([architecture.md](architecture.md) §3.7, §9.8). |
| - | `cudaq.translate` prints other OpenQASM than a `ServerHelper` receives | Not planned | `translate` runs extra passes ([architecture.md](architecture.md) §9.7). A surprise for us, not shown to be a bug. |

Before opening each one:

1. Run its script again on the newest CUDA-Q release (#5 reproduces on 0.16.0 and
   0.16.0.post1, checked 2026-11-10), and on `main` if a nightly build is easy to get.
   `Compiler.cpp` is changing (#5113, #5154), so results may differ.
2. Search the issue tracker again, and the documentation: #7 looked like a bug until the
   specification showed it is allowed. Searched on 2026-11-10: nothing on
   `mapping_reorder_idx`; #3080 and #5385 are the nearest to #5.
3. One problem per issue. Say what was run and what was not; mark the vendor-server part
   as unknown.
4. Offer a pull request for #5 (pass the layout) once a maintainer agrees on the shape
   in [#5882](https://github.com/NVIDIA/cuda-quantum/issues/5882).
