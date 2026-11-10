# Development: build and test the C++ plugin

Date: 2026-11-09. Status: living document.
Reader: anyone building the plugin. Why a container and not a native Mac build:
[decision 0002](decisions/0002-build-in-linux-dev-container.md).

The C++ plugin in `plugin/` builds **inside CUDA-Q's own source tree**. The
pip `cudaq` package has no C++ headers or CMake files, so you need a source
build of CUDA-Q 0.16. Do it in NVIDIA's dev container.

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

It runs six cases and prints one `OK` line for each: a Bell pair; a kernel with `rx`, `ry`,
`z`, `y`, `s`, `t` and `u3`; a 20-qubit GHZ (routing); a kernel that measures out of order; the
`mapping_file` override; and a backend without `/properties`, which must stop. A last `PROBE`
line shows that `emulate=True` still fails ([architecture.md](architecture.md) §8 item 7).
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
