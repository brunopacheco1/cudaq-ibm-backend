# `ibm` plugin for CUDA-Q

The C++ part of this project: a CUDA-Q backend plugin that runs kernels on IBM Quantum.
It started as a copy of CUDA-Q's `mock_rest` example plugin (see `../NOTICE`).

Status: M1 done (IBM login, submit, poll, results), M2 done (gate rewrite, first `ibm_fez` run). M3 done on
hardware (routing; GHZ-5 on `ibm_fez`, 2026-11-10). M4 done (results checked in CI, the wheel, first release
`v0.1.0rc1` and a hardware run from it, 2026-11-11; [../docs/roadmap.md](../docs/roadmap.md)).
How it works: [../docs/architecture.md](../docs/architecture.md).

## Files

| File | Role |
|---|---|
| `IBMServerHelper.cpp` | The `cudaq::ServerHelper` for IBM: IAM login, job body, polling, result decoding. Details: [../docs/architecture.md](../docs/architecture.md) §2-§4. |
| `Qasm2ToIsa.h` | Rewrites CUDA-Q's OpenQASM 2 into IBM's native gates, as OpenQASM 3. Header-only. |
| `Layout.h` | M3 routing: usable region, root, best-first numbering, device file, label -> qubit search. Header-only. |
| `ChipData.h` | M3: IBM's `/configuration` and `/properties` replies -> the chip `Layout.h` works on. Stops or marks broken what it cannot read. Header-only. |
| `ResultBits.h` | IBM's hex samples -> CUDA-Q bit strings, keeping the measured qubits. Header-only. |
| `targets/ibm.yml.in` | The target: compiler pipeline and target arguments. |
| `CMakeLists.txt` | Builds the plugin as a CUDA-Q external project. |
| `build_against_wheel.sh` | Builds the plugin against the pip `cudaq` wheel, without a CUDA-Q source build. CI uses it. |
| `build_wheel.sh`, `test_wheel.sh`, `packaging/` | The wheel: Python package `cudaq_ibm_plugin` with a `cudaq.backends` entry point, built around the library and tested as installed ([../docs/development.md](../docs/development.md) §7). |
| `tests/test_qasm2_to_isa.cpp`, `tests/test_layout.cpp`, `tests/test_chip_data.cpp`, `tests/test_result_bits.cpp` | Unit tests for the four headers. Plain `g++`, no CUDA-Q needed (run `test_layout` from the repo root; `test_chip_data` needs nlohmann/json). |

## Build

The quick way, on any Linux with `g++` and a Python environment that has `cudaq`
([../docs/development.md](../docs/development.md) §6), from the repository root:

```sh
plugin/build_against_wheel.sh    # writes build/external/ibm, about a minute
```

The documented CUDA-Q way, inside the dev container, from the CUDA-Q source tree:

```sh
cd /work/cuda-quantum
cmake -B build -DCUDAQ_EXTERNAL_PROJECTS=ibm \
  -DCUDAQ_EXTERNAL_IBM_SOURCE_DIR=/src/cudaq-ibm-backend/plugin
ninja -C build -j 2 cudaq-example-serverhelper-ibm
```

Output: `build/external/ibm/` with `targets/ibm.yml` and `lib/libcudaq-serverhelper-ibm.so`.

## Use

```sh
export IBM_QUANTUM_API_KEY=...   # never as a target argument
export IBM_QUANTUM_CRN=crn:v1:...
```

```python
import cudaq

cudaq.register_backend_path("build/external/ibm")   # a local build; not needed with the installed wheel
cudaq.set_target("ibm", backend="ibm_fez")

@cudaq.kernel
def bell():
    q = cudaq.qvector(2)
    h(q[0]); cx(q[0], q[1])
    mz(q)

print(cudaq.sample(bell, shots_count=1000))
```

Target arguments: `backend` (default `ibm_fez`), `url` (default
`https://quantum.cloud.ibm.com/api`), `iam_url` (tests only), `mapping_file` (a device file to
route on instead of the chip data from IBM; tests). Set `CUDAQ_LOG_LEVEL=info` to see the
circuit sent and the raw results.

Kernels made of `x`, `y`, `z`, `h`, `rx`, `ry`, `rz`, `u3` and `cx` (and gates CUDA-Q turns
into those, such as `s`, `t` and `cz`) are accepted; anything else throws. Since M3 the kernel
is routed onto the chip, around qubits and links IBM reports as broken. Not supported yet:
`emulate=True` and `cudaq.observe`; both stop with an error that says so. Known limits: [../docs/architecture.md](../docs/architecture.md) §8.

## Test

```sh
# Header unit tests (any machine with g++, also in CI), from the repo root:
for t in qasm2_to_isa layout result_bits chip_data; do
  g++ -std=c++20 -I plugin plugin/tests/test_$t.cpp -o /tmp/test_$t && /tmp/test_$t
done

# End to end against the fake IBM server: see ../docs/development.md §4.
```

## Install as a package

Users install the wheel from a release of this repository (see the README at the
repository root). To build and test it: [../docs/development.md](../docs/development.md) §7.

```sh
plugin/build_wheel.sh                    # writes dist/cudaq_ibm-<version>-py3-none-<platform>.whl
plugin/test_wheel.sh dist/*.whl 0.16.0   # install in a fresh environment and run the tests
```

`python3 -m cudaq_ibm_plugin --install-nvqpp` links the installed package into the folder
where `nvq++` looks for plugins. The link is tested; `nvq++` with this plugin is not
**[U]**.
