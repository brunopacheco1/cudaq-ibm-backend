# Roadmap

Date: 2026-11-11. Status: living document. Update it when a milestone or risk changes.
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
| M4 | Packaging: wheels (Linux x86_64, aarch64), ABI check against pip `cudaq`, `--install-nvqpp`, README, CI (build in dev container, run fake-server tests) | 2-3 days | `pip install` then `cudaq.set_target("ibm")` works | In progress: decisions taken 2026-11-10, [m4-spec.md](m4-spec.md) §3 and §4. Steps 1 to 4 of 5 done: CI builds the plugin against the pip wheel; the fake server simulates the circuits, so CI compares the plugin's results with CUDA-Q's simulator; idle qubits keep their bits; `emulate=True` and `observe` are refused with a clear error; `examples/expectation_from_samples.py` computes expectation values from `sample` counts (Bruno, 2026-11-11). CI also runs the Python tests and the C++ unit tests. The plugin is a wheel, `cudaq-ibm`, for Linux x86_64 and aarch64: CI builds it in the `manylinux_2_28` image and tests it as installed, and a version tag publishes it on a GitHub Release (2026-11-11, [development.md](development.md) §7). Next: the first release and Bruno's hardware run from the installed wheel. |
| M5 | Optional: `transport=qrmi` using the bundled `libqrmi` ([decision 0007](decisions/0007-qrmi-later-not-in-v1.md)); upstream PRs ([upstream.md](upstream.md): token refresh in `Future.cpp`, `RestClient` TLS default, native IBM basis patterns, `mapping_v2p` export, fake IBM server) | 1-2 weeks | PRs opened with DCO sign-off | Not started |

## 2. Next steps

1. Upstream: the first issue is open since 2026-11-10,
   [NVIDIA/cuda-quantum#5882](https://github.com/NVIDIA/cuda-quantum/issues/5882) ([upstream.md](upstream.md) #5). Follow the answer.
   The second, a feature request, is open since the same day:
   [NVIDIA/cuda-quantum#5886](https://github.com/NVIDIA/cuda-quantum/issues/5886) ([upstream.md](upstream.md) #1,
   `getHeaders()` on every poll). Follow the answer; the pull request comes after it.
2. M4, in the order of [m4-spec.md](m4-spec.md) §4 (Bruno's decisions of 2026-11-10 replaced
   the earlier plan for idle qubits, `emulate=True` and `observe`). Done: CI builds the
   plugin against the pip wheel; the fake server simulates circuits, so CI checks results;
   `dqe` is out of the pipeline, so idle qubits keep their bits; `emulate=True` and
   `observe` stop with a clear error; Bruno's example computes expectation values from
   `sample` counts; the wheel for Linux x86_64 and aarch64 is built and tested in CI.
   Next (step 5): Bruno tags `v0.1.0rc1`, which makes the first GitHub Release, and runs
   one kernel on hardware from the installed wheel. Then the M4 spec is folded into the
   other documents.
3. After M4: a macOS wheel; the package name before PyPI; `emulate=True` and `observe`
   once CUDA-Q's announced change to `sample` and `observe` is out.
4. Later, if results matter: a label search that prefers low numbers, and a better forecast
   ([architecture.md](architecture.md) §9.8).

## 3. Open risks

Evidence is in the linked decision records.

| Risk | Status | Plan |
|---|---|---|
| Physical qubit ids compacted by CUDA-Q | **[V]** reproduced: a routed qubit 9 arrives as 5 ([architecture.md](architecture.md) §9.2); routing borrows qubits often | Assignment search in `Layout.h` ([decision 0009](decisions/0009-route-with-cudaq-then-assign-qubits.md)); upstream fix ([upstream.md](upstream.md) #5) |
| Routing quality | **[V]** GHZ-20 on `ibm_fez`: 3 swaps with `placement=auto search=sabre`, 44 with CUDA-Q's default (architecture §9.6) | Noise-aware router later, if it matters |
| Tests check gates and links, not results | Closed 2026-11-10 **[V]**: the fake server simulates the circuit, and CI compares 25 kernels with CUDA-Q's simulator ([architecture.md](architecture.md) §7). Left: no noise in the simulator, and the mirror-image limit described there | Hardware run at the end of each milestone |
| `emulate=True` and `observe` on the `ibm` target | **[V]** 2026-11-10: both are refused with a clear error, before any job is sent ([architecture.md](architecture.md) §8 item 7). Before M4 emulation failed inside CUDA-Q and `observe` failed or crashed Python ([m4-spec.md](m4-spec.md) F6) | Not supported in this release (Bruno, m4-spec D6 and D7). Expectation values from `sample` counts: `examples/expectation_from_samples.py`. Decide again after CUDA-Q's change to `sample` and `observe` |
| CUDA-Q will change `sample` and `observe` | **[V]** `import cudaq` 0.16.0 prints a `FutureWarning` saying so; the page it links has no details yet (read 2026-11-10) | Watch the release notes; the bit-order rule in [decision 0010](decisions/0010-measure-all-then-keep-measured-bits.md) depends on today's `sample` contract |
| Kernel with an idle qubit returns a shorter bit string | Closed 2026-11-10 **[V]**: `dqe` removed from the pipeline; six kernels with idle qubits in the CI result checks ([architecture.md](architecture.md) §8 item 6) | Cost: an idle qubit takes a chip qubit and a readout |
| The forecast behind the root rule overstates results | **[V]** 2026-11-10, two GHZ-5 runs on `ibm_fez`: old rule 81.2% (forecast 82.9%), new rule ([decision 0012](decisions/0012-root-by-best-region-best-first-numbering.md)) 90.5% (forecast 95.0%). The rule picks better qubits; the number it prints is a few points too high. The label search also took qubit 125 (number 14) where a cheaper chain fits (architecture §9.8) | Treat the logged forecast as an upper bound. Later, if it matters: next step 4 |
| Label -> qubit search refuses large circuits | **[V]** fine up to about 100 qubits (architecture §8 item 5) | Goes away when upstream passes the layout ([upstream.md](upstream.md) #5) |
| Real `/properties` differs from the FakeFez snapshot | **[V]** 2026-11-10: real `ibm_fez` data parses with 0 unreadable entries; it has no "operational" item per qubit, and marks stale benchmarks with an error of 1 (architecture §3.7) | The plugin stops rather than guess, and leaves out what has an error of 1 ([decision 0011](decisions/0011-stop-when-properties-cannot-be-read.md)) |
| Plugin ABI vs pip `cudaq` | **[V]** for Linux x86_64 and aarch64, 2026-11-11: built against the pip wheel of `cudaq` 0.16.0, the plugin loads into pip `cudaq` 0.16.0 and 0.16.0.post1 and passes the fake-server cases ([architecture.md](architecture.md) §8 item 4). macOS **[U]** | Workflow `wheels` on every pull request; macOS after M4 |
| Dev container image pinned by a digest NVIDIA may delete | **[V]** tags already gone | Build our own image if the digest disappears |
| CUDA-Q pass names are an internal API | **[U]** | Pin `cudaq-version` |
| Rewrite rules on hardware | **[V]** h, cx and x ran on `ibm_fez`; others proven in unit test and against the fake server only | A hardware kernel with rx, ry, z when QPU time allows |
| Token expiry during long queue waits | **[V]** accepted for v1 | [decision 0004](decisions/0004-accept-token-expiry-in-v1.md); upstream #1 |
| `RestClient` traps (JSON only, logs bodies, TLS off) | **[V]** worked around | [decision 0005](decisions/0005-iam-login-with-libcurl.md); upstream #2, #3 |
| IBM API drift (service renamed; legacy names until 2026-11-21) | **[V]** | Watch the changelog; the fake server must follow |
| `check-ibm` lit test likely fails without credentials | Closed 2026-11-11: the test was removed, never run ([architecture.md](architecture.md) §8 item 3) | The fake-server scripts cover what it checked |
