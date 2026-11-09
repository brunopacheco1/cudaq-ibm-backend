# M3 spec: routing

Date: 2026-11-09. Status: **choices made (§3), code in review; review fixes done, three
proposals wait for Bruno (decision 0009 items 3-5)**. Deleted when M3 is done
(facts go to [architecture.md](architecture.md), choices to [decisions/](decisions/)).
Reader: Bruno.
Tags: **[V]** verified (source given), **[U]** unverified. CUDA-Q file references are in the
`0.16.0` tag.

## 1. Goal

Today the plugin sends CUDA-Q's virtual qubits 0..n-1 as physical qubits `$0..$n-1`. That only
works when every 2-qubit gate happens to land on a wired pair (the Bell pair on `ibm_fez` 0-1
did). M3 makes any circuit fit the chip's wiring.

Done when ([roadmap.md](roadmap.md)): a 5-qubit GHZ runs on hardware, and a 20-qubit GHZ is
accepted by the fake server, which then checks every `cz` against the real coupling map.

## 2. What we found

### 2.1 How routing works in CUDA-Q

- The YAML pass `qubit-mapping{device=file(F)}` routes the kernel on a device graph read from
  file `F`. It adds swaps and records the final layout **[V]** `Mapping.cpp:3315-3366`.
- Its default start layout is **identity** (virtual `v` on device qubit `v`), with no layout
  search **[V]** `Passes.td:1376-1383` (`placement="identity"`, `search="none"`). Options
  `placement=auto|greedy` and `search=sabre` exist.
- A device graph with qubits that cannot be reached fails: "cannot place two-qubit
  interaction ... on disconnected device topology" **[V]** our experiment, 2026-11-09. So the
  graph must be pruned first.
- The helper fills `%PLACEHOLDER%` in the YAML at every compile through
  `getPipelineSubstitutions` **[V]** `BaseRemoteRESTQPU.h:225-229`.

### 2.2 How IQM does it (the reference)

**[V]** `IQMServerHelper.cpp:450-600`, `iqm.yml`:

1. `getPipelineSubstitutions` fetches the chip's architecture over REST.
2. It keeps only qubits that can do every operation, numbers them 0..k-1, and keeps a
   name map (`qubitNameMap`).
3. It writes a temporary device file and returns `{"%QPU_ARCH%": path}`. Override for
   tests: `mapping_file` target argument or the `IQM_QPU_QA` variable.
4. The YAML runs `qubit-mapping{device=file(%QPU_ARCH%)}` and later `regtomem`.
5. `initialize` calls `parseConfigForCommonParams` so `processResults` can apply
   `reorderIdx` (results come back in physical order; issue #4621 in the comment).

### 2.3 What reaches our helper

- Only `mapping_reorder_idx` is passed on (`KernelExecution.h:29` → `Executor.cpp:54` →
  `reorderIdx.<task>` → `ServerHelper.cpp:39`). `mapping_v2p` (the layout) is **not** **[V]**.
- Our `processResults` does not apply `reorderIdx` yet **[V]** `IBMServerHelper.cpp`.

### 2.4 The blocker: `regtomem` renumbers the qubits

**[V]** experiment with pip `cudaq` 0.16.0, reproducible with
[`experiments/m3_qubit_ids.py`](../experiments/m3_qubit_ids.py). A 5-qubit GHZ on a star
device whose centre is qubit 9:

| | Result |
|---|---|
| `mapping_v2p` | `[9, 1, 2, 3, 4]`: routing used device qubits {0,1,2,3,4,9} |
| QASM2 we receive | `qreg var0[6]`, and qubit 9 is printed as `var0[5]` |
| QIR (`qir-base`, as OQC uses) | also `5`, not `9` |
| Before `regtomem` (`wireset-to-profile-qir`) | the id is still `9`, but our QIR translation of that form failed (cause **[U]**) |

So `regtomem` packs the used qubits into 0..m-1 (`RegToMem.cpp:560-590` makes one new
`alloca` per used wire). With the identity start the packing keeps device order; with
`placement=auto` the labels follow the kernel's qubits, so neither order can be relied on. If routing uses device qubits that are not 0..m-1, the ids we
receive are wrong, and we cannot rebuild them: the layout is not passed to us (§2.3).
OQC and Anyon also route and then run `regtomem`, so they may have the same problem **[U]**:
not tested on their devices. This is the upstream item #5 in [upstream.md](upstream.md),
now with a small reproduction.

### 2.5 IBM side

- `GET /v1/backends/{name}/configuration` returns `n_qubits`, `coupling_map` (pairs) and
  `basis_gates` **[V]** the Python prototype uses it (`src/cudaq_ibm/client.py`,
  `isa.py`).
- `coupling_map` lists each pair in both directions (352 entries for 176 links) **[V]**
  qiskit-ibm-runtime 0.52.0 FakeFez snapshot `conf_fez.json`.
- `GET /v1/backends/{name}/properties` returns `qubits[i]` as a list of `{name, value}`
  (`readout_error`, `T1`, ...) and `gates[]` entries `{gate, qubits, parameters}` with
  `gate_error` **[V]** `props_fez.json`, `qiskit_ibm_runtime/api/rest/cloud_backend.py`.
- Broken links: 7 cz pairs have `gate_error` = 1 in the snapshot **[V]**. An optional
  `operational` parameter (0/1) marks down qubits or gates; missing means working **[V]**
  `backend_properties.py:338-352, 461-472`. Whether today's real `ibm_fez` reply uses both is
  **[U]** until the first real run.

### 2.6 Routing borrows qubits often

**[V]** [`experiments/m3_routing.py`](../experiments/m3_routing.py) and a 30-circuit sweep on
the `ibm_fez` wiring, numbered breadth-first: routing used a device qubit outside 0..n-1 in
20 of 30 circuits, including a 20-qubit GHZ chain. Giving the router only a spanning tree
reduced this but did not stop it. So the D1-A guard would refuse too much (§3, D1).

### 2.7 Any valid assignment of labels works

After packing, each label is still one device qubit; only which one is lost. A circuit is a
list of gates on labels, so running it through any one-to-one map to chip qubits where every
2-qubit gate lands on a link is the same computation (noise aside); borrowed qubits start in
|0> wherever they sit. A depth-first search finds such a map: 300/300 simulated cases in
`plugin/tests/test_layout.cpp`, and every routed circuit above, in at most a few hundred steps.

### 2.8 Result bit order needs one more pass

**[V]** [`experiments/m3_bit_order.py`](../experiments/m3_bit_order.py), ground truth =
`cudaq.sample` on the local simulator. CUDA-Q's result lists the measured qubits sorted by
allocation order (`Mapping.cpp:3330`). Our first pipeline gave the bits in measure-statement
order, which is wrong when a kernel measures out of order (`mz(q[2]); mz(q[0])`) or measures
registers in reverse: 11 of 120 random kernels. (An earlier version of the experiment only
measured in order and wrongly found no problem.)

Fix: run `combine-measurements` before routing (then `expand-measurements`,
`cc-loop-unroll`). The circuit then measures every qubit in allocation order, and
`output_names` lists the qubits the kernel measured; `processResults` keeps those bits
(`plugin/ResultBits.h`). 0 of 120 wrong, on path, star, ring and `ibm_fez` graphs.
`reorderIdx` does not fit IBM: it assumes results sorted by physical qubit.

### 2.9 The router's start layout matters

**[V]** `experiments/m3_routing.py`, root 62: two-qubit gate counts after routing.

| Kernel | `placement=identity search=none` (default) | `placement=auto search=sabre` |
|---|---|---|
| GHZ-5 chain | 10 | 4 |
| GHZ-20 chain | 151 | 28 |
| 12-qubit ring | 78 | 12 |

### 2.10 The search on a nearly full chip

**[V]** stress test (random connected circuits on `ibm_fez`, labels shuffled, budget 10^6
steps): 0 of 40 refused up to 130 labels, 19 of 40 at all 156 (worst 0.36 s). With labels in
device order: 0 of 40 at every size. A refusal is a clear error, never a wrong placement.

### 2.11 Kernels without `mz`

**[V]** A kernel with no `mz` and a qubit it never touches: CUDA-Q drops the idle qubit
before measuring, so its bit is missing (`cudaq.sample` locally shows it as 0). Same before and
after the §2.8 fix. Rare; documented, not fixed.

## 3. Choices for Bruno

### D1. How do we get correct physical ids despite §2.4?

- **A. Prefix layout + guard (recommended for v1).** Number the chip so every prefix
  0..k-1 is connected (breadth-first from a root qubit), and write that as the device file.
  With the identity start layout, a kernel with n qubits starts on 0..n-1, so every one of
  them is used. If routing borrows no extra qubit, the used set is exactly 0..n-1, packing
  changes nothing, and our name map turns 0..n-1 back into IBM ids. The helper can detect the
  bad case: QASM2 `qreg` size > n (a qubit was borrowed). Then it throws a clear error
  instead of sending a wrong circuit. Small, and every step is visible. Cost: some circuits
  are refused (when routing would need a qubit outside 0..n-1).
- **B. Keep ids with `wireset-to-profile-qir`** and convert QIR to OpenQASM 3 in the helper.
  Correct in all cases, but it replaces M2's QASM2 converter and the translation failed in
  our first try (§2.4).
- **C. Fix it upstream** (#5): keep ids through `regtomem`, or pass `mapping_v2p` to helpers.
  The right fix, but slow, and we need M3 before it ships.
- **D. Route in the helper ourselves** ([decision 0001](decisions/0001-cudaq-routes-helper-rewrites-gates.md)
  option B). The most control, the most code.

Recommendation: **A now, C in parallel.** The A guard proves on every job that the ids are
right.

**Chosen (2026-11-09):** after §2.6 showed the guard refuses too much, Bruno chose a variant
of A: keep the prefix layout, and replace the refusal with the assignment search of §2.7.
C in parallel. Recorded in [decision 0009](decisions/0009-route-with-cudaq-then-assign-qubits.md).

Two things A rests on, to check in M3's first step: that every qubit gets at least one
operation (true for measured kernels), and that the device file accepts our relabelled numbers.

### D2. Which qubits form the region (the root for numbering)?

- **A. Lowest-id qubit of the largest connected part** (simple, deterministic).
- **B. A target argument** `initial_qubit=N` (user picks a good area), default as A.
- **C. Noise-aware:** pick the root from `/properties` error rates. Better results, more code.

Recommendation: **B** (A as default). C later, if results matter.

**Chosen:** C, with the score in decision 0009 (mean cz error of the root's links plus its
readout error). The kernel size is unknown when the device file is written, so the score
cannot depend on it.

### D3. When to fetch the configuration

- **A. Every compile**, like IQM (always current; one GET per kernel).
- **B. Once per process**, cached.

Recommendation: **A**, plus an override for tests: `mapping_file` target argument, as IQM.

**Chosen:** A.

## 4. Work split

| Step | Who | Status |
|---|---|---|
| D1-D3 choices | Bruno | Done |
| Numbering rule (breadth-first) and its proof that prefixes stay connected | Bruno (review) | Written in `Layout.h` §3, to review |
| `getPipelineSubstitutions`, fetch, prune, root, numbering, device file, YAML | Claude | Done, unit tested |
| Assignment search, `$k` relabel in the converter | Claude | Done, unit tested |
| Result bit order (`combine-measurements`, `ResultBits.h`) | Claude | Done, unit tested (§2.8) |
| Review fixes (search, one-way broken links, `/properties` parsing, 60 s chip cache, atomic device file) | Claude | Done |
| Fake server: `/configuration`, `/properties`, reject `cz` on unwired or broken pairs | Claude | Done, `tests/test_fake_server.py` |
| Build the plugin, run `tests/run_fake_ibm.py` (incl. GHZ-20, `mapping_file`) | Bruno (container) | Next |
| GHZ-5 on `ibm_fez` | Bruno | After that |
| Upstream issue for §2.4 | Bruno opens, Claude drafts | Draft next |

## 5. Unverified, to settle during M3

1. ~~`coupling_map` direction~~ (§2.5, done). How the real `ibm_fez` marks broken qubits
   today: first real run.
2. Why the `wireset-to-profile-qir` QIR translation failed (§2.4): dropped, D1-B not chosen.
3. Whether IQM, OQC and Anyon are really affected by §2.4 (for the upstream issue).
4. The plugin itself: built only by Bruno; here the helper is syntax-checked against stub
   headers and the pipeline is run with pip CUDA-Q.
