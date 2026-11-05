"""Run a Bell pair three ways and compare.

    python examples/bell.py            # CUDA-Q ideal + local noisy IBM simulation
    python examples/bell.py ibm_fez    # ...plus a real IBM QPU (uses your QPU minutes)
"""

import sys

import cudaq

from cudaq_ibm import run_on_ibm, simulate_locally


@cudaq.kernel
def bell():
    q = cudaq.qvector(2)
    h(q[0])
    cx(q[0], q[1])
    mz(q)


print("1. CUDA-Q ideal simulator:", dict(cudaq.sample(bell, shots_count=1000).items()))

local = simulate_locally(bell, shots=1000)
print(f"2. Noisy local copy of {local.backend}:", local.counts)
print("   ISA circuit the chip would run:")
print(local.isa_circuit.draw(idle_wires=False))

if len(sys.argv) > 1:
    real = run_on_ibm(bell, backend=sys.argv[1], shots=1000)
    print(f"3. Real {real.backend} (job {real.job_id}):", real.counts)
