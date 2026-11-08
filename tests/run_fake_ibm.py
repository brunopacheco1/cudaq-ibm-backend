# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""Run a kernel through the C++ 'ibm' plugin against the fake IBM server.

Start the server first:  python3 tests/fake_ibm_server.py 62455
Then, from /work/cuda-quantum:  python3 /src/cudaq-ibm-backend/tests/run_fake_ibm.py
"""

import os

os.environ["IBM_QUANTUM_API_KEY"] = "test-key"
os.environ["IBM_QUANTUM_CRN"] = "test-crn"

import cudaq  # noqa: E402

PORT = 62455
cudaq.register_backend_path("build/external/ibm")
cudaq.set_target("ibm",
                 backend="ibm_fake",
                 url=f"http://localhost:{PORT}/api",
                 iam_url=f"http://localhost:{PORT}/identity/token")

# A Bell pair: h and cx are NOT native on IBM, so this also exercises the
# M2 rewrite into {rz, sx, x, cz}; the fake server rejects anything else.
kernel = cudaq.make_kernel()
q = kernel.qalloc(2)
kernel.h(q[0])
kernel.cx(q[0], q[1])
kernel.mz(q)

counts = cudaq.sample(kernel, shots_count=3)
print(counts)
# The fake server returns samples 0x1, 0x1, 0x2 (IBM bit order). After the
# plugin reverses bits into CUDA-Q order, that is 10, 10, 01.
assert counts["10"] == 2 and counts["01"] == 1, counts
print("OK: ISA rewrite, auth, submit, poll and bit-order decoding all work.")
