# Phase 3 design: a C++ CUDA-Q backend plugin for IBM Quantum

Date: 2026-11-06, updated 2026-11-09.
Status: accepted. Bruno chose Option A (§3) on 2026-11-06. M0 and M1 are done, M2 is in progress (§5).
Reader: Bruno.
Tags: **[V]** verified (source given), **[U]** unverified.
File references like `runtime/common/ServerHelper.h:44` are in the CUDA-Q `0.16.0` tag.
Detailed spec for M1: [m1-spec.md](m1-spec.md).

Review notes (2026-11-06): the `h` and ZSX gate identities were checked numerically with Qiskit
(both equal up to global phase); the `regtomem` renumbering was reproduced; the 2026-02-01
`transpiled_circuits` removal was confirmed in IBM's changelog.

## 1. Summary and recommendation

The plugin is feasible and the framework fits well. CUDA-Q 0.16 has an official out-of-tree
plugin route (`ServerHelper` + target YAML + pip wheel). Its MLIR pipeline already contains a
SABRE qubit router that loads a device topology file at run time, and the IQM backend already
shows how to fetch that topology from the vendor before each compile.

Two things CUDA-Q cannot do today:

1. Decompose to IBM's native gates `{rz, sx, x, cz}`. No rewrite patterns exist for that basis.
2. Keep physical qubit numbers in the emitted program. The `regtomem` step renumbers qubits 0..n-1.

IBM, in turn, offers no server-side transpilation for Open-plan users.

**Recommendation: Option A (§3).** Let CUDA-Q route (coupling map fetched from IBM at run
time). Let the `ServerHelper` do the small, fixed gate rewrite to `{rz, sx, x, cz}` and emit
OpenQASM 3 with physical qubits. Plan two small upstream contributions (native IBM basis
patterns; export of the final layout) that remove the workarounds. Do not depend on QRMI for
v1, but keep the transport behind an interface so a QRMI transport can be added later
(CUDA-Q itself already bundles `libqrmi`).

## 2. How a CUDA-Q REST plugin works

A target is a YAML file plus one shared library. The YAML says "use the built-in
`remote_rest` QPU", names the MLIR pass pipeline to run on each kernel, and names the output
format. The library implements `cudaq::ServerHelper`, which only knows HTTP: headers, job
payload, job id, polling, result decoding. **[V]** `docs/sphinx/using/extending/backend.rst`,
`packaging.rst`; interface `runtime/common/ServerHelper.h:44-130`.

```
cudaq.set_target("ibm", backend="ibm_fez")      python: entry point "cudaq.backends" -> register_backend_path()
        |
   cudaq.sample(kernel)
        |
   BaseRemoteRESTQPU (lib/libcudaq-rest-qpu.so, shipped in the pip wheel)
        |  1. helper->getPipelineSubstitutions()   -> e.g. %QPU_ARCH% = /tmp/ibm_fez_topology.txt (M3)
        |  2. JIT: canonicalize, hw-jit-prep, expand-measurements, jit-deploy,
        |          <jit-mid-level-pipeline from YAML>, jit-finalize      [V] observed log, Compiler.cpp:161
        |  3. codegen-emission (qasm2 | qir-base | qir-adaptive | iqm)  -> KernelExecution{code, output_names, mapping_reorder_idx}
        v
   ServerHelper (lib/libcudaq-serverhelper-ibm.so)
        |  createJob()        QASM2 -> ISA OpenQASM 3 (Qasm2ToIsa.h); POST /api/v1/jobs
        |  jobIsDone()        GET /api/v1/jobs/{id}   state.status
        |  processResults()   GET /api/v1/jobs/{id}/results -> hex samples -> counts, bit reversal
        v
   cudaq::sample_result
```

Methods to implement (pure virtual): `name`, `initialize`, `getHeaders`, `createJob`,
`extractJobId`, `constructGetJobPath` (two overloads), `jobIsDone`, `processResults`.
Optional: `getCookies`, `nextResultPollingInterval`, `getPipelineSubstitutions`.
Register with `CUDAQ_REGISTER_TYPE(cudaq::ServerHelper, cudaq::IBMServerHelper, ibm)`.
YAML keys: `platform-qpu`, `codegen-emission`, `jit-high/mid/low-level-pipeline`,
`post-codegen-passes`, `link-libs`, `target-arguments`, `cudaq-version`. **[V]**
`cudaq/lib/Target/Yaml/TargetConfigYaml.cpp:378-417`. The exact call order is in m1-spec §1.

**Build.** **[V]** The pip wheel (`cuda-quantum-cu13 0.16.0`) ships `lib/libcudaq-rest-qpu`,
`libcudaq-common`, all in-tree serverhelpers and `targets/*.yml` for Linux x86_64, Linux
aarch64 and macOS 13+ arm64. It ships **no CUDA-Q headers, no CMake config and no `nvq++`**
(only `cpr` headers). So the plugin is compiled inside a CUDA-Q source build
(`-DCUDAQ_EXTERNAL_PROJECTS=ibm`, the documented route), and the resulting `.so` is later
packaged as a wheel (M4).

**Where we build (updated 2026-11-08).** The native macOS build, documented in `Building.md`
"Building on macOS", **failed** on Bruno's Mac: LLVM 22 `lld` cannot read the Xcode 27 SDK
(`arm64e.x1` architecture) **[V]** build log. We build instead in NVIDIA's Linux dev container,
run with Podman on Apple Silicon and pinned by digest. Steps: README section "Develop the C++
plugin (Linux container)".

**ABI check.** **[U]** Whether a plugin built against the source tree loads cleanly into a
pip-installed `cudaq` depends on an ABI match (same compiler, same `nlohmann::json`, same
flags). Not tested yet; moved from M0 to M4 (§5, risk 3).

## 3. The ISA problem: options

IBM requires ISA circuits: "When submitting a job to an IBM Quantum backend, the circuits
must adhere to the backend's ISA." **[V]** https://quantum.cloud.ibm.com/docs/guides/transpile.
Server-side transpilation is gone: the REST changelog says primitives stopped storing
transpiled circuits in April 2024, and the `transpiled_circuits` endpoint was dropped on
2026-02-01 **[V]** https://quantum.cloud.ibm.com/docs/api/qiskit-runtime-rest/changelog. The
only remote transpiler is the Qiskit Transpiler Service (`POST
https://cloud-transpiler.quantum.ibm.com/transpile`). It accepts QASM2/3 text and returns ISA
QASM plus layout, but it is "only available for IBM Quantum Premium Plan members" **[V]**
https://quantum.cloud.ibm.com/docs/api/qiskit-transpiler-service-rest.

What CUDA-Q 0.16 can and cannot do. All **[V]** by experiment with the pip wheel's Python MLIR
bindings (throwaway scripts, not in this repo):

| Capability | Status |
|---|---|
| Route on a 156-qubit heavy-hex graph loaded from a file | Works: `qubit-mapping{device=file(F)}`, SABRE (`Mapping.cpp:812`), 0.01-0.02 s per kernel; file format `N --> {a, b}` (`helpers/oqc/lucy.txt`). |
| Load the topology at run time from the vendor | Works: `ServerHelper::getPipelineSubstitutions` is called on every compile (`BaseRemoteRESTQPU.h:225-229`); IQM fetches its architecture and writes a temp file (`IQMServerHelper.cpp:457-490, 503-661`). |
| Decompose to `{cz, rz, sx, x}` | Fails: `basis-conversion{basis=z(1),rz,rx,x}` -> "failed to legalize operation 'quake.h'". No H/RY-to-rz/rx patterns; the only native 1-qubit target is IQM's `phased_rx` (pattern list in `DecompositionPatterns.cpp`, pipelines in `CodeGen/Passes.cpp:25-98`). |
| Decompose to a textbook basis | Works, with gaps: `decomposition{basis=h,rx,ry,rz,x,z,x(1)}` turns `s`, `t`, `r1` into `rz` and `cz` into `h cx h`, but leaves `y` and `u3` as they are **[V]** observed QASM2 output, 2026-11-08. So the rewrite (§3 Option A) must handle `y` and `u3` too. |
| Keep physical qubit ids in emitted QASM2/QIR | Fails: `regtomem` counts unique wires and renumbers (`RegToMem.cpp:121-140`); wires 40-42 came out as 0-2 in both `openqasm2` and `qir-base`. The final layout is stored as `mapping_v2p` (`Mapping.cpp:3315-3328`) but not exported to the helper (`KernelExecution.h:23-32` carries only `mapping_reorder_idx`). All in-tree backends run `regtomem` too (`cudaq/test/Transforms/wireset_codegen.qke:10-12`). Placement packs into ascending low ids (`Mapping.cpp:99-135`), so in practice ids are 0..n-1, but this is not guaranteed. |
| Routing quality | Mediocre: a 20-qubit GHZ line on Fez needed 23 swaps although a swap-free 20-qubit path exists on heavy-hex. Not noise-aware. |
| Disconnected topology (isolated qubits) | Error "disconnected device topology" (`Mapping.cpp:3189`); the helper must prune isolated qubits. |

**Option A. CUDA-Q routes, the helper finishes the job (chosen).**

- YAML pipeline: the IQM/OQC pattern (`decomposition` to a small textbook basis,
  `qubit-mapping{device=file(%QPU_ARCH%)}`, `regtomem`), `codegen-emission: qasm2`.
- The helper (1) fetches `GET /backends/{name}/configuration` once per target, prunes
  isolated qubits and writes the topology file; (2) rewrites the QASM2 text gate by gate into
  `{rz, sx, x, cz}` with fixed identities; (3) emits OpenQASM 3 with `$k` physical qubits and
  `c[i] = measure $k`.
- Identities. Proven in `plugin/tests/test_qasm2_to_isa.cpp` **[V]**:
  `h = rz(π/2) sx rz(π/2)`; `cx(c,t) = h(t) cz(c,t) h(t)`.
  Checked numerically, not yet in code: `rx(θ) = rz(π/2) sx rz(θ+π) sx rz(π/2)`; `z = rz(π)`.
  Still open: `y`, `ry`, `u3` (Bruno's M2 work). General form: the ZSX Euler form
  `U(θ,φ,λ) = rz(φ+π) sx rz(θ+π) sx rz(λ)`. `swap` arrives as 3 `cx`.
- Effort: small (~400 lines of C++ beyond the HTTP code).
- Risk: the physical-id compaction (table above) is tolerated, not fixed. The helper will
  label qubits so that ids 0..m-1 form a connected, good-quality region (BFS order from the
  best-calibrated qubit using `/properties`). This makes "ids are 0..n-1" hold in practice
  **[U]** until an upstream fix.
- Learning value: high (every quantum concept is visible in ~400 lines). Maintenance: low;
  depends on stable pass names.

**Option B. The helper is a mini-transpiler.** `codegen-emission: qasm2` with a textbook
basis and no CUDA-Q mapping. The helper does layout, SABRE routing and gate rewrite itself in
C++, with the live coupling map and error rates. Full control, correct physical ids,
noise-aware. Effort: large (routing ~1-2k lines plus tests). Learning value: highest.
Maintenance: all yours. Good as a later upgrade of A's gate-rewrite module, not as v1.

**Option C. Someone else transpiles.** IBM's transpiler service (Premium only, so not for
this project) or a local Python/Qiskit sidecar called from C++ (works, but brings Qiskit and
a Python runtime back into a C++ plugin). Keep as an optional escape hatch for comparison
tests; do not build the design on it.

Plan: Option A now; B's layout logic later if routing quality matters. Two upstream PRs
(native IBM basis patterns in `DecompositionPatterns.cpp`; export `mapping_v2p` into
`KernelExecution`) turn A's main caveat into a non-issue for every superconducting backend,
not only IBM.

## 4. Architecture

What exists today (main after PR #2) and what is planned:

```
cudaq-ibm-backend/
  src/cudaq_ibm/              Python prototype (phase 1), ran on ibm_fez 2026-11-05
  plugin/                     C++ plugin, built as a CUDA-Q external project
    CMakeLists.txt            links cudaq-common, cudaq-logger, CURL::libcurl
    targets/ibm.yml.in        target YAML (below)
    IBMServerHelper.cpp       done (M1): IAM login via libcurl, token cache, job submit/poll/results, hex decoding
    Qasm2ToIsa.h              done for h, cx (M2): header-only QASM2 -> ISA OpenQASM 3, no I/O, unit-testable
    tests/test_qasm2_to_isa.cpp   done: tiny unitary simulator, proves each rule up to global phase
    IBMTopology.{h,cpp}       planned (M3): configuration JSON -> pruned/relabelled graph -> topology file + id map
    python/*.py.in, pyproject.toml.in   from mock_rest; entry point "cudaq.backends" (packaging in M4)
  tests/
    fake_ibm_server.py        done (M1): FastAPI fake of IAM + jobs API, port 62455, rejects non-ISA circuits
    run_fake_ibm.py           done (M1): Bell pair end to end against the fake server
```

Changes from the 2026-11-06 sketch:

- No separate `IamToken` class. The IAM call and token cache live as private members of
  `IBMServerHelper`. IAM uses libcurl directly because `RestClient::post` cannot send a form
  body (m1-spec §4).
- The converter is one header, `Qasm2ToIsa.h`, so the unit test compiles with plain `g++`
  and no CUDA-Q.
- The fake server lives in the top-level `tests/` (Python), not under `plugin/tests/`.

Current `targets/ibm.yml.in` (no qubit mapping yet; that comes in M3):

```yaml
name: ibm
cudaq-version: "@CUDA_QUANTUM_VERSION@"
config:
  platform-qpu: remote_rest
  gen-target-backend: true
  preprocessor-defines: ["-D CUDAQ_QUANTUM_DEVICE"]
  link-libs: ["-lcudaq-rest-qpu"]
  jit-high-level-pipeline: "expand-measurements"
  jit-mid-level-pipeline: "decomposition{basis=h,rx,ry,rz,x,z,x(1)},quake-to-cc-prep,func.func(memtoreg{quantum=0})"
  codegen-emission: qasm2
  library-mode: false
target-arguments:
  - { key: backend, required: false, type: string, platform-arg: backend, help-string: "IBM backend, default ibm_fez" }
  - { key: url,     required: false, type: string, platform-arg: url,     help-string: "API base URL" }
  - { key: iam_url, required: false, type: string, platform-arg: iam_url, help-string: "IAM token URL (tests only)" }
```

Credentials come **only** from the environment (`IBM_QUANTUM_API_KEY`, `IBM_QUANTUM_CRN`), not
from target arguments. Reason: target arguments end up in `backendConfig`, which CUDA-Q may
log, and the key must never be logged.

Planned for M3: add `qubit-mapping{device=file(%QPU_ARCH%)},func.func(regtomem)` to the mid-level
pipeline and a `topology-file` override argument.

Data flow per `cudaq.sample`: (M3: `getPipelineSubstitutions` -> cached configuration ->
topology file + `idmap[k] = physical qubit`) -> compile -> `KernelExecution.code` (QASM2 with
`qreg var0[n]`, one 1-bit `creg varK[1]` per measurement, gates from the basis) ->
`qasm2ToIsaQasm3` -> payload `{program_id:"sampler", backend, params:{pubs:[[qasm3,null,shots]], version:2}}`
(the exact shape that ran on `ibm_fez` on 2026-11-05 **[V]** README) -> poll `state.status`
until COMPLETED (FAILED and CANCELLED throw) -> `results[0].data.c.samples` hex -> counts with
the little-endian bit reversal from `results.py`. In M3, also apply `reorderIdx` as OQC does
(`OQCServerHelp.cpp:412-434`, filled by `Executor.cpp:52`). The converter concatenates the
1-bit `creg`s in program order into one `bit[n] c`, so IBM returns a single register.

Output format. CUDA-Q can emit QASM2 (`codegen-emission: qasm2`, used by Braket/Infleqtion
**[V]** their `.yml`), but it is `OPENQASM 2.0; include "qelib1.inc"` with virtual registers.
IBM's Sampler REST docs show OpenQASM 3 with `include "stdgates.inc"` **[V]**
https://quantum.cloud.ibm.com/docs/guides/sampler-rest-api. Whether the endpoint also parses
QASM2 is **[U]** and does not matter, because we rewrite anyway. Qiskit's client-side ISA
check accepts both `$k` physical qubits and a `qubit[156] q;` declaration **[V]**
`is_isa_circuit` experiment. We emit `$k`, the form that already succeeded on hardware.

## 5. Milestones

Effort is rough, for part-time work. Each milestone is shippable.

| # | Deliverable | Effort | Done when | Status (2026-11-09) |
|---|---|---|---|---|
| M0 | Dev environment: CUDA-Q 0.16.0 source build in NVIDIA's dev container; build and run the `mock_rest` reference plugin | 1-2 days | `mock_rest` sample runs end to end | **Done** 2026-11-08 (Podman, see §2). The ABI check moved to M4. |
| M1 | `ibm` plugin: YAML (no mapping yet), IAM auth, job POST/poll/results, hex decoding; fake IBM server | 2-3 days | Bell pair end to end against the fake server | **Done** 2026-11-08, PR #1. Result `{ 01:1 10:2 }`. Spec: [m1-spec.md](m1-spec.md). |
| M2 | `qasm2ToIsaQasm3` gate rewrite with unit tests; first real Bell pair on `ibm_fez` qubits 0-1 | 3-5 days | Hardware counts match the Python prototype | **In progress.** h, cx proven and merged (PR #2). Open: z, y, rx, ry, u3 rules; first hardware run. |
| M3 | Routing: fetch configuration, prune/relabel, topology file, `qubit-mapping` in YAML, `reorderIdx`; fake server checks 2-qubit gates against the real coupling map | 3-5 days | 5-qubit GHZ on hardware; 20-qubit GHZ accepted by the fake server | Not started |
| M4 | Packaging: wheels (Linux x86_64, aarch64), ABI check against pip `cudaq`, `--install-nvqpp`, README, CI (build in dev container, run fake-server tests) | 2-3 days | `pip install` then `cudaq.set_target("ibm")` works | Not started. CI already runs the Python tests and the ISA unit test. |
| M5 | Optional: `transport=qrmi` using the bundled `libqrmi`; upstream PRs (token refresh in `Future.cpp`, `RestClient` TLS default, native IBM basis patterns, `mapping_v2p` export, fake IBM server) | 1-2 weeks | PRs opened with DCO sign-off | Not started |

## 6. Risks and open questions

1. **Physical-id compaction** (§3) **[V]**. Mitigated by relabelling; fixed only upstream. If a run ever shows non-contiguous placement, the circuit would silently use wrong qubits. Add a fake-server check that every 2-qubit gate is on an edge of the *real* coupling map (`is_isa_circuit` does exactly this).
2. **Routing quality** **[V]** 23 swaps for GHZ-20. Fine for learning; a noise-aware layout (Option B's first piece) is the obvious follow-up.
3. **Plugin ABI vs pip wheel** **[U]**. Not tested yet (moved to M4). Fallback: use the dev-container `cudaq`, which is what the docs assume.
4. **macOS** **[V]** The native build fails with the Xcode 27 SDK (§2). We depend on NVIDIA's dev container, pinned by digest because the `releases-v0.16.0` arm64 tags are gone. If that digest disappears, we must rebuild the image ourselves.
5. **Pass names are an internal API** **[U]**. The docs even say "Contact the CUDA-Q team for help setting this up" (`backend.rst:172`). Pin `cudaq-version`.
6. **Gate identities**. `h` and `cx` are proven in the unit test **[V]**. `rx` and `z` are checked numerically but not yet in code. `y`, `ry`, `u3` are **[U]** until unit-tested.
7. **Token expiry during long queues** **[V]** `Future.cpp` calls `getHeaders()` once per job, then reuses those headers for the whole poll loop (unlike `getCookies()`, which is called on every poll). IBM tokens last ~60 min, so a job that waits longer in the queue fails to poll. v1 documents the limit. Fix: upstream PR that moves `getHeaders()` into the loop. Fallback, only if upstream rejects it: our own polling in `processResults()`.
8. **RestClient traps** **[V]** `RestClient::post` always sends JSON, logs the body at INFO, and turns off TLS checks by default (`enableSsl = false`), including for the Executor's job POST. Details and our workarounds: m1-spec §4. The TLS default is an upstream issue to report.
9. **IBM API drift**. Service renamed to "IBM Quantum Compute Service"; legacy names supported until 2026-11-21 **[V]** QRMI README line 20. The `version: 2` field is in our working payload but not shown in the docs **[V]**.
10. **QRMI fit**. QRMI v0.26.6, Apache-2.0, Rust core with a C header (`cbindgen.toml`, `QRMI_VERSION 0.26.6`), C API `qrmi_resource_{new,acquire,task_start,task_status,task_result,target,...}` (`src/cext.rs`); IBM resources `ibm-quantum-compute-service` and `ibm-quantum-system` (Direct Access); payload `{program_id, parameters}` is the Sampler V2 schema (`qrmi_payload_v1_schema.json`); `target()` returns the backend configuration + properties JSON (`src/ibm/quantum_compute_service.rs:597-625`), which is exactly what the topology builder needs; config via `QRMI_IBM_QCS_*` env vars. Activity: 49 tags, last commit 2026-11-05, 65 stars **[V]** clone + GitHub page. CUDA-Q 0.16 already bundles `libqrmi` (`cuda_quantum_cu13.libs/libqrmi-9ed0df30.so` in the wheel) for the Pasqal connector, Linux only, QRMI >= 0.12 (`runtime/cudaq/platform/pasqal/CMakeLists.txt`). Assessment: it does not solve the ISA problem (no transpilation), and `acquire()` defaults to a dedicated session (`QRMI_IBM_QCS_SESSION_MODE` default "dedicated"), which the Open plan may not allow **[U]**. The API has churned (renames, deprecations since v0.23). Good second transport once v1 works, and a natural place for Bruno to contribute; wrong place to start.
11. **Upstream path**. NVIDIA's docs say "All external backends are developed as external plugins ... without modifying the core repository" (`backend.rst:6-9`) **[V]**, so an in-tree `ibm` target is not the expected route. Contributions need DCO sign-off (`Contributing.md:38-79`) **[V]**. No issue or PR about IBM support was found (`gh search issues/prs` on NVIDIA/cuda-quantum, 2026-11-06) **[V]**. The welcome contributions are compiler-side (native-basis patterns, layout export) plus the runtime fixes in risks 7 and 8.
12. **Testing**. In-tree pattern: FastAPI mock per backend under `python/tests/utils/mock_qpu/<name>/`, started by a pytest session fixture in a `Process` (`python/tests/backends/test_IQM.py:36-60`) or by `unittests/nvqpp/backends/*/StartServerAndTest.sh.in` for C++ lit tests; deps `requirements-mock-qpu.txt` (fastapi, uvicorn, llvmlite); CI runs `python/tests/backends` in `python_wheels.yml:348` **[V]**. Our fake server (§4) already covers IAM `POST /identity/token`, `POST /jobs`, `GET /jobs/{id}`, `GET /jobs/{id}/results`, and rejects non-ISA gates. Still to add: `GET /backends/{name}/configuration` (serve FakeFez's JSON, M3) and automated failure tests (m1-spec §6).

## 7. Sources

- CUDA-Q 0.16.0 source (tag `0.16.0`, commit `62fce8b`): `docs/sphinx/using/extending/{backend,packaging}.rst`; `runtime/common/{ServerHelper.h,BaseRemoteRESTQPU.h,CodeGenConfig.cpp,KernelExecution.h,Executor.cpp,Future.cpp,RestClient.cpp}`; `runtime/cudaq/platform/default/rest/helpers/{iqm,oqc,anyon,braket,infleqtion}/*`; `cudaq/lib/Optimizer/Transforms/{Mapping.cpp,RegToMem.cpp,DecompositionPatterns.cpp}`; `cudaq/lib/Optimizer/CodeGen/{Passes.cpp,TranslateToOpenQASM.cpp,TranslateToIQMJson.cpp}`; `cudaq/lib/Target/Yaml/TargetConfigYaml.cpp`; `cudaq/test/Transforms/wireset_codegen.qke`; `docs/sphinx/examples/plugins/mock_rest/`; `python/tests/utils/mock_qpu/`, `python/tests/backends/test_IQM.py`; `Contributing.md`; `Building.md`.
- Rendered docs: https://nvidia.github.io/cuda-quantum/0.16.0/using/extending/backend.html and `.../packaging.html`.
- Experiments (pip `cuda-quantum-cu13 0.16.0.post1`, Python MLIR bindings): mapping on a 156-qubit Fez topology, `basis-conversion` failure, GHZ-20 swap count, qubit-id compaction; wheel inventories via `pip show -f` and the macOS wheel from PyPI. Plugin runs in the dev container (2026-11-08): QASM2 output of the decomposition pipeline, fake-server end-to-end.
- IBM: https://quantum.cloud.ibm.com/docs/guides/transpile ; https://quantum.cloud.ibm.com/docs/guides/sampler-rest-api ; https://quantum.cloud.ibm.com/docs/api/qiskit-runtime-rest/changelog ; https://quantum.cloud.ibm.com/docs/api/qiskit-transpiler-service-rest ; https://quantum.cloud.ibm.com/docs/api/qiskit-ibm-transpiler/release-notes ; qiskit-ibm-runtime 0.51.0 `utils/utils.py::is_isa_circuit`.
- QRMI: https://github.com/qiskit-community/qrmi (`Cargo.toml`, `cbindgen.toml`, `src/cext.rs`, `src/ibm/*.rs`, `qrmi_payload_v1_schema.json`, `examples/qrmi/c/ibm_quantum_compute_service/`).
- Prototype: this repo (`README.md`, `src/cudaq_ibm/*.py`).
