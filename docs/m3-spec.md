# M3 spec: routing

Date: 2026-11-09. Status: **draft, waiting for Bruno's choices in §3**. Deleted when M3 is done
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

So `regtomem` packs the used qubits into 0..m-1 in order (`RegToMem.cpp:560-590` makes one
new `alloca` per used wire). If routing uses device qubits that are not 0..m-1, the ids we
receive are wrong, and we cannot rebuild them: the layout is not passed to us (§2.3).
OQC and Anyon also route and then run `regtomem`, so they may have the same problem **[U]**:
not tested on their devices. This is the upstream item #5 in [upstream.md](upstream.md),
now with a small reproduction.

### 2.5 IBM side

- `GET /v1/backends/{name}/configuration` returns `n_qubits`, `coupling_map` (pairs) and
  `basis_gates` **[V]** the Python prototype uses it (`src/cudaq_ibm/client.py`,
  `isa.py`).
- Whether `coupling_map` lists each pair in both directions, and how IBM marks a broken
  qubit or link (probably `/properties`), is **[U]**. To check with one real call before
  coding.

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

Two things A rests on, to check in M3's first step: that every qubit gets at least one
operation (true for measured kernels), and that the device file accepts our relabelled numbers.

### D2. Which qubits form the region (the root for numbering)?

- **A. Lowest-id qubit of the largest connected part** (simple, deterministic).
- **B. A target argument** `initial_qubit=N` (user picks a good area), default as A.
- **C. Noise-aware:** pick the root from `/properties` error rates. Better results, more code.

Recommendation: **B** (A as default). C later, if results matter.

### D3. When to fetch the configuration

- **A. Every compile**, like IQM (always current; one GET per kernel).
- **B. Once per process**, cached.

Recommendation: **A**, plus an override for tests: `mapping_file` target argument, as IQM.

## 4. Work split

| Step | Who |
|---|---|
| D1-D3 choices; numbering rule (breadth-first order) and its proof that prefixes stay connected | Bruno |
| One real call to `/configuration` (and `/properties`) to settle §2.5 | Bruno (credentials) |
| `getPipelineSubstitutions`, fetch, prune, relabel, device file, name map, YAML change | Claude |
| Guard (`qreg` size), `$k` relabel in the converter, `reorderIdx` in `processResults` | Claude |
| Fake server: serve `/configuration`, reject `cz` on unwired pairs; GHZ-20 run | Claude |
| GHZ-5 on `ibm_fez` | Bruno |
| Upstream issue for §2.4 with `experiments/m3_qubit_ids.py` | Bruno opens, Claude drafts |

## 5. Unverified, to settle during M3

1. `coupling_map` direction and how broken qubits are marked (§2.5).
2. Why the `wireset-to-profile-qir` QIR translation failed (§2.4), only if we pick D1-B.
3. Whether OQC and Anyon are really affected by §2.4.
