# Development: build and test the C++ plugin

Date: 2026-11-11. Status: living document.
Reader: anyone building the plugin. Why a container and not a native Mac build:
[decision 0002](decisions/0002-build-in-linux-dev-container.md).

There are two ways to build the C++ plugin in `plugin/`:

- **Inside CUDA-Q's own source tree** (§1 to §5), in NVIDIA's dev container. This is the
  way NVIDIA documents, and the one you need to change CUDA-Q itself (upstream work).
- **Against the pip `cudaq` wheel** (§6), on any Linux with `g++` and Python. About a
  minute, no source build. CI uses it.

The examples use Podman on an Apple Silicon Mac. Docker works the same way:
replace `podman` with `docker`.

## Layout

| Where | What | Survives |
|---|---|---|
| volume `cudaq-work` → `/work` | CUDA-Q source and its build (`/work/cuda-quantum/build`) | yes, until `podman volume rm` |
| your repo on the Mac → `/src/cudaq-ibm-backend` | this repo (bind mount: edit on the Mac or in the container) | yes |
| the container itself (`/root`, `/usr`, ...) | `.bashrc`, apt packages (clangd) | only until `podman rm` |

The image is pinned **by digest**. NVIDIA deleted the arm64 `releases-v0.16.0`
tags, and this `main` image uses the same LLVM commit (`def143a6`) as 0.16.0.

```bash
IMAGE=ghcr.io/nvidia/cuda-quantum-devcontainer@sha256:5cfd7dab741f41c935204d56930d9c8324d5127746e0ed4989e204377de517c1
```

## 1. One time: Podman machine

The full build needs about 8 GB of RAM. With less, `ConvertExpr.cpp` runs out
of memory.

```bash
brew install podman krunkit
podman machine init
podman machine set --cpus 6 --memory 8192
podman machine start
```

## 2. One time: build CUDA-Q 0.16 from source (hours)

```bash
podman run -it --name cudaq-ibm \
  -v cudaq-work:/work \
  -v ~/dev/personal_git/cudaq-ibm-backend:/src/cudaq-ibm-backend \
  $IMAGE bash
```

Inside the container:

```bash
cd /work
git clone --branch 0.16.0 https://github.com/NVIDIA/cuda-quantum
cd cuda-quantum
CUDAQ_BUILD_TESTS=FALSE bash scripts/build_cudaq.sh -j 1
```

`-j 1` is slow but avoids the out-of-memory crash. Then make the
source-built CUDA-Q the default in every shell:

```bash
echo 'export PYTHONPATH=/work/cuda-quantum/build/python' >> /root/.bashrc
echo 'export PATH=/work/cuda-quantum/build/bin:$PATH' >> /root/.bashrc
source /root/.bashrc
```

The image also contains an older `cudaq`, so `python3 -c "import cudaq;
print(cudaq.__file__)"` must print a path under `/work/cuda-quantum/build/python`.

## 3. Every day: start, attach, stop

```bash
podman machine start
podman start cudaq-ibm
podman exec -it -e HOME=/root -w /work/cuda-quantum cudaq-ibm bash
podman stop cudaq-ibm
```

Always pass `-e HOME=/root`. **[V]** Without it, `podman exec` starts bash with `HOME=/home`
(checked 2026-11-09), so bash never reads `/root/.bashrc`, `PYTHONPATH` stays empty and
`import cudaq` fails. A shell alias on the Mac saves typing (add it to `~/.zshrc`):

```bash
alias cq='podman exec -it -e HOME=/root -w /work/cuda-quantum cudaq-ibm bash'
```

Run `podman exec` (or `cq`) again for each extra shell. If you ever need to recreate
the container (`podman rm cudaq-ibm`, then the `podman run` from step 2), the
CUDA-Q build in the volume is kept. Only the `.bashrc` lines and apt packages
must be redone.

## 4. Build and test the plugin (seconds)

```bash
cd /work/cuda-quantum
cmake -B build -DCUDAQ_EXTERNAL_PROJECTS=ibm \
  -DCUDAQ_EXTERNAL_IBM_SOURCE_DIR=/src/cudaq-ibm-backend/plugin
ninja -C build -j 2 cudaq-example-serverhelper-ibm
```

Run `cmake` again only after changing `plugin/CMakeLists.txt` or the YAML.
The plugin lands in `build/external/ibm/` (`lib/libcudaq-serverhelper-ibm.so`,
`targets/ibm.yml`).

End-to-end against the fake IBM server (no account, no QPU time), in two shells:

```bash
pip install fastapi uvicorn python-multipart
python3 /src/cudaq-ibm-backend/tests/fake_ibm_server.py 62455
```

```bash
cd /work/cuda-quantum
python3 /src/cudaq-ibm-backend/tests/run_fake_ibm.py
```

It runs eight cases and prints one `OK` line for each: a Bell pair; a kernel with `rx`, `ry`,
`z`, `y`, `s`, `t` and `u3`; a 20-qubit GHZ (routing); a kernel that measures out of order; the
`mapping_file` override; a backend without `/properties`, which must stop; and
`cudaq.observe` and `emulate=True`, which must be refused with a clear error
([architecture.md](architecture.md) §8 item 7).
These eight check the protocol with fixed samples. The results themselves are checked by a
second script, which starts its own fake server and compares 26 kernels with CUDA-Q's
simulator ([architecture.md](architecture.md) §7):

```bash
python3 /src/cudaq-ibm-backend/tests/run_fake_ibm_results.py
```

Add `CUDAQ_LOG_LEVEL=info` to see the chip numbering, the label -> qubit map and the ISA
circuit the plugin sends. Stop an older fake server on port 62455 first.

Token expiry while polling ([architecture.md](architecture.md) §8 item 1), one shell. The
script starts its own fake server on port 62456 with tokens that live 12 s:

```bash
cd /work/cuda-quantum
python3 /src/cudaq-ibm-backend/tests/run_token_expiry.py
```

It prints the server log and one `RESULT` line: a failed poll (HTTP 401) on CUDA-Q 0.16.0,
a finished job on a CUDA-Q that asks for the headers on every poll.

The four unit tests need no CUDA-Q and also run in CI. From the repository root:

```bash
JSON=/work/cuda-quantum/tpls/json/single_include   # in the dev container
for t in qasm2_to_isa layout result_bits chip_data; do
  g++ -std=c++20 -I plugin -I $JSON plugin/tests/test_$t.cpp -o /tmp/test_$t && /tmp/test_$t | tail -1
done
```

Outside the container, `apt install nlohmann-json3-dev` replaces the `-I $JSON` part.

To try the parser and the numbering on real IBM data without sending a job (needs the
credentials of [decision 0003](decisions/0003-credentials-from-environment.md); the files go
to the git-ignored `chipdata/`):

```bash
python3 experiments/fetch_chip_data.py
/tmp/test_chip_data chipdata/ibm_fez-configuration.json chipdata/ibm_fez-properties.json
```

Real hardware, which spends QPU time (about 3 seconds for both kernels). Set the two pass
marks before the run; the script refuses to start without the last flag
([architecture.md](architecture.md) §9.8):

```bash
CUDAQ_LOG_LEVEL=info python3 /src/cudaq-ibm-backend/tests/run_ibm_hardware.py \
  --ghz-mark 0.88 --order-mark 0.95 --yes-spend-qpu-time
```

The gate rules on real hardware: one job, ten qubits, one certain answer
([architecture.md](architecture.md) §7). Rehearse it for free first, then set the mark and
run it. Every qubit must give its expected bit in at least that share of the shots; a wrong
rule leaves a qubit at about half, readout noise costs a few percent (2026-11-11 on
`ibm_fez`, mark 0.85: the lowest qubit was at 97.5%):

```bash
python3 /src/cudaq-ibm-backend/tests/run_ibm_hardware_gates.py --qubit-mark 0.90 --fake
python3 /src/cudaq-ibm-backend/tests/run_ibm_hardware_gates.py --qubit-mark 0.90 --yes-spend-qpu-time
```

With the installed wheel in the plain container of §7 (the script reads `.env` itself; the
rehearsal needs the fake server's packages):

```bash
podman exec cudaq-ibm-rc pip install -q fastapi uvicorn python-multipart
podman exec -e CUDAQ_IBM_PLUGIN=installed cudaq-ibm-rc python -W ignore /repo/tests/run_ibm_hardware_gates.py --qubit-mark 0.90 --fake
podman exec -e CUDAQ_IBM_PLUGIN=installed cudaq-ibm-rc python -W ignore /repo/tests/run_ibm_hardware_gates.py --qubit-mark 0.90 --yes-spend-qpu-time
```

The limits on real hardware ([architecture.md](architecture.md) §8 item 9): how wide a GHZ
chain and how many `cx` in a row survive the noise, and what IBM answers to a NaN angle.
Ten jobs. It measures, there is no pass mark: write down what you expect before the run.
The script waits 13 s between jobs, because IBM takes 5 jobs per minute. First the free
rehearsal; every line it prints must show 100%, and the NaN angle must be refused:

```bash
podman exec cudaq-ibm-rc pip install -q fastapi uvicorn python-multipart
podman exec -e CUDAQ_IBM_PLUGIN=installed cudaq-ibm-rc python -W ignore /repo/tests/run_ibm_hardware_limits.py --fake
```

Without Stim the rehearsal skips chains of more than 24 qubits and says so. Stim has no
ready wheel for Linux aarch64 (the container on a Mac): `pip install stim` builds it there
and needs `g++` (`apt-get update && apt-get install -y g++` in the container) **[V]**
2026-11-12, `stim` 1.16.0, Python 3.12. Then, on its own, the real run, which spends QPU
time:

```bash
podman exec -e CUDAQ_IBM_PLUGIN=installed cudaq-ibm-rc python -W ignore /repo/tests/run_ibm_hardware_limits.py --yes-spend-qpu-time
```

Run the two blocks one after the other, and the real run only when the rehearsal passed:
on 2026-11-12 both were pasted at once and the real run started after a rehearsal that had
failed. (A pasted line that starts with `#` gives `zsh: command not found: #` on a Mac;
that is harmless.) The result of that run on `ibm_fez` is in
[architecture.md](architecture.md) §9.8, run 5.

To see where a chain ran, add `--trace` (width part): for each job it prints the links and
qubits with the highest errors in IBM's calibration data, what that data alone predicts,
and the IBM qubits of every weak pair. One login and one GET more, no extra job. The
rehearsal at 20 qubits, which needs no Stim, then a free check that IBM hands out its
calibration data (the rehearsal cannot show that: it asks the fake server), then two
widths again as two real jobs:

```bash
podman exec -e CUDAQ_IBM_PLUGIN=installed cudaq-ibm-rc python -W ignore /repo/tests/run_ibm_hardware_limits.py --parts width --widths 20 --trace --fake
```

```bash
podman exec cudaq-ibm-rc python /repo/tests/hardware_trace.py ibm_fez
```

```bash
podman exec -e CUDAQ_IBM_PLUGIN=installed cudaq-ibm-rc python -W ignore /repo/tests/run_ibm_hardware_limits.py --parts width --widths 20,40 --trace --yes-spend-qpu-time
```

Fewer jobs: `--parts depth`, `--widths 5,20`, `--depths 1,101`. The check of IBM's limit of
5 jobs per minute is not in the default parts: `--parts rate-limit` sends six one-shot jobs
without a pause.

## 5. Optional: VS Code inside the container

1. Install the **Dev Containers** extension on the Mac. Point it at Podman
   with `"dev.containers.dockerPath": "podman"`, and run
   `sudo podman-mac-helper install` once so `/var/run/docker.sock` works.
2. With `cudaq-ibm` running: **Dev Containers: Attach to Running Container…** →
   `cudaq-ibm`, then open `/src/cudaq-ibm-backend`.
3. In the container: `apt-get update && apt-get install -y clangd`, and install
   the **clangd** extension in the container window.
   `.vscode/settings.json` points clangd at
   `/work/cuda-quantum/build/compile_commands.json`.
4. **Cmd+Shift+B** runs the `ibm: build` task from `.vscode/tasks.json`.
   Errors show in the Problems panel.

If `podman ps` doesn't list `cudaq-ibm`, the container has stopped. Run
`podman start cudaq-ibm` before attaching.

## 6. Without the dev container: build against the pip wheel (a minute)

The pip `cudaq` package has the CUDA-Q libraries but no C++ headers. The script
`plugin/build_against_wheel.sh` takes the headers from the CUDA-Q git commit the installed
wheel was built from (the wheel reports it in `cudaq.__version__`) and links against the
wheel's `libcudaq-common.so` and `libcudaq-logger.so`. It is one `g++` call. Why the plugin
is built this way: [decision 0013](decisions/0013-build-against-the-pip-wheel.md).

Needs Linux (x86_64 is tested), `g++` with C++20, `git`, and Python 3.11 to 3.14. From the
repository root:

```bash
python3 -m venv .venv-plugin && source .venv-plugin/bin/activate
pip install cudaq==0.16.0 fastapi uvicorn python-multipart
plugin/build_against_wheel.sh              # writes build/external/ibm
python3 tests/fake_ibm_server.py 62455 &   # the fake IBM server
python3 tests/run_fake_ibm.py              # eight OK lines, as in §4
python3 tests/run_fake_ibm_results.py      # 26 OK lines: results against CUDA-Q's simulator
```

The first build downloads the headers (about 50 MB, kept in `build/cache`); later builds
take about 20 seconds. The CI job `plugin` runs exactly these steps for every `cudaq`
release the plugin supports.

The limit probes ([architecture.md](architecture.md) §8 item 9) run the same way, by hand,
not in CI. 215 probes, each in its own process, about 5 minutes on 4 cores:

```bash
pip install stim                                        # checks circuits too wide to simulate
python3 experiments/limits/run.py                       # everything
python3 experiments/limits/run.py gates api --only mz   # some groups, some probes
python3 experiments/limits/run.py --report /tmp/report.md
```

Each line starts with the outcome: `same` (equal to CUDA-Q's simulator), `WRONG`, `error`
(with the message the user sees), `CRASH` or `HANG`. Several probes are meant to end in
`error` or `HANG`: compare a new report with
`experiments/limits/report-2026-11-12.md`, do not expect all `same`. With the installed
wheel: `CUDAQ_IBM_PLUGIN=installed`, as for the other scripts.

Limits: the library runs on systems whose C library is at least as new as the build
machine's, so a file built on Ubuntu 24.04 is not a release build. On aarch64 the script
runs in the workflow of §7 **[V]**; macOS is not tested **[U]**.

## 7. The wheel and a release

The wheel is what a user installs: one file that `pip` puts next to pip `cudaq`. It holds
the library of §6, the target file and a small Python package, `cudaq_ibm_plugin`, whose
only job is to tell CUDA-Q where the two are. `import cudaq` finds it through the entry
point `cudaq.backends` **[V]** pip `cudaq` 0.16.0, `cudaq/__init__.py`.

```bash
plugin/build_wheel.sh                      # writes dist/cudaq_ibm-<version>-py3-none-<platform>.whl
plugin/test_wheel.sh dist/*.whl 0.16.0     # fresh environment: install, then the tests of §6 with the installed plugin
```

`test_wheel.sh` makes four checks: `cudaq.has_target("ibm")` right after `pip install`,
the eight protocol cases, the 26 result kernels, and
`python -m cudaq_ibm_plugin --install-nvqpp` (it links the package into
`~/.local/share/cudaq/plugins/ibm`, where the C++ compiler `nvq++` looks). The scripts in
`tests/` use the installed plugin when `CUDAQ_IBM_PLUGIN=installed` is set, and refuse to
run if a local build and an installed wheel could mix (`tests/plugin_under_test.py`).

**Why the file name matters.** The end of the name says where the wheel may be installed:

| Tag | Meaning |
|---|---|
| `py3-none` | Any Python 3: the library is C++ and does not depend on the Python version |
| `manylinux_2_28_x86_64` | Linux on x86_64 with glibc 2.28 or newer. The same tag as pip `cudaq` itself |
| `linux_x86_64` | This machine only. What you get when you build outside the old image |

A library asks the system's C library (glibc) for functions by version. Built on Ubuntu
24.04 it asks for glibc 2.38 and does not load on anything older **[V]** `objdump -T` on
that build, 2026-11-10; pip `cudaq` itself was built with GCC 12.2.1 for glibc 2.28 **[V]**
`readelf` on its libraries. So release wheels are built inside `quay.io/pypa/manylinux_2_28`, the image the Python
community keeps for this: an old Linux (glibc 2.28) with a current compiler.
`plugin/packaging/wheel_platform.py` reads what the built library asks for and gives it
the tag `manylinux_2_28` only if that is true; the release build fails otherwise.

**The workflow** `.github/workflows/wheels.yml` runs on every pull request, on `main` and
on version tags:

| Job | What it does |
|---|---|
| `build` (x86_64, aarch64) | `build_wheel.sh` inside the manylinux image, against `cudaq` 0.16.0, the oldest release the wheel supports |
| `test` (2 machines x 2 systems) | `test_wheel.sh` with that wheel: on the oldest system it claims (the manylinux image, Python 3.11, `cudaq` 0.16.0) and on a current one (Ubuntu 24.04, Python 3.14, `cudaq` 0.16.0.post1) |
| `release` (tags only) | Checks that the tag is `v` + the version in the wheels, then creates a GitHub Release with the two wheels |

First green run, 2026-11-11 **[V]**
[run 43100474789](https://github.com/brunopacheco1/cudaq-ibm-backend/actions/runs/43100474789):
the image has GCC 14.2.1 and glibc 2.28, both wheels got the tag `manylinux_2_28`, and all
four `test` jobs passed. First release, the same day **[V]**
[run 43106367874](https://github.com/brunopacheco1/cudaq-ibm-backend/actions/runs/43106367874):
the tag `v0.1.0rc1` built and tested both wheels again and the `release` job created the
pre-release [v0.1.0rc1](https://github.com/brunopacheco1/cudaq-ibm-backend/releases/tag/v0.1.0rc1).

**To make a release** (Bruno):

1. Set `version` in `plugin/packaging/pyproject.toml`, merge.
2. Tag that commit on `main` and push the tag: `git tag v0.1.0rc1 && git push origin v0.1.0rc1`.
3. The workflow builds, tests and publishes. A version with letters (`0.1.0rc1`) becomes
   a pre-release.

A release cannot be taken back cleanly once someone has downloaded it: make a new version
instead of replacing files. The same holds for a tag: if the release job fails, fix it and
tag the next version; do not move the tag.

**To try a release as a stranger would**, in a plain Python container (Podman or Docker;
on an Apple Silicon Mac this is Linux aarch64). Run it from your clone: `-v "$PWD"` gives
the container the folder you are in, and from your home folder that would be all your
files.

```bash
cd cudaq-ibm-backend
podman run -d --name cudaq-ibm-rc -v "$PWD":/repo:ro docker.io/library/python:3.12-slim sleep infinity
podman exec cudaq-ibm-rc bash -c 'pip install -q cudaq "https://github.com/brunopacheco1/cudaq-ibm-backend/releases/download/v0.1.0rc1/cudaq_ibm-0.1.0rc1-py3-none-manylinux_2_28_$(uname -m).whl"'
podman exec cudaq-ibm-rc python -W ignore -c 'import cudaq; print(cudaq.has_target("ibm"))'       # True
podman exec -w /tmp cudaq-ibm-rc python -W ignore /repo/examples/expectation_from_samples.py      # simulator, free
# Real hardware, three jobs: this spends QPU time. The credentials come from .env.
podman exec -w /tmp cudaq-ibm-rc bash -c 'set -a; . /repo/.env; set +a; python -W ignore /repo/examples/expectation_from_samples.py --target ibm --yes-spend-qpu-time'
podman rm -f cudaq-ibm-rc
```

This passed on 2026-11-11 with `v0.1.0rc1` **[V]**; the hardware result is in
[architecture.md](architecture.md) §9.8.

Not covered: macOS (open item, [decision 0014](decisions/0014-first-release-for-linux-x86-64-and-aarch64.md));
`nvq++` itself (pip `cudaq` has no `nvq++`, so only the link is checked) **[U]**; PyPI
([decision 0015](decisions/0015-github-release-first-settle-the-name-before-pypi.md): the
name must be settled first).
