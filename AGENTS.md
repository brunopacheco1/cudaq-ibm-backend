# AGENTS.md

Instructions for AI coding agents working in this repository. Humans: see
[README.md](README.md) and [docs/](docs/README.md).

## What this is

An open-source IBM Quantum backend for CUDA-Q, and a **learning project** for its owner,
Bruno. Two parts:

- `src/cudaq_ibm/`: phase 1 Python prototype (CUDA-Q -> Qiskit -> IBM REST). Done; it is the
  reference for facts about IBM's API.
- `plugin/`: the C++ CUDA-Q plugin (`ServerHelper` + target YAML). Work in progress.

Start with [docs/architecture.md](docs/architecture.md) (how it works now) and
[docs/decisions/](docs/decisions/) (why). Status and next steps: [docs/roadmap.md](docs/roadmap.md).

## Division of work

- **Agents may write plumbing**: C++ HTTP/JSON code, CMake, YAML, Python test
  infrastructure (fake servers, run scripts), CI and docs.
- **Bruno owns the quantum side and design decisions**: gate rewrite rules in
  `plugin/Qasm2ToIsa.h` and their proofs, routing and layout
  choices, and real hardware runs. Do not implement these unless he asks in the task. Explain,
  give hints and review instead.
- Any choice that is hard to reverse needs his decision; record it in `docs/decisions/`.

## Commands

```bash
# Python prototype tests (any machine, also in CI). Never touch IBM.
pip install -e ".[test]" && pytest -q

# Gate rewrite unit test (any machine with g++, also in CI). No CUDA-Q needed.
g++ -std=c++20 -Wall -Wextra -Werror -I plugin plugin/tests/test_qasm2_to_isa.cpp -o /tmp/test_isa && /tmp/test_isa
```

The C++ plugin builds in two ways ([docs/development.md](docs/development.md)):

```bash
# Against the pip wheel: any Linux with g++, about a minute, also in CI (job `plugin`).
pip install cudaq==0.16.0 fastapi uvicorn python-multipart
plugin/build_against_wheel.sh                 # writes build/external/ibm
python3 tests/fake_ibm_server.py 62455 &      # fake IBM, never the real one
python3 tests/run_fake_ibm.py                 # eight OK lines (protocol, fixed samples)
python3 tests/run_fake_ibm_results.py         # 25 OK lines (results; starts its own server)

# The wheel: build it, then test it as installed (fresh environment, same two scripts).
plugin/build_wheel.sh                         # writes dist/cudaq_ibm-<version>-py3-none-<platform>.whl
plugin/test_wheel.sh dist/*.whl 0.16.0        # ends with "RESULT: the wheel ... passes all four checks."
```

The other way is inside a CUDA-Q 0.16 source build in NVIDIA's Linux dev container. Only
Bruno has that; it is needed for changes to CUDA-Q itself. So an agent can build the plugin
and run it against the fake server: do that before claiming a change works. Real IBM
hardware runs are Bruno's.

When you add a rewrite rule (after Bruno has derived it), add a case to `kRuleCases` in
`plugin/tests/test_qasm2_to_isa.cpp`; the test proves it up to global phase.

## Rules

- **Secrets.** IBM credentials come only from `IBM_QUANTUM_API_KEY` and `IBM_QUANTUM_CRN`
  (or a git-ignored `.env`). Never put them in target arguments, logs, commits, chat or
  memory. The API key must never pass through `RestClient` (it logs bodies at INFO).
- **TLS.** CUDA-Q's `RestClient` turns certificate checks off by default. Calls we make
  ourselves must verify TLS. CUDA-Q's libcurl has no default CA store, so name a bundle
  ([docs/architecture.md](docs/architecture.md) §2.3).
- **Facts.** Tag claims in docs **[V]** verified (with source) or **[U]** unverified. Check
  CUDA-Q behaviour against the `0.16.0` tag source, not memory.
- **Docs.** Follow the conventions in [docs/README.md](docs/README.md). Update
  `docs/architecture.md` in the same change as the code it describes. Its section numbers are
  cited by code comments (`§3.1` etc.); keep them stable.
- **Licensing.** Files adapted from CUDA-Q keep NVIDIA's header and add "Modifications
  copyright (c) 2026 Bruno Pacheco. Adapted from ..." (Apache-2.0 §4). Keep `NOTICE`.
- **Style.** C++20, `.clang-format` in the repo root. Keep `Qasm2ToIsa.h` free of I/O and
  CUDA-Q includes so its test compiles with plain `g++`.
- **Writing.** Simple, direct English. Explain the quantum idea behind a step when it is not
  obvious; this is a learning project.
- **Git.** Work on a branch and open a PR; never push to `main` and never rewrite its
  history.
- **Authorship.** Bruno is the author of every commit. An agent commits with
  `--author` set to the identity on the commits of `main`
  (`git log -1 --format='%an <%ae>' main`) and names itself only in a `Co-Authored-By:`
  trailer. An agent cannot sign with Bruno's key, so its commits do not go to `main` as they
  are: Bruno merges each PR with **Squash and merge**, which makes one commit signed by
  GitHub.
- **Releases.** A version tag (`v0.1.0`) publishes wheels to a GitHub Release
  ([docs/development.md](docs/development.md) §7). Only Bruno creates tags and releases;
  an agent never does, and never uploads to PyPI.
- **Upstream.** CUDA-Q contributions need a DCO sign-off (`Signed-off-by:`). It is Bruno's
  personal statement: only he adds it, with `git commit -s`. Candidates are in
  [docs/upstream.md](docs/upstream.md).

## Gotchas

- Bit order: IBM returns little-endian hex (bit 0 right-most); CUDA-Q puts qubit 0 left-most.
  Results must be reversed.
- CUDA-Q's `Future::get` calls `getHeaders()` once per job, so tokens can expire during long
  polls ([decision 0004](docs/decisions/0004-accept-token-expiry-in-v1.md)).
- The decomposition pipeline leaves `y` and `u3` in the QASM2 output; the converter must
  handle or reject them.
- The dev container image also ships an older `cudaq`. `cudaq.__file__` must point into
  `/work/cuda-quantum/build/python`.
- Never `pip install` the Python prototype inside the dev container.
