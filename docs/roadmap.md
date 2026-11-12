# Roadmap

Date: 2026-11-12. Status: living document. Update it when a milestone or risk changes.
Reader: Bruno.
Tags: **[V]** verified (source given), **[U]** unverified.

The plan follows [decision 0001](decisions/0001-cudaq-routes-helper-rewrites-gates.md). Effort is
rough, for part-time work. Each milestone is shippable.

## 1. Milestones

| # | Deliverable | Effort | Done when | Status |
|---|---|---|---|---|
| M0 | Dev environment: CUDA-Q 0.16.0 source build in NVIDIA's dev container; build and run the `mock_rest` reference plugin | 1-2 days | `mock_rest` sample runs end to end | **Done** 2026-11-08 (Podman, [decision 0002](decisions/0002-build-in-linux-dev-container.md)). The ABI check moved to M4. |
| M1 | `ibm` plugin: YAML (no mapping yet), IAM auth, job POST/poll/results, hex decoding; fake IBM server | 2-3 days | Bell pair end to end against the fake server | **Done** 2026-11-08, PR #1. Result `{ 01:1 10:2 }`. |
| M2 | `qasm2ToIsaQasm3` gate rewrite with unit tests; first real Bell pair on `ibm_fez` qubits 0-1 | 3-5 days | Hardware counts match the Python prototype | **Done** 2026-11-09. Rules h, cx (PR #2) and z, y, rx, ry, u3 (derived by Bruno, PR #4). Bell on `ibm_fez`: `{ 00:495 11:449 01:39 10:17 }`, 94.4% correlated (prototype: 95.1%). |
| M3 | Routing: fetch configuration and properties, prune, noise-aware numbering, device file, `qubit-mapping` in YAML, label -> IBM qubit assignment; fake server checks 2-qubit gates against the real coupling map | 3-5 days | 5-qubit GHZ on hardware; 20-qubit GHZ accepted by the fake server | **Done** 2026-11-10, PR #7 (decisions [0009](decisions/0009-route-with-cudaq-then-assign-qubits.md) to [0012](decisions/0012-root-by-best-region-best-first-numbering.md)). GHZ-5 on `ibm_fez`: 81.2% of 1000 shots in `00000` or `11111` with the first root rule, **90.5%** after decision 0012. Out-of-order measurement kernel: 98.0% of 200 shots correct, twice. GHZ-20 accepted by the fake server with 28 `cz`. How it works and what the runs showed: [architecture.md](architecture.md) §9. |
| M4 | Packaging: wheels (Linux x86_64, aarch64), ABI check against pip `cudaq`, `--install-nvqpp`, README, CI (build in dev container, run fake-server tests) | 2-3 days | `pip install` then `cudaq.set_target("ibm")` works | **Done** 2026-11-11, PRs #14 to #21 (decisions [0013](decisions/0013-build-against-the-pip-wheel.md) to [0019](decisions/0019-no-observe-in-the-first-release.md)). It grew beyond packaging: CI builds the plugin against the pip wheel and compares its results with CUDA-Q's simulator through a simulating fake server; idle qubits keep their bits; `emulate=True` and `observe` are refused with a clear error; `examples/expectation_from_samples.py` computes expectation values from `sample` counts (Bruno). The plugin is a wheel, `cudaq-ibm`, for Linux x86_64 and aarch64, built in the `manylinux_2_28` image and tested as installed. First release: [v0.1.0rc1](https://github.com/brunopacheco1/cudaq-ibm-backend/releases/tag/v0.1.0rc1). From that wheel in a plain container, a Bell pair on `ibm_fez`: fidelity **0.958 ± 0.005** ([architecture.md](architecture.md) §9.8). CI built against the wheel, not in the dev container. |
| M5 | Optional: `transport=qrmi` using the bundled `libqrmi` ([decision 0007](decisions/0007-qrmi-later-not-in-v1.md)); upstream PRs ([upstream.md](upstream.md): token refresh in `Future.cpp`, `RestClient` TLS default, native IBM basis patterns, `mapping_v2p` export, fake IBM server) | 1-2 weeks | PRs opened with DCO sign-off | Not started |

## 2. Next steps

1. Upstream: the first issue is open since 2026-11-10,
   [NVIDIA/cuda-quantum#5882](https://github.com/NVIDIA/cuda-quantum/issues/5882) ([upstream.md](upstream.md) #5). Follow the answer.
   The second, a feature request, is open since the same day:
   [NVIDIA/cuda-quantum#5886](https://github.com/NVIDIA/cuda-quantum/issues/5886) ([upstream.md](upstream.md) #1,
   `getHeaders()` on every poll). Follow the answer; the pull request comes after it.
2. After M4: use the release (`v0.1.0rc1`) and collect what breaks. Open items: a macOS
   wheel ([decision 0014](decisions/0014-first-release-for-linux-x86-64-and-aarch64.md));
   the package name before PyPI
   ([decision 0015](decisions/0015-github-release-first-settle-the-name-before-pypi.md));
   `emulate=True` and `observe` once CUDA-Q's announced change to `sample` and `observe`
   is out (decisions [0018](decisions/0018-refuse-emulate.md) and
   [0019](decisions/0019-no-observe-in-the-first-release.md)); `nvq++` with the plugin,
   never tried; the CMake build in the dev container after the M4 edit of
   `plugin/CMakeLists.txt`, to run once.
3. M5 (optional): see the table above.
4. Later, if results matter: a label search that prefers low numbers, and a better forecast
   ([architecture.md](architecture.md) §9.8).
5. From the limit probes of 2026-11-12 ([architecture.md](architecture.md) §8 item 9).
   Candidates, none decided; Bruno picks:
   - Plumbing, small: refuse an angle that is NaN or infinite and `shots_count=0` before
     a job is sent; compare the number of samples with the shots; say what is wrong when
     a reply is not JSON, when a `mapping_file` is not a device file, and when the chip
     has no `cz`; accept a `url` that ends in `/`.
   - Plumbing, larger: return the named measurement results and the order of the shots;
     try our own requests again after a transient error (chip data, results). The job
     POST and the wait loop are CUDA-Q's ([upstream.md](upstream.md) #13).
   - Quantum side (Bruno): rules for `s`, `sdg`, `t`, `tdg`, which makes `my` work;
     `reset` (does IBM take it in a circuit of native gates? **[U]**); why `mx` fails in
     our pipeline.
   - Hardware (Bruno starts them): how wide and how deep before noise drowns the answer,
     and what IBM really answers to a NaN angle, to 0 shots and to a 6th job in a minute.
     The script is ready and rehearsed: `tests/run_ibm_hardware_limits.py`
     ([development.md](development.md) §4).
   - A release after `v0.1.0rc1` (Bruno tags it): it carries the fix for `mz` on 50 or
     more qubits, which the released wheel does not have.

## 3. Open risks

Evidence is in the linked decision records.

| Risk | Status | Plan |
|---|---|---|
| Physical qubit ids compacted by CUDA-Q | **[V]** reproduced: a routed qubit 9 arrives as 5 ([architecture.md](architecture.md) §9.2); routing borrows qubits often | Assignment search in `Layout.h` ([decision 0009](decisions/0009-route-with-cudaq-then-assign-qubits.md)); upstream fix ([upstream.md](upstream.md) #5) |
| Routing quality | **[V]** GHZ-20 on `ibm_fez`: 3 swaps with `placement=auto search=sabre`, 44 with CUDA-Q's default (architecture §9.6) | Noise-aware router later, if it matters |
| Tests check gates and links, not results | Closed 2026-11-10 **[V]**: the fake server simulates the circuit, and CI compares 26 kernels with CUDA-Q's simulator ([architecture.md](architecture.md) §7). Left: no noise in the simulator, and the mirror-image limit described there | Hardware run at the end of each milestone |
| `emulate=True` and `observe` on the `ibm` target | **[V]** 2026-11-10: both are refused with a clear error, before any job is sent ([architecture.md](architecture.md) §8 item 7). Before M4 emulation failed inside CUDA-Q and `observe` failed or crashed Python ([decision 0019](decisions/0019-no-observe-in-the-first-release.md)) | Not supported in this release (decisions [0018](decisions/0018-refuse-emulate.md) and [0019](decisions/0019-no-observe-in-the-first-release.md)). Expectation values from `sample` counts: `examples/expectation_from_samples.py`. Decide again after CUDA-Q's change to `sample` and `observe` |
| CUDA-Q will change `sample` and `observe` | **[V]** `import cudaq` 0.16.0 prints a `FutureWarning` saying so; the page it links has no details yet (read 2026-11-10). A concrete change was in review on 2026-11-10: NVIDIA/cuda-quantum PR 5875, by a maintainer. By its description kernels will need an explicit `cudaq.record(...)`, the router stops producing `mapping_reorder_idx`, and a `ServerHelper` gets the recorded qubits; whether those are device ids is **[U]** | Watch the release notes; the bit-order rule in [decision 0010](decisions/0010-measure-all-then-keep-measured-bits.md) depends on today's `sample` contract, and the result checks in CI will show at once if it breaks. Read the PR before any design of `emulate` or `observe` |
| Kernel with an idle qubit returns a shorter bit string | Closed 2026-11-10 **[V]**: `dqe` removed from the pipeline; six kernels with idle qubits in the CI result checks ([architecture.md](architecture.md) §8 item 6) | Cost: an idle qubit takes a chip qubit and a readout |
| The forecast behind the root rule overstates results | **[V]** 2026-11-10, two GHZ-5 runs on `ibm_fez`: old rule 81.2% (forecast 82.9%), new rule ([decision 0012](decisions/0012-root-by-best-region-best-first-numbering.md)) 90.5% (forecast 95.0%). The rule picks better qubits; the number it prints is a few points too high. The label search also took qubit 125 (number 14) where a cheaper chain fits (architecture §9.8) | Treat the logged forecast as an upper bound. Later, if it matters: next step 4 |
| Label -> qubit search refuses large circuits | **[V]** fine up to about 100 qubits (architecture §8 item 5) | Goes away when upstream passes the layout ([upstream.md](upstream.md) #5) |
| A failed request while waiting loses a job that is paid for | **[V]** 2026-11-12, fake server: one HTTP 500 during the wait ends `sample`; nothing tries again ([architecture.md](architecture.md) §8 item 9) | For jobs that matter: `sample_async`, keep `str(future)`, ask again. Upstream: [upstream.md](upstream.md) #13 |
| IBM takes 5 jobs per minute per user | **[V]** IBM REST reference, read 2026-11-12. The plugin does not wait and try again: the 6th job fails, and a `sample` over a list of argument sets loses the answers before it **[V]** fake server, same day. IBM's real reply **[U]** | Keep a list of argument sets to 5, or space the jobs. A hardware check costs no QPU time if the 6th job is refused |
| The released wheel `v0.1.0rc1` cannot compile a kernel with `mz` on 50 or more qubits | **[V]** 2026-11-12, probes `s_x_pattern_with_mz_050` and three more ([architecture.md](architecture.md) §8 item 9). Fixed on `main` after this change, not in a release yet | With `v0.1.0rc1`: leave the `mz` out. A new release candidate carries the fix (Bruno tags it) |
| A result with the wrong shape and no error | **[V]** 2026-11-12: extra bits for a gate with 3 or more controls in a kernel without `mz` (CUDA-Q does this for every hardware target); named measurement results come back as one register ([architecture.md](architecture.md) §8 item 9) | Write the `mz`. Named results: next step 5 |
| Real `/properties` differs from the FakeFez snapshot | **[V]** 2026-11-10: real `ibm_fez` data parses with 0 unreadable entries; it has no "operational" item per qubit, and marks stale benchmarks with an error of 1 (architecture §3.7) | The plugin stops rather than guess, and leaves out what has an error of 1 ([decision 0011](decisions/0011-stop-when-properties-cannot-be-read.md)) |
| Plugin ABI vs pip `cudaq` | **[V]** for Linux x86_64 and aarch64, 2026-11-11: built against the pip wheel of `cudaq` 0.16.0, the plugin loads into pip `cudaq` 0.16.0 and 0.16.0.post1 and passes the fake-server cases ([architecture.md](architecture.md) §8 item 4). macOS **[U]** | Workflow `wheels` on every pull request, for every supported `cudaq` release; the dev container build stays as the fallback ([decision 0013](decisions/0013-build-against-the-pip-wheel.md)). macOS later |
| Dev container image pinned by a digest NVIDIA may delete | **[V]** tags already gone | Build our own image if the digest disappears |
| CUDA-Q pass names are an internal API | **[U]** | Pin `cudaq-version` |
| Rewrite rules on hardware | **[V]** h, cx and x ran on `ibm_fez`; on 2026-11-11 `sdg` followed by `h` (the Y-basis change of the example) and, in one 10-qubit job, rx, ry, z and y: every qubit gave its expected bit in 97.5% to 99.7% of 1000 shots, mark 85% ([architecture.md](architecture.md) §9.8 run 4). Open: `ruleU3` has not run on hardware (CUDA-Q splits `u3` before the plugin sees it); a few fixed angles, one run | Unit tests compare the matrices at several angles. Run `tests/run_ibm_hardware_gates.py` again after a change to `Qasm2ToIsa.h`; Bruno starts it and sets the mark before |
| Token expiry during long queue waits | **[V]** accepted for v1 | [decision 0004](decisions/0004-accept-token-expiry-in-v1.md); upstream #1 |
| `RestClient` traps (JSON only, logs bodies, TLS off) | **[V]** worked around | [decision 0005](decisions/0005-iam-login-with-libcurl.md); upstream #2, #3 |
| IBM API drift (service renamed; legacy names until 2026-11-21) | **[V]** | Watch the changelog; the fake server must follow |
| `check-ibm` lit test likely fails without credentials | Closed 2026-11-11: the test was removed, never run ([architecture.md](architecture.md) §8 item 3) | The fake-server scripts cover what it checked |
| No macOS wheel: on a Mac the plugin runs only in a Linux container | Open ([decision 0014](decisions/0014-first-release-for-linux-x86-64-and-aarch64.md)) | Later, when someone needs it |
| The package name `cudaq-ibm` contains "IBM" | Open: working name on a GitHub Release only ([decision 0015](decisions/0015-github-release-first-settle-the-name-before-pypi.md)) | Settle it before any upload to PyPI |
