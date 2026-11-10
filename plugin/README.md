# `ibm` plugin for CUDA-Q

The C++ part of this project: a CUDA-Q backend plugin that runs kernels on IBM Quantum.
It started as a copy of CUDA-Q's `mock_rest` example plugin (see `../NOTICE`).

Status: M1 done (IBM login, submit, poll, results), M2 done (gate rewrite, first `ibm_fez` run). M3 done on
hardware (routing; GHZ-5 on `ibm_fez`, 2026-11-10; [../docs/roadmap.md](../docs/roadmap.md)).
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
| `python/`, `pyproject.toml.in` | Python package with a `cudaq.backends` entry point (still named `cudaq_example_ibm`; renamed in M4). |
| `tests/test_qasm2_to_isa.cpp`, `tests/test_layout.cpp`, `tests/test_chip_data.cpp`, `tests/test_result_bits.cpp` | Unit tests for the four headers. Plain `g++`, no CUDA-Q needed (run `test_layout` from the repo root; `test_chip_data` needs nlohmann/json). |
| `tests/check_plugin.cpp`, `tests/lit.*` | Lit test inherited from `mock_rest` (`ninja check-ibm`). |

## Build

Inside the dev container ([../docs/development.md](../docs/development.md)), from the CUDA-Q
source tree:

```sh
cd /work/cuda-quantum
cmake -B build -DCUDAQ_EXTERNAL_PROJECTS=ibm \
  -DCUDAQ_EXTERNAL_IBM_SOURCE_DIR=/src/cudaq-ibm-backend/plugin
ninja -C build -j 2 cudaq-example-serverhelper-ibm
```

Output: `build/external/ibm/` with `targets/ibm.yml`, `lib/libcudaq-serverhelper-ibm.so` and
the Python package files.

## Use

```sh
export IBM_QUANTUM_API_KEY=...   # never as a target argument
export IBM_QUANTUM_CRN=crn:v1:...
```

```python
import cudaq

cudaq.register_backend_path("build/external/ibm")   # not needed once pip-installed (M4)
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
`emulate=True` and `observe`. Known limits: [../docs/m3-spec.md](../docs/m3-spec.md) §2.10-§2.13.

## Test

```sh
# Header unit tests (any machine with g++, also in CI), from the repo root:
for t in qasm2_to_isa layout result_bits chip_data; do
  g++ -std=c++20 -I plugin plugin/tests/test_$t.cpp -o /tmp/test_$t && /tmp/test_$t
done

# End to end against the fake IBM server: see ../docs/development.md §4.
```

`ninja -C build check-ibm` runs the inherited lit test. **Unverified:** it calls
`set_target('ibm')` without IBM credentials, which `initialize` now refuses, so it probably
fails until it is adapted (M4).

## Install as a package (M4, not ready)

The build output is a Python package (`python3 -m pip install build/external/ibm`), and
`python3 -m cudaq_example_ibm --install-nvqpp` registers it for `nvq++`. Whether a plugin
built in the dev container loads into a pip-installed `cudaq` (ABI match) is not tested yet.
