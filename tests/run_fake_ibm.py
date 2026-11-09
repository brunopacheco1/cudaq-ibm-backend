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

# The M2 rules beyond h and cx. CUDA-Q decomposes to {h, rx, ry, rz, x, z} plus
# cx before the plugin sees the circuit, so this sends the QASM2 text CUDA-Q
# really emits for rx, ry, z and friends (angle formatting included). The fake
# server rejects any line that is not a native gate with a numeric angle.
# Its samples are fixed, so this checks the rewrite is accepted, not physics.
kernel = cudaq.make_kernel()
q = kernel.qalloc(2)
kernel.rx(0.7, q[0])
kernel.ry(-2.3, q[1])
kernel.z(q[0])
kernel.y(q[1])
kernel.s(q[0])
kernel.t(q[1])
kernel.u3(0.3, -1.1, 2.0, q[0])
kernel.cx(q[1], q[0])
kernel.mz(q)

counts = cudaq.sample(kernel, shots_count=3)
print(counts)
assert counts["10"] == 2 and counts["01"] == 1, counts
print("OK: rx, ry, z, y, s, t, u3 rewrite into ISA gates the server accepts.")

# M3: a 20-qubit GHZ chain. The fake server serves ibm_fez's real wiring
# (156 qubits), marks link 62-63 broken and qubit 61 down, and rejects any
# cz that is not on a working link. So acceptance proves the routing, the
# device file and the label -> IBM qubit assignment all work together.
kernel = cudaq.make_kernel()
q = kernel.qalloc(20)
kernel.h(q[0])
for i in range(19):
    kernel.cx(q[i], q[i + 1])
kernel.mz(q)

counts = cudaq.sample(kernel, shots_count=3)
print(counts)
# Same fixed samples, now read as 20 bits.
assert counts["1" + "0" * 19] == 2 and counts["01" + "0" * 18] == 1, counts
print("OK: GHZ-20 routed onto ibm_fez wiring; every cz is on a working link.")

# M3: the mapping_file override (no /configuration fetch). Node ids are IBM
# qubit ids: here the path 0-1-2-3-4, which is wired on ibm_fez.
import tempfile  # noqa: E402

with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
    f.write("Number of nodes: 5\nNumber of edges: 4\n"
            "0 --> {1}\n1 --> {0, 2}\n2 --> {1, 3}\n3 --> {2, 4}\n4 --> {3}\n")
cudaq.set_target("ibm",
                 backend="ibm_fake",
                 url=f"http://localhost:{PORT}/api",
                 iam_url=f"http://localhost:{PORT}/identity/token",
                 mapping_file=f.name)
kernel = cudaq.make_kernel()
q = kernel.qalloc(5)
kernel.h(q[0])
for i in range(4):
    kernel.cx(q[0], q[i + 1])  # a star: needs swaps on a path
kernel.mz(q)

counts = cudaq.sample(kernel, shots_count=3)
print(counts)
assert counts["10000"] == 2 and counts["01000"] == 1, counts
print("OK: mapping_file override routes on the given device file.")
os.remove(f.name)
