# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""M3 experiment: after routing, is the QASM2 classical-bit order already the
user's qubit order, or must we apply mapping_reorder_idx like IQM and OQC?

Routes 40 random classical-reversible kernels (x and cx only, so the answer
is one known bitstring), simulates CUDA-Q's OpenQASM 2 with Qiskit, and
compares bit i of the classical register with the user's i-th measured qubit.
Result with cudaq 0.16.0, for both placement options: 40/40 match WITHOUT
reorderIdx; applying it breaks the routed ones. So IBMServerHelper::processResults must not apply it.

Needs: pip install cudaq==0.16.0 qiskit
Run:   python experiments/m3_bit_order.py
"""

import importlib.util
import random
import re
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import cudaq  # noqa: E402,F401
from cudaq.mlir._mlir_libs._quakeDialects import cudaq_runtime  # noqa: E402
from cudaq.mlir.ir import Module  # noqa: E402
from cudaq.mlir.passmanager import PassManager  # noqa: E402
from qiskit import QuantumCircuit  # noqa: E402
from qiskit.providers.basic_provider import BasicSimulator  # noqa: E402

HIGH = ("canonicalize,hw-jit-prep-pipeline{allow-early-exit=false},"
        "expand-measurements,jit-deploy-pipeline")
MID = ("func.func(erase-implicit-output),decomposition{{basis=h,rx,ry,rz,x,z,x(1)}},"
       "func.func(add-dealloc,combine-quantum-alloc,canonicalize,factor-quantum-alloc,"
       "dqe,cse,memtoreg),add-wireset,func.func(assign-wire-indices),"
       "qubit-mapping{{device={dev} {opts}}},func.func(delay-measurements),lower-to-cfg,"
       "func.func(regtomem),quake-to-cc-prep,func.func(memtoreg{{quantum=0}})")


def compile_routed(name, n, xs, pairs, measured, device, opts):
    body = [f"    x(q[{i}])" for i in xs]
    body += [f"    x.ctrl(q[{a}], q[{b}])" for a, b in pairs]
    body += [f"    mz(q[{i}])" for i in measured]
    src = (f"import cudaq\n@cudaq.kernel\ndef {name}():\n"
           f"    q = cudaq.qvector({n})\n" + "\n".join(body) + "\n")
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    k = getattr(mod, name)
    _, m0 = k.prepare_call()
    m = Module.parse(str(m0), m0.context)
    PassManager.parse(f"builtin.module({HIGH},{MID.format(dev=device, opts=opts)})",
                      m0.context).run(m.operation)
    text = str(m)
    found = re.search(r"mapping_reorder_idx = \[([^\]]*)\]", text)
    reorder = [int(v) for v in re.findall(r"\d+", found.group(1))] if found else None
    return cudaq_runtime.translate_impl(k.uniqName, m, "openqasm2"), reorder


def check(opts: str) -> None:
    random.seed(3)
    plain = with_reorder = 0
    trials = 40
    for t in range(trials):
        n = random.randint(3, 8)
        xs = [i for i in range(n) if random.random() < 0.5]
        pairs = [tuple(random.sample(range(n), 2))
                 for _ in range(random.randint(1, 3 * n))]
        measured = (list(range(n)) if t % 2 == 0
                    else sorted(random.sample(range(n), random.randint(1, n))))
        bits = [1 if i in xs else 0 for i in range(n)]
        for a, b in pairs:
            bits[b] ^= bits[a]
        expect = "".join(str(bits[i]) for i in measured)
        device = random.choice([f"path({n + 2})", f"star({n + 1})", f"ring({n + 1})"])
        qasm, reorder = compile_routed(f"k{t}_{len(opts)}", n, xs, pairs, measured, device, opts)
        key = next(iter(BasicSimulator().run(QuantumCircuit.from_qasm_str(qasm),
                                             shots=1).result().get_counts()))
        corder = key.replace(" ", "")[::-1]  # Qiskit prints c[0] right-most
        plain += corder == expect
        if reorder:
            with_reorder += "".join(corder[i] for i in reorder) == expect
        else:
            with_reorder += corder == expect
    print(f"[{opts}]")
    print(f"  classical-bit order = user order:   {plain}/{trials}")
    print(f"  after applying mapping_reorder_idx: {with_reorder}/{trials}")


def main() -> None:
    for opts in ("placement=identity search=none", "placement=auto search=sabre"):
        check(opts)


if __name__ == "__main__":
    main()
