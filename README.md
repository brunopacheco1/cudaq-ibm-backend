# cudaq-ibm-backend

Run [CUDA-Q](https://github.com/NVIDIA/cuda-quantum) kernels on IBM Quantum hardware.

CUDA-Q is NVIDIA's open-source, vendor-neutral quantum SDK. It supports many
hardware providers, but **IBM is not one of them**. This project adds that
missing link. It is also a learning project, so the code explains the
quantum ideas behind each step.

> **Status.** Early and unofficial: a learning project, not affiliated with IBM or
> NVIDIA. The C++ plugin runs `cudaq.sample` on IBM hardware: on `ibm_fez` a Bell pair
> gave 94% of 1000 shots correlated (2026-11-09) and a 5-qubit GHZ state 90% of 1000
> shots in `00000` or `11111` (2026-11-10). It is packaged as a wheel for Linux; the first
> release is the pre-release `v0.1.0rc1`, and with that wheel a Bell pair on `ibm_fez`
> reached a fidelity of 0.958 (2026-11-11). Not supported yet: `cudaq.observe`,
> `emulate=True`, macOS. Known bug of `v0.1.0rc1`: a kernel with `mz` on 50 or more
> qubits does not compile; leave the `mz` out (fixed on `main`). Expect breaking changes.
> Milestones and risks: [docs/roadmap.md](docs/roadmap.md).

## Install

You need Linux (x86_64 or aarch64, glibc 2.28 or newer) and Python 3.11 to 3.14: the same
as pip `cudaq` 0.16. On a Mac, use a Linux container.

Wheels are attached to the
[releases](https://github.com/brunopacheco1/cudaq-ibm-backend/releases) of this
repository. Replace `<version>` with the release you want (the first one is `0.1.0rc1`):

```bash
pip install cudaq
pip install "https://github.com/brunopacheco1/cudaq-ibm-backend/releases/download/v<version>/cudaq_ibm-<version>-py3-none-manylinux_2_28_$(uname -m).whl"
```

That is all: `import cudaq` finds the plugin by itself. To build the wheel yourself, see
[docs/development.md](docs/development.md) §7. The package is not on PyPI, and its name
`cudaq-ibm` is a working name.

## Use

Credentials come from two environment variables, never from code (see
[Credentials](#credentials)).

```python
import cudaq

cudaq.set_target("ibm", backend="ibm_fez")

@cudaq.kernel
def bell():
    q = cudaq.qvector(2)
    h(q[0])
    cx(q[0], q[1])
    mz(q)

print(cudaq.sample(bell, shots_count=1000))   # sends a job: this spends QPU time
```

What happens on the way: CUDA-Q routes the kernel onto the chip's wiring, around qubits
and links IBM reports as broken; the plugin rewrites it into IBM's native gates (`rz`,
`sx`, `x`, `cz`), sends it to IBM's Sampler and turns the answer back into CUDA-Q's bit
order. How: [docs/architecture.md](docs/architecture.md).

- Works: `cudaq.sample`, with kernels made of `x`, `y`, `z`, `h`, `s`, `sdg`, `t`, `tdg`,
  `rx`, `ry`, `rz`, `r1`, `u3`, `cx`, `cz` and `swap` (each one is in the result checks
  of CI).
- Refused with a clear error: `cudaq.observe` and `emulate=True`. For expectation values,
  [examples/expectation_from_samples.py](examples/expectation_from_samples.py) shows how
  to compute them from `sample` counts.
- Known limits: [docs/architecture.md](docs/architecture.md) §8.

## The Python prototype

Phase 1 of this project was a prototype in Python (`src/cudaq_ibm`), which uses Qiskit for
the hardware-ready step. It ran the first Bell pair on `ibm_fez` on 2026-11-05 (95% of
1000 shots correlated). It stays in the repository as a readable reference; it is not in
the wheel.

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

How the prototype works:

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

## Develop the C++ plugin

The plugin is in `plugin/`. It builds in about a minute against the pip `cudaq`
([docs/development.md](docs/development.md) §6), or inside a CUDA-Q source build in
NVIDIA's Linux dev container (§1 to §4, for work on CUDA-Q itself). How the plugin works:
[docs/architecture.md](docs/architecture.md).

## Credentials

You need an [IBM Quantum Platform](https://quantum.cloud.ibm.com) account. The
free Open Plan gives about 10 minutes of QPU time per rolling 28 days.

The plugin reads two environment variables. Never put the values in code, commit them or
paste them anywhere public.

```bash
export IBM_QUANTUM_API_KEY=...        # IBM Cloud API key
export IBM_QUANTUM_CRN=crn:v1:...     # your instance's CRN (instance page)
```

The prototype and the scripts in `tests/` that talk to real hardware also read them from a
`.env` file at the repository root (it is git-ignored):

```bash
python examples/bell.py ibm_fez
```

## Tests

```bash
pip install -e ".[test]"
pytest
```

The tests never touch IBM. A fake IBM server (`tests/fake_ibm_server.py`) stands in for
IBM: it checks every circuit against the wiring of `ibm_fez` and simulates it, so CI
compares the plugin's results with CUDA-Q's own simulator. All commands:
[docs/development.md](docs/development.md).

## Known limits of the prototype

- Only the Sampler (counts). No Estimator (expectation values).
- The transpiler ignores qubit error rates, so it may pick noisy qubits.
- There is no error mitigation, sessions or batching.

## Roadmap

1. **Python prototype** (done). The go/no-go point was one successful real-QPU run.
2. **C++ plugin** (M0 to M4 done, first pre-release out). It uses CUDA-Q 0.16's [backend plugin
   framework](https://nvidia.github.io/cuda-quantum/0.16.0/using/extending/backend.html):
   a `ServerHelper` subclass and a `targets/ibm.yml` file, installed with pip, so that
   `cudaq.set_target("ibm")` works like any other provider. The milestones (M0-M5) and
   their status are in [docs/roadmap.md](docs/roadmap.md).
3. **Docs, a blog post**, and a conversation with the CUDA-Q maintainers.

## License and trademarks

Apache-2.0, the same license as CUDA-Q and Qiskit. Parts of `plugin/` and `tests/` are
adapted from CUDA-Q, copyright NVIDIA Corporation & Affiliates (see [NOTICE](NOTICE)).

This is an independent project. It is not affiliated with, endorsed by or supported by
IBM or NVIDIA.

IBM, IBM Quantum and Qiskit are trademarks of International Business Machines
Corporation, registered in many jurisdictions worldwide. CUDA-Q is a product of NVIDIA
Corporation. Other names may be trademarks of their owners.
