# Roadmap

Date: 2026-11-09. Status: living document. Update it when a milestone or risk changes.
Reader: Bruno.
Tags: **[V]** verified (source given), **[U]** unverified.

The plan follows [decision 0001](decisions/0001-cudaq-routes-helper-rewrites-gates.md). Effort is
rough, for part-time work. Each milestone is shippable.

## 1. Milestones

| # | Deliverable | Effort | Done when | Status |
|---|---|---|---|---|
| M0 | Dev environment: CUDA-Q 0.16.0 source build in NVIDIA's dev container; build and run the `mock_rest` reference plugin | 1-2 days | `mock_rest` sample runs end to end | **Done** 2026-11-08 (Podman, [decision 0002](decisions/0002-build-in-linux-dev-container.md)). The ABI check moved to M4. |
| M1 | `ibm` plugin: YAML (no mapping yet), IAM auth, job POST/poll/results, hex decoding; fake IBM server | 2-3 days | Bell pair end to end against the fake server | **Done** 2026-11-08, PR #1. Result `{ 01:1 10:2 }`. |
| M2 | `qasm2ToIsaQasm3` gate rewrite with unit tests; first real Bell pair on `ibm_fez` qubits 0-1 | 3-5 days | Hardware counts match the Python prototype | **In progress.** All rewrite rules proven (h, cx in PR #2; z, y, rx, ry, u3 derived by Bruno 2026-11-09). Open: first hardware run. |
| M3 | Routing: fetch configuration, prune/relabel, topology file, `qubit-mapping` in YAML, `reorderIdx`; fake server checks 2-qubit gates against the real coupling map | 3-5 days | 5-qubit GHZ on hardware; 20-qubit GHZ accepted by the fake server | Not started |
| M4 | Packaging: wheels (Linux x86_64, aarch64), ABI check against pip `cudaq`, `--install-nvqpp`, README, CI (build in dev container, run fake-server tests) | 2-3 days | `pip install` then `cudaq.set_target("ibm")` works | Not started. CI already runs the Python tests and the ISA unit test. |
| M5 | Optional: `transport=qrmi` using the bundled `libqrmi` ([decision 0007](decisions/0007-qrmi-later-not-in-v1.md)); upstream PRs ([upstream.md](upstream.md): token refresh in `Future.cpp`, `RestClient` TLS default, native IBM basis patterns, `mapping_v2p` export, fake IBM server) | 1-2 weeks | PRs opened with DCO sign-off | Not started |

## 2. Next steps

1. Rebuild the plugin and rerun `tests/run_fake_ibm.py` in the dev container.
2. First real Bell pair on `ibm_fez` through the plugin. Check the logged results JSON for
   `num_bits` ([architecture.md](architecture.md) §3.5).

## 3. Open risks

Evidence is in the linked decision records.

| Risk | Status | Plan |
|---|---|---|
| Physical qubit ids compacted by CUDA-Q | **[V]** tolerated | Relabel qubits (M3); upstream layout export ([upstream.md](upstream.md) #5) |
| Routing quality (23 swaps for GHZ-20) | **[V]** | Noise-aware layout later, if it matters |
| Plugin ABI vs pip `cudaq` | **[U]** untested | Check in M4 |
| Dev container image pinned by a digest NVIDIA may delete | **[V]** tags already gone | Build our own image if the digest disappears |
| CUDA-Q pass names are an internal API | **[U]** | Pin `cudaq-version` |
| Rewrite rules untested on hardware | **[V]** proven in unit test; hardware run pending | M2 hardware run |
| Token expiry during long queue waits | **[V]** accepted for v1 | [decision 0004](decisions/0004-accept-token-expiry-in-v1.md); upstream #1 |
| `RestClient` traps (JSON only, logs bodies, TLS off) | **[V]** worked around | [decision 0005](decisions/0005-iam-login-with-libcurl.md); upstream #2, #3 |
| IBM API drift (service renamed; legacy names until 2026-11-21) | **[V]** | Watch the changelog; the fake server must follow |
| `check-ibm` lit test likely fails without credentials | **[U]** not run | Fix in M4 |
