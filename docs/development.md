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
podman exec -it cudaq-ibm bash
podman stop cudaq-ibm
```

Run `podman exec` again for each extra shell. If you ever need to recreate
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

The expected output ends with `OK: ISA rewrite, auth, submit, poll and
bit-order decoding all work.` Add `CUDAQ_LOG_LEVEL=info` to see the ISA
circuit the plugin sends.

The gate-rewrite unit test needs no CUDA-Q and also runs in CI:

```bash
g++ -std=c++20 -I plugin plugin/tests/test_qasm2_to_isa.cpp -o /tmp/test_isa && /tmp/test_isa
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
