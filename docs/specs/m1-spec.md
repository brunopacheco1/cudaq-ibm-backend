# M1 spec: IBMServerHelper talks to IBM's REST API

Date: 2026-11-08, updated 2026-11-09.
Status: implemented 2026-11-08 (PR #1). The Bell pair runs end to end against the fake IBM server.
Reader: Bruno.
Tags: **[V]** verified (source given), **[U]** unverified.
File references like `runtime/common/Future.cpp` are in the CUDA-Q `0.16.0` tag.
Milestone M1 in [roadmap.md](../roadmap.md); design background in [research/2026-11-06-phase3-design.md](../research/2026-11-06-phase3-design.md).
Section numbers are cited by code comments in `plugin/IBMServerHelper.cpp`; keep them stable.

## Summary

Goal of M1: the plugin logs in to IBM, submits a Sampler job, polls it and turns the result
into CUDA-Q counts. It is tested against a **fake IBM server**, not real IBM, because real
IBM only accepts ISA circuits, which come in M2.

Facts come from the working Python prototype (`src/cudaq_ibm/client.py`, `results.py`),
which ran on `ibm_fez` on 2026-11-05, or from the CUDA-Q 0.16 source (paths given).

Result: `tests/run_fake_ibm.py` returned `{ 01:1 10:2 }`, the expected counts (§6) **[V]**
run in the dev container, 2026-11-08.

## 1. How CUDA-Q calls the class

The order of calls **[V]** `runtime/common/Executor.cpp`, `runtime/common/Future.cpp`:

1. `initialize(config)`: once per `set_target`, and **again** inside `Future::get()`.
2. `createJob(codes)` returns `{postUrl, headers, [jobBody...]}`.
3. CUDA-Q POSTs **each** `jobBody` to `postUrl` with `headers`.
4. `extractJobId(postResponse)` returns the job id.
5. `getHeaders()` is called **once**, then reused for the whole poll loop. So a token can
   expire during a long queue wait. Limit accepted for v1 ([decision 0004](../decisions/0004-accept-token-expiry-in-v1.md)).
6. Loop: GET `constructGetJobPath(jobId)` until `jobIsDone(response)` is true, sleeping
   `nextResultPollingInterval()` between GETs.
7. `processResults(lastJobResponse, jobId)` returns `sample_result`.

## 2. IBM endpoints

Source: `src/cudaq_ibm/client.py` **[V]** ran on `ibm_fez`.
Base URL: `https://quantum.cloud.ibm.com/api/v1` (default; the `url` target argument
overrides `https://quantum.cloud.ibm.com/api`, and the plugin adds `/v1`).

### 2.1 Login (IAM)
- `POST https://iam.cloud.ibm.com/identity/token` (the `iam_url` target argument overrides it, for tests only)
- Headers: `Content-Type: application/x-www-form-urlencoded`, `Accept: application/json`
- Body (form, **not JSON**): `grant_type=urn:ibm:params:oauth:grant-type:apikey&apikey=<KEY>`
- Response: `{"access_token": "...", "expires_in": 3600, ...}`

### 2.2 Common headers for all API calls
```
Authorization: Bearer <access_token>
Service-CRN:   <IBM_QUANTUM_CRN>
Accept:        application/json
Content-Type:  application/json
```

### 2.3 Submit job
- `POST {base}/jobs`
- Body:
```json
{
  "program_id": "sampler",
  "backend": "ibm_fez",
  "params": {
    "pubs": [["<OpenQASM 3 text>", null, 1000]],
    "version": 2
  }
}
```
- Response: `{"id": "d4abc...", ...}` (only `id` is used)

### 2.4 Poll job
- `GET {base}/jobs/{id}`
- Response: `{"state": {"status": "Queued" | "Running" | "Completed" | "Failed" | "Cancelled", ...}, ...}`
- The prototype upper-cases `status` before comparing. The plugin does the same.

### 2.5 Get results
- `GET {base}/jobs/{id}/results`
- Response (one entry per PUB, one key per classical register):
```json
{"results": [{"data": {"c": {"samples": ["0x0", "0x3", "0x3", ...]}}}]}
```
- One hex string per shot. Bit 0 is the **right-most** bit (little-endian). CUDA-Q puts
  qubit 0 **left-most**, so the plugin reverses it: `"0x1"` on 2 bits -> `"01"`
  little-endian -> `"10"` CUDA-Q.
- Register size: taken from the circuit we sent (`outputNames` for the job). Fallbacks:
  `num_bits` in the response, then the widest sample. Whether IBM sends `num_bits` is
  **[U]**; the plugin logs the results JSON at INFO, so the first hardware run (M2) will tell.

## 3. Method by method

As implemented in `plugin/IBMServerHelper.cpp`.

| Method | What it does |
|---|---|
| `initialize` | Reads `backend` (default `ibm_fez`), `url` and `iam_url` from `config`. Reads `IBM_QUANTUM_API_KEY` and `IBM_QUANTUM_CRN` from the environment and throws if missing. Keeps the key in a **private member**, never in `backendConfig`. Calls `parseConfigForCommonParams(config)`, then sets shots if given. |
| `getHeaders` | Returns the 4 headers from §2.2. Gets the token through a private `accessToken()` that caches it and refreshes it 60 s before expiry (same logic as `client.py::_access_token`). |
| `createJob` | For each `KernelExecution`, converts `circuitCode.code` with `qasm2ToIsaQasm3` (M2, `Qasm2ToIsa.h`), logs the ISA circuit at INFO, and builds the body from §2.3. Returns `{base + "/jobs", getHeaders(), bodies}`. |
| `extractJobId` | Returns `postResponse["id"]`; throws if missing. |
| `constructGetJobPath(jobId)` | `base + "/jobs/" + jobId` |
| `constructGetJobPath(postResponse)` | `constructGetJobPath(extractJobId(postResponse))` |
| `jobIsDone` | Upper-cases `state.status`. `COMPLETED` returns true. `FAILED`/`CANCELLED` **throw** with the status (otherwise CUDA-Q polls forever). Anything else returns false. |
| `nextResultPollingInterval` | 5 seconds, like the prototype. |
| `processResults` | Makes an extra `GET {base}/jobs/{jobId}/results` with `RestClient`, `getHeaders()` and TLS checks on (IonQ does the same, `IonQServerHelper.cpp` ~lines 315-385). Requires a single register. Decodes the hex samples (§2.5) into `CountsDictionary` and returns `sample_result(ExecutionResult(counts))`. |

## 4. Traps in CUDA-Q's RestClient

Source **[V]** `runtime/common/RestClient.cpp`.

1. **`post()` always sends JSON**: the body is `post.dump()`. IAM wants a form body (§2.1);
   a JSON string would be sent *with quotes*. So the IAM call cannot use `RestClient::post`.
   **Chosen:** call libcurl directly for this one request (`requestNewToken()`; honours
   `CURL_CA_BUNDLE`, throws on HTTP errors). Whether IAM also accepts a JSON body is **[U]**:
   the cloud test environment cannot reach `iam.cloud.ibm.com`, and it no longer matters.
2. **`post()` logs the body** at INFO level ("Posting to ... with data = ..."). The API key
   never goes through `RestClient`; only the libcurl call above sees it, and it logs nothing.
3. **`enableSsl` defaults to `false`**, which **turns off TLS certificate checking**. Our own
   calls turn it on (libcurl verifies by default; `processResults` passes `true`). The
   Executor's job POST still uses `false`. Upstream issue to report (M5).

## 5. Out of scope for M1

- Turning the circuit into IBM's ISA (`rz, sx, x, cz` on physical qubits, OpenQASM 3): M2
  and M3. Status 2026-11-09: `h` and `cx` are done (PR #2); `z`, `y`, `rx`, `ry`, `u3` are
  Bruno's next step; routing is M3.
- Token refresh during long polls (§1, step 5; upstream PR later).
- Estimator, sessions, error mitigation.

## 6. Test plan

1. **Fake IBM server** `tests/fake_ibm_server.py` (FastAPI, default port 62455) — **done**:
   - `POST /identity/token` returns a fixed token. Rejects anything that is not a
     form-encoded body with the key `test-key`.
   - `POST /api/v1/jobs` checks `Authorization: Bearer fake-token` and `Service-CRN: test-crn`,
     checks `program_id` is `sampler`, and (since M2) rejects circuits with non-ISA gates.
     Returns a new job id.
   - `GET /api/v1/jobs/{id}` returns `Running` twice, then `Completed`.
   - `GET /api/v1/jobs/{id}/results` returns the samples `["0x1","0x1","0x2"]` on 2 bits.
2. The IAM URL is a target argument (`iam_url`), so the test points it at the fake server — **done**.
3. `tests/run_fake_ibm.py` sends a Bell pair and expects `{ 10:2 01:1 }`, which proves the
   bit reversal — **done, passes** (see Summary).
4. Failure tests — **not automated yet**: missing env vars throw; status `Failed` throws;
   HTTP 401 surfaces a clear error. The code paths exist; add tests that drive them through
   the fake server.

How to run all of this: [development.md](../development.md) §4.
