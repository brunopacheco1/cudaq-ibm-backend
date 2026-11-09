# Architecture: how the C++ plugin works today

Date: 2026-11-09. Status: living document. Update it in the same PR as the code it describes.
Reader: anyone working on the plugin.
Tags: **[V]** verified (source given), **[U]** unverified.
CUDA-Q file references like `runtime/common/Future.cpp` are in the `0.16.0` tag.

This page describes the code as it is now. Why it is built this way: [decisions/](decisions/).
What is next: [roadmap.md](roadmap.md). Code comments cite the § numbers below; keep them stable.

## 1. The big picture

CUDA-Q has a generic "remote REST QPU". A vendor plugs in with two things: a target YAML file
and a shared library that implements `cudaq::ServerHelper`. CUDA-Q compiles the kernel and
makes the HTTP calls; the `ServerHelper` only says what to send and how to read the answer
**[V]** `runtime/common/ServerHelper.h:44-130`, `docs/sphinx/using/extending/backend.rst`.

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

The pip `cudaq` wheel has no CUDA-Q headers, CMake config or `nvq++` **[V]** wheel inventory,
so the plugin is built inside a CUDA-Q source build (`-DCUDAQ_EXTERNAL_PROJECTS=ibm`), in the
dev container ([development.md](development.md)).

## 2. How CUDA-Q calls the ServerHelper

### 2.1 Call order

**[V]** `runtime/common/Executor.cpp`, `runtime/common/Future.cpp`:

1. `initialize(config)`: once per `set_target`, and **again** inside `Future::get()`.
2. `createJob(codes)` returns `{postUrl, headers, [jobBody...]}`.
3. CUDA-Q POSTs **each** `jobBody` to `postUrl` with `headers`.
4. `extractJobId(postResponse)` returns the job id.
5. `getHeaders()` is called **once**, then reused for the whole poll loop. So a token can
   expire during a long queue wait ([decision 0004](decisions/0004-accept-token-expiry-in-v1.md)).
6. Loop: GET `constructGetJobPath(jobId)` until `jobIsDone(response)` is true, sleeping
   `nextResultPollingInterval()` between GETs.
7. `processResults(lastJobResponse, jobId)` returns `sample_result`.

### 2.2 RestClient traps

**[V]** `runtime/common/RestClient.cpp`:

1. `post()` always sends JSON (`post.dump()`). IAM needs a form body (§3.1).
2. `post()` logs the body at INFO ("Posting to ... with data = ...").
3. `enableSsl` defaults to `false`, which **turns off TLS certificate checks**. The Executor's
   job POST uses that default.

So the IAM login uses libcurl directly ([decision 0005](decisions/0005-iam-login-with-libcurl.md)),
and our own `RestClient` calls pass `enableSsl = true`. Upstream fixes: [upstream.md](upstream.md) #2, #3.

### 2.3 TLS needs a CA bundle

**[V]** CUDA-Q builds its own libcurl with `-DCURL_CA_BUNDLE=none -DCURL_CA_PATH=none`
(`scripts/install_prerequisites.sh` at `0.16.0`), so libcurl has **no certificate store**.
`RestClient` picks one in its constructor: `CURL_CA_BUNDLE` if that file exists, else
`cacert.pem` two levels above the `cudaq-common` library, else none. With none, every call
with checks on fails with "SSL peer certificate or SSH remote key was not OK". Our IAM call
used to set a bundle only from `CURL_CA_BUNDLE`, so the first `ibm_fez` run failed at login
(2026-11-09), although the dev container has `/work/cuda-quantum/build/cacert.pem`.

So `initialize` finds a bundle **the same way `RestClient` does** (`CURL_CA_BUNDLE` if the file
exists, else CUDA-Q's `cacert.pem`) and passes it to the IAM call with `CURLOPT_CAINFO`. Login and
`RestClient` therefore trust the same certificates. If there is none, it throws and asks for
`CURL_CA_BUNDLE`; it never turns checks off.

**[V]** How CUDA-Q's own helpers do HTTPS (0.16.0 source): all of them use `RestClient`; none calls
libcurl directly or picks a CA bundle itself. Most keep checks off (`enableSsl = false`): IonQ
and OQC results, IQM, all Quantinuum calls, Anyon and Fermioniq login, and the `Future`
polling. A few turn them on: qBraid, OQC `/admin/qpu`, Scaleway (when `secure`). Quantinuum's
login passes `enableLogging = false` to keep secrets out of the log.

## 3. IBM REST API

Source **[V]** `src/cudaq_ibm/client.py` and `results.py`, which ran on `ibm_fez`.
Base URL: `{url}/v1`, where `url` defaults to `https://quantum.cloud.ibm.com/api`.

### 3.1 Login (IAM)
- `POST https://iam.cloud.ibm.com/identity/token` (target argument `iam_url` overrides it, for tests)
- Headers: `Content-Type: application/x-www-form-urlencoded`, `Accept: application/json`
- Body (form, **not JSON**): `grant_type=urn:ibm:params:oauth:grant-type:apikey&apikey=<KEY>`
- Response: `{"access_token": "...", "expires_in": 3600, ...}`
- Whether IAM also accepts a JSON body is **[U]** and no longer matters.

### 3.2 Common headers for all API calls
```
Authorization: Bearer <access_token>
Service-CRN:   <IBM_QUANTUM_CRN>
Accept:        application/json
Content-Type:  application/json
```

### 3.3 Submit job
- `POST {base}/jobs`, body:
```json
{
  "program_id": "sampler",
  "backend": "ibm_fez",
  "params": { "pubs": [["<OpenQASM 3 text>", null, 1000]], "version": 2 }
}
```
- Response: `{"id": "d4abc...", ...}` (only `id` is used). The circuit format is in §6
  and [decision 0006](decisions/0006-send-openqasm3-with-physical-qubits.md).

### 3.4 Poll job
- `GET {base}/jobs/{id}`
- Response: `{"state": {"status": "Queued" | "Running" | "Completed" | "Failed" | "Cancelled"}, ...}`
- Compare upper-cased, like the prototype.

### 3.5 Get results
- `GET {base}/jobs/{id}/results`
- Response (one entry per PUB, one key per classical register):
  `{"results": [{"data": {"c": {"samples": ["0x0", "0x3", ...]}}}]}`
- One hex string per shot. Bit 0 is the **right-most** bit (little-endian). CUDA-Q puts qubit
  0 **left-most**, so we reverse: `"0x1"` on 2 bits -> `"01"` -> `"10"` in CUDA-Q.
- Register size: from the circuit we sent (`outputNames` for the job); fallbacks: `num_bits`
  in the response, then the widest sample. **[V]** IBM sends `num_bits` (2 for a Bell pair on
  `ibm_fez`, 2026-11-09).

## 4. IBMServerHelper, method by method

| Method | What it does |
|---|---|
| `initialize` | Reads `backend` (default `ibm_fez`), `url`, `iam_url`. Reads `IBM_QUANTUM_API_KEY` and `IBM_QUANTUM_CRN` from the environment and throws if missing ([decision 0003](decisions/0003-credentials-from-environment.md)). Calls `parseConfigForCommonParams`, sets shots. |
| `getHeaders` | The 4 headers of §3.2. The token comes from a private `accessToken()` that caches it and refreshes it 60 s before expiry. |
| `createJob` | Converts each kernel with `qasm2ToIsaQasm3` (§6), logs the ISA circuit at INFO, builds the body of §3.3. |
| `extractJobId` | `postResponse["id"]`; throws if missing. |
| `constructGetJobPath` | `{base}/jobs/{id}` (both overloads). |
| `jobIsDone` | `COMPLETED` -> true; `FAILED`/`CANCELLED` -> **throw** (otherwise CUDA-Q polls forever); else false. |
| `nextResultPollingInterval` | 5 seconds. |
| `processResults` | Extra `GET {base}/jobs/{id}/results` with TLS checks on (IonQ does the same). Requires one register. Decodes §3.5 into counts. Logs the results JSON at INFO. |

## 5. Components

| File | Role | Status |
|---|---|---|
| `plugin/targets/ibm.yml.in` | Target YAML: compiler pipeline, `codegen-emission: qasm2`, target arguments `backend`, `url`, `iam_url` | Done (M1) |
| `plugin/IBMServerHelper.cpp` | §2-§4 | Done (M1) |
| `plugin/Qasm2ToIsa.h` | §6. Header-only, no I/O, no CUDA-Q includes | M2 in progress |
| `plugin/tests/test_qasm2_to_isa.cpp` | Tiny unitary simulator; proves each rewrite rule up to global phase. Plain `g++`, runs in CI | Done |
| `plugin/tests/check_plugin.cpp` | Lit test inherited from CUDA-Q's `mock_rest` example (`ninja check-ibm`) | **[U]** may fail, §8 |
| `plugin/CMakeLists.txt`, `plugin/python/*`, `plugin/pyproject.toml.in` | Build as a CUDA-Q external project; Python package with a `cudaq.backends` entry point | From `mock_rest`; still named `cudaq_example_ibm` (M4) |
| `tests/fake_ibm_server.py`, `tests/run_fake_ibm.py` | Fake IBM and an end-to-end Bell run (§7) | Done (M1) |
| `src/cudaq_ibm/` | Phase 1 Python prototype (uses Qiskit for the ISA step) | Done; reference for the C++ code |

## 6. The gate rewrite

IBM runs only native gates on wired qubits ([decision 0001](decisions/0001-cudaq-routes-helper-rewrites-gates.md)).
On `ibm_fez`: `rz`, `sx`, `x`, `cz`; `rz` is virtual (free, done in software). CUDA-Q's YAML
pipeline produces a textbook basis, and `Qasm2ToIsa.h` rewrites each gate:

| Gate | Rewrite | Status |
|---|---|---|
| `x`, `rz` | unchanged | proven in unit test |
| `h` | `rz(π/2) sx rz(π/2)` | proven in unit test |
| `cx c,t` | `h t; cz c,t; h t` | proven in unit test |
| `z` | `rz(π)` | proven in unit test |
| `y` | `rz(π) x` | proven in unit test |
| `rx(θ)` | `rz(π/2) sx rz(θ+π) sx rz(π/2)` | proven in unit test |
| `ry(θ)` | `sx rz(θ+π) sx rz(π)` | proven in unit test |
| `u3(θ,φ,λ)` | `rz(λ) sx rz(θ+π) sx rz(φ+π)` | proven in unit test |

Gates are in circuit order. How the last three follow from each other: `ry(θ) = rz(−π/2) rx(θ)
rz(π/2)` (turn Y onto X, rotate, turn back), then merge neighbouring `rz`; `u3 = rz(λ) ry(θ) rz(φ)`,
then merge again. Each rule is tested at several angles, including negative ones and π.

CUDA-Q's decomposition leaves `y` and `u3` in the output **[V]** observed QASM2, 2026-11-08.
Any gate without a rule (for example `swap`) makes the converter throw.

**[V]** End to end (second kernel of `tests/run_fake_ibm.py`, 2026-11-09): `rx`, `ry`, `z` and `y`
reach the converter and come out as in the table; the whole ISA circuit equals the kernel up to
global phase (|tr(U†V)|/4 = 1 − 7·10⁻¹⁵). In that builder kernel `u3` arrived already split into
`rz rx rz`, and `s`/`t` arrived as `rz(1.570796)` and `rz(0.7853982)`: π rounded to about 7
digits by CUDA-Q (cause **[U]**). The error is ~3·10⁻⁷ rad, far below hardware noise.

Output ([decision 0006](decisions/0006-send-openqasm3-with-physical-qubits.md)):
`OPENQASM 3.0; include "stdgates.inc"; bit[n] c;`, qubits as `$k`, measurements as
`c[i] = measure $k;`. CUDA-Q's 1-bit `creg`s are merged in program order into `c`.
Today there is **no routing**: virtual qubit k runs on physical qubit k (M3 adds routing).

## 7. Testing

- `pytest`: Python prototype, with `responses` and `FakeFez`. Never touches IBM.
- `plugin/tests/test_qasm2_to_isa.cpp`: rewrite rules (CI).
- `tests/fake_ibm_server.py` ([decision 0008](decisions/0008-test-against-a-fake-ibm-server.md)),
  default port 62455:
  - `POST /identity/token`: only a form body with key `test-key`; returns `fake-token`.
  - `POST /api/v1/jobs`: checks `Bearer fake-token`, `Service-CRN: test-crn`, `program_id`
    `sampler`, and that every gate is native.
  - `GET /api/v1/jobs/{id}`: `Running` twice, then `Completed`.
  - `GET /api/v1/jobs/{id}/results`: samples `["0x1","0x1","0x2"]` on 2 bits.
- `tests/run_fake_ibm.py`: Bell pair through the real plugin; expects `{ 10:2 01:1 }`, which
  proves the bit reversal. Passed 2026-11-08 **[V]**.
- Not automated yet: missing env vars throw; `Failed` status throws; HTTP 401 gives a clear error.

How to run them: [development.md](development.md) §4.

## 8. Known limits

1. **No routing yet** (M3). Circuits must fit the chip's wiring as written.
2. **Token expiry during long queue waits** ([decision 0004](decisions/0004-accept-token-expiry-in-v1.md)).
3. **One register, Sampler only.** No Estimator, sessions or error mitigation.
4. **`check-ibm` lit test** **[U]**: it calls `set_target('ibm')` without credentials, which
   `initialize` refuses. Not run since M1; fix in M4.
5. **Plugin vs pip `cudaq` ABI** **[U]**: not tested yet (M4).
