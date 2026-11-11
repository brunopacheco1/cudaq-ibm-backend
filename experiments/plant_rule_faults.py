# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""Proof that the gate-rule kernel fails when a rewrite rule is wrong.

A check that has never failed proves nothing. This script makes one rule of
plugin/Qasm2ToIsa.h wrong at a time, rebuilds the plugin against the pip
wheel and runs tests/run_ibm_hardware_gates.py --fake (the simulating fake
server, never IBM). For each fault it prints the qubits that fall under the
mark. At the end it restores the file and rebuilds.

From the repository root, in an environment with cudaq and the fake
server's packages (docs/development.md, section 6). About 5 minutes:

    python3 experiments/plant_rule_faults.py

Run 2026-11-11 (cudaq 0.16.0): the control passes; each of the 11 faults
leaves at least one qubit at 54% or less (1000 shots). The weakest cases are
"half angle" and "z becomes s": the qubit becomes a coin flip, about 50%.

It edits a tracked file while it runs: do not run it with uncommitted
changes in plugin/Qasm2ToIsa.h, and check `git status` afterwards.
"""

import os
import re
import subprocess
import sys

SOURCE = "plugin/Qasm2ToIsa.h"
MARK = 0.90


def main() -> int:
    original = open(SOURCE).read()

    def in_rule(rule: str, old: str, new: str) -> str:
        start = original.index(f"inline void {rule}(")
        first_line_end = original.index("\n", start)
        one_line = "{ o." in original[start:first_line_end]
        end = first_line_end if one_line else original.index("\n}", start) + 1
        body = original[start:end]
        assert old in body, (rule, old)
        return original[:start] + body.replace(old, new, 1) + original[end:]

    faults = {
        "none (control)": original,
        "rx: angle sign flipped": in_rule(
            "ruleRX", "o.rz(t + PI, a);", "o.rz(-t + PI, a);"),
        "rx: +pi forgotten": in_rule(
            "ruleRX", "o.rz(t + PI, a);", "o.rz(t, a);"),
        "rx: first rz sign flipped": in_rule(
            "ruleRX", "o.rz(PI / 2, a);", "o.rz(-PI / 2, a);"),
        "rx: half angle": in_rule(
            "ruleRX", "o.rz(t + PI, a);", "o.rz(t / 2 + PI, a);"),
        "ry: angle sign flipped": in_rule(
            "ruleRY", "o.rz(t + PI, a);", "o.rz(-t + PI, a);"),
        "ry: last rz(pi) dropped": in_rule(
            "ruleRY", "  o.rz(PI, a);\n", ""),
        "ry: half angle": in_rule(
            "ruleRY", "o.rz(t + PI, a);", "o.rz(t / 2 + PI, a);"),
        "z: becomes s": in_rule("ruleZ", "o.rz(PI, a);", "o.rz(PI / 2, a);"),
        "z: becomes nothing": in_rule("ruleZ", "o.rz(PI, a);", "o.rz(0, a);"),
        "y: becomes x": in_rule("ruleY", "  o.rz(PI, a);\n", ""),
        "y: becomes z": in_rule("ruleY", "  o.x(a);\n", ""),
    }
    env = dict(os.environ, PYTHON=sys.executable)
    env.pop("CUDAQ_IBM_PLUGIN", None)      # the local build, not a wheel

    def build() -> bool:
        done = subprocess.run(["plugin/build_against_wheel.sh"], env=env,
                              capture_output=True, text=True)
        if done.returncode:
            print("BUILD FAILED:", done.stderr[-300:])
        return done.returncode == 0

    wrong = 0
    try:
        for name, text in faults.items():
            control = name.startswith("none")
            assert control or text != original, name
            open(SOURCE, "w").write(text)
            if not build():
                wrong += 1
                continue
            run = subprocess.run(
                [sys.executable, "-W", "ignore",
                 "tests/run_ibm_hardware_gates.py", "--fake",
                 "--qubit-mark", str(MARK)],
                env=env, capture_output=True, text=True)
            failing = re.findall(r"FAIL: (q\d) .*?: ([0-9.]+)%", run.stdout)
            caught = run.returncode == 1 and bool(failing)
            as_expected = (run.returncode == 0) if control else caught
            wrong += not as_expected
            print(f"{'ok ' if as_expected else 'BAD'} {name:26} "
                  + ("passes" if run.returncode == 0 else
                     "fails: " + ", ".join(f"{q} {s}%" for q, s in failing)),
                  flush=True)
    finally:
        open(SOURCE, "w").write(original)
        build()
    print(f"RESULT: {'every fault is caught' if not wrong else f'{wrong} lines are not as expected'}.")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
