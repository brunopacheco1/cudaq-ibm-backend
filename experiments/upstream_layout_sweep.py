# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""Upstream check: how often does routing leave a kernel on device qubits
that are not 0..m-1? (Then `regtomem` renames them; see
upstream_layout_lost.py.)

For each device graph: 150 random kernels (3-12 qubits, 1-4 cx, mz on all),
run through that target's own pipeline up to `qubit-mapping` with default
options, then read the device qubits the kernel borrowed.

Result with cudaq 0.16.0 (seed 1):

    anyon berkeley-25q : 47/150 kernels not on 0..m-1
    oqc toshiko        : 12/150
    anyon telegraph-8q :  0/150
    iqm Crystal_20     :  0/150   (graph of CUDA-Q's IQM mock server)

So it depends on how the device is numbered. On ibm_fez, numbered
breadth-first, it was 20 of 30 circuits.

Needs: pip install cudaq==0.16.0
Run:   python experiments/upstream_layout_sweep.py
"""

import importlib.util
import os
import random
import re
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import cudaq  # noqa: E402
from cudaq.mlir.ir import Module  # noqa: E402
from cudaq.mlir.passmanager import PassManager  # noqa: E402

MAPPING = Path(os.path.dirname(cudaq.__file__)).parent / "targets" / "mapping"
HIGH = ("canonicalize,hw-jit-prep-pipeline{allow-early-exit=false},"
        "expand-measurements,jit-deploy-pipeline")
# The shipped YAML pipelines up to qubit-mapping; GATES is the target's own
# gate-set pass.
ROUTING = ("func.func(erase-implicit-output),GATES,func.func(add-dealloc,"
           "combine-quantum-alloc,canonicalize,factor-quantum-alloc,dqe,cse,"
           "memtoreg),add-wireset,func.func(assign-wire-indices),"
           "qubit-mapping{device=file(DEVICE)}")
# python/tests/utils/mock_qpu/iqm/__init__.py, Crystal_20 (QBn -> n-1).
CRYSTAL_20 = [(1, 2), (1, 4), (2, 5), (3, 4), (3, 8), (4, 5), (4, 9), (5, 6),
              (5, 10), (6, 7), (6, 11), (7, 12), (8, 9), (8, 13), (9, 10),
              (9, 14), (10, 11), (10, 15), (11, 12), (11, 16), (12, 17),
              (13, 14), (14, 15), (14, 18), (15, 16), (15, 19), (16, 17),
              (16, 20), (18, 19), (19, 20)]
GEN = Path(tempfile.mkdtemp())


def crystal_file() -> str:
    adj = {i: set() for i in range(20)}
    for a, b in CRYSTAL_20:
        adj[a - 1].add(b - 1)
        adj[b - 1].add(a - 1)
    lines = ["Number of nodes: 20", "Number of edges: 30"]
    lines += [f"{i} --> {{{', '.join(map(str, sorted(adj[i])))}}}"
              for i in range(20)]
    path = GEN / "crystal20.txt"
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def make_kernel(name: str, n: int, body: list[str]):
    src = ["import cudaq", "@cudaq.kernel", f"def {name}():",
           f"    q = cudaq.qvector({n})"] + ["    " + b for b in body]
    path = GEN / f"{name}.py"
    path.write_text("\n".join(src + ["    mz(q)"]) + "\n")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, name)


def sweep(label: str, device: str, gates: str, count: int = 150) -> None:
    nodes = int(re.search(r"Number of nodes:\s*(\d+)",
                          Path(device).read_text()).group(1))
    routing = ROUTING.replace("GATES", gates).replace("DEVICE", device)
    random.seed(1)
    off = 0
    example = None
    for t in range(count):
        n = random.randint(3, min(12, nodes - 1))
        body = [f"x.ctrl(q[{a}], q[{b}])" for a, b in
                (random.sample(range(n), 2)
                 for _ in range(random.randint(1, 4)))]
        k = make_kernel(re.sub(r"\W", "_", f"{label}_{t}"), n, body)
        _, mod = k.prepare_call()
        m = Module.parse(str(mod), mod.context)
        PassManager.parse(f"builtin.module({HIGH},{routing})",
                          mod.context).run(m.operation)
        used = sorted({int(i) for i in
                       re.findall(r"borrow_wire @\w+\[(\d+)\]", str(m))})
        if used != list(range(len(used))):
            off += 1
            example = example or (n, body, used)
    print(f"{label:19s}: {off:2d}/{count} kernels not on 0..m-1")
    if example:
        print(f"    e.g. {example[0]} qubits, {example[1]} -> {example[2]}")


def main() -> None:
    sweep("anyon berkeley-25q", str(MAPPING / "anyon" / "berkeley-25q.txt"),
          "anyon-pgate-set-mapping")
    sweep("oqc toshiko", str(MAPPING / "oqc" / "toshiko.txt"),
          "oqc-gate-set-mapping")
    sweep("anyon telegraph-8q", str(MAPPING / "anyon" / "telegraph-8q.txt"),
          "anyon-cgate-set-mapping")
    sweep("iqm Crystal_20", crystal_file(), "iqm-gate-set-mapping")


if __name__ == "__main__":
    main()
