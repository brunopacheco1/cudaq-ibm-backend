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
| `tests/run_fake_ibm_results.py` | Result checks through the built plugin: 26 kernels against CUDA-Q's own simulator (§7). In CI | Done (M4) |
| `tests/run_fake_ibm_errors.py` | Input checks and error messages through the built plugin: 12 cases, some with a fault in the fake server (`FAKE_IBM_FAULT`, §7). In CI | Done (quality step 1) |
| `tests/gate_rule_kernel.py`, `tests/run_ibm_hardware_gates.py` | A 10-qubit kernel of `rx`, `ry`, `z`, `y` and `u3` with one certain answer: a wrong rewrite rule leaves a known qubit at about half or flips it (§7). The script sends it to real hardware (spends QPU time) or, with `--fake`, to the fake server | Done; ran on `ibm_fez` 2026-11-11, all ten qubits pass (§9.8 run 4) |
| `examples/expectation_from_samples.py`, `tests/test_expectation_example.py` | Expectation values without `cudaq.observe` (§8 item 7): basis-change gates, `sample`, average of the parity. Prints `<ZZ>`, `<XX>`, `<YY>` and the fidelity of a Bell pair, on the simulator or on IBM (`--target ibm`, spends QPU time). The four quantum functions are Bruno's. Its tests compare with `cudaq.observe` on `qpp-cpu` (CI) | Done (M4) |
| `tests/hardware_trace.py`, `tests/test_hardware_trace.py` | For `run_ibm_hardware_limits.py --trace`: reads the plugin's info log of one job (the `cz` gates sent, the IBM qubit of each result bit) and IBM's calibration data, and prints the links and qubits with the highest errors, what the calibration alone predicts, and where each weak pair was measured. Its tests are in CI | Written 2026-11-12; rehearsed, not yet run on hardware |
| `tests/run_ibm_hardware_limits.py` | Limits on real hardware (§8 item 9): GHZ chains of 5 to 80 qubits, 1 to 1001 `cx` in a row, a NaN angle and, when asked, six jobs without a pause (that part has not run). It measures; there is no pass mark. Spends QPU time, or `--fake` for a free rehearsal | Ran on `ibm_fez` 2026-11-12 (§9.8 run 5) |
| `tests/run_ibm_hardware.py` | The two kernels of the hardware runs (§9.8). Spends QPU time; refuses to run without `--yes-spend-qpu-time` | Done (M3) |
| `experiments/` | Scripts behind the **[V]** tags of §9 and of [upstream.md](upstream.md). Not part of the plugin | Evidence |
| `experiments/limits/` | The limit probes of §8 item 9: `run.py` (runner), `cases_*.py` (the probes), `probe_server.py` (the fake server plus faults, odd chips and Stim for wide circuits), and the report of the last full run | Run by hand, 2026-11-12 |
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
| `z` | `rz(π)` | proven in unit test; right on `ibm_fez` (§9.8 run 4) |
| `y` | `rz(π) x` | proven in unit test; right on `ibm_fez` (§9.8 run 4) |
| `rx(θ)` | `rz(π/2) sx rz(θ+π) sx rz(π/2)` | proven in unit test; right on `ibm_fez` (§9.8 run 4) |
| `ry(θ)` | `sx rz(θ+π) sx rz(π)` | proven in unit test; right on `ibm_fez` (§9.8 run 4) |
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
  starts its own fake server (port 62457, jobs done at the first poll) and runs 26 kernels
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
  - The gate-rule kernel of `tests/gate_rule_kernel.py`: ten qubits, no two-qubit gate,
    two qubits each for `rx`, `ry`, `z`, `y` and `u3`, and one certain answer
    (`1011011110`). It is built for real hardware, where a certain answer is easy to tell
    from noise: each gate is used once on a qubit in 0 and once on a qubit on the equator,
    because one input state cannot show every mistake. With 11 wrong rules planted in
    `Qasm2ToIsa.h`, one at a time, at least one qubit falls to 54% or less each time
    **[V]** `experiments/plant_rule_faults.py`, 2026-11-11, against the fake server. `u3`
    reaches the plugin as `rz`, `rx`, `rz` from a builder kernel, so its two qubits check
    CUDA-Q's split and the `rx` rule, not `ruleU3`.

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
- `tests/run_fake_ibm_errors.py`: needs the built plugin; CI job `plugin` runs it. Twelve
  cases, each in its own process against its own fake server (port 62461); some start the
  server with `FAKE_IBM_FAULT=<name>`, which makes one reply wrong (an HTML login page, a
  status word the plugin does not know, half the samples, ...). Each case checks that the
  call fails or not as expected, that the output holds the expected message, and, where
  the kernel is refused, that no job reached the server. Passed 2026-11-12 **[V]**, about
  45 s; with the plugin of `main` c94ef61 11 of 12 fail (the twelfth, a future saved as
  text, guards against a false warning).
- `tests/run_token_expiry.py`: needs the built plugin. Starts the fake server with
  `FAKE_IBM_TOKEN_TTL=12` (every login gets a new token that stops working after 12 s) and
  a job that needs 5 polls, then reports whether the poll survived (§8 item 1). The server
  mode itself is tested in CI (`tests/test_fake_server.py`). Ran 2026-11-10 with the built
  plugin on CUDA-Q 0.16.0 **[V]**: polls 1 to 3 passed, poll 4 got HTTP 401 after 15 s, all
  four with the same token.
- `tests/run_ibm_hardware.py`: real jobs on `ibm_fez`, only with Bruno's go (§9.8).
- `tests/run_ibm_hardware_gates.py`: the gate-rule kernel as one real job, only with
  Bruno's go; `--fake` rehearses the same script against the fake server for free. Ran
  once on `ibm_fez`, 2026-11-11: all ten qubits pass (§9.8 run 4).
- `tests/run_ibm_hardware_limits.py`: width, depth and bad input as real jobs, only with
  Bruno's go; `--fake` rehearses it for free. Ran once on `ibm_fez`, 2026-11-12 (§9.8
  run 5).
- `experiments/limits/run.py`: 215 probes that look for the edges, not for a pass: what
  is wrong, refused, slow, or hangs (§8 item 9). By hand, not in CI: it takes about 5
  minutes on 4 cores and many probes are meant to fail.
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
   decisions [0018](decisions/0018-refuse-emulate.md) and
   [0019](decisions/0019-no-observe-in-the-first-release.md)).
   - `emulate=True`: `initialize` throws when the target is set, before it reads
     credentials or talks to a server. Why not supported: in emulation CUDA-Q simulates its
     own compiled kernel and calls none of this plugin's gate rewrite, qubit choice or
     result decoding; and with this target's router the emulated bit order was wrong in a
     test **[V]** decision 0018. Before M4 it failed inside CUDA-Q with "Multiple qalloc
     statements found" (`combine-measurements` runs late in emulation **[V]**
     `Compiler.cpp:307-319`), after logging in to IBM.
   - `cudaq.observe`: `getPipelineSubstitutions` throws. It is the first plugin code CUDA-Q
     calls for a launch, before it compiles the kernel, and `cudaq::getExecutionContext()`
     (`common/ExecutionContext.h`, exported by `libcudaq-common.so`) tells it the call is
     an `observe` **[V]** built plugin, 2026-11-10: a 2-qubit kernel, a kernel with an idle
     qubit and the 5-qubit star that used to crash Python (decision 0019) all get the error,
     no job is sent, and `sample` works afterwards. Expectation values can be computed
     from `sample` counts: `examples/expectation_from_samples.py` shows how (`h` before
     `mz` for X, `sdg` then `h` for Y, then the average of the parity) **[V]** 2026-11-11:
     its 38 tests agree with `cudaq.observe` on `qpp-cpu`, and through the built plugin
     against the simulating fake server a Bell pair gave `<ZZ>` = +1, `<XX>` = +1,
     `<YY>` = -1 (run by hand, not in CI).
8. **The label search takes the first placement that fits, not the cheapest**, and **the
   logged forecast is an upper bound** (§9.8).
9. **What the limit probes found** (2026-11-12). `experiments/limits/run.py` runs
   215 probes through the plugin against the fake server: every gate and kernel feature,
   width, depth, the calls around `sample`, a misbehaving server, odd chips, and 340 random
   kernels. Each probe runs in its own process with a time limit; wherever a right answer
   exists it is compared with CUDA-Q's simulator, with Stim, or with the exact value. Every line below is **[V]** by
   [`experiments/limits/report-2026-11-12.md`](../experiments/limits/report-2026-11-12.md)
   (local build, pip `cudaq` 0.16.0) unless tagged otherwise; the probe name is in
   brackets. The released wheel `v0.1.0rc1` with `cudaq` 0.16.0.post1 gives the same
   outcome for every probe but the four of the bug below. The fake chip has no noise: this is about what the plugin
   computes and how it fails, not about what a chip returns.

   **A bug, found and fixed in the same change.** Up to `v0.1.0rc1` a kernel with `mz`
   on 50 or more qubits did not compile: "Could not successfully translate to qasm2"
   (in the log: "'quake.concat' op unable to translate"). Our pipeline turns the
   measurements into one loop over the measured qubits and unrolls it with
   `cc-loop-unroll`, whose default is 50 rounds **[V]** `Passes.td:385`, tag 0.16.0.
   The pass now gets `maximum-iterations=1024`, the limit CUDA-Q itself uses for the
   loops of a kernel; `tests/test_target_yml.py` fails without it
   [`s_x_pattern_with_mz_050`, `s_ghz_chain_with_mz_080`]. Way around with
   `v0.1.0rc1`: leave the `mz` out; `sample` then measures every qubit. The first
   round of probes missed it, because every wide probe was written without `mz`: it
   showed up when the hardware script, which had one, was rehearsed.

   **What holds.**
   - Gates and kernels: all one- and two-qubit gates, controlled rotations, `swap`,
     Toffoli, `ccz`, controlled `swap`, negated controls, `exp_pauli`, custom one- and
     two-qubit unitaries, kernels calling kernels, `cudaq.adjoint`, `cudaq.control`,
     amplitudes as a list (`cudaq.qvector([...])`), arguments (int, float, list), several
     registers, QFT on 8 qubits, Grover on 3, `cz` between every pair of 8 [`g_*`].
   - 340 random kernels of up to 10 qubits and 80 gates, measured in full, in part or not
     at all: none differs from the simulator [`f_*`]. The check can fail: with a wrong
     `z`, `ry` or `y` rule planted in a copy of `Qasm2ToIsa.h`, 3, 25 and 4 of 100 kernels
     differ (run by hand, 2026-11-12).
   - Width: right answers on every usable qubit of the fake chip (153 of 156), for a
     pattern of `x` with and without `mz`, GHZ as a chain and as a star, and 459 random `x`/`cx` between any two
     of 153 qubits (4984 `cz` after routing, about 1.5 s). The wide circuits are checked with
     Stim, an independent stabilizer simulator. One qubit more gives "the circuit needs
     154 qubits but the usable chip has 153" [`s_*`].
   - Depth: 200 000 one-qubit gates (a 9.7 MB job, about a minute), 101 101 `cx` from
     nested loops and 100 001 `cx` from a builder kernel (15 MB jobs, 30 to 45 s)
     [`d_*`]. IBM's own caps are far higher: 5 million two-qubit gates per
     circuit **[V]** IBM "Job limits" guide, read 2026-11-12.
   - Shots from 1 to 10 million (IBM's cap for a Sampler job **[V]** same guide);
     `sample_async`, 20 futures at once, a future saved as text and read back, a list of
     argument sets, 8 Python threads, 6 processes, 3000 jobs in a row (about 22 ms per job; peak memory grows by
     18 MB in a run of 300 jobs and by 25 MB in a run of 3000), switching targets, a good job after a failed one
     [`a_*`]. The API key, the token and the CRN are in no log line, at `info` or `trace`.

   **Answers that are not what the user expects, without an error.**

   | What | What happens | Whose limit | Way around |
   |---|---|---|---|
   | A gate with 3 or more controls (or a rotation with 2) in a kernel without `mz` [`g_x_with_3_controls_no_mz`] | Each bit string has extra bits: the helper qubits CUDA-Q adds to split the gate are measured too | CUDA-Q's compile path for hardware: `ionq`, `quantinuum`, `oqc` and `anyon` do the same with `emulate=True` [`g_other_hardware_targets_in_emulation`] | Write the `mz`; then the answer is right [`..._and_mz_on_all`] |
   | An angle far above 2π [`g_angle_very_large`] | Ten million turns plus half a turn (62831856.2 rad) should give 1 on every shot; it is sent as `rx(6.283186e+07)` and 81% of the shots give 00 on two qubits. CUDA-Q prints angles in OpenQASM 2 with 7 significant digits **[V]** `TranslateToOpenQASM.cpp:64`. Within one turn the error is below 10⁻⁶ rad and no probe sees it [`g_angle_many_digits`] | CUDA-Q | Reduce angles to one turn in the caller |
   | `shots_count=0` [`a_shots_0`] | An empty result and no error. No job is sent: `cudaq.sample` runs the kernel until it has `shots_count` shots, so with 0 it never does **[V]** `python/cudaq/runtime/sample.py:174`, tag 0.16.0; the probe's server sees no POST, and on `ibm_fez` the call returned in 0 s (§9.8 run 5) | CUDA-Q | |
   | Named measurement results (`a = mz(q[0])`) [`g_two_named_measurement_registers`] | The counts are right, but only the register `__global__` comes back | Plugin: `processResults` builds one register | |
   | `get_sequential_data()` [`a_result_methods`] | Empty: the order of the shots is dropped, though IBM sends it | Plugin | |
   | `noise_model=`, unknown target arguments | CUDA-Q refuses a noise model; an unknown target argument is accepted silently | CUDA-Q | |

   **Not supported; the error does not say why.**

   | What | Error | Cause | Way around |
   |---|---|---|---|
   | `mx` [`g_mx`] | `Remote rest platform Quake lowering failed` (above it: "'quake.mx' op unsupported mid-circuit measurement") | In our pipeline; the four shipped targets above compile it. Which pass **[U]** | `h` then `mz` [`g_x_basis_by_hand_h_then_mz`] |
   | `my` [`g_my`] | `unsupported gate 'sdg' (no rewrite rule yet)` | The `sdg` of the basis change is added after the decomposition, so it reaches the converter, which has no rule for `s`, `sdg`, `t`, `tdg` | `sdg`, `h`, then `mz`, as in `examples/expectation_from_samples.py` |
   | One loop of 1024 rounds or more [`d_one_loop_of_1024_rounds`] | `Could not successfully translate to qasm2` | CUDA-Q unrolls at most 1024 rounds per loop **[V]** `LoopUnroll.cpp:135-138`, and in 0.16.0 not a loop of exactly the limit (NVIDIA/cuda-quantum#5815, closed) | Nested loops, or a builder kernel |
   | `2.0 ** j` with a loop variable [`g_float_power_of_a_loop_variable`] | Same message | CUDA-Q does not fold the power before the OpenQASM printer ("'math.fpowi' op unable to translate") | Halve a variable in the loop; `2 ** j` with integers works up to 2⁶² |
   | A `cudaq.State` as kernel argument [`g_state_from_cudaq_state_object`] | Same message | CUDA-Q: "cannot perform state preparation synthesis on arguments to the kernel" | Pass the amplitudes as a list |

   **Changed after the probes** (quality step 1, 2026-11-12). These rows were in the two
   tables above; each now has a case in `tests/run_fake_ibm_errors.py` (§7), which fails
   on the plugin before this change **[V]**.

   | What | Before | Now |
   |---|---|---|
   | An angle that is NaN or infinite, also from `2 ** 64` in a kernel [`g_angle_nan`] | The job was sent with `rz(nan)`. IBM accepts the POST and ends the job as `Failed` with "Undefined symbol 'nan'" **[V]** §9.8 run 5. CUDA-Q's own simulator aborts Python on it | Refused before any job is sent: "gate 'rx' has an angle that is not a finite number, in: rx(nan) var0[0];" (`Qasm2ToIsa.h`) |
   | `reset` [`g_reset`] | `cannot parse QASM line: reset var0[0];x var1[0];` (CUDA-Q prints it without a line break **[V]** `TranslateToOpenQASM.cpp:353`) | "reset is not supported on the 'ibm' target yet". Still no rule for it |
   | A reply to our own requests that is not JSON, or lacks a field [`e_login_answers_html`, `e_status_missing`] | The JSON library's own message, e.g. `parse error at line 1, column 1` | The message names the request: "the reply to GET /backends/ibm_fez/configuration is not JSON (...)". The login reply is never shown (it may hold the token). The job POST and its reply are CUDA-Q's code, so a non-JSON reply there still gives the library's message |
   | `url` or `iam_url` ending in `/` | HTTP 404 | Accepted: the trailing `/` is removed |
   | A `mapping_file` that is not a device file | "no chip layout; the kernel was not compiled for 'ibm'" | "mapping_file ... has no qubits", with an example line |
   | The server returns fewer samples than shots [`e_results_half_the_samples`] | Returned as it is, silently | Returned as it is, with a warning in the log: "job ... returned 10 samples for 20 shots". Not an error: the samples are real and the job is paid for |
   | A job status word the plugin does not know [`e_status_unknown_word`] | Polled every 5 s for ever, silently | Same, with one warning in the log naming the word. Not an error: an error would end `sample` while the job runs on and is billed |

   Refused with a clear error, by CUDA-Q or by us: `observe`, `emulate=True` (item 7),
   `get_state`, `cudaq.run` and any `if` on a measurement, `explicit_measurements`, a
   kernel wider than the usable chip, missing credentials, a chip without working links.
   `cudaq.draw` returns an empty text with a warning.

   **When IBM misbehaves** [`e_*`, `c_rate_limit_*`].
   - **No second try.** One HTTP 500 on the job POST or while waiting ends `sample` with
     an error; in the second case the job runs on and is billed. IBM's own client tries five times on 500, 502, 503, 504 and
     52x **[V]** `qiskit-ibm-runtime` 0.52.0, `api/session.py`. The POST and the wait
     loop are CUDA-Q's code (`Executor.cpp`, `Future.cpp`). Way around: `sample_async`,
     keep `str(future)`, and ask a future rebuilt from that text again
     [`e_poll_500_once_then_ask_again`].
   - **IBM takes 5 jobs per minute per user** **[V]** IBM REST reference, "Run a job",
     read 2026-11-12. One `sample` is one job. With a 6th refused (HTTP 429, as the probe
     server fakes it; IBM's real reply **[U]**), `cudaq.sample(kernel, [8 argument sets])`
     fails and the five answers already paid for are lost; with `sample_async` the first
     five futures still give their results.
   - **No time limit.** A job that stays `Queued`, or a status word the plugin does not
     know, is polled every 5 s for ever [`e_job_never_finishes`, `e_status_unknown_word`];
     an unknown word now gets one warning in the log (see above).
     The words IBM's client knows are the five we handle: Queued, Running, Completed,
     Failed, Cancelled **[V]** `runtime_job_v2.py`, same version. A slow POST (75 s) is
     waited for; whether anything ends that wait **[U]**. The login gives up after 30 s.
   - `Failed` and `Cancelled` jobs, HTTP 401, 404, 429 and 500 on any request, a wrong
     key or CRN, unreadable chip data, samples that are not hex or too wide: an error
     with the status or the reason in it.
   - A chip whose two-qubit gate is not `cz` (IBM's Eagle chips use `ecr`): the plugin
     reads only `cz` errors, finds none and stops with "no cz error rate for any link.
     The 'ibm' target supports backends whose 2-qubit gate is cz"
     [`c_chip_whose_2_qubit_gate_is_ecr`].

   **Speed.** The plugin's own work is small: for 10 qubits and 1000 layers (4500 `cx`,
   a job of 1.4 MB) the label search took 20 ms and the rewrite 60 ms, of 18 s in all;
   17 s were CUDA-Q's compiler passes **[V]** `info` log, by hand, 2026-11-12. That
   time grows faster than the circuit: 0.4 s for 100 layers, 2 s for 300. Routing cost
   on `ibm_fez`'s wiring: GHZ on 153 qubits as a chain 542 `cz` (152 `cx` written),
   as a star 1361; QFT on 32 qubits 2861, on 100 qubits 34 917 (a 5.6 MB job, 7 to 9 s).

   **What these probes cannot tell.** Where noise drowns the answer, and what IBM itself
   answers. `tests/run_ibm_hardware_limits.py` asks a real chip; it ran on `ibm_fez` on
   2026-11-12 (§9.8 run 5): a GHZ chain holds to about 20 qubits (64%) and breaks at one
   weak pair by 40 (10.5%); 11 `cx` in a row give 92.9%, 101 give 43.8%; IBM fails a job
   with `rz(nan)` with a clear reason. Still open: IBM's answer to a 6th job in a minute
   (`--parts rate-limit`, not run);
   token expiry in a real queue (item 1); `nvq++` and macOS (never run); chips other
   than `ibm_fez`.

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
runs `combine-measurements` before routing (then `expand-measurements`, `cc-loop-unroll`
with `maximum-iterations=1024`: the default of 50 rounds stopped kernels with `mz` on 50
or more qubits, §8 item 9).
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

**Run 3, 2026-11-11, from the released wheel.** The first run that did not use a local
build: wheel `cudaq-ibm` 0.1.0rc1 (aarch64) from the GitHub Release, next to pip `cudaq`
0.16.0.post1 in a plain `python:3.12-slim` container, started by Bruno
([development.md](development.md) §7). `examples/expectation_from_samples.py --target ibm`
sent three jobs of 1000 shots, one Bell pair per measurement basis; pass mark set before
the run: signs +, +, - and fidelity of at least 0.85 **[V]**.

| Term | Counts | Value |
|---|---|---|
| `<ZZ>` | `00`:494 `11`:485 `01`:14 `10`:7 | +0.958 ± 0.009 |
| `<XX>` | `00`:503 `11`:464 `01`:17 `10`:16 | +0.934 ± 0.011 |
| `<YY>` | `01`:505 `10`:465 `00`:18 `11`:12 | -0.940 ± 0.011 |
| Fidelity with the ideal Bell pair, (1 + ZZ + XX - YY) / 4 | | **0.958 ± 0.005** |

What it shows: the installed wheel logs in over TLS with the certificate file that pip
`cudaq` ships (§2.3), and the basis changes of the example (`h` for X, `sdg` then `h` for
Y) are right on a chip; two qubits without entanglement cannot pass 0.5. Limits: one run,
one 2-qubit kernel; the ± is shot noise only, and readout errors are inside the numbers.
Which qubits the pair ran on was not logged. Cost **[V]** IBM dashboard after the run
(Bruno): the nine jobs this project has sent since 2026-11-05 (1 + 1 + 4 + these 3) used
0.29 of the 10.00 "RUs" of the Open plan's cycle together; what one RU is, the screen does
not say **[U]**.

**Run 4, 2026-11-11, the gate rules.** One job of 1000 shots with
`tests/run_ibm_hardware_gates.py --qubit-mark 0.85`, started by Bruno in the same plain
container as run 3 (wheel 0.1.0rc1, aarch64), 22:45 UTC. The kernel is the gate-rule
kernel of §7: ten qubits, no two-qubit gate, expected answer `1011011110`. Pass mark set
before the run: every qubit gives its expected bit in at least 85% of the shots **[V]**.

| Label | IBM qubit | Sequence | Expects | Share right |
|---|---|---|---|---|
| 0 | 121 | `rx`, twice a quarter turn | 1 | 98.1% |
| 1 | 122 | `rx`, from the Y axis | 0 | 99.7% |
| 2 | 123 | `ry`, twice a quarter turn | 1 | 98.6% |
| 3 | 124 | `ry`, then `h` | 1 | 99.0% |
| 4 | 136 | `z` on 0 | 0 | 99.4% |
| 5 | 143 | `z` on + | 1 | 99.5% |
| 6 | 142 | `y` on 0 | 1 | 99.0% |
| 7 | 144 | `y` on + | 1 | 99.3% |
| 8 | 145 | `u3`, twice | 1 | 97.5% |
| 9 | 146 | `u3`, from + | 0 | 99.5% |

Whole string right in 900 shots (90.0%; the product of the ten shares is 90.1%). The four
largest wrong outcomes are single flips: of label 8 (23 shots), 0 (18), 2 (13) and 3 (10).

What it shows: the rules for `rx`, `ry`, `z` and `y` are right on a chip, for the faults
the kernel was built to catch. Each of the 11 wrong rules planted in §7 leaves a qubit at
54% or less; here the lowest qubit is at 97.5%. Limits:

- `ruleU3` did not run. From a builder kernel `u3` reaches the plugin as `rz`, `rx`, `rz`
  (§6), so labels 8 and 9 test CUDA-Q's split and the `rx` rule at two more angles.
- A few fixed angles, one run, one chip, one calibration.
- An outcome test cannot see the sign of every `rz` flipped at once: all probabilities
  stay equal. The unit tests compare matrices up to a global phase and do see it (§5).
- The plugin logged a forecast of 91.9% for these ten qubits. That number multiplies
  readout and link errors (§9.4), and this kernel uses no link, so it is not a forecast
  of this result; measured 90.0% ± 0.9 (shot noise).
- The three qubits that expect 0 average 99.5%, the seven that expect 1 average 98.7%.
  A qubit in 1 can decay during readout, which would explain it; with three against
  seven qubits and one run this is a guess **[U]**.

**Run 5, 2026-11-12, limits.** `tests/run_ibm_hardware_limits.py --yes-spend-qpu-time`,
started by Bruno at 07:25 UTC (the jobs were created from 07:25 to 07:30 **[V]** IBM's job
list) in the plain container (wheel 0.1.0rc1, aarch64): nine
jobs of 1000 shots and one of 10. No pass mark: this run measures where the answers stop
being usable. The qubits the plugin chose were not logged **[U]**. The first job waited
196 s in the queue, the others took 7 to 20 s. IBM's job list shows ten jobs: nine
completed at 0.03 RUs each, whatever the circuit, so 0.27 RUs for the run, and one failed
**[V]** screenshots, 2026-11-12. What one RU is, the page does not say **[U]**.

GHZ as a chain, `h` then `cx` from each qubit to the next. "Neighbours agree" is the share
of shots in which qubits i and i+1 of the chain give the same bit; 50% means no relation.

| Qubits | All 0 or all 1 | Neighbours agree, mean | Weakest pair |
|---|---|---|---|
| 5 | 93.0% | 97.8% | (3,4) 97.2% |
| 10 | 81.4% | 96.6% | (0,1) 95.7% |
| 20 | 64.4% | 96.1% | (7,8) 94.5% |
| 40 | 10.5% | 91.0% | (19,20) 54.6% |
| 80 | 3.3% | 88.8% | (22,23) 69.8% |

Two qubits, `x` on the first, then an odd number of `cx`: the right answer is `11`.

| `cx` | `11` | `10` | `01` | `00` |
|---|---|---|---|---|
| 1 | 96.6% | 1.3% | 1.6% | 0.5% |
| 11 | 92.9% | 3.1% | 2.4% | 1.6% |
| 101 | 43.8% | 38.6% | 7.9% | 9.7% |
| 1001 | 12.9% | 11.6% | 30.5% | 45.0% |

What it shows:

- **Width: usable to about 20 qubits, and then one weak spot ends it.** From 5 to 20
  qubits each added qubit costs 2.3% to 2.6% of the shots. At that rate 40 qubits would
  give about 40%; the run gave 10.5%. One pair, (19,20), agrees in 54.6% of the shots:
  the chain is cut there, and the two halves are close to unrelated. Why **[U]**: the
  run did not log the qubits. Two candidates. A link with a high `cz` error is still
  "usable": §9.4 step 1 drops only an error of exactly 1, and the router does not look
  at errors. Or the two qubits are far apart on the chip and the router joined them
  with many swaps.
- **Depth: 11 `cx` are fine, 101 are not.** From 1 to 11 `cx` each one costs 0.4% of the
  shots. At that rate 101 would give about 65%; the run gave 43.8%. The loss is not
  spread over the wrong answers: `10` (control right, target wrong) has 38.6%. An error
  that points the same way in every `cx` adds up over 101 equal gates instead of
  averaging out; that would explain it, and it is a guess **[U]**. The product of
  per-gate errors is too hopeful for a circuit that repeats one gate.
- **1001 `cx` is below chance.** `11` has 12.9%, less than the 25% of noise that hits
  all four answers alike, and `00` has 45.0%: the first qubit reads 0 in 75.5% of the
  shots. Qubits lose their energy during a circuit this long and end in 0 (the duration
  was not measured **[U]**).
- **A NaN angle costs a job, not a result.** IBM accepts the POST and ends the job as
  `Failed`; the plugin reports IBM's reason: `IBM job ended with status FAILED: Job not
  valid. Error loading QASM circuit with the standard Qiskit loaders: "6,3: Undefined
  symbol 'nan'.` after 7 s. IBM's page for that job: status code 1603, pending 1 s, time on
  QPU 0 s, usage 0.00 RUs ("not yet finalized" when read) **[V]** screenshot.
- `shots_count=0` returned an empty result in 0 s: CUDA-Q sends no job (§8 item 9). IBM's
  job list agrees: ten jobs, not eleven.
- The rehearsal before this run did not pass: the container had no Stim, so the fake
  server answered HTTP 500 for 20, 40 and 80 qubits. The real run started anyway,
  because the recipe gave both commands in one block. Since then the rehearsal skips
  what it cannot simulate and says so, and [development.md](development.md) §4 gives
  the real run its own block.
- Since this run the script also lists every pair that agrees in less than 90% of the
  shots. One weak pair means a cut between two qubits; two weak pairs side by side
  mean the qubit between them.
