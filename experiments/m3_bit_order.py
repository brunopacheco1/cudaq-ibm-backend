# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""M3 experiment: do our counts come back in the bit order CUDA-Q promises?

CUDA-Q's contract: a sample lists the measured qubits sorted by allocation
order, whatever order the kernel measured them in. Ground truth here is
cudaq.sample on the local simulator. Each random kernel uses only x and cx,
so its answer is one known bitstring.

For each kernel this script compiles with the target pipeline, simulates the
compiled kernel (Qiskit), reads the classical bits the way IBM returns them
(c[i] = i-th measurement), and compares. The circuit is built from the
compiled IR, after the passes the runtime's OpenQASM 2 translation runs, and
not from `cudaq.translate`: that function runs extra passes, so its output
is not what the helper receives (docs/architecture.md, section 9.7).

- OLD: the pipeline before the fix, bits read as is. Wrong when the kernel
  measures qubits out of order. The router options do not matter: the same
  kernels fail with CUDA-Q's default identity start.
- NEW: plugin/targets/ibm.yml.in as it is now, bits selected as
  IBMServerHelper::processResults does (plugin/ResultBits.h): keep c[q] for
  each qubit q in output_names, ascending.

Devices: small path, star and ring graphs, and ibm_fez numbered
breadth-first from qubit 62 (as m3_routing.py builds it). Result with cudaq
0.16.0, 60 kernels each: OLD wrong in 6 (seed 1) and 5 (seed 2), every one
with shuffled mz calls or registers measured in reverse; NEW wrong in 0.

Needs: pip install cudaq==0.16.0 qiskit
Run from the repository root: python experiments/m3_bit_order.py [seed] [count]
"""

import importlib.util
import json
import random
import re
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import cudaq  # noqa: E402
from cudaq.mlir.ir import Module  # noqa: E402
from cudaq.mlir.passmanager import PassManager  # noqa: E402
from qiskit import QuantumCircuit  # noqa: E402
from qiskit.providers.basic_provider import BasicSimulator  # noqa: E402

from m3_routing import fez_device  # noqa: E402  (same folder)

ROOT = Path(__file__).resolve().parent.parent
# What the runtime runs before the target's own pipeline.
HIGH = ("canonicalize,hw-jit-prep-pipeline{allow-early-exit=false},"
        "expand-measurements,jit-deploy-pipeline")
NEW = re.search(r'jit-mid-level-pipeline: "([^"]*)"',
                (ROOT / "plugin/targets/ibm.yml.in").read_text()).group(1)
OLD = NEW.replace("combine-measurements),expand-measurements,"
                  "func.func(cc-loop-unroll,canonicalize,", "")
assert OLD != NEW, "ibm.yml.in no longer has the combine-measurements step"
# The passes of the runtime's OpenQASM 2 translation that can change gates
# (Pipelines.cpp, addPipelineTranslateToOpenQASM, tag 0.16.0).
CODEGEN = ("func.func(cse,normalize-phase-placement,lower-phase,canonicalize,"
           "expand-control-negations)")
GEN = Path(tempfile.mkdtemp())
FEZ = fez_device(62)


def make_kernel(name, sizes, body):
    src = ["import cudaq", "@cudaq.kernel", f"def {name}():"]
    src += [f"    q{r} = cudaq.qvector({s})" for r, s in enumerate(sizes)]
    src += ["    " + b for b in body]
    path = GEN / f"{name}.py"
    path.write_text("\n".join(src) + "\n")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, name)


def compile_bits(k, mid, device):
    """Classical bits in measurement order, and output_names qubit numbers."""
    mid = mid.replace("file(%QPU_ARCH%)", device)
    _, m0 = k.prepare_call()
    m = Module.parse(str(m0), m0.context)
    PassManager.parse(f"builtin.module({HIGH},{mid},{CODEGEN})",
                      m0.context).run(m.operation)
    text = str(m)
    found = re.search(r'output_names = "((?:[^"\\]|\\.)*)"', text)
    qnums = ([e[1][0] for e in json.loads(found.group(1).replace("\\22", '"'))[0]]
             if found else [])
    body = text[text.index("func.func @__nvqpp__mlirgen__" + k.name):]
    body = body[:body.index("\n  }")].splitlines()[1:]

    # One qubit per allocation, numbered in order: the labels the helper sees.
    qubit = {}
    for line in body:
        alloc = re.match(r"\s*(%\S+) = quake\.alloca !quake\.ref", line)
        if alloc:
            qubit[alloc.group(1)] = len(qubit)
    measures = sum("quake.mz" in line for line in body)
    qc = QuantumCircuit(len(qubit), measures)
    bit = 0
    for line in body:
        if "quake.alloca" in line or "quake.dealloc" in line:
            continue
        op = re.match(r"\s*(?:%\S+ = )?quake\.(\w+)(.*?) : ", line)
        if not op:
            assert "quake." not in line, line
            continue
        name = op.group(1)
        operands = [qubit[v] for v in re.findall(r"%[\w.]+", op.group(2))]
        if name == "x" and len(operands) == 1:
            qc.x(operands[0])
        elif name == "x" and len(operands) == 2:
            qc.cx(operands[0], operands[1])
        elif name == "mz" and len(operands) == 1:
            qc.measure(operands[0], bit)
            bit += 1
        else:
            raise RuntimeError(f"unexpected operation: {line.strip()}")
    key = next(iter(BasicSimulator().run(qc, shots=1).result().get_counts()))
    return key.replace(" ", "")[::-1], qnums  # Qiskit prints c[0] right-most


def main() -> None:
    random.seed(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    wrong = {"OLD": 0, "NEW": 0}
    old_modes = {}
    for t in range(count):
        sizes = [random.randint(2, 5)] + ([random.randint(1, 3)]
                                          if random.random() < 0.3 else [])
        qs = [f"q{r}[{i}]" for r, s in enumerate(sizes) for i in range(s)]
        n = len(qs)
        body = [f"x({q})" for q in qs if random.random() < 0.5]
        body += [f"x.ctrl({a}, {b})" for a, b in
                 (random.sample(qs, 2) for _ in range(random.randint(1, 3 * n)))]
        mode = random.choice(["all", "shuffled", "subset", "regs reversed"])
        if mode == "all":
            body += [f"mz(q{r})" for r in range(len(sizes))]
        elif mode == "regs reversed":
            body += [f"mz(q{r})" for r in reversed(range(len(sizes)))]
        else:
            sel = random.sample(qs, random.randint(1, n))
            if mode == "subset":
                sel = [q for q in qs if q in sel]
            body += [f"mz({q})" for q in sel]
        k = make_kernel(f"k{t}", sizes, body)
        truth = str(cudaq.sample(k, shots_count=1)).strip("{} \n").split(":")[0]
        device = random.choice([f"path({n + 2})", f"star({n + 1})",
                                f"ring({n + 1})", f"file('{FEZ}')"])

        bits, _ = compile_bits(k, OLD, device)
        if bits != truth:
            wrong["OLD"] += 1
            old_modes[mode] = old_modes.get(mode, 0) + 1
        bits, qnums = compile_bits(k, NEW, device)
        keep = sorted(set(qnums)) or list(range(len(bits)))
        got = ("".join(bits[q] for q in keep)
               if max(keep) < len(bits) else "out of range")
        if got != truth:
            wrong["NEW"] += 1
            print(f"  NEW wrong: {mode} sizes={sizes} truth={truth} got={got}")
    print(f"{count} kernels: OLD wrong {wrong['OLD']} {old_modes}, "
          f"NEW wrong {wrong['NEW']}")


if __name__ == "__main__":
    main()
