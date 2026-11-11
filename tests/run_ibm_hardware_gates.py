# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""Gate rules on real hardware: one job on a real IBM backend. SPENDS QPU TIME.

The rules for rx, ry, z and y are proven in the unit test and checked against
the simulating fake server. This run asks the last question: do IBM's real
rz, sx and x gates behave like the ones in our simulator?

It sends the kernel of tests/gate_rule_kernel.py: ten qubits, one certain
answer. Each qubit must give its expected bit in at least --qubit-mark of
the shots. Set the mark BEFORE the run. A wrong rule leaves a qubit at about
half of its shots or less (experiments/plant_rule_faults.py); readout noise
costs a few percent. The share of shots with the whole string right is printed too, as
information: with ten qubits it is about the product of the ten shares.

Run it only after tests/run_fake_ibm_results.py passes. From the repository
root, with a local build (plugin/build_against_wheel.sh):

    python3 tests/run_ibm_hardware_gates.py --qubit-mark 0.90 --yes-spend-qpu-time

With the installed wheel, set CUDAQ_IBM_PLUGIN=installed first.

A free rehearsal of this script, against the fake IBM server instead of IBM
(needs fastapi, uvicorn and python-multipart; every qubit must give 100%):

    python3 tests/run_ibm_hardware_gates.py --qubit-mark 0.90 --fake

Credentials: IBM_QUANTUM_API_KEY and IBM_QUANTUM_CRN from the environment,
or from the git-ignored .env at the repository root. They are never printed.
With CUDAQ_LOG_LEVEL=info the plugin also logs which IBM qubits it used.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import gate_rule_kernel  # noqa: E402
import plugin_under_test  # noqa: E402
from run_ibm_hardware import load_env_file  # noqa: E402

SHOTS = 1000
FAKE_PORT = 62458


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backend", default="ibm_fez")
    parser.add_argument("--qubit-mark", type=float, required=True,
                        help="lowest accepted share of the expected bit, "
                             "for every qubit")
    parser.add_argument("--yes-spend-qpu-time", action="store_true",
                        help="confirms that a real job may be sent")
    parser.add_argument("--fake", action="store_true",
                        help="rehearsal against the fake IBM server: free, "
                             "never touches IBM")
    args = parser.parse_args()
    if args.fake == args.yes_spend_qpu_time:
        print("Refusing to run: add --yes-spend-qpu-time to send a real job, "
              "or --fake for a free rehearsal (not both).")
        return 2

    server = None
    if args.fake:
        # Test credentials replace any real ones: the real key must never be
        # sent to another server, not even to localhost.
        os.environ["IBM_QUANTUM_API_KEY"] = "test-key"
        os.environ["IBM_QUANTUM_CRN"] = "test-crn"
        from run_token_expiry import start_server, stop_server
        server = start_server(ttl=0, polls=0, port=FAKE_PORT)
        target = dict(backend="ibm_fake",
                      url=f"http://localhost:{FAKE_PORT}/api",
                      iam_url=f"http://localhost:{FAKE_PORT}/identity/token")
    else:
        load_env_file()
        for name in ("IBM_QUANTUM_API_KEY", "IBM_QUANTUM_CRN"):
            if not os.environ.get(name):
                print(f"Set {name} (environment or .env).")
                return 2
        target = dict(backend=args.backend)

    import cudaq

    try:
        plugin_under_test.register(cudaq)
        cudaq.set_target("ibm", **target)
        counts = dict(cudaq.sample(gate_rule_kernel.build(cudaq),
                                   shots_count=SHOTS).items())
    finally:
        if server:
            stop_server(*server)
    print(f"Gate rules on {target['backend']}, {SHOTS} shots, "
          f"expected {gate_rule_kernel.EXPECTED}")
    shares = gate_rule_kernel.share_per_qubit(counts)
    failed = 0
    for k, ((label, bit, _), share) in enumerate(
            zip(gate_rule_kernel.CASES, shares)):
        ok = share >= args.qubit_mark
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}: q{k} {label:25} expects {bit}: "
              f"{share:.1%} (mark {args.qubit_mark:.0%})")
    whole = counts.get(gate_rule_kernel.EXPECTED, 0) / SHOTS
    product = 1.0
    for share in shares:
        product *= share
    print(f"Whole string right: {whole:.1%} of the shots "
          f"(product of the ten shares: {product:.1%})")
    most = sorted(counts.items(), key=lambda item: -item[1])[:5]
    print("Most frequent:", ", ".join(f"{bits}:{n}" for bits, n in most))
    print(f"RESULT: {'all ten qubits pass' if not failed else f'{failed} of ten qubits fail'}.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
