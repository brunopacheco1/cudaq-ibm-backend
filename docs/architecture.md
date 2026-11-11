# Architecture: how the C++ plugin works today

Date: 2026-11-11. Status: living document. Update it in the same PR as the code it describes.
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
   IBMServerHelper.getPipelineSubstitutions (plugin/IBMServerHelper.cpp)
        |   fetch the chip's wiring and error rates, leave out what does not work,
        |   number the good qubits, write the device file   (plugin/ChipData.h, Layout.h)
        v
   CUDA-Q compiler (pipeline from targets/ibm.yml)
        |   decompose into {h, rx, ry, rz, x, z, cx}, route on the device file
        |   (qubit-mapping), print as OpenQASM 2 with qubit labels 0..m-1
        v
   IBMServerHelper
        |   createJob:      find an IBM qubit for every label          (plugin/Layout.h)
        |                   QASM2 -> ISA OpenQASM 3 {rz, sx, x, cz}   (plugin/Qasm2ToIsa.h)
        |                   -> Sampler job body
        |   CUDA-Q POSTs it to {url}/v1/jobs, then polls GET /v1/jobs/{id}
        |   jobIsDone:      read state.status
        |   processResults: GET /v1/jobs/{id}/results, hex samples -> counts,
        |                   keeping the bits the kernel measured       (plugin/ResultBits.h)
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
2. `getPipelineSubstitutions()`: at every compile, and twice per `sample` **[V]**
   `launch.h:83-86`, `RemoteRESTQPU.cpp:33`. It fills the `%PLACEHOLDER%`s of the YAML
   pipeline **[V]** `BaseRemoteRESTQPU.h:225-229`. Ours returns the device file (§9.4).
   Then CUDA-Q compiles the kernel.
3. `createJob(codes)` returns `{postUrl, headers, [jobBody...]}`.
4. CUDA-Q POSTs **each** `jobBody` to `postUrl` with `headers`.
5. `extractJobId(postResponse)` returns the job id.
6. `getHeaders()` is called **once**, then reused for the whole poll loop. So a token can
   expire during a long queue wait ([decision 0004](decisions/0004-accept-token-expiry-in-v1.md)).
7. Loop: GET `constructGetJobPath(jobId)` until `jobIsDone(response)` is true, sleeping
   `nextResultPollingInterval()` between GETs.
8. `processResults(lastJobResponse, jobId)` returns `sample_result`.

### 2.2 RestClient traps

**[V]** `runtime/common/RestClient.cpp`:

1. `post()` always sends JSON (`post.dump()`). IAM needs a form body (§3.1).
2. `post()` logs the body at INFO ("Posting to ... with data = ..."). It logs bodies, not
   headers **[V]** `RestClient.cpp:71,104`. The plugin never logs the key or the token; a
   hardware run at INFO had no such line (2026-11-10).
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
- Register size: `num_bits` in the response; fallback: the widest sample. **[V]** IBM sends
  `num_bits` (2 for a Bell pair on `ibm_fez`, 2026-11-09). Any width (no 64-bit limit).
- Which bits CUDA-Q gets ([decision 0010](decisions/0010-measure-all-then-keep-measured-bits.md),
  §9.5): our circuit measures every qubit in allocation order, so `c[i]` is qubit i. We keep
  `c[q]` for each qubit q in the job's `output_names`, ascending; with no `output_names`, every
  bit. Code: `plugin/ResultBits.h`.

### 3.6 Chip wiring
- `GET {base}/backends/{name}/configuration`
- Used: `n_qubits` and `coupling_map`, a list of pairs. Each link is listed in both
  directions (352 entries for the 176 links of `ibm_fez`) **[V]** real reply, 2026-11-10.
- The reply also has `basis_gates`; the plugin does not read it (the Python prototype does).

### 3.7 Chip calibration
- `GET {base}/backends/{name}/properties`
- `qubits[i]` is a list of `{name, value, date}` items for qubit i: `readout_error`,
  `prob_meas0_prep1`, `prob_meas1_prep0`, `T1`, `T2`, ... `gates[]` has one entry per gate
  and qubit set: `{gate, qubits, parameters: [{name: "gate_error", value}, ...]}`
  **[V]** real `ibm_fez` reply, 2026-11-10; same shape as `props_fez.json` in
  qiskit-ibm-runtime 0.52.0.
- Used: `readout_error` per qubit; `gate_error` of `cz` per link; `gate_error` of `sx` and `x`
  per qubit; `operational` where present.
- `operational` (0/1) is optional and missing means working **[V]** qiskit-ibm-runtime
  `backend_properties.py:338-352, 461-472`. The real `ibm_fez` reply had no such item at all.
  The FakeFez snapshot marks 7 cz pairs with an error of 1 **[V]** `props_fez.json`.
- **An error of 1** means the benchmark of that gate failed for several days. IBM calls the
  value stale and undefined: "proceed with caution" **[V]** IBM guide
  ["QPU information"](https://quantum.cloud.ibm.com/docs/en/guides/qpu-information). On
  2026-11-10 `ibm_fez` had it for `cz` on link 32-33 and for `sx`, `x`, `id`, `rx` on
  qubits 72, 148 and 149 **[V]**.
- `readout_error` is the mean of `prob_meas0_prep1` and `prob_meas1_prep0`, and it counts
  preparation errors too, not only measurement errors **[V]** same guide.
- The values can be old: on 2026-11-10 at 13:00 UTC the readout errors dated from 23:54 UTC
  the day before, and a later reply carried new timestamps with the same values **[V]**.
- That these two GETs use no QPU time is **[U]** but normal: they are plain reads and start
  no job. Tool to save the replies: `experiments/fetch_chip_data.py`.
- What the plugin does with unreadable or missing values (fail closed):
  [decision 0011](decisions/0011-stop-when-properties-cannot-be-read.md), `plugin/ChipData.h`.

## 4. IBMServerHelper, method by method

| Method | What it does |
|---|---|
| `initialize` | Reads `backend` (default `ibm_fez`), `url`, `iam_url`. Reads `IBM_QUANTUM_API_KEY` and `IBM_QUANTUM_CRN` from the environment and throws if missing ([decision 0003](decisions/0003-credentials-from-environment.md)). Calls `parseConfigForCommonParams`, sets shots. |
| `getHeaders` | The 4 headers of §3.2. The token comes from a private `accessToken()` that caches it and refreshes it 60 s before expiry. |
| `getPipelineSubstitutions` | Returns `{"%QPU_ARCH%": device file}` for `qubit-mapping`. Fetches §3.6 and §3.7 (kept 60 s, because CUDA-Q asks twice per `sample`), builds the chip (`ChipData.h`), numbers it (§9.4) and writes the device file to a fresh private temp file. With the `mapping_file` target argument it uses that file instead and fetches nothing. Throws when `/properties` cannot be read ([decision 0011](decisions/0011-stop-when-properties-cannot-be-read.md)). Logs the usable qubits, the root and the forecast at INFO. |
| `createJob` | For each kernel: logs the OpenQASM 2 it received, finds an IBM qubit for every label (§9.3), converts with `qasm2ToIsaQasm3` (§6), logs the label -> qubit map and the ISA circuit at INFO, builds the body of §3.3. |
| `extractJobId` | `postResponse["id"]`; throws if missing. |
| `constructGetJobPath` | `{base}/jobs/{id}` (both overloads). |
| `jobIsDone` | `COMPLETED` -> true; `FAILED`/`CANCELLED` -> **throw** (otherwise CUDA-Q polls forever); else false. |
| `nextResultPollingInterval` | 5 seconds. |
| `processResults` | Extra `GET {base}/jobs/{id}/results` with TLS checks on (IonQ does the same). Requires one register. Decodes §3.5 into counts, keeping only the bits of the qubits in `output_names`. Logs the results JSON at INFO. |

## 5. Components

| File | Role | Status |
|---|---|---|
| `plugin/targets/ibm.yml.in` | Target YAML: compiler pipeline with routing (§9.1), `codegen-emission: qasm2`, target arguments `backend`, `url`, `iam_url`, `mapping_file` | Done (M3) |
| `plugin/IBMServerHelper.cpp` | §2-§4 | Done (M3) |
| `plugin/Qasm2ToIsa.h` | §6. Header-only, no I/O, no CUDA-Q includes | Done (M2; register table and `$k` relabel in M3) |
| `plugin/ChipData.h` | §3.6, §3.7: IBM's two replies -> a `Chip`; fail-closed rules. Header-only, needs nlohmann/json | Done (M3) |
| `plugin/Layout.h` | §9.3, §9.4: usable region, root, numbering, device file, label -> qubit search. Header-only, no I/O | Done (M3) |
| `plugin/ResultBits.h` | §3.5, §9.5: which result bits CUDA-Q gets | Done (M3) |
| `plugin/tests/test_qasm2_to_isa.cpp` | Tiny unitary simulator; proves each rewrite rule up to global phase. Plain `g++`, runs in CI | Done |
| `plugin/tests/test_layout.cpp`, `test_chip_data.cpp`, `test_result_bits.cpp` | Unit tests of the three headers above. Plain `g++`, run in CI. `test_chip_data` also reads two saved IBM replies (file mode) | Done |
| `tests/test_target_yml.py` | Compiles kernels with the pipeline of `ibm.yml.in` using pip `cudaq` and checks which gates come out (§9.7). In CI | Done |
| `plugin/CMakeLists.txt` | Builds the library and the target file inside a CUDA-Q source build, as an external project | From `mock_rest` |
| `plugin/build_against_wheel.sh` | Builds the same two files against pip `cudaq`, without a source build ([development.md](development.md) §6). CI and the wheel use it | Done (M4) |
| `plugin/build_wheel.sh`, `plugin/packaging/*` | The wheel `cudaq-ibm`: Python package `cudaq_ibm_plugin` with a `cudaq.backends` entry point around the library; `wheel_platform.py` chooses the platform tag ([development.md](development.md) §7) | Done (M4) |
| `plugin/test_wheel.sh`, `tests/plugin_under_test.py` | Installs a wheel next to pip `cudaq` in a fresh environment and runs the fake-server scripts with the installed plugin. In CI (`wheels.yml`) | Done (M4) |
| `tests/fake_ibm_server.py`, `tests/test_fake_server.py`, `tests/run_fake_ibm.py` | Fake IBM with the `ibm_fez` wiring, its own tests (CI), and end-to-end runs through the built plugin (§7) | Done (M3) |
| `tests/isa_simulator.py`, `tests/test_isa_simulator.py` | Statevector simulator for native-gate circuits (`rz`, `sx`, `x`, `cz`, measurements at the end), no noise; the fake server answers jobs with it. The quantum functions are Bruno's. Its tests compare it with Qiskit (CI) | Done (M4) |
| `tests/run_fake_ibm_results.py` | Result checks through the built plugin: 25 kernels against CUDA-Q's own simulator (§7). In CI | Done (M4) |
| `examples/expectation_from_samples.py`, `tests/test_expectation_example.py` | Expectation values without `cudaq.observe` (§8 item 7): basis-change gates, `sample`, average of the parity. Prints `<ZZ>`, `<XX>`, `<YY>` and the fidelity of a Bell pair, on the simulator or on IBM (`--target ibm`, spends QPU time). The four quantum functions are Bruno's. Its tests compare with `cudaq.observe` on `qpp-cpu` (CI) | Done (M4) |
| `tests/run_ibm_hardware.py` | The two kernels of the hardware runs (§9.8). Spends QPU time; refuses to run without `--yes-spend-qpu-time` | Done (M3) |
| `experiments/` | Scripts behind the **[V]** tags of §9 and of [upstream.md](upstream.md). Not part of the plugin | Evidence |
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
Any gate without a rule (for example `swap`) makes the converter throw; the second
`decomposition` in the pipeline removes the router's swaps before that (§9.7).

**[V]** End to end (second kernel of `tests/run_fake_ibm.py`, 2026-11-09): `rx`, `ry`, `z` and `y`
reach the converter and come out as in the table; the whole ISA circuit equals the kernel up to
global phase (|tr(U†V)|/4 = 1 − 7·10⁻¹⁵). In that builder kernel `u3` arrived already split into
`rz rx rz`, and `s`/`t` arrived as `rz(1.570796)` and `rz(0.7853982)`: π rounded to about 7
digits by CUDA-Q (cause **[U]**). The error is ~3·10⁻⁷ rad, far below hardware noise.

Output ([decision 0006](decisions/0006-send-openqasm3-with-physical-qubits.md)):
`OPENQASM 3.0; include "stdgates.inc"; bit[n] c;`, qubits as `$k`, measurements as
`c[i] = measure $k;`. CUDA-Q's 1-bit `creg`s are merged in program order into `c`.
The qubits of the input are numbered over all `qreg` declarations in order (`QregTable`),
because the runtime sends one register per qubit (§9.7). Label i becomes `$k` with k the IBM
qubit that §9.3 found for it; without that map, label i is sent as `$i`.

## 7. Testing

Free checks first; only the last one spends QPU time.

- `pytest` (CI): the Python prototype with `responses` and `FakeFez`, the fake server
  (`tests/test_fake_server.py`), its simulator (`tests/test_isa_simulator.py`, compared with
  Qiskit on 40 random circuits) and the target pipeline (`tests/test_target_yml.py`, §9.7).
  Never touches IBM.
- Four C++ unit tests (CI, plain `g++`): `test_qasm2_to_isa` (rewrite rules, register
  table), `test_layout` (region, root, numbering, device file, label search),
  `test_chip_data` (IBM JSON, fail-closed rules), `test_result_bits`.
- `tests/fake_ibm_server.py` ([decision 0008](decisions/0008-test-against-a-fake-ibm-server.md)),
  default port 62455:
  - `POST /identity/token`: only a form body with key `test-key`; returns `fake-token`.
  - `GET /api/v1/backends/{name}/configuration` and `/properties`: the real `ibm_fez` wiring
    (156 qubits) with obstacles around the best qubit 62: link 63-64 broken (error 1), qubit
    56 not operational, link 60-61 with an unreadable error in one direction, qubit 84 with
    a stale `sx` error (1). Backend `ibm_no_properties` answers 503 on `/properties`.
  - `POST /api/v1/jobs`: checks `Bearer fake-token`, `Service-CRN: test-crn`, `program_id`
    `sampler`, that every gate is native, that no gate touches an unusable qubit, and that
    every `cz` is on a working link.
  - `GET /api/v1/jobs/{id}`: `Running` twice, then `Completed`.
  - `GET /api/v1/jobs/{id}/results`: one sample per shot, with `num_bits` of the circuit.
    Since M4 the server simulates the circuit it was sent (`tests/isa_simulator.py`: only
    the qubits the circuit touches, at most 24, no noise) and draws the samples with a
    generator seeded per job (`FAKE_IBM_SEED`, default 2026), so a rerun gives the same
    samples. The backend name `ibm_fixed_samples` keeps the old answer, always
    `["0x1","0x1","0x2"]`: the tests of bit decoding need an answer that does not depend
    on the circuit. `FAKE_IBM_LOG_CIRCUITS=1` prints every circuit a job sends.
- `tests/run_fake_ibm.py`: needs the built plugin, from the dev container or from
  `plugin/build_against_wheel.sh` ([development.md](development.md) §6; CI job `plugin`
  runs it on every push since M4). Eight cases against `ibm_fixed_samples`, each prints
  `OK`: Bell pair (`{ 10:2 01:1 }`, which proves the bit reversal), the gate rules, a
  20-qubit GHZ (routing, device file, label search), a kernel that measures out of order,
  the `mapping_file` override, a backend without `/properties` (must stop), `cudaq.observe`
  (refused, and `sample` works after it) and `emulate=True` (refused), see §8 item 7.
  Passed 2026-11-10 **[V]**: GHZ-20 was sent with 28 `cz` and no swap.
- `tests/run_fake_ibm_results.py`: needs the built plugin; CI job `plugin` runs it. It
  starts its own fake server (port 62457, jobs done at the first poll) and runs 25 kernels
  twice: on CUDA-Q's simulator (`qpp-cpu`) and through the plugin against the simulating
  server. The results must agree:
  - 12 random kernels of `x` and `cx` on 2 to 7 qubits, measured in full, in part and out
    of order, or with no `mz`. Each has one right answer, which the script also computes
    with plain bit logic.
  - 5 kernels with qubits no gate touches (one with no gate at all), same check, and a GHZ
    state with an idle qubit in the middle (§8 item 6).
  - GHZ on 3, 8 and 16 qubits: only all-zeros and all-ones, about half each.
  - Two kernels with rotations: the M2 gate-rule kernel, and a 3-qubit kernel with every
    one- and two-qubit gate of the kernel builder, also with `mz` on two qubits and with no
    `mz`. The outcome distributions (20 000 shots) must be within 0.03 of the reference
    (total variation distance; shot noise is about 0.01).

  Passed 2026-11-10 **[V]** with `cudaq` 0.16.0 and 0.16.0.post1; the script takes about 3
  seconds. Planted faults, same day **[V]**: a wrong `ry` rule, a wrong `z` rule, a `cx`
  rule with the Hadamards on the control, a simulator `rz` with half the angle and a
  reversed classical register were each reported. Two limits:
  - The 3-qubit kernel was picked by a search (`experiments/m4_test_kernel_search.py`), so
    that a mistake in any one kind of gate moves the distribution by at least 0.117. A
    first kernel written by hand let the wrong `ry` rule pass: its two `ry` gates
    cancelled the fault.
  - No test of this kind can see the mirror image of a circuit. Changing the sign of every
    `rz` angle at once gives the same probabilities for every outcome (it flips the Y axis
    of every qubit, and a measurement along Z from the state 00...0 cannot tell). Run
    2026-11-10 **[V]**: with that change in the simulator every kernel still passed. The
    unit test of the rules (`test_qasm2_to_isa`, matrices up to a global phase) does see
    it.
- `tests/run_token_expiry.py`: needs the built plugin. Starts the fake server with
  `FAKE_IBM_TOKEN_TTL=12` (every login gets a new token that stops working after 12 s) and
  a job that needs 5 polls, then reports whether the poll survived (§8 item 1). The server
  mode itself is tested in CI (`tests/test_fake_server.py`). Ran 2026-11-10 with the built
  plugin on CUDA-Q 0.16.0 **[V]**: polls 1 to 3 passed, poll 4 got HTTP 401 after 15 s, all
  four with the same token.
- `tests/run_ibm_hardware.py`: real jobs on `ibm_fez`, only with Bruno's go (§9.8).
- Every `set_target("ibm")` in a test must pass the localhost `url` and `iam_url`. A probe
  without them once sent the fake key to IBM's real login (rejected, HTTP 400).
- Not automated yet: missing env vars throw; `Failed` status throws; HTTP 401 gives a clear error.

How to run them: [development.md](development.md) §4.

## 8. Known limits

1. **Token expiry during long queue waits** ([decision 0004](decisions/0004-accept-token-expiry-in-v1.md)).
   `tests/run_token_expiry.py` shows it in half a minute against the fake server
   (tokens of 12 s). Ran 2026-11-10 with the built plugin on CUDA-Q 0.16.0 **[V]**: the
   plugin logged in three times (chip data, job POST, start of the poll loop; with tokens
   shorter than its 60 s refresh margin every `getHeaders()` logs in), then every poll
   carried the third token, and the fourth poll failed with HTTP 401 three seconds after
   that token expired. Not shown against the real service **[U]**: that needs a queue wait
   of about an hour.
2. **One register, Sampler only.** No Estimator, sessions or error mitigation.
3. **`check-ibm` lit test: removed in M4.** It came with the `mock_rest` example, needed a
   CUDA-Q source build and was never run after M1. The fake-server scripts in CI cover
   what it checked (the target loads and a kernel runs), for a local build and for the
   installed wheel.
4. **Plugin vs pip `cudaq` ABI**: a plugin built against the pip wheel loads into pip
   `cudaq` 0.16.0 and 0.16.0.post1 and passes the fake-server cases, on Linux x86_64 and
   aarch64 **[V]** CI job `plugin` (x86_64) and workflow `wheels` (both), 2026-11-11. The
   release wheel is built once, against `cudaq` 0.16.0 with GCC 14.2.1 (the `manylinux_2_28`
   image), while the `cudaq` wheel itself was built with GCC 12.2.1; it still passes with
   both `cudaq` releases, on glibc 2.28 with Python 3.11 and on Ubuntu 24.04 with Python
   3.14. Whether a plugin built in the dev container loads into pip `cudaq`, and macOS:
   **[U]**.
5. **Large circuits may be refused.** The label search (§9.3) gives up after 10^6 steps
   with a clear error, never a wrong placement. Random connected circuits on `ibm_fez`, 40
   cases per cell, refused cases **[V]** `experiments/m3_search_stress.cpp`:

   | Circuit | Labels | 100 | 130 | 150 | 156 qubits |
   |---|---|---|---|---|---|
   | Sparse (tree + 10% of the other links) | device order | 0 | 4 | 0 | 0 |
   | Sparse | shuffled | 0 | 4 | 6 | 7 |
   | Dense (tree + 50%) | either | 0 | 0 | 0 | 0 |

   Worst time about 1.2 s. Routed circuits are sparse, so: fine up to about 100 qubits.
6. **Fixed in M4: a qubit no gate touches keeps its bit.** Until 2026-11-10 the pipeline had
   the `dqe` pass (taken over from `iqm.yml`), which removes an idle qubit before the
   missing measurements are added **[V]** `Compiler.cpp:421, 467-473`: a 4-qubit kernel
   with one idle qubit returned `111` where the simulator returns `1011` **[V]** built
   plugin. CUDA-Q's specification allows that ("may not appear in the implicit measurement
   results" **[V]** `algorithmic_primitives.rst`; `oqc` and `anyon` do the same
   **[V]** `experiments/m3_idle_qubit.py`), but it surprises. The pipeline now has no `dqe`:
   every allocated qubit is placed on the chip and measured, so an idle qubit costs one
   chip qubit and one readout. Six kernels in `tests/run_fake_ibm_results.py` check it
   **[V]** 2026-11-10. GHZ-20 is still sent with 28 `cz`.
7. **`emulate=True` and `cudaq.observe` are refused with a clear error** (M4, Bruno's
   decisions D6 and D7 in [m4-spec.md](m4-spec.md)).
   - `emulate=True`: `initialize` throws when the target is set, before it reads
     credentials or talks to a server. Why not supported: in emulation CUDA-Q simulates its
     own compiled kernel and calls none of this plugin's gate rewrite, qubit choice or
     result decoding; and with this target's router the emulated bit order was wrong in a
     test **[V]** m4-spec F5. Before M4 it failed inside CUDA-Q with "Multiple qalloc
     statements found" (`combine-measurements` runs late in emulation **[V]**
     `Compiler.cpp:307-319`), after logging in to IBM.
   - `cudaq.observe`: `getPipelineSubstitutions` throws. It is the first plugin code CUDA-Q
     calls for a launch, before it compiles the kernel, and `cudaq::getExecutionContext()`
     (`common/ExecutionContext.h`, exported by `libcudaq-common.so`) tells it the call is
     an `observe` **[V]** built plugin, 2026-11-10: a 2-qubit kernel, a kernel with an idle
     qubit and the 5-qubit star that used to crash Python (m4-spec F6) all get the error,
     no job is sent, and `sample` works afterwards. Expectation values can be computed
     from `sample` counts: `examples/expectation_from_samples.py` shows how (`h` before
     `mz` for X, `sdg` then `h` for Y, then the average of the parity) **[V]** 2026-11-11:
     its 38 tests agree with `cudaq.observe` on `qpp-cpu`, and through the built plugin
     against the simulating fake server a Bell pair gave `<ZZ>` = +1, `<XX>` = +1,
     `<YY>` = -1 (run by hand, not in CI).
8. **The label search takes the first placement that fits, not the cheapest**, and **the
   logged forecast is an upper bound** (§9.8).

## 9. Routing

IBM runs a 2-qubit gate only on a wired pair, and some qubits and links work badly. Routing
makes any kernel fit: CUDA-Q inserts swaps for a device graph we give it, and the helper
maps the result onto IBM qubits. Why this split: decisions
[0001](decisions/0001-cudaq-routes-helper-rewrites-gates.md) and
[0009](decisions/0009-route-with-cudaq-then-assign-qubits.md).

### 9.1 How CUDA-Q routes

- The YAML pass `qubit-mapping{device=file(F)}` routes the kernel on a device graph read from
  file `F`. It adds swaps and records the final layout **[V]** `Mapping.cpp:3315-3366`.
- Its default start layout is identity (virtual `v` on device qubit `v`) with no layout
  search **[V]** `Passes.td:1376-1383`. Options `placement=auto|greedy` and `search=sabre`
  exist; we use `placement=auto search=sabre` (§9.6).
- A device graph with unreachable qubits fails with the default options: "cannot place
  two-qubit interaction ... on disconnected device topology" **[V]** experiment, 2026-11-09.
  So we give it one connected part only.
- The reference is IQM **[V]** `IQMServerHelper.cpp:450-600`, `iqm.yml`: fetch the
  architecture in `getPipelineSubstitutions`, keep the usable qubits, write a temporary
  device file, return `{"%QPU_ARCH%": path}`, with a `mapping_file` override for tests.
- Our pipeline (`plugin/targets/ibm.yml.in`), in order: decompose into the textbook gates;
  `combine-measurements` (§9.5); `qubit-mapping`; decompose again, because the router adds
  `swap` gates (§9.7); `regtomem`; print OpenQASM 2.

### 9.2 What reaches the helper: labels, not device qubits

**[V]** pip `cudaq` 0.16.0, `experiments/m3_qubit_ids.py`. A 5-qubit GHZ on a star device
whose centre is qubit 9:

| | Result |
|---|---|
| `mapping_v2p` | `[9, 1, 2, 3, 4]`: routing used device qubits {0,1,2,3,4,9} |
| QASM2 from `cudaq.translate` | `qreg var0[6]`, and qubit 9 is printed as `var0[5]` |
| QIR (`qir-base`, as OQC uses) | also `5`, not `9` |

`regtomem` packs the used qubits into labels 0..m-1 (`RegToMem.cpp:560-590` makes one new
`alloca` per used wire). With the identity start the packing keeps device order; with
`placement=auto` the labels follow the kernel's qubits. Neither can be relied on, and the
layout is not passed to the helper: only `mapping_reorder_idx` is (`KernelExecution.h:29`
-> `Executor.cpp:54` -> `ServerHelper.cpp:39`), not `mapping_v2p` **[V]**.

Routing leaves 0..n-1 often: in 20 of 30 circuits on the `ibm_fez` wiring, including a
20-qubit GHZ chain **[V]** `experiments/m3_routing.py`. Giving the router only a spanning
tree reduced this but did not stop it.

OQC and Anyon also route and then run `regtomem`, and their generated code shows the same
loss **[V]** `experiments/upstream_layout_lost.py`, `upstream_layout_sweep.py`. What their
servers do with it is **[U]**. Upstream item #5 in [upstream.md](upstream.md).

### 9.3 From labels to IBM qubits

After packing, each label is still one device qubit; only which one is lost. A circuit is a
list of gates on labels, so running it through any one-to-one map to chip qubits where every
2-qubit gate lands on a link is the same computation (noise aside); borrowed qubits start
in |0> wherever they sit.

`assignQubits` (`Layout.h`) finds such a map with a depth-first search: each label tries
the device qubit with its own number first, then low numbers. It returns a valid map or
throws; never a wrong one. 300 of 300 simulated cases in `plugin/tests/test_layout.cpp`, and
every routed circuit tried, in at most a few hundred steps. Limits: §8 items 5 and 8.

### 9.4 Numbering the chip

`Layout.h`, in order ([decision 0012](decisions/0012-root-by-best-region-best-first-numbering.md)):

1. **Usable region.** Drop links that are not operational or have a cz error of 1, and
   links of qubits that are not operational or have an `sx` or `x` error of 1 (§3.7). IBM
   lists each link twice; if either direction is bad the link is dropped, otherwise it
   keeps the worse error. Keep the largest connected part.
2. **Root.** For every usable qubit, grow a patch of 10 qubits best-first and multiply
   (1 - readout error) over its qubits and (1 - cz error) over the link each one was
   reached by: the forecast. The root is the qubit with the best forecast. Roots inside the
   same patch tie; then the lower readout error wins, then the lower IBM id.
3. **Best-first numbering.** Label 0 is the root. The next label goes to the qubit, linked
   to a numbered one, with the lowest readout error + cz error of its best link into the
   numbered set. So every prefix 0..k-1 is connected (each label has a neighbour with a
   smaller label), and a badly measured qubit is numbered late.
4. **Device file** in IQM's text format, with our labels. `layout.ibmId[label]` is kept to
   translate back.

The kernel size is not known at this point (`getPipelineSubstitutions` gets no kernel), so
the patch size is fixed. With `placement=auto` the router's own start is the most central
qubit of the device file, not label 0 **[V]** `Mapping.cpp:205-222`. That does not matter:
only the packed labels reach us, and §9.3 places them near label 0.

### 9.5 Result bit order

CUDA-Q's result lists the measured qubits sorted by allocation order **[V]**
`Mapping.cpp:3330`. IBM returns bits in the order of the measure statements. With a plain
pipeline, kernels that measure out of order (`mz(q[2]); mz(q[0])`) or measure registers in
reverse came back wrong: 11 of 120 random kernels, with any router options **[V]**
`experiments/m3_bit_order.py`, ground truth `cudaq.sample` on the simulator.

Fix ([decision 0010](decisions/0010-measure-all-then-keep-measured-bits.md)): the pipeline
runs `combine-measurements` before routing (then `expand-measurements`, `cc-loop-unroll`).
The circuit then measures every qubit in allocation order, and `output_names` lists the
qubits the kernel measured; `processResults` keeps those bits (`plugin/ResultBits.h`). 0 of
120 wrong, on path, star, ring and `ibm_fez` graphs, and correct on hardware (§9.8).
`mapping_reorder_idx` does not fit IBM: it assumes results sorted by physical qubit.

### 9.6 Router options

Two-qubit gate counts after routing **[V]** `experiments/m3_routing.py`, `ibm_fez` wiring:

| Kernel | identity, none (default) | identity, sabre | auto, none | auto, sabre (ours) |
|---|---|---|---|---|
| GHZ-5 chain | 10 | 10 | 4 | 4 |
| GHZ-20 chain | 151 | 136 | 34 | 28 |
| 12-qubit ring | 78 | 57 | 12 | 12 |
| 6-qubit star | 14 | 14 | 11 | 11 |

Most of the gain is the placement; sabre adds a little. A swap is 3 `cx`, so GHZ-20 (19
`cx`) needs 3 swaps with our options and 44 with the default.

### 9.7 The OpenQASM the helper receives is not what `cudaq.translate` prints

Found on 2026-11-10 in the first two runs of the built plugin **[V]**:

- After `regtomem` every qubit is its own allocation, and the runtime's OpenQASM emitter
  prints one register per allocation: `qreg var0[1]; qreg var1[1];`, then
  `cx var0[0], var1[0];` (`TranslateToOpenQASM.cpp:160-175`). `cudaq.translate(...,
  "openqasm2")` runs extra passes first (`QPU.cpp:98-134`) and prints one register,
  `qreg var0[2];`; the runtime path does not (`RuntimeMLIR.cpp`, "qasm2" translation).
  Hence `QregTable` (§6).
- The router's `swap` gates reached the helper; `cudaq.translate` had turned them into
  `cx`. Hence the second `decomposition` after `qubit-mapping`, as `iqm.yml` repeats its
  gate-set mapping there.

Guard: `tests/test_target_yml.py` compiles kernels with the pipeline of `ibm.yml.in`, then
with the gate-changing passes of the runtime's OpenQASM translation (`Pipelines.cpp`,
`addPipelineTranslateToOpenQASM`), and checks that only gates with a rewrite rule remain.

Rule for this project: an experiment with pip `cudaq` shows what the passes do, not what
the plugin receives. Check the compiled kernel, not `cudaq.translate`, and count a claim as
verified only after a run of the built plugin.

### 9.8 What the hardware runs showed

Two runs on `ibm_fez` on 2026-11-10, two hours apart on the same calibration, with
`tests/run_ibm_hardware.py`; pass marks set by Bruno before each run **[V]**.

| | Run 1: old root rule | Run 2: rule of §9.4 |
|---|---|---|
| Root, qubits of GHZ-5 | 114; 112, 113, 114, 115, 99 | 121; 121, 122, 123, 124, 125 |
| GHZ-5, 1000 shots, `00000` + `11111` | 422 + 390 = **81.2%** (mark 75%) | 471 + 434 = **90.5%** (mark 88%) |
| Forecast for those qubits and links | 82.9% | 95.0% |
| `x(q[0]); mz(q[2]); mz(q[0])`, 200 shots, `10` | 196 = **98.0%** (mark 95%) | 196 = **98.0%** |

Run 2 used the plugin built at commit ac3f03a. Each GHZ job: 4 `cz`, no swap, about 7 s
from POST to results with no queue, 1.3 to 1.4 s of it on the chip. The second kernel proves the bit order of §9.5: a wrong order would give `01`.

Full counts. Run 1: `{ 00000:422 00001:21 00010:2 00011:2 00100:1 00111:4 01000:15 01011:1
01101:2 01110:1 01111:48 10000:30 10001:1 10100:3 10110:3 10111:17 11000:6 11011:5 11100:6
11101:9 11110:11 11111:390 }`. Run 2: `{ 00000:471 00001:19 00010:1 00011:8 00100:2 00111:3
01000:1 01011:1 01110:1 01111:12 10000:4 10111:10 11000:3 11010:1 11011:4 11100:2 11101:5
11110:18 11111:434 }`.

Readout errors of the qubits used (calibration measured 2026-11-09 23:54 UTC):

| Run 1 | 112 | 113 | 114 | 115 | 99 |
|---|---|---|---|---|---|
| Readout error | 1.17% | 11.72% | 0.10% | 0.83% | 3.27% |
| **Run 2** | **121** | **122** | **123** | **124** | **125** |
| Readout error | 0.34% | 0.39% | 0.54% | 0.49% | 2.39% |

cz errors: 0.17% to 0.27% on all eight links.

What we learned:

- **The old root rule could not see a bad neighbour.** It scored a qubit by its own numbers
  and numbered breadth-first. Qubit 114 was the best single qubit, but its neighbour 113 had
  a readout error of 11.7% (chip median 1.2%) and got label 1. Hence decision 0012.
- **The gain is real**: 9.3 points, about six times the sampling error of the difference.
- **The forecast ranks regions correctly but is too high**: 1.7 points in run 1 (inside
  the sampling error), 4.5 points in run 2 (well outside). Not in the model: 15 `sx` gates,
  idle time while the chain is built, measuring five qubits at once, and calibration values
  14 hours old. Which matters most is **[U]**.
- **The label search is first-fit.** In run 2 the fifth qubit was 125, number 14 in the
  numbering and the worst of the five; `00001` and `11110` are the largest wrong outcomes
  (37 shots). The numbering is 121, 122, 123, 124, 136, 143, ...; 136 hangs off 123, not
  124, so label 4 could not sit on it and took the first neighbour of 124 that was free.
  The chain 121, 122, 123, 136, 143 also fits **[V]** `tests/data/ibm_fez_coupling.txt` and
  forecasts about 96.5% instead of 95.0% **[U]** (two of its cz errors assumed at 0.25%).
- **Where qubit 113's error went, a hypothesis [U].** In run 1, a readout flip of 113 alone
  (`01000`, `10111`) shows in 32 shots, far below 11.7%. But `readout_error` also counts
  shots where the qubit did not start in 0 (§3.7), and 113's two values were almost equal
  (12.3% and 11.1%), unusual for a pure measurement error. A qubit 113 that starts in 1
  flips every qubit after it in the chain: `01111` and `10000`, 78 shots, of which about 12
  are expected from qubit 112's own readout. Together about 10%. A test that would settle
  it: measure 113 alone with and without an `x`, and compare with a kernel that resets it
  first.
