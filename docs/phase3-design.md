# Phase 3 design: a C++ CUDA-Q backend plugin for IBM Quantum

Date: 2026-11-06. Status: draft for review. Reader: Bruno.
Each important claim is tagged **[V]** verified (source given) or **[U]** unverified.
Reviewer spot-checks (2026-11-06): the `h` and ZSX gate identities were checked numerically with Qiskit (both equivalent up to global phase); the `regtomem` renumbering was reproduced; the 2026-02-01 `transpiled_circuits` removal was confirmed in IBM's changelog.
File references like `runtime/common/ServerHelper.h:44` are in the CUDA-Q `0.16.0` tag

## 1. Summary and recommendation

The plugin is feasible and the framework fits well: CUDA-Q 0.16 has an official out-of-tree
plugin route (`ServerHelper` + target YAML + pip wheel), its MLIR pipeline already contains a
SABRE qubit router that loads a device topology file at run time, and the IQM backend already
shows the pattern of fetching that topology from the vendor before each compile. Two things
CUDA-Q cannot do today: (a) decompose to IBM's native gates `{rz, sx, x, cz}` (no rewrite
patterns exist for that basis), and (b) keep physical qubit numbers in the emitted program
(the `regtomem` step renumbers qubits 0..n-1). IBM, in turn, offers no server-side
transpilation for Open-plan users. **Recommendation: Option A below.** Let CUDA-Q route
(coupling map fetched from IBM at run time), let the `ServerHelper` do the small, fixed
gate rewrite to `{rz, sx, x, cz}` and emit OpenQASM 3 with physical qubits, and plan two
small upstream contributions (native IBM basis patterns; export of the final layout) that
remove the hacks. Do not take a dependency on QRMI for v1, but keep the transport behind an
interface so a QRMI transport can be added later (CUDA-Q itself already bundles `libqrmi`).

## 2. How a CUDA-Q REST plugin works

A target is a YAML file plus one shared library. The YAML says "use the built-in
`remote_rest` QPU", names the MLIR pass pipeline to run on each kernel, and names the output
format. The library implements `cudaq::ServerHelper`, which only knows HTTP: headers, job
payload, job-id extraction, polling, result decoding. **[V]** docs source
`docs/sphinx/using/extending/backend.rst`, `packaging.rst`; interface
`runtime/common/ServerHelper.h:44-130`.

```
cudaq.set_target("ibm", backend="ibm_fez")      python: entry point "cudaq.backends" -> register_backend_path()
        |
   cudaq.sample(kernel)
        |
   BaseRemoteRESTQPU (lib/libcudaq-rest-qpu.so, shipped in the pip wheel)
        |  1. helper->getPipelineSubstitutions()   -> e.g. %QPU_ARCH% = /tmp/ibm_fez_topology.txt
        |  2. JIT: canonicalize, hw-jit-prep, expand-measurements, jit-deploy,
        |          <jit-mid-level-pipeline from YAML>, jit-finalize      [V] observed log, Compiler.cpp:161
        |  3. codegen-emission (qasm2 | qir-base | qir-adaptive | iqm)  -> KernelExecution{code, output_names, mapping_reorder_idx}
        v
   ServerHelper (lib/libcudaq-serverhelper-ibm.so)
        |  createJob()        text rewrite -> OpenQASM 3 ISA circuit; POST /api/v1/jobs
        |  jobIsDone()        GET /api/v1/jobs/{id}   state.status
        |  processResults()   GET /api/v1/jobs/{id}/results -> hex samples -> counts, reorder, bit flip
        v
   cudaq::sample_result
```

Methods to implement (pure virtual): `name`, `initialize`, `getHeaders`, `createJob`,
`extractJobId`, `constructGetJobPath` (two overloads), `jobIsDone`, `processResults`;
optional: `getCookies`, `nextResultPollingInterval`, `getPipelineSubstitutions`.
Register with `CUDAQ_REGISTER_TYPE(cudaq::ServerHelper, cudaq::IBMServerHelper, ibm)`.
YAML keys: `platform-qpu`, `codegen-emission`, `jit-high/mid/low-level-pipeline`,
`post-codegen-passes`, `link-libs`, `target-arguments`, `cudaq-version` **[V]**
`cudaq/lib/Target/Yaml/TargetConfigYaml.cpp:378-417`.

Build and platforms. **[V]** The pip wheel (`cuda-quantum-cu13 0.16.0`) ships
`lib/libcudaq-rest-qpu`, `libcudaq-common`, all in-tree serverhelpers and `targets/*.yml` for
Linux x86_64, Linux aarch64 and macOS 13+ arm64, but **no CUDA-Q headers, no CMake config and
no `nvq++`** (only `cpr` headers). So the plugin must be compiled inside a CUDA-Q source build
(`-DCUDAQ_EXTERNAL_PROJECTS=ibm`, the documented route) and then the resulting `.so` is
packaged as a wheel. **[U]** Whether a plugin built against a source tree loads cleanly into a
pip-installed `cudaq` depends on ABI match (same compiler, same `nlohmann::json`, same
flags); M0 checks this. Update 2026-11-06: a native macOS (Apple Silicon, CPU-only) source build **is** documented
in the 0.16.0 tag **[V]** `Building.md` "Building on macOS", `Dev_Setup.md` "Working on macOS"
(`./scripts/build_cudaq.sh -p`, which first builds LLVM from source). The dev container is
not available on macOS. Chosen path for M0: native Mac build.

## 3. The ISA problem: options

IBM requires ISA circuits: "When submitting a job to an IBM Quantum backend, the circuits
must adhere to the backend's ISA." **[V]** https://quantum.cloud.ibm.com/docs/guides/transpile.
Server-side transpilation is gone: the REST changelog says primitives stopped storing
transpiled circuits in April 2024 and the `transpiled_circuits` endpoint was dropped on
2026-02-01 **[V]** https://quantum.cloud.ibm.com/docs/api/qiskit-runtime-rest/changelog. The
only remote transpiler is the Qiskit Transpiler Service (`POST
https://cloud-transpiler.quantum.ibm.com/transpile`, accepts QASM2/3 text, returns ISA QASM
plus layout) and it is "only available for IBM Quantum Premium Plan members" **[V]**
https://quantum.cloud.ibm.com/docs/api/qiskit-transpiler-service-rest.

What CUDA-Q 0.16 can and cannot do (all **[V]** by experiment with the pip wheel's Python MLIR
bindings, throwaway experiment scripts, not in this repo):

| Capability | Status |
|---|---|
| Route on a 156-qubit heavy-hex graph loaded from a file | Works: `qubit-mapping{device=file(F)}`, SABRE (`Mapping.cpp:812`), 0.01-0.02 s per kernel; file format `N --> {a, b}` (`helpers/oqc/lucy.txt`). |
| Load the topology at run time from the vendor | Works: `ServerHelper::getPipelineSubstitutions` is called on every compile (`BaseRemoteRESTQPU.h:225-229`); IQM fetches its architecture and writes a temp file (`IQMServerHelper.cpp:457-490, 503-661`). |
| Decompose to `{cz, rz, sx, x}` | Fails: `basis-conversion{basis=z(1),rz,rx,x}` -> "failed to legalize operation 'quake.h'". No H/RY-to-rz/rx patterns; the only native 1-qubit target is IQM's `phased_rx` (pattern list in `DecompositionPatterns.cpp`, pipelines in `CodeGen/Passes.cpp:25-98`). |
| Keep physical qubit ids in emitted QASM2/QIR | Fails: `regtomem` counts unique wires and renumbers (`RegToMem.cpp:121-140`); wires 40-42 came out as 0-2 in both `openqasm2` and `qir-base`. The final layout is stored as `mapping_v2p` (`Mapping.cpp:3315-3328`) but not exported to the helper (`KernelExecution.h:23-32` carries only `mapping_reorder_idx`). All in-tree backends run `regtomem` too (`cudaq/test/Transforms/wireset_codegen.qke:10-12`). Placement packs into ascending low ids (`Mapping.cpp:99-135`), so in practice ids are 0..n-1, but this is not guaranteed. |
| Routing quality | Mediocre: a 20-qubit GHZ line on Fez needed 23 swaps although a swap-free 20-qubit path exists on heavy-hex. Not noise-aware. |
| Disconnected topology (isolated qubits) | Error "disconnected device topology" (`Mapping.cpp:3189`); the helper must prune isolated qubits. |

**Option A. CUDA-Q routes, the helper finishes the job (recommended).** YAML pipeline =
the IQM/OQC pattern (`decomposition` to a small textbook basis, `qubit-mapping{device=file(%QPU_ARCH%)}`,
`regtomem`), `codegen-emission: qasm2`. The helper (1) fetches
`GET /backends/{name}/configuration` once per target, prunes isolated qubits, writes the
topology file; (2) rewrites the QASM2 text gate-by-gate into `{rz, sx, x, cz}` with fixed
identities (h = rz(pi/2) sx rz(pi/2); cx a,b = h b; cz a,b; h b; swap = 3 cx; rx/ry via the
ZSX Euler form U(t,p,l) = rz(p+pi) sx rz(t+pi) sx rz(l), to be checked numerically in tests);
(3) emits OpenQASM 3 with `$k` physical qubits and `c[i] = measure $k`. Effort: small
(~400 lines of C++ beyond the HTTP code). Risk: the physical-id compaction (table above) is
tolerated, not fixed; the helper labels qubits so that ids 0..m-1 form a connected,
good-quality region (BFS order from the best-calibrated qubit using `/properties`), which
makes the "ids are 0..n-1" assumption hold in practice **[U]** until upstream fix. Learning
value: high (every quantum concept is visible in ~400 lines). Maintenance: low; depends on
stable pass names.

**Option B. The helper is a mini-transpiler.** `codegen-emission: qasm2` with a textbook
basis, no CUDA-Q mapping; the helper does layout + SABRE routing + gate rewrite itself in
C++ with the live coupling map and error rates. Full control, correct physical ids,
noise-aware. Effort: large (routing ~1-2k lines plus tests). Learning value: highest.
Maintenance: all yours. Good as a later upgrade of A's gate-rewrite module, not as v1.

**Option C. Someone else transpiles.** IBM's transpiler service (Premium only, so not for
this project) or a local Python/Qiskit sidecar called from C++ (works, but re-introduces
Qiskit and a Python runtime into a C++ plugin). Keep as an optional `transpiler=qiskit-sidecar`
escape hatch for comparison tests; do not build the design on it.

Option A now; B's layout logic later if routing quality matters; two upstream PRs (native IBM
basis patterns in `DecompositionPatterns.cpp`; export `mapping_v2p` into `KernelExecution`) turn
A's main caveat into a non-issue for every superconducting backend, not only IBM.

## 4. Proposed architecture

```
cudaq-ibm-backend/            (same repo as the Python prototype; new top-level dir)
  plugin/
    CMakeLists.txt            add_subdirectory child of CUDA-Q (CUDAQ_EXTERNAL_PROJECTS), links cudaq-common, cudaq-logger
    targets/ibm.yml.in        see sketch below
    IBMServerHelper.cpp       ServerHelper: auth, topology file, job lifecycle, result decoding
    IBMTopology.{h,cpp}       configuration JSON -> pruned/relabelled graph -> CUDA-Q topology file + id map
    Qasm2ToIsaQasm3.{h,cpp}   pure function: QASM2 text + id map -> ISA OpenQASM 3 text (no I/O, unit-testable)
    IamToken.{h,cpp}          IBM Cloud IAM api-key -> bearer token, cached, refreshed 60 s early (port of client.py)
    python/__init__.py.in, __main__.py.in, pyproject.toml.in   entry point "cudaq.backends", --install-nvqpp
    tests/                    lit + pytest; mock IBM server (FastAPI) in tests/mock_ibm/
```

`targets/ibm.yml` sketch (pipeline copied from the IQM/OQC pattern, verified to run on the
156-qubit file in `exp6.py`):

```yaml
name: ibm
description: "CUDA-Q target for IBM Quantum (Sampler, OpenQASM 3)."
cudaq-version: "@CUDA_QUANTUM_VERSION@"
config:
  platform-qpu: remote_rest
  gen-target-backend: true
  preprocessor-defines: ["-D CUDAQ_QUANTUM_DEVICE"]
  link-libs: ["-lcudaq-rest-qpu"]
  jit-high-level-pipeline: "expand-measurements"
  jit-mid-level-pipeline: "func.func(erase-implicit-output),decomposition{basis=h,rx,ry,rz,x,z(1),x(1)},func.func(add-dealloc,combine-quantum-alloc,canonicalize,factor-quantum-alloc,dqe,cse,memtoreg),add-wireset,func.func(assign-wire-indices),qubit-mapping{device=file(%QPU_ARCH%)},func.func(regtomem)"
  codegen-emission: qasm2
target-arguments:
  - { key: backend,  required: true,  type: string, platform-arg: backend,  help-string: "IBM backend, e.g. ibm_fez" }
  - { key: api-key,  required: false, type: string, platform-arg: api_key,  help-string: "IBM Cloud API key (or IBM_QUANTUM_API_KEY)" }
  - { key: crn,      required: false, type: string, platform-arg: crn,      help-string: "Instance CRN (or IBM_QUANTUM_CRN)" }
  - { key: url,      required: false, type: string, platform-arg: url,      help-string: "API base URL" }
  - { key: topology-file, required: false, type: string, platform-arg: topology_file, help-string: "Override: use this topology file instead of fetching" }
```

Data flow per `cudaq.sample`: `getPipelineSubstitutions` -> (cached) configuration ->
topology file + `idmap[k] = physical qubit` -> compile -> `KernelExecution.code` (QASM2 with
`qreg var0[n]`, one `creg` per `mz`, gates from the basis plus `swap` as 3 `cx`) ->
`Qasm2ToIsaQasm3` -> payload `{program_id:"sampler", backend, params:{pubs:[[qasm3,null,shots]], version:2}}`
(the exact shape that ran on `ibm_fez` on 2026-11-05 **[V]** README) -> poll `state.status`
in {COMPLETED, FAILED, CANCELLED} -> `results[0].data[creg].samples` hex -> counts; apply
`reorderIdx` as OQC does (`OQCServerHelp.cpp:412-434`, filled by `Executor.cpp:52`) and the
little-endian flip from `results.py`. Register naming: the QASM2 emitter writes one 1-bit
`creg` per measurement in program order (`TranslateToOpenQASM.cpp`, observed), so the
converter concatenates them in that order into one `bit[n] c` to keep IBM's result shape
simple.

Output format answers (section 2 of the brief). CUDA-Q can emit QASM2 (`codegen-emission:
qasm2`, used by Braket/Infleqtion **[V]** their `.yml`), but it is `OPENQASM 2.0; include
"qelib1.inc"` with virtual registers. IBM's Sampler REST docs show OpenQASM 3 with
`include "stdgates.inc"` **[V]** https://quantum.cloud.ibm.com/docs/guides/sampler-rest-api;
whether the endpoint also parses QASM2 is **[U]** and irrelevant once we rewrite anyway.
Qiskit's client-side ISA check accepts both `$k` physical qubits and a `qubit[156] q;`
declaration with indices used as physical **[V]** `is_isa_circuit` experiment; we emit `$k`,
the form that already succeeded on hardware.

## 5. Milestones (each shippable, rough effort for part-time work)

| # | Deliverable | Effort | Done when |
|---|---|---|---|
| M0 | Dev environment: CUDA-Q 0.16.0 source build in NVIDIA's dev container; build and run the `mock_rest` reference plugin; load its `.so` into pip `cudaq` (ABI check) | 1-2 days | `cudaq.has_target("mock_rest")` is true in a pip venv |
| M1 | `ibm` plugin skeleton: YAML (no mapping yet), IAM auth, job POST/poll/results, hex decoding; mock IBM server (FastAPI, same endpoints as `client.py`) | 2-3 days | Bell pair end-to-end against the mock; `emulate=true` path works |
| M2 | `Qasm2ToIsaQasm3` gate rewrite with unit tests (unitary equivalence checked from Python tests via Qiskit, dev-only dependency); first real run of a Bell pair on `ibm_fez` qubits 0-1 | 3-5 days | Hardware counts match the Python prototype |
| M3 | Routing: fetch configuration, prune/relabel, topology file, `qubit-mapping` in YAML, `reorderIdx`; mock validates ISA with `is_isa_circuit` | 3-5 days | 5-qubit GHZ on hardware; 20-qubit GHZ accepted by the mock |
| M4 | Packaging: wheels (linux x86_64, aarch64), `--install-nvqpp`, README, CI (GitHub Actions: build in dev container, run mock tests) | 2-3 days | `pip install` then `cudaq.set_target("ibm")` works |
| M5 | Optional: `transport=qrmi` using the bundled `libqrmi`; upstream PRs (native IBM basis patterns; `mapping_v2p` export; the mock IBM server) | 1-2 weeks | PRs opened with DCO sign-off |

## 6. Risks and open questions

1. **Physical-id compaction** (section 3) **[V]**. Mitigated by relabelling; fixed only upstream. If a run ever shows non-contiguous placement, the circuit would silently use wrong qubits; add a mock-side check that every 2-qubit gate is on an edge of the *real* coupling map (`is_isa_circuit` does exactly this).
2. **Routing quality** **[V]** 23 swaps for GHZ-20. Fine for learning; a noise-aware layout (Option B's first piece) is the obvious follow-up.
3. **Plugin ABI vs pip wheel** **[U]**. M0 tests it; fallback is "use the dev-container `cudaq`", which is what the docs assume.
4. **macOS** **[V]** native dev builds are documented (see section 2); first build is long because LLVM is built from source.
5. **Pass names are an internal API** **[U]**; the docs even say "Contact the CUDA-Q team for help setting this up" (`backend.rst:172`). Pin `cudaq-version`.
6. **Gate identities** **[U]** until unit-tested; sign conventions of `rx`/`ry`/`phased_rx` vs Qiskit must be checked numerically.
7. **IBM API drift**: service renamed to "IBM Quantum Compute Service", legacy names supported until 2026-11-21 **[V]** QRMI README line 20; `version: 2` field is in our working payload but not shown in the docs **[V]**.
8. **QRMI fit** (brief question 4). QRMI v0.26.6, Apache-2.0, Rust core with a C header (`cbindgen.toml`, `QRMI_VERSION 0.26.6`), C API `qrmi_resource_{new,acquire,task_start,task_status,task_result,target,...}` (`src/cext.rs`); IBM resources `ibm-quantum-compute-service` and `ibm-quantum-system` (Direct Access); payload `{program_id, parameters}` is the Sampler V2 schema (`qrmi_payload_v1_schema.json`); `target()` returns the backend configuration + properties JSON (`src/ibm/quantum_compute_service.rs:597-625`), which is exactly what the topology builder needs; config via `QRMI_IBM_QCS_*` env vars. Activity: 49 tags, last commit 2026-11-05, 65 stars **[V]** clone + GitHub page. CUDA-Q 0.16 already bundles `libqrmi` (`cuda_quantum_cu13.libs/libqrmi-9ed0df30.so` in the wheel) for the Pasqal connector, Linux only, QRMI >= 0.12 (`runtime/cudaq/platform/pasqal/CMakeLists.txt`). Honest assessment: it does not solve the ISA problem (no transpilation) and `acquire()` defaults to a dedicated session (`QRMI_IBM_QCS_SESSION_MODE` default "dedicated"), which the Open plan may not allow **[U]**; the API has churned (renames, deprecations since v0.23). Good second transport once v1 works, and a natural place for Bruno to contribute; wrong place to start.
9. **Upstream path** (brief question 6). NVIDIA's docs state "All external backends are developed as external plugins ... without modifying the core repository" (`backend.rst:6-9`) **[V]**, so an in-tree `ibm` target is not the expected route; contributions need DCO sign-off (`Contributing.md:38-79`) **[V]**. No issue or PR about IBM support was found (`gh search issues/prs` on NVIDIA/cuda-quantum, 2026-11-06) **[V]**. The welcome contributions are compiler-side: native-basis patterns, layout export, maybe a mock server.
10. **Testing** (brief question 5). In-tree pattern: FastAPI mock per backend under `python/tests/utils/mock_qpu/<name>/`, started by a pytest session fixture in a `Process` (`python/tests/backends/test_IQM.py:36-60`) or by `unittests/nvqpp/backends/*/StartServerAndTest.sh.in` for C++ lit tests; deps `requirements-mock-qpu.txt` (fastapi, uvicorn, llvmlite); CI runs `python/tests/backends` in `python_wheels.yml:348` **[V]**. Our mock adds IAM `POST /identity/token`, `GET /backends/{name}/configuration` (serve FakeFez's JSON), `POST /jobs`, `GET /jobs/{id}`, `GET /jobs/{id}/results`, and should reject non-ISA circuits like the real service.

## 7. Sources

- CUDA-Q 0.16.0 source (tag `0.16.0`, commit `62fce8b`): `docs/sphinx/using/extending/{backend,packaging}.rst`; `runtime/common/{ServerHelper.h,BaseRemoteRESTQPU.h,CodeGenConfig.cpp,KernelExecution.h,Executor.cpp}`; `runtime/cudaq/platform/default/rest/helpers/{iqm,oqc,anyon,braket,infleqtion}/*`; `cudaq/lib/Optimizer/Transforms/{Mapping.cpp,RegToMem.cpp,DecompositionPatterns.cpp}`; `cudaq/lib/Optimizer/CodeGen/{Passes.cpp,TranslateToOpenQASM.cpp,TranslateToIQMJson.cpp}`; `cudaq/lib/Target/Yaml/TargetConfigYaml.cpp`; `cudaq/test/Transforms/wireset_codegen.qke`; `docs/sphinx/examples/plugins/mock_rest/`; `python/tests/utils/mock_qpu/`, `python/tests/backends/test_IQM.py`; `Contributing.md`.
- Rendered docs: https://nvidia.github.io/cuda-quantum/0.16.0/using/extending/backend.html and `.../packaging.html`.
- Experiments (pip `cuda-quantum-cu13 0.16.0.post1`, Python MLIR bindings): mapping on a 156-qubit Fez topology, `basis-conversion` failure, GHZ-20 swap count, qubit-id compaction; wheel inventories via `pip show -f` and the macOS wheel from PyPI.
- IBM: https://quantum.cloud.ibm.com/docs/guides/transpile ; https://quantum.cloud.ibm.com/docs/guides/sampler-rest-api ; https://quantum.cloud.ibm.com/docs/api/qiskit-runtime-rest/changelog ; https://quantum.cloud.ibm.com/docs/api/qiskit-transpiler-service-rest ; https://quantum.cloud.ibm.com/docs/api/qiskit-ibm-transpiler/release-notes ; qiskit-ibm-runtime 0.51.0 `utils/utils.py::is_isa_circuit`.
- QRMI: https://github.com/qiskit-community/qrmi (`Cargo.toml`, `cbindgen.toml`, `src/cext.rs`, `src/ibm/*.rs`, `qrmi_payload_v1_schema.json`, `examples/qrmi/c/ibm_quantum_compute_service/`).
- Prototype: this repo (`README.md`, `src/cudaq_ibm/*.py`).
