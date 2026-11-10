# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""The compiler pipeline in plugin/targets/ibm.yml.in must leave only what
the C++ helper can read.

These tests run the pipeline with pip CUDA-Q and look at the compiled kernel
(the IR), not at `cudaq.translate`: that function runs extra passes, so its
OpenQASM is not what the plugin receives (docs/m3-spec.md, section 2.14).
The first run of the built plugin failed twice on such differences: one qreg
per qubit, and `swap` gates left by the router.
"""

import re
import sys
from pathlib import Path

import cudaq
from cudaq.mlir.ir import Module
from cudaq.mlir.passmanager import PassManager

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiments"))
from m3_routing import fez_device  # noqa: E402

# What the runtime runs before the target's own pipeline.
HIGH = ("canonicalize,hw-jit-prep-pipeline{allow-early-exit=false},"
        "expand-measurements,jit-deploy-pipeline")
MID = re.search(r'jit-mid-level-pipeline: "([^"]*)"',
                (ROOT / "plugin/targets/ibm.yml.in").read_text()).group(1)
# What the runtime's OpenQASM 2 translation runs before it prints the code
# (Pipelines.cpp, addPipelineTranslateToOpenQASM, tag 0.16.0): the passes
# that can change gates. A global phase (`quake.phase`) is dropped here.
CODEGEN = ("func.func(cse,normalize-phase-placement,lower-phase,canonicalize,"
           "expand-control-negations)")
# Gates plugin/Qasm2ToIsa.h has a rule for (a controlled x is `cx`), plus
# the operations that are not gates.
KNOWN = {"h", "x", "y", "z", "rx", "ry", "rz", "u3", "mz", "alloca", "dealloc"}


@cudaq.kernel
def ghz20():
    q = cudaq.qvector(20)
    h(q[0])
    for i in range(19):
        x.ctrl(q[i], q[i + 1])
    mz(q)


@cudaq.kernel
def many_gates():
    q = cudaq.qvector(4)
    rx(0.3, q[0])
    ry(0.4, q[1])
    y(q[2])
    s(q[3])
    t(q[0])
    z(q[1])
    x.ctrl(q[0], q[3])
    z.ctrl(q[1], q[2])
    swap(q[0], q[2])
    mz(q[3])
    mz(q[0])


def compiled_ops(kernel, device: str) -> list[tuple[str, int]]:
    """(operation, number of qubit operands) for each line of the kernel."""
    _, module = kernel.prepare_call()
    m = Module.parse(str(module), module.context)
    mid = MID.replace("file(%QPU_ARCH%)", device)
    PassManager.parse(f"builtin.module({HIGH},{mid},{CODEGEN})",
                      module.context).run(m.operation)
    text = str(m)
    body = text[text.index("func.func @__nvqpp__mlirgen__" + kernel.name):]
    body = body[:body.index("\n  }")]
    ops = []
    for line in body.splitlines()[1:]:
        found = re.match(r"\s*(?:%\S+ = )?quake\.(\w+)(.*?)(?: : |$)", line)
        assert found or "quake." not in line.split(" : ")[0], line
        if found:
            # Operands in (...) are angles; the others are qubits.
            qubits = re.sub(r"\([^)]*\)", "", found.group(2))
            ops.append((found.group(1), len(re.findall(r"%", qubits))))
    return ops


def check(kernel, device: str) -> list[tuple[str, int]]:
    ops = compiled_ops(kernel, device)
    assert ops, "no operations found; the test no longer reads the IR"
    unknown = sorted({name for name, _ in ops} - KNOWN)
    assert not unknown, f"the helper has no rule for {unknown}"
    wide = [(n, k) for n, k in ops if k > 2]
    assert not wide, f"gates on more than 2 qubits: {wide}"
    assert all(n == "x" for n, k in ops if k == 2), "only cx may have 2 qubits"
    return ops


def test_routed_ghz20_on_fez_has_no_swap_left():
    ops = check(ghz20, f"file('{fez_device(62)}')")
    # 19 cx of the kernel plus 3 cx for each swap the router added.
    assert sum(1 for n, k in ops if n == "x" and k == 2) >= 19


def test_every_gate_kind_ends_in_the_known_set():
    for device in ("path(6)", "star(6)", f"file('{fez_device(62)}')"):
        check(many_gates, device)
