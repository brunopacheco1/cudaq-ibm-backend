# M4 spec: results checked in CI, idle qubits, emulation, observe, packaging

Date: 2026-11-10. Status: **draft, waiting for Bruno's decisions (§3). No code before that.**
Reader: Bruno.
Tags: **[V]** verified (source given), **[U]** unverified.
"Today's runs" means: cloud container, Ubuntu 24.04 x86_64, g++ 13.3, Python 3.13, pip
`cudaq` 0.16.0, on 2026-11-10. The scripts are in the project files, folder
`cudaq-ibm/m4-experiments/` (throwaway; the useful ones become tests in M4).

This page follows the spec rule in [README.md](README.md): it lives while M4 is in progress.

## 1. Goal

After M4 a stranger can install the plugin and trust what it returns:

1. `pip install` of one file, then `cudaq.set_target("ibm")` works with the pip `cudaq`.
2. CI builds the plugin and checks **results**, not only that IBM would accept the gates.
3. A kernel never comes back with fewer bits than it has qubits.
4. `emulate=True` and `cudaq.observe` either work or stop with a clear sentence. Today
   they fail with a compiler message or crash Python (§2, F5 and F6).

Done when: the items above pass in CI, and you ran one small kernel on `ibm_fez` from the
installed wheel (not from the dev container build).

## 2. What I checked today

These facts changed the plan, so please read them before §3.

| # | Fact | Source |
|---|---|---|
| F1 | **The plugin builds without a CUDA-Q source build.** One `g++` call, about a minute: headers from the CUDA-Q `0.16.0` git tag, libraries from the pip wheel (`libcudaq-common.so`, `libcudaq-logger.so`; the wheel also exports libcurl 8.21.0). The result loads into pip `cudaq` and passes all six cases of `tests/run_fake_ibm.py`. The same file also loads into `0.16.0.post1`. This closes the "plugin ABI vs pip cudaq" risk for Linux x86_64 | **[V]** `build_against_wheel.sh` |
| F2 | pip `cudaq` 0.16.0 exists for Linux x86_64, Linux aarch64 and macOS arm64 (macOS 13+), Python 3.11 to 3.14. Its libraries were built with GCC 12.2.1 for glibc 2.28. My build on Ubuntu needs glibc 2.38, so a wheel for other people must be built in an older image (`manylinux_2_28`) | **[V]** PyPI file list; `readelf`/`objdump` on the wheel and on my build |
| F3 | With a simulator behind the fake server (60 lines of numpy, a prototype), today's plugin returns the **right answers** for kernels that measure everything, measure a part out of order, or have no `mz` | **[V]** `sim_server.py`, `e4_sample_sim.py` |
| F4 | Idle qubits. The fix planned in the roadmap (`add-measurements` early) works for `sample` but **breaks `observe`**: "Cannot observe kernel with non dangling measurements". Taking `dqe` out of the pipeline fixes both. `dqe` is the pass that deletes qubits no gate touches; with it, the remaining qubits are renumbered | **[V]** `e2_idle.py`, `e7_observe_idle.py` (variants v4, v5, v6) |
| F5 | `emulate=True`. Today: "Multiple qalloc statements found". One more pass at the end (`combine-quantum-alloc`) removes the error, but then the **bit order is wrong without any warning**: `1110` instead of `1011`. Cause: in emulation CUDA-Q sorts bits with its own `reorderIdx`, which is wrong with our router options `placement=auto search=sabre` ([upstream.md](upstream.md) #8). With CUDA-Q's default start layout the emulated results are right: 3 sample kernels, 16 observe operators | **[V]** `e1_emulate.py`, `e3_observe.py`, `e7_observe_idle.py` (variants v1, v2, v6) |
| F6 | `cudaq.observe` on the real path. Today: the same qalloc error for 2 qubits, and a **segmentation fault** (Python dies) for a 5-qubit star. With the extra pass the circuit reaches our helper as one register-wide `measure var0 -> var4;`, which the helper does not read yet. With `placement=auto` the 5-qubit star still crashes, inside CUDA-Q, before our code runs | **[V]** `e3_observe.py`, `e5_observe_small.py`, `e8_dump.py` |
| F7 | The same two problems exist on **targets NVIDIA ships**, with `emulate=True`: `observe` on `anyon` (`berkeley-25q`) crashes Python for a 3-qubit kernel, and on `anyon` and `oqc` a kernel with an idle qubit returns a wrong expectation value (`<Z1>` = -1 instead of +1). The crash has the same root as your issue NVIDIA/cuda-quantum#5882 | **[V]** `e6_anyon_observe.py`, `e6b_anyon_observe_no_idle.py`; 0.16.0 only, not rerun on 0.16.0.post1 |
| F8 | CUDA-Q says `sample` and `observe` "will change in a future release". A concrete change is in review: NVIDIA/cuda-quantum PR 5875 (open, by a maintainer, 2026-11-09). By its description, kernels will need an explicit `cudaq.record(...)`, the router stops producing `mapping_reorder_idx`, and a `ServerHelper` gets the recorded qubits instead. If it merges, the next CUDA-Q release changes how this plugin learns the bit order and how `emulate` and `observe` work | **[V]** `FutureWarning` at `import cudaq`. PR 5875: read by the upstream thread on 2026-11-10 (new fields seen on the PR branch), not by me; whether the recorded qubits are device ids is **[U]** |

Limits of these facts: one machine, one architecture, few kernels. F5 and F6 need a
random-kernel test before anyone relies on them.

## 3. Decisions for you

Each one has my recommendation and what it costs. Answer "all as recommended" or pick.

### D1. How is the plugin built for CI and for releases?

- **A. Against the pip wheel (F1).** Minutes in GitHub's CI. I can build and run the plugin
  in the cloud too, so fewer "please run this in your container" round trips.
- **B. Inside the CUDA-Q source build**, as today. This is the way NVIDIA documents
  **[V]** `packaging.rst`. A full build takes hours and the image is pinned by a digest
  NVIDIA may delete.
- **C. Both: A for CI and releases, B stays your environment for upstream work**
  (the `getHeaders()` change needs a source build anyway).

Recommended: **C**. Risk of A: it is not the documented way. If headers and wheel differ,
the plugin could misbehave at run time instead of failing at compile time. Guard: CI builds
and runs the end-to-end tests against every `cudaq` version we claim to support.

### D2. Which platforms does the first release cover?

- **A.** Linux x86_64 only (verified, F1).
- **B.** A plus Linux aarch64. That is what your Podman machine is, so you could use the
  plugin in any small Python container, without the dev container.
- **C.** B plus macOS arm64: the plugin would run directly on your Mac.

Recommended: **B, and two hours to try C.** macOS is **[U]**: other compiler, other C++
library. If it does not work in two hours, it becomes an open item, not a blocker.

### D3. Where do the wheels go, and under which name?

- **A. GitHub Release** of this repository: wheel files to download.
- **B. PyPI**: `pip install <name>` for everyone. An uploaded file cannot be replaced, a
  fix needs a new version number **[U]** (PyPI's long-standing rule; its help page has
  moved and I could not reread it today).
- **C.** No wheels, only build instructions.

Recommended: **A now, B when someone other than you has used it.** Name: `cudaq-ibm` is
free on PyPI today **[V]** (so are `cudaq-ibm-backend`, `cudaq-ibm-plugin`). Two things to
weigh: "IBM" in the name of an unofficial package (the README would say "not affiliated
with IBM or NVIDIA"), and the Python prototype in `src/` already uses the names
`cudaq-ibm-backend` and `cudaq_ibm`. My proposal: plugin = `cudaq-ibm`, prototype stays
unpublished. Your call.

### D4. What simulates the circuits in the fake server, and who writes it?

The server receives the OpenQASM 3 we send to IBM: only `rz`, `sx`, `x`, `cz` and `measure`
on physical qubits. To answer with real samples it must simulate that.

- **A. Our own small statevector simulator** in `tests/` (numpy). n qubits are 2^n complex
  numbers; a gate multiplies them by a small matrix; measuring draws an outcome with
  probability |amplitude|^2. It simulates only the qubits the circuit touches (up to about
  24), so a 156-qubit chip is no problem. Independent of both CUDA-Q and Qiskit.
- **B. Qiskit Aer.** Heavier; whether Qiskit's OpenQASM 3 import accepts physical qubits
  (`$62`) is **[U]**.
- **C. CUDA-Q's simulator.** Then CUDA-Q checks CUDA-Q: a shared mistake stays hidden.

Recommended: **A.** The tests then compare three things that should agree: the kernel on
CUDA-Q's simulator, and the same kernel through the plugin and the fake server.

Who writes `simulate()`: it is about 40 lines and pure quantum mechanics (statevector,
gates as matrices, bit order, sampling). **I suggest you write it**; I prepare the function
signature, hints and the tests it must pass, and all the server plumbing around it. If you
prefer, I write it. (My prototype is `sim_server.py` in the experiments folder: do not open
it if you want to do this yourself.)

### D5. Idle qubits

- **A. Remove `dqe` from the pipeline** (F4). Every allocated qubit keeps its place and is
  measured. Cost: an idle qubit now occupies a chip qubit and adds a readout.
- **B. `add-measurements` early**, the roadmap's plan. Breaks `observe` (F4).
- **C. Leave it.** CUDA-Q's specification allows the shorter bit string.

Recommended: **A.** It also removes the cause of the wrong expectation values in F7.

### D6. `emulate=True`

- **A. Refuse it with a clear sentence** ("the ibm target does not emulate; use the default
  simulator, or the fake server for an end-to-end run"). About an hour: the helper's
  `initialize` receives the `emulate` setting **[V]** by reading `qpu_utils.cpp:166` and
  `BaseRemoteRESTQPU.h:203`, **[U]** by a run.
- **B. Support it**: in emulation the helper switches the router to CUDA-Q's default
  start layout, where results are right (F5). About a day, with a random-kernel test in CI.
- **C.** Leave today's compiler error.

Recommended: **A for this release.** In emulation CUDA-Q simulates its own IR and never
calls our gate rewrite, qubit assignment or result decoding, so emulation tests CUDA-Q,
not this plugin. B would also route differently from the hardware path, and it rests on
`reorderIdx`, which is already wrong in one setting (F5) and sits in code NVIDIA announced
it will change (F8). A silent wrong bit order is the worst failure this plugin can have.
Revisit after that CUDA-Q change.

### D7. `cudaq.observe` (expectation values)

- **A. Not in this release.** Document it, give a clear error where our code is reached,
  and add an example that computes `<ZZ>` and `<XX>` of a Bell pair from `sample` counts.
- **B. Implement it now**: read the register-wide `measure`, keep the bits of each term.
  Works only while routing stays inside the first qubits; otherwise CUDA-Q crashes before
  our code (F6), and we cannot catch that.
- **C.** Wait for NVIDIA's answer to #5882, then decide.

Recommended: **A, then C.** The crash is the #5882 problem showing up in a second place,
and F7 shows it on shipped targets, which makes your issue stronger (the thread
"Build IBM backend plugin for CUDA-Q" has the evidence). The `sample` example is quantum
work for you: measuring in the X basis means an `h` before `mz`, and an expectation value
is "shots with even parity minus shots with odd parity, divided by shots". Limit: for
large kernels `observe` may still crash instead of printing our error **[V]** F6; whether
the helper can detect `observe` earlier is **[U]**, one hour to try.

## 4. What gets built (if you take the recommendations)

Smallest useful step first; each step is one PR.

| Step | What | Who |
|---|---|---|
| 1 | CI job: build the plugin against the wheel (F1), start the fake server, run the six existing cases. Matrix: `cudaq` 0.16.0 and 0.16.0.post1 | Claude |
| 2 | Simulating fake server: `simulate()` (D4), server plumbing, a backend name that keeps the fixed samples for the bit-order case. Tests compare with CUDA-Q's simulator: random `x`/`cx` kernels (one right answer each), GHZ, the gate-rule kernel (so `rx`, `ry`, `u3`, `s`, `t` are checked for physics end to end, not only accepted), partial and missing `mz` | `simulate()`: Bruno. Rest: Claude |
| 3 | Pipeline: remove `dqe` (D5), idle-qubit test, clear errors for `emulate=True` and `observe` (D6, D7), the `sample`-based expectation example | Pipeline and errors: Claude. Example: Bruno |
| 4 | Packaging: rename `cudaq_example_ibm`, wheel build per platform in a `manylinux_2_28` image (D2), release workflow (D3), `--install-nvqpp` check, README install section. Remove the inherited lit test `check-ibm`: it needs a source build, and steps 1 and 4 cover what it checked | Claude |
| 5 | You: one kernel on `ibm_fez` from the installed wheel. Then close M4: facts to `architecture.md`, choices to `decisions/`, delete this spec | Bruno, then Claude |

Effort: about 4 to 6 part-time days. The roadmap said 2 to 3, but that was packaging alone.

Note: the fake server got a token-expiry mode on 2026-11-10 (PR 12). Step 2 builds on that
version and keeps the mode.

## 5. Test plan

- Free, in CI on every push: C++ unit tests (as today), plugin build against the wheel,
  end-to-end against the simulating fake server, on each supported `cudaq` version.
- Free, by hand: install the wheel in a clean container, `cudaq.has_target("ibm")`,
  `python -m <package> --install-nvqpp`, `nvq++ --list-targets`.
- QPU time: one small kernel, started by you (step 5). A few seconds.

## 6. Risks

| Risk | Plan |
|---|---|
| Wheel-based build breaks on a later `cudaq` (headers and binary drift apart) | CI matrix per supported version; the dev container build stays as the fallback |
| `manylinux_2_28` image has another GCC than the wheel (12.2.1) **[U]** | Try in step 4; fallback: NVIDIA's `manylinux` devdeps image |
| aarch64 and macOS builds **[U]** | D2: aarch64 in step 4, macOS time-boxed |
| The numpy simulator and the plugin share a wrong idea about bit order | The reference is CUDA-Q's simulator on the original kernel, and the two hardware runs of M3 already confirmed the order on a real chip |
| Without `dqe`, something else in the pipeline changes **[U]** | The random-kernel tests of step 2 exist before step 3 changes the pipeline |
| CUDA-Q changes `sample`/`observe` (F8, PR 5875) | D6 and D7 avoid building on that code now. Our own bit-order rule ([decision 0010](decisions/0010-measure-all-then-keep-measured-bits.md)) will also need a second look when that release comes; the result tests of step 2 will show at once if it breaks. Read the PR before any design of `emulate` or `observe` |
