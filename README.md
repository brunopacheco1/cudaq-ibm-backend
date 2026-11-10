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
> native gates) is done: on 2026-11-09 the plugin ran a Bell pair on `ibm_fez`
> with 94% of 1000 shots correlated. M3 (routing around broken qubits) ran on
> `ibm_fez` on 2026-11-10: a 5-qubit GHZ state gave 90% of 1000 shots in `00000`
> or `11111`. Expect breaking changes.

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

## Develop the C++ plugin

The C++ plugin in `plugin/` is built inside a CUDA-Q 0.16 source build, in NVIDIA's
Linux dev container. Step-by-step setup, daily use, build and tests:
[docs/development.md](docs/development.md). How the plugin works:
[docs/architecture.md](docs/architecture.md).

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
   milestones (M0-M5) and their status are in
   [docs/roadmap.md](docs/roadmap.md). To build it, see
   [docs/development.md](docs/development.md).
3. **Docs, a blog post**, and a conversation with the CUDA-Q maintainers.

## License

Apache-2.0, the same license as CUDA-Q and Qiskit.
