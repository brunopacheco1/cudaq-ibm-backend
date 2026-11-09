# cudaq-ibm-backend

Run [CUDA-Q](https://github.com/NVIDIA/cuda-quantum) kernels on IBM Quantum hardware.

CUDA-Q is NVIDIA's open-source, vendor-neutral quantum SDK. It supports many
hardware providers, but **IBM is not one of them**. This project adds that
missing link. It is also a learning project, so the code explains the
quantum ideas behind each step.

> **Status.** Phase 1, the Python prototype, ran a Bell pair on `ibm_fez` on
> 2026-11-05: 95% of 1000 shots were correlated, as expected. Phase 2, the
> C++ CUDA-Q plugin, is in progress. M1 (IBM login, job submit, poll and
> results) works against a fake IBM server. M2 (rewriting circuits into IBM's
> native gates) handles `h` and `cx`. Expect breaking changes.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate   # Python 3.11 to 3.14 (CUDA-Q has no 3.15 wheels yet)
pip install -e ".[local]"      # Linux, WSL or Apple Silicon Mac (macOS 13+)
python examples/bell.py        # ideal vs. noisy IBM simulation, no account needed
```

```python
import cudaq
from cudaq_ibm import simulate_locally, run_on_ibm

@cudaq.kernel
def bell():
    q = cudaq.qvector(2)
    h(q[0]); cx(q[0], q[1])
    mz(q)

simulate_locally(bell).counts                 # {'00': 483, '11': 484, '01': 17, '10': 16}
run_on_ibm(bell, backend="ibm_fez").counts    # real hardware, needs credentials
```

## How it works

```
CUDA-Q kernel ──► OpenQASM 2 ──► Qiskit circuit ──► ISA circuit ──► OpenQASM 3
   (convert.py)                                       (isa.py)          │
                                                                        ▼
CUDA-Q style counts ◄── hex samples ◄── IBM Sampler job (REST, client.py)
   (results.py)
```

1. **Export** (`convert.py`). CUDA-Q prints the kernel as OpenQASM 2, a text
   format for circuits. Kernels with arguments are first *synthesized*: the
   argument values are baked into the circuit.
2. **Make it hardware-ready** (`isa.py`). A real chip runs only a few
   *native gates* (IBM Heron: `cz`, `rz`, `sx`, `x`). Two-qubit gates work only
   between physically wired qubits (the *coupling map*). The transpiler
   rewrites the circuit to respect both. The result is an *ISA circuit*, and
   IBM rejects anything else. Run `examples/bell.py` to see a CNOT become
   `rz`/`sx` gates around a `cz`.
3. **Submit** (`client.py`). These are plain HTTP calls to IBM's REST API.
   They swap an API key for a token, read the chip's configuration, `POST
   /v1/jobs` with the `sampler` program, poll, and fetch results. We avoid
   `qiskit-ibm-runtime` here on purpose, because the future C++ plugin must
   make the same calls.
4. **Decode** (`results.py`). IBM returns one hex string per shot. Qiskit and
   IBM are little-endian: bit 0 is the **right-most** character. CUDA-Q puts
   qubit 0 **left-most**. So `x(q[0])` on 3 qubits is `"001"` in Qiskit and
   `"100"` in CUDA-Q. We flip each register to match CUDA-Q.

## Develop the C++ plugin (Linux container)

The C++ plugin in `plugin/` builds **inside CUDA-Q's own source tree**. The
pip `cudaq` package has no C++ headers or CMake files, so you need a source
build of CUDA-Q 0.16. Do it in NVIDIA's dev container. A native macOS build
fails today, because the Xcode 27 SDK's `arm64e.x1` is unreadable by LLVM 22's
linker.

The examples use Podman on an Apple Silicon Mac. Docker works the same way:
replace `podman` with `docker`.

### Layout

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

### 1. One time: Podman machine

The full build needs about 8 GB of RAM. With less, `ConvertExpr.cpp` runs out
of memory.

```bash
brew install podman krunkit
podman machine init
podman machine set --cpus 6 --memory 8192
podman machine start
```

### 2. One time: build CUDA-Q 0.16 from source (hours)

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

### 3. Every day: start, attach, stop

```bash
podman machine start
podman start cudaq-ibm
podman exec -it cudaq-ibm bash
podman stop cudaq-ibm
```

Run `podman exec` again for each extra shell. If you ever need to recreate
the container (`podman rm cudaq-ibm`, then the `podman run` from step 2), the
CUDA-Q build in the volume is kept. Only the `.bashrc` lines and apt packages
must be redone.

### 4. Build and test the plugin (seconds)

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

The expected output ends with `OK: ISA rewrite, auth, submit, poll and
bit-order decoding all work.` Add `CUDAQ_LOG_LEVEL=info` to see the ISA
circuit the plugin sends.

The gate-rewrite unit test needs no CUDA-Q and also runs in CI:

```bash
g++ -std=c++20 -I plugin plugin/tests/test_qasm2_to_isa.cpp -o /tmp/test_isa && /tmp/test_isa
```

### 5. Optional: VS Code inside the container

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

## Credentials

You need an [IBM Quantum Platform](https://quantum.cloud.ibm.com) account. The
free Open Plan gives about 10 minutes of QPU time per rolling 28 days.

Put two values in a `.env` file at the repo root (it is git-ignored), or
export them as environment variables. Never commit them or paste them
anywhere public.

```bash
# .env
IBM_QUANTUM_API_KEY=...        # IBM Cloud API key
IBM_QUANTUM_CRN=crn:v1:...     # your instance's CRN (instance page)
```

```bash
python examples/bell.py ibm_fez
```

## Tests

```bash
pip install -e ".[test]"
pytest
```

The tests never touch IBM. A fake REST server (`responses`) stands in for
IBM, and a fake chip (`FakeFez`) stands in for the hardware.

## Known limits (phase 1)

- Only the Sampler (counts). No Estimator (expectation values) yet.
- The transpiler ignores qubit error rates, so it may pick noisy qubits.
- There is no error mitigation, sessions or batching.

## Roadmap

1. **Python prototype** (done). The go/no-go point was one successful real-QPU run.
2. **C++ plugin.** This uses CUDA-Q 0.16's [backend plugin
   framework](https://nvidia.github.io/cuda-quantum/0.16.0/using/extending/backend.html):
   a `ServerHelper` subclass, a `targets/ibm.yml` file and CMake, installed with
   pip. Then `cudaq.set_target("ibm")` works like any other provider. The
   design and milestones (M0-M5) are in
   [docs/phase3-design.md](docs/phase3-design.md). To build it, see
   [Develop the C++ plugin](#develop-the-c-plugin-linux-container).
3. **Docs, a blog post**, and a conversation with the CUDA-Q maintainers.

## License

Apache-2.0, the same license as CUDA-Q and Qiskit.
