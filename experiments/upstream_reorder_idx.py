# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""Upstream check: is `mapping_reorder_idx` right with every router option?

Models a backend that returns one bit per measured qubit sorted by qubit (as
IQM's and OQC's helpers expect), applies `mapping_reorder_idx`, and compares
with cudaq.sample on the local simulator. 60 random x/cx kernels, 3-7
qubits, path, star and ring devices.

Result with cudaq 0.16.0:

    placement=identity search=none (default): wrong 0/60
    placement=auto search=sabre:              wrong 32/60

This is a MODEL of a backend, not a run on one. No target shipped with
CUDA-Q uses placement=auto, and in emulation oqc and anyon return the right
order for out-of-order mz (0 of 25 wrong). So it matters only for a target
that turns on placement=auto and uses reorderIdx.

Needs: pip install cudaq==0.16.0 qiskit
Run from the repository root: python experiments/upstream_reorder_idx.py
"""
import random
import re
import m3_bit_order as b, cudaq
from cudaq.mlir.ir import Module
from cudaq.mlir.passmanager import PassManager
from cudaq.mlir._mlir_libs._quakeDialects import cudaq_runtime
from qiskit import QuantumCircuit
from qiskit.providers.basic_provider import BasicSimulator
IQM = ("func.func(erase-implicit-output),decomposition{basis=h,rx,ry,rz,x,z,x(1)},func.func(add-dealloc,combine-quantum-alloc,canonicalize,factor-quantum-alloc,dqe,cse,memtoreg),"
       "add-wireset,func.func(assign-wire-indices),qubit-mapping{device=DEV OPTS},func.func(delay-measurements),lower-to-cfg,func.func(regtomem),quake-to-cc-prep,func.func(memtoreg{quantum=0})")
for opts in ["placement=identity search=none", "placement=auto search=sabre"]:
    random.seed(5); bad = tot = 0; modes = {}
    for t in range(60):
        n = random.randint(3, 7)
        qs = [f"q0[{i}]" for i in range(n)]
        body = [f"x({q})" for q in qs if random.random() < 0.5]
        body += [f"x.ctrl({a}, {c})" for a, c in (random.sample(qs, 2) for _ in range(random.randint(1, 3 * n)))]
        mode = random.choice(["all", "shuffled"])
        sel = qs if mode == "all" else random.sample(qs, n)
        body += [f"mz({q})" for q in sel] if mode == "shuffled" else ["mz(q0)"]
        k = b.make_kernel(f"r{len(opts)}_{t}", [n], body)
        truth = str(cudaq.sample(k, shots_count=1)).strip("{} \n").split(":")[0]
        dev = random.choice([f"path({n+2})", f"star({n+1})", f"ring({n+1})"])
        _, m0 = k.prepare_call(); m = Module.parse(str(m0), m0.context)
        PassManager.parse(f"builtin.module({b.HIGH},{IQM.replace('DEV', dev).replace('OPTS', opts)})", m0.context).run(m.operation)
        ro = re.search(r"mapping_reorder_idx = \[([^\]]*)\]", str(m))
        ro = [int(v) for v in re.findall(r"\d+", ro.group(1))] if ro else None
        qasm = cudaq_runtime.translate_impl(k.uniqName, m, "openqasm2")
        labels = [int(x) for x in re.findall(r"^measure \w+\[(\d+)\]", qasm, re.M)]
        key = next(iter(BasicSimulator().run(QuantumCircuit.from_qasm_str(qasm), shots=1).result().get_counts()))
        stmt = key.replace(" ", "")[::-1]
        byphys = "".join(stmt[i] for i in sorted(range(len(labels)), key=lambda i: labels[i]))
        got = "".join(byphys[i] for i in ro) if ro else byphys
        tot += 1
        if got != truth:
            bad += 1; modes[mode] = modes.get(mode, 0) + 1
    print(f"{opts}: IQM-style (sort by physical, then reorderIdx) wrong {bad}/{tot} {modes}")
