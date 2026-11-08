# M1 spec: IBMServerHelper talks to IBM's REST API

Goal of M1: the plugin logs in to IBM, submits a Sampler job, polls it and
turns the result into CUDA-Q counts. Test it against a **fake IBM server**
first, then against real IBM in M2, once the circuit is in IBM's format.

Every fact below comes from your working Python prototype
(`src/cudaq_ibm/client.py`, `results.py`), which ran on `ibm_fez`, or from
the CUDA-Q 0.16 source (file paths given). Items marked **VERIFY** are
not confirmed yet. Check them before you rely on them.

## 1. How CUDA-Q calls your class

The order of calls (`runtime/common/Executor.cpp`, `runtime/common/Future.cpp`):

1. `initialize(config)`: once per `set_target`, and **again** inside `Future::get()`.
2. `createJob(codes)` returns `{postUrl, headers, [jobBody...]}`.
3. CUDA-Q POSTs **each** `jobBody` to `postUrl` with `headers`.
4. `extractJobId(postResponse)` returns the job id.
5. `getHeaders()` is called **once**, then reused for the whole poll loop (the token-expiry limit we accepted).
6. Loop: GET `constructGetJobPath(jobId)` until `jobIsDone(response)` is true, sleeping `nextResultPollingInterval()` between GETs.
7. `processResults(lastJobResponse, jobId)` returns `sample_result`.

## 2. IBM endpoints (from client.py)

Base URL: `https://quantum.cloud.ibm.com/api/v1` (default; overridable with the `url` target argument).

### 2.1 Login (IAM)
- `POST https://iam.cloud.ibm.com/identity/token`
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
- Response: `{"id": "d4abc...", ...}` (you need only `id`)

### 2.4 Poll job
- `GET {base}/jobs/{id}`
- Response: `{"state": {"status": "Queued" | "Running" | "Completed" | "Failed" | "Cancelled", ...}, ...}`
- The prototype upper-cases `status` before comparing. Do the same.

### 2.5 Get results
- `GET {base}/jobs/{id}/results`
- Response (one entry per PUB, one key per classical register):
```json
{"results": [{"data": {"c": {"samples": ["0x0", "0x3", "0x3", ...]}}}]}
```
- One hex string per shot. Bit 0 is the **right-most** bit (little-endian).
  CUDA-Q puts qubit 0 **left-most**, so reverse it: `"0x1"` on 2 bits -> `"01"` little-endian -> `"10"` CUDA-Q.
- Register names and sizes come from the circuit we sent. **VERIFY** whether the response also carries `num_bits`; if not, we use the size we know.

## 3. Method by method

| Method | What it must do |
|---|---|
| `initialize` | Read `backend` (default `ibm_fez`) and `url` (default base above) from `config`. Read `IBM_QUANTUM_API_KEY` and `IBM_QUANTUM_CRN` from the environment and throw if missing. Store the key in a **private member**. Call `parseConfigForCommonParams(config)`, then `setShots` if `shots` is given. |
| `getHeaders` | Return the 4 headers from 2.2. Get the token through a private `accessToken()` that caches it and refreshes it 60 s before expiry (same logic as `client.py::_access_token`). |
| `createJob` | For each `KernelExecution`, build the body from 2.3 with `circuitCode.code` as the circuit and `shots`. Return `{base + "/jobs", getHeaders(), bodies}`. |
| `extractJobId` | Return `postResponse["id"]`; throw if missing. |
| `constructGetJobPath(jobId)` | `base + "/jobs/" + jobId` |
| `constructGetJobPath(postResponse)` | `constructGetJobPath(extractJobId(postResponse))` |
| `jobIsDone` | Upper-case `state.status`. `COMPLETED` returns true. `FAILED`/`CANCELLED` **throw** with the status (otherwise CUDA-Q polls forever). Anything else returns false. |
| `nextResultPollingInterval` (optional) | 5 seconds, like the prototype. |
| `processResults` | Make an extra `GET base/jobs/{jobId}/results` with `RestClient` and `getHeaders()` (IonQ does the same in `IonQServerHelper.cpp` ~lines 315-385). Decode the hex samples (2.5) into `CountsDictionary`, then return `sample_result(ExecutionResult(counts))`. |

## 4. Traps found in CUDA-Q's RestClient (runtime/common/RestClient.cpp)

1. **`post()` always sends JSON**: the body is `post.dump()`. IAM wants a form body (2.1). A JSON string would be sent *with quotes*. So the IAM call cannot use `RestClient::post` as is. Options: (a) call `cpr::Post` / libcurl directly for this one request, or (b) check whether IAM also accepts JSON. **VERIFY (b)** from your Mac with `curl` and a dummy key: compare the error for a JSON body against a form body.
2. **`post()` logs the body** at INFO level ("Posting to ... with data = ..."). Never let the API key go through a logged call. Pass `enableLogging = false`.
3. **`enableSsl` defaults to `false`**, which **turns off TLS certificate checking**. For IAM and IBM calls you make yourself, pass `enableSsl = true`. Note: the Executor's job POST uses `false`. That's a possible upstream issue; write it down.

## 5. Out of scope for M1

- Turning the circuit into IBM's ISA (`rz, sx, x, cz` on physical qubits, OpenQASM 3): **M2/M3**. Until then, real IBM will reject the job. That's why M1 is tested against a fake server.
- Token refresh during long polls (limit accepted; upstream PR later).
- Estimator, sessions, error mitigation.

## 6. Test plan for M1

1. **Fake IBM server** (Python FastAPI, about 60 lines, you write it), on `localhost`, implementing 2.1-2.5 with canned answers:
   - `/identity/token` returns a fixed token. Check that the body is form-encoded and the key is the one you set.
   - `POST /api/v1/jobs` checks the `Authorization` and `Service-CRN` headers, then returns `{"id": "job-1"}`.
   - `GET /api/v1/jobs/job-1` returns `Running` twice, then `Completed`.
   - `GET /api/v1/jobs/job-1/results` returns fixed samples, for example `["0x1","0x1","0x2"]` on 2 bits.
2. Make the IAM URL a target argument too (`iam_url`), so the test can point it at the fake server.
3. Expected counts for the samples above: `{ 10:2 01:1 }`. That proves the bit reversal.
4. Failure tests: missing env vars throw; status `Failed` throws; HTTP 401 surfaces a clear error.
