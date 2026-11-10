# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""M3 hardware session: two small jobs on a real IBM backend. SPENDS QPU TIME.

Run it only after tests/run_fake_ibm.py passes, and only with pass marks
that were set before the run (docs/m3-spec.md, section 6, step 3):

    cd /work/cuda-quantum
    python3 /src/cudaq-ibm-backend/tests/run_ibm_hardware.py \\
        --ghz-mark 0.80 --order-mark 0.90 --yes-spend-qpu-time

1. GHZ-5, 1000 shots: the share of 00000 + 11111 must reach --ghz-mark.
2. A kernel whose answer is not symmetric, 200 shots: x on q0, then measure
   q2 before q0. CUDA-Q's contract gives "10" (q0, q2 in allocation order).
   A wrong bit order gives "01". The share of "10" must reach --order-mark.

Credentials: IBM_QUANTUM_API_KEY and IBM_QUANTUM_CRN from the environment,
or from the git-ignored .env at the repository root. They are never printed.
With CUDAQ_LOG_LEVEL=info the plugin also logs the label -> qubit map and
the circuit it sends. At that level CUDA-Q logs request bodies, not headers
(RestClient.cpp, tag 0.16.0), and the plugin never logs the key or the token.
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env_file() -> None:
    """Read KEY=VALUE lines from .env for variables that are not set yet."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def share(counts, keys, shots: int) -> float:
    return sum(counts.count(k) for k in keys) / shots


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backend", default="ibm_fez")
    parser.add_argument("--ghz-mark", type=float, required=True,
                        help="lowest accepted share of 00000 + 11111")
    parser.add_argument("--order-mark", type=float, required=True,
                        help="lowest accepted share of 10")
    parser.add_argument("--yes-spend-qpu-time", action="store_true",
                        help="required: confirms that real jobs may be sent")
    args = parser.parse_args()
    if not args.yes_spend_qpu_time:
        print("Refusing to run: add --yes-spend-qpu-time to send real jobs.")
        return 2

    load_env_file()
    for name in ("IBM_QUANTUM_API_KEY", "IBM_QUANTUM_CRN"):
        if not os.environ.get(name):
            print(f"Set {name} (environment or .env).")
            return 2

    import cudaq

    cudaq.register_backend_path("build/external/ibm")
    cudaq.set_target("ibm", backend=args.backend)

    ghz = cudaq.make_kernel()
    q = ghz.qalloc(5)
    ghz.h(q[0])
    for i in range(4):
        ghz.cx(q[i], q[i + 1])
    ghz.mz(q)
    shots = 1000
    counts = cudaq.sample(ghz, shots_count=shots)
    print("GHZ-5:", counts)
    ghz_share = share(counts, ("00000", "11111"), shots)
    ghz_ok = ghz_share >= args.ghz_mark
    print(f"{'PASS' if ghz_ok else 'FAIL'}: GHZ-5 00000 + 11111 = "
          f"{ghz_share:.1%} (mark {args.ghz_mark:.0%})")

    order = cudaq.make_kernel()
    q = order.qalloc(3)
    order.x(q[0])
    order.mz(q[2])
    order.mz(q[0])
    shots = 200
    counts = cudaq.sample(order, shots_count=shots)
    print("x(q0), mz(q2), mz(q0):", counts)
    order_share = share(counts, ("10",), shots)
    order_ok = order_share >= args.order_mark
    print(f"{'PASS' if order_ok else 'FAIL'}: bit order, '10' = "
          f"{order_share:.1%} (mark {args.order_mark:.0%}); "
          f"'01' = {share(counts, ('01',), shots):.1%}")
    return 0 if ghz_ok and order_ok else 1


if __name__ == "__main__":
    sys.exit(main())
