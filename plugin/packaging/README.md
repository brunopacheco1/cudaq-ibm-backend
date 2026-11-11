# cudaq-ibm

Run [CUDA-Q](https://github.com/NVIDIA/cuda-quantum) kernels on IBM Quantum hardware.
This package adds the target `ibm` to a pip-installed `cudaq`.

**Unofficial.** A learning project by Bruno Pacheco. It is not affiliated with, endorsed
by or supported by IBM or NVIDIA. Early version: expect breaking changes.

```python
import cudaq

cudaq.set_target("ibm", backend="ibm_fez")

kernel = cudaq.make_kernel()
q = kernel.qalloc(2)
kernel.h(q[0])
kernel.cx(q[0], q[1])
kernel.mz(q)

print(cudaq.sample(kernel, shots_count=1000))   # sends a job, spends QPU time
```

Credentials come from two environment variables, never from code:
`IBM_QUANTUM_API_KEY` (an IBM Cloud API key) and `IBM_QUANTUM_CRN` (the CRN of your
IBM Quantum instance).

Supported: `cudaq.sample` on Linux (x86_64 and aarch64), `cudaq` 0.16. Not supported yet:
`cudaq.observe`, `emulate=True`, macOS. Documentation, limits and source:
https://github.com/brunopacheco1/cudaq-ibm-backend

IBM, IBM Quantum and Qiskit are trademarks of International Business Machines
Corporation, registered in many jurisdictions worldwide. CUDA-Q is a product of NVIDIA
Corporation. Other names may be trademarks of their owners.

License: Apache-2.0. Parts are adapted from CUDA-Q, copyright NVIDIA Corporation &
Affiliates (see NOTICE).
