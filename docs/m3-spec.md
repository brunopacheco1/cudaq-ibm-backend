# M3 spec: routing

Date: 2026-11-10. Status: **all choices made (decisions 0009-0011); code done; next is the
container run, then hardware (§6)**. Deleted when M3 is done
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
- A device graph with qubits that cannot be reached failed with the default options: "cannot
  place two-qubit interaction ... on disconnected device topology" **[V]** our experiment,
  2026-11-09. With greedy placement 0.16.0 can pack a disconnected device **[V]**
  `Passes.td:1384-1394`; not tried **[U]**. We prune to one connected part anyway.
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
OQC and Anyon also route and then run `regtomem`, and the same thing happens with their own
pipelines and device files **[V]** at the level of the code they generate: on Anyon's
`berkeley-25q` a 3-qubit kernel routed onto {0, 1, 2, 6} comes out as qubits 0..3
([`experiments/upstream_layout_lost.py`](../experiments/upstream_layout_lost.py)); 47 of 150
random kernels there and 12 of 150 on OQC `toshiko` leave 0..m-1, none on Anyon
`telegraph-8q` or on IQM's 20-qubit mock graph
([`experiments/upstream_layout_sweep.py`](../experiments/upstream_layout_sweep.py)). What
their servers then do with it is **[U]**: we have no access. This is upstream item #5 in
[upstream.md](upstream.md).

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
registers in reverse: 11 of 120 random kernels. The router options do not matter: the same 6
of 60 kernels fail with the identity start and with `placement=auto search=sabre` **[V]**
review run, 2026-11-10. (An earlier version of the experiment only measured in order and
wrongly found no problem.)

Fix ([decision 0010](decisions/0010-measure-all-then-keep-measured-bits.md)): run
`combine-measurements` before routing (then `expand-measurements`, `cc-loop-unroll`). The
circuit then measures every qubit in allocation order, and `output_names` lists the qubits the
kernel measured; `processResults` keeps those bits (`plugin/ResultBits.h`). 0 of 120 wrong, on
path, star, ring and `ibm_fez` graphs. `reorderIdx` does not fit IBM: it assumes results
sorted by physical qubit.

### 2.9 The router's start layout matters

**[V]** `experiments/m3_routing.py`, root 62: two-qubit gate counts after routing.

| Kernel | identity, none (default) | identity, sabre | auto, none | auto, sabre (ours) |
|---|---|---|---|---|
| GHZ-5 chain | 10 | 10 | 4 | 4 |
| GHZ-20 chain | 151 | 136 | 34 | 28 |
| 12-qubit ring | 78 | 57 | 12 | 12 |
| 6-qubit star | 14 | 14 | 11 | 11 |

Most of the gain is the placement; sabre adds a little. A swap is 3 `cx`, so GHZ-20 (19 `cx`)
needs 3 swaps with our options and 44 with the default. With `placement=auto` the greedy
start begins at the most central qubit of the device file, not at label 0 **[V]**
`Mapping.cpp:205-222`. The circuit still ends near our root, because the assignment search
tries each label's own number first (`Layout.h`, step 4).

### 2.10 The search above about 100 qubits

**[V]** [`experiments/m3_search_stress.cpp`](../experiments/m3_search_stress.cpp): random
connected circuits on `ibm_fez`, 40 cases per cell, budget 10^6 steps. Refused cases:

| Circuit | Labels | 100 | 130 | 150 | 156 |
|---|---|---|---|---|---|
| Sparse (tree + 10% of the other links) | device order | 0 | 4 | 0 | 0 |
| Sparse | shuffled | 0 | 4 | 6 | 7 |
| Dense (tree + 50%) | either | 0 | 0 | 0 | 0 |

Worst time about 1.2 s. A refusal is a clear error, never a wrong placement. Routed circuits
are sparse, so the honest limit is "fine up to about 100 qubits". (An earlier claim of "0 of
40 up to 130" came from a denser generator.)

### 2.11 Kernels without `mz`

**[V]** A kernel with no `mz` and a qubit it never touches: CUDA-Q removes the idle qubit
(`dqe`) before it adds the missing measurements (`Compiler.cpp:421, 467-473`), so that bit is
missing: a 4-qubit kernel returned 2-bit strings. Same before and after the §2.8 fix. Adding
`add-measurements` at the start of the mid-level pipeline fixed it at pass level **[V]**
review run; in the built plugin, and together with `observe`, **[U]**.

CUDA-Q allows this **[V]**: its specification says a qubit that is allocated but not used
"may not appear in the implicit measurement results" (`algorithmic_primitives.rst`, note
after the `__global__` rules, tag 0.16.0). `oqc` and `anyon` do the same in emulation, the
simulator and quantinuum, ionq, infleqtion and braket do not
([`experiments/m3_idle_qubit.py`](../experiments/m3_idle_qubit.py)). So it is a difference
from the simulator, not a wrong result, and not an upstream bug. Documented for M3. Bruno
moved the fix to M4 on 2026-11-10, to be done with `emulate=True` and `observe`
([roadmap.md](roadmap.md)).

### 2.12 `emulate=True` and `observe`

In emulation CUDA-Q takes `combine-measurements` out of the pipeline and runs it at the end
**[V]** `Compiler.cpp:307-319`. On a routed circuit that late pass fails with "Multiple qalloc
statements found" **[V]** at pass level, pip CUDA-Q, and **[V]** in the built plugin
(2026-11-10, probe at the end of `tests/run_fake_ibm.py`: "Remote rest platform Quake
lowering failed", after "Multiple qalloc statements found"). The plugin also logs in to IBM
before it emulates, so `emulate=True` needs credentials today. `cudaq.observe` on this
target is untested **[U]**. Both are "not supported in M3" (decision 0010).

### 2.13 `/properties`: fail closed

[Decision 0011](decisions/0011-stop-when-properties-cannot-be-read.md). The parser
(`plugin/ChipData.h`) reads the FakeFez snapshot with 0 unreadable entries and leaves 154 of
156 qubits usable **[V]** `plugin/tests/test_chip_data.cpp` in file mode. Whether today's real
`ibm_fez` reply has the same shape is **[U]** until the free fetch in §6.

### 2.14 The QASM the helper receives is not what `cudaq.translate` prints

Found on 2026-11-10, in the first run of the built plugin: the Bell pair failed with
"bad 2-qubit gate on labels 0, 0". Cause **[V]** in the CUDA-Q source:

- After `regtomem` every qubit is its own allocation, and the OpenQASM emitter prints one
  register per allocation: `qreg var0[1]; qreg var1[1];`, then `cx var0[0], var1[0];`
  (`TranslateToOpenQASM.cpp:160-175`).
- `cudaq.translate(..., "openqasm2")`, which all experiments here use, runs extra passes
  first (`QPU.cpp:98-134`) and prints one register, `qreg var0[2];`. The runtime path does
  not run them (`RuntimeMLIR.cpp`, "qasm2" translation).

So our parser, which read only the index in the brackets, saw qubit 0 twice. Fix:
`QregTable` in `Qasm2ToIsa.h` numbers the qubits over all registers in the order they are
declared; both forms give the same labels (unit tested). The exact text the runtime sends
is **[U]** until the container run logs it.

The second run found the same kind of gap: the router's `swap` gates reached the helper,
which has no rule for `swap` (GHZ-20: 3 swaps). `cudaq.translate` had turned them into `cx`.
Fix: a second `decomposition{...}` after `qubit-mapping` in `ibm.yml.in`, as `iqm.yml`
repeats its gate-set mapping there **[V]** at pass level: 0 swaps, 28 `cx` for GHZ-20.

What changed in how we check, so that pip CUDA-Q can catch this class of problem:

- [`tests/test_target_yml.py`](../tests/test_target_yml.py) (in CI) compiles kernels with the
  pipeline of `ibm.yml.in`, then with the gate-changing passes of the runtime's OpenQASM
  translation (`Pipelines.cpp`, `addPipelineTranslateToOpenQASM`), and checks that only
  gates with a rewrite rule remain. It fails without the second decomposition.
- `experiments/m3_bit_order.py` now simulates that compiled kernel itself, not the output
  of `cudaq.translate`. Result unchanged: before the fix 6 and 5 of 60 wrong, after 0.

Lesson: an experiment with pip `cudaq` shows what the passes do, not what the plugin
receives. Check the compiled kernel, not `cudaq.translate`, and count a claim as verified
only after a run of the built plugin.

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

**Chosen:** A, with the chip data kept 60 s because CUDA-Q asks twice per `sample`
(decision 0009 item 3, 2026-11-10).

## 4. Work split

| Step | Who | Status |
|---|---|---|
| D1-D3 choices | Bruno | Done |
| Numbering rule (breadth-first) and its proof that prefixes stay connected | Bruno (review) | Written in `Layout.h` §3, to review |
| `getPipelineSubstitutions`, fetch, prune, root, numbering, device file, YAML | Claude | Done, unit tested |
| Assignment search, `$k` relabel in the converter | Claude | Done, unit tested |
| Result bit order (`combine-measurements`, `ResultBits.h`) | Claude | Done, unit tested (§2.8) |
| Review fixes (search, one-way broken links, 60 s chip cache, atomic device file) | Claude | Done |
| Fail closed on `/properties` (`ChipData.h`, decision 0011) | Claude | Done, unit tested |
| Fake server: `/configuration`, `/properties`, reject `cz` on unwired or broken pairs | Claude | Done, `tests/test_fake_server.py` |
| Build the plugin, run `tests/run_fake_ibm.py` | Bruno (container) | Next (§6 step 1) |
| Look at real `ibm_fez` data, then the hardware session | Bruno | After that (§6 steps 2-3) |
| Upstream issues | Bruno opens, Claude drafts | Drafts ready ([upstream.md](upstream.md) #5, #7, #8, with an issue plan); #5 after the hardware session |

## 5. Unverified, to settle during M3

1. ~~`coupling_map` direction~~ (§2.5, done). How the real `ibm_fez` marks broken qubits
   today: first real run.
2. Why the `wireset-to-profile-qir` QIR translation failed (§2.4): dropped, D1-B not chosen.
3. ~~Whether IQM, OQC and Anyon are affected by §2.4~~: OQC and Anyon generate wrong ids
   (§2.4, done); IQM not shown affected. Still unknown: what their servers do with it.
4. The plugin itself: built only by Bruno; here the helper is syntax-checked against stub
   headers and the pipeline is run with pip CUDA-Q.

## 6. Test plan to close M3

Every free check comes before the one step that spends QPU time.

1. **Container.** Rebuild, then `tests/run_fake_ibm.py`. It must print 6 `OK` lines (Bell,
   gate rules, GHZ-20, out-of-order `mz`, `mapping_file`, no `/properties`) and one `PROBE`
   line for `emulate=True`. Note what the probe prints.
   **Done 2026-11-10**, on the third run: 6 `OK`. The first two runs found two bugs the
   pip-CUDA-Q experiments could not see (§2.14). GHZ-20 was sent with 28 `cz` on 20
   qubits; the out-of-order kernel was sent as `x $62` and measures of 62, 61, 63, and came
   back as (q0, q2). The probe failed as expected (§2.12).
2. **Real data, no job.** Save the real `/configuration` and `/properties` of `ibm_fez` to two
   files with [`experiments/fetch_chip_data.py`](../experiments/fetch_chip_data.py) and run
   `test_chip_data` on them (see its header). Expect 0 unreadable entries and a
   region close to 156 qubits. That these GETs use no quota is **[U]** but normal.
   **Done 2026-11-10**: 156 qubits, 176 links, usable region 156, root 114, 0 unreadable
   entries, every link has a cz error and every qubit a readout error. Two facts about
   the real data: no qubit has an "operational" item (so a broken qubit shows only through
   its error rates and its links), and the gate list also has `rzz` on every link.
3. **Hardware, one session**, with `CUDAQ_LOG_LEVEL=info` (logs the label -> qubit map and the
   ISA circuit):
   Script: `tests/run_ibm_hardware.py --ghz-mark M1 --order-mark M2 --yes-spend-qpu-time`
   (it refuses to run without the last flag). At INFO, CUDA-Q logs request bodies, not
   headers **[V]** `RestClient.cpp:71`, and the plugin never logs the key or the token.
   - GHZ-5, 1000 shots. Proposed pass mark: `00000` + `11111` in at least 80% of the shots.
     Rough estimate: the M2 Bell pair gave 94.4% with 1 `cz` and 2 readouts; GHZ-5 has 4 `cz`
     and 5 readouts, so about 85-90% **[U]**. Bruno sets the mark **before** the run.
   - One non-symmetric kernel, because a GHZ result reads the same in any bit order: 3
     qubits, `x(q[0]); mz(q[2]); mz(q[0])`, 200 shots. Proposed pass mark: `10` in at least
     90% of the shots. A wrong bit order would give mostly `01`.
4. Open the first upstream issue; fold this spec into architecture.md; delete it.
