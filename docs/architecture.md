# Architecture: how the C++ plugin works today

Date: 2026-11-09. Status: living document. Update it in the same PR as the code it describes.
Reader: anyone working on the plugin.
Tags: **[V]** verified (source given), **[U]** unverified.
File references like `runtime/common/Future.cpp` are in the CUDA-Q `0.16.0` tag.

This page describes the code as it is now. The reasons behind it are in
[decisions/](decisions/), and the original options analysis is in
[specs/phase3-design.md](specs/phase3-design.md).

## 1. The big picture

CUDA-Q has a generic "remote REST QPU". A vendor plugs in with two things: a target YAML file
and a shared library that implements `cudaq::ServerHelper`. CUDA-Q compiles the kernel and
does the HTTP calls; the `ServerHelper` only says what to send and how to read the answer
**[V]** `runtime/common/ServerHelper.h:44-130`.

```
cudaq.set_target("ibm", backend="ibm_fez")
        |
   cudaq.sample(kernel)
        |
   CUDA-Q compiler (pipeline from targets/ibm.yml)
        |   decompose into {h, rx, ry, rz, x, z, cx}, print as OpenQASM 2
        v
   IBMServerHelper (plugin/IBMServerHelper.cpp)
        |   createJob:      QASM2 -> ISA OpenQASM 3 {rz, sx, x, cz}   (plugin/Qasm2ToIsa.h)
        |                   -> Sampler job body
        |   CUDA-Q POSTs it to {url}/v1/jobs, then polls GET /v1/jobs/{id}
        |   jobIsDone:      read state.status
        |   processResults: GET /v1/jobs/{id}/results, hex samples -> counts
        v
   cudaq::sample_result
```

The exact order of calls is in [specs/m1-spec.md](specs/m1-spec.md) §1.

## 2. Components

| File | Role | Status |
|---|---|---|
| `plugin/targets/ibm.yml.in` | Target YAML: compiler pipeline, `codegen-emission: qasm2`, target arguments `backend`, `url`, `iam_url` | Done (M1) |
| `plugin/IBMServerHelper.cpp` | IAM login (libcurl), token cache, job body, polling, result decoding | Done (M1) |
| `plugin/Qasm2ToIsa.h` | Header-only rewrite of CUDA-Q's QASM2 into IBM's native gates, emitted as OpenQASM 3 with physical qubits `$k` | `h`, `cx` done; `z`, `y`, `rx`, `ry`, `u3` open (M2) |
| `plugin/tests/test_qasm2_to_isa.cpp` | Tiny unitary simulator; proves each rewrite rule up to global phase. Runs in CI with plain `g++` | Done |
| `plugin/tests/check_plugin.cpp` | Lit test inherited from CUDA-Q's `mock_rest` example (`ninja check-ibm`) | **[U]** may fail now, see §5 |
| `plugin/CMakeLists.txt`, `plugin/python/*`, `plugin/pyproject.toml.in` | Build as a CUDA-Q external project; Python package with a `cudaq.backends` entry point | Inherited from `mock_rest`; names still `cudaq_example_ibm` (M4) |
| `tests/fake_ibm_server.py` | FastAPI fake of IBM IAM and the jobs API; rejects non-ISA gates | Done (M1) |
| `tests/run_fake_ibm.py` | Bell pair through the real plugin against the fake server | Done (M1) |
| `src/cudaq_ibm/` | Phase 1 Python prototype (uses Qiskit for the ISA step) | Done; reference for the C++ code |

## 3. Configuration and credentials

- Target arguments: `backend` (default `ibm_fez`), `url` (default
  `https://quantum.cloud.ibm.com/api`), `iam_url` (tests only).
- Credentials: environment variables `IBM_QUANTUM_API_KEY` and `IBM_QUANTUM_CRN`, never
  target arguments ([decision 0003](decisions/0003-credentials-from-environment.md)).
- Logging: `CUDAQ_LOG_LEVEL=info` shows the ISA circuit sent and the raw results JSON. The
  API key is never logged.

## 4. The gate rewrite

IBM only runs ISA circuits: native gates on physically connected qubits **[V]**
https://quantum.cloud.ibm.com/docs/guides/transpile. On `ibm_fez` the native gates are
`rz`, `sx`, `x`, `cz`; `rz` is virtual (free, done in software).

CUDA-Q cannot decompose into that basis **[V]** (specs/phase3-design.md §3), so the YAML asks
for a small textbook basis and `Qasm2ToIsa.h` rewrites each gate with a fixed identity:

| Gate | Rewrite | Status |
|---|---|---|
| `x`, `rz` | unchanged | proven in unit test |
| `h` | `rz(π/2) sx rz(π/2)` | proven in unit test |
| `cx c,t` | `h t; cz c,t; h t` | proven in unit test |
| `z` | `rz(π)` | open (M2) |
| `rx(θ)` | `rz(π/2) sx rz(θ+π) sx rz(π/2)` | checked numerically, not in code yet |
| `y`, `ry(θ)`, `u3(θ,φ,λ)` | to derive | open (M2) |

The decomposition pass leaves `y` and `u3` in the output **[V]** observed QASM2, so they must
be handled here. Any other gate makes the converter throw.

The converter also renames registers: CUDA-Q's `qreg var0[n]` becomes physical qubits `$0..$n-1`,
and its one-bit `creg`s are merged in program order into one `bit[n] c`. Today there is **no
routing**: virtual qubit k runs on physical qubit k, so 2-qubit gates only work where those
qubits are wired. Routing comes in M3.

## 5. Known limits

1. **No routing yet** (M3). Circuits must fit the chip's wiring as written.
2. **Token expiry during long queue waits** ([decision 0004](decisions/0004-accept-token-expiry-in-v1.md)).
3. **One register, Sampler only.** No Estimator, sessions or error mitigation.
4. **`check-ibm` lit test** **[U]**: it calls `set_target('ibm')` without IBM credentials, and
   `initialize` now throws when they are missing. Not run since M1; fix in M4.
5. **Plugin vs pip `cudaq` ABI** **[U]**: not tested yet (M4).
6. Unverified IBM details: whether results carry `num_bits`, and whether IAM accepts a JSON
   body ([specs/m1-spec.md](specs/m1-spec.md) §2.5, §4).

## 6. How to build and run

See [development.md](development.md).
