# Roadmap

Date: 2026-11-10. Status: living document. Update it when a milestone or risk changes.
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
| M3 | Routing: fetch configuration and properties, prune, noise-aware numbering, device file, `qubit-mapping` in YAML, label -> IBM qubit assignment; fake server checks 2-qubit gates against the real coupling map | 3-5 days | 5-qubit GHZ on hardware; 20-qubit GHZ accepted by the fake server | **Code done, not yet run in the built plugin** 2026-11-10 (decisions [0009](decisions/0009-route-with-cudaq-then-assign-qubits.md), [0010](decisions/0010-measure-all-then-keep-measured-bits.md), [0011](decisions/0011-stop-when-properties-cannot-be-read.md)). Unit tests and pip-CUDA-Q runs of the pipeline pass. Next: [m3-spec.md](m3-spec.md) §6. |
| M4 | Packaging: wheels (Linux x86_64, aarch64), ABI check against pip `cudaq`, `--install-nvqpp`, README, CI (build in dev container, run fake-server tests) | 2-3 days | `pip install` then `cudaq.set_target("ibm")` works | Not started. CI already runs the Python tests and the ISA unit test. |
| M5 | Optional: `transport=qrmi` using the bundled `libqrmi` ([decision 0007](decisions/0007-qrmi-later-not-in-v1.md)); upstream PRs ([upstream.md](upstream.md): token refresh in `Future.cpp`, `RestClient` TLS default, native IBM basis patterns, `mapping_v2p` export, fake IBM server) | 1-2 weeks | PRs opened with DCO sign-off | Not started |

## 2. Next steps

Free checks first, QPU time last ([m3-spec.md](m3-spec.md) §6 has the details and pass marks).

1. Bruno: rebuild the plugin in the container and run `tests/run_fake_ibm.py` (6 checks and
   an `emulate=True` probe).
2. Bruno: save the real `/configuration` and `/properties` of `ibm_fez` and run
   `test_chip_data` on them. No job, no QPU time.
3. Bruno: one hardware session: GHZ-5 plus one non-symmetric kernel (GHZ cannot show a wrong
   bit order).
4. Open the first upstream issue ([upstream.md](upstream.md) #5); fold m3-spec.md into
   architecture.md and close M3.
5. M4: make the fake server simulate small circuits, so CI checks results, not only gates.
6. M4: measure idle qubits in kernels without `mz` (`add-measurements` early in the
   pipeline, with a fake-server test; m3-spec §2.11), together with `emulate=True` and
   `observe`, which touch the same passes. Moved from "right after M3" by Bruno on
   2026-11-10: CUDA-Q's specification allows today's behaviour, so it is not a bug fix.

## 3. Open risks

Evidence is in the linked decision records.

| Risk | Status | Plan |
|---|---|---|
| Physical qubit ids compacted by CUDA-Q | **[V]** reproduced: a routed qubit 9 arrives as 5 ([m3-spec.md](m3-spec.md) §2.4); routing borrows qubits often (§2.6) | Assignment search in `Layout.h` ([decision 0009](decisions/0009-route-with-cudaq-then-assign-qubits.md)); upstream fix ([upstream.md](upstream.md) #5) |
| Routing quality | **[V]** GHZ-20 on `ibm_fez`: 3 swaps with `placement=auto search=sabre`, 44 with CUDA-Q's default (m3-spec §2.9) | Noise-aware router later, if it matters |
| Tests check gates and links, not results: the fake server returns 3 fixed samples | **[V]** `tests/fake_ibm_server.py` | Non-symmetric kernel in the hardware session; simulating fake server in M4 |
| `emulate=True` and `observe` on the `ibm` target | **[V]** emulation fails at pass level, **[U]** in the built plugin; `observe` untested | Not supported in M3 ([decision 0010](decisions/0010-measure-all-then-keep-measured-bits.md)); probe in `run_fake_ibm.py` |
| CUDA-Q will change `sample` and `observe` | **[V]** `import cudaq` 0.16.0 prints a `FutureWarning` saying so; the page it links has no details yet (read 2026-11-10) | Watch the release notes; the bit-order rule in [decision 0010](decisions/0010-measure-all-then-keep-measured-bits.md) depends on today's `sample` contract |
| Kernel with no `mz` and an idle qubit returns a shorter bit string | **[V]** m3-spec §2.11. Allowed by CUDA-Q's specification; `oqc` and `anyon` do the same | Documented for M3; fix in M4 (next step 6), Bruno 2026-11-10 |
| Label -> qubit search refuses large circuits | **[V]** fine up to about 100 qubits (m3-spec §2.10) | Goes away when upstream passes the layout ([upstream.md](upstream.md) #5) |
| Real `/properties` differs from the FakeFez snapshot | **[U]** | Next step 2; the plugin stops rather than guess ([decision 0011](decisions/0011-stop-when-properties-cannot-be-read.md)) |
| Plugin ABI vs pip `cudaq` | **[U]** untested | Check in M4 |
| Dev container image pinned by a digest NVIDIA may delete | **[V]** tags already gone | Build our own image if the digest disappears |
| CUDA-Q pass names are an internal API | **[U]** | Pin `cudaq-version` |
| Rewrite rules on hardware | **[V]** h, cx ran on `ibm_fez`; others proven in unit test only | Fake-server kernel with rx, ry, z |
| Token expiry during long queue waits | **[V]** accepted for v1 | [decision 0004](decisions/0004-accept-token-expiry-in-v1.md); upstream #1 |
| `RestClient` traps (JSON only, logs bodies, TLS off) | **[V]** worked around | [decision 0005](decisions/0005-iam-login-with-libcurl.md); upstream #2, #3 |
| IBM API drift (service renamed; legacy names until 2026-11-21) | **[V]** | Watch the changelog; the fake server must follow |
| `check-ibm` lit test likely fails without credentials | **[U]** not run | Fix in M4 |
