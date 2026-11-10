# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""M3 experiment: does CUDA-Q keep physical qubit ids after routing?

Runs a 5-qubit GHZ kernel through `qubit-mapping` on a 10-qubit star device
whose centre is qubit 9 (qubits 0-8 only touch 9), then prints
`mapping_v2p` and the OpenQASM 2 that the plugin would receive.

Needs only the pip wheel: `pip install cudaq==0.16.0`, then
`python experiments/m3_qubit_ids.py`. See docs/m3-spec.md §2.4.
"""

import re
import tempfile
import warnings

warnings.filterwarnings("ignore")

import cudaq  # noqa: E402
from cudaq.mlir._mlir_libs._quakeDialects import cudaq_runtime  # noqa: E402
from cudaq.mlir.ir import Module  # noqa: E402
from cudaq.mlir.passmanager import PassManager  # noqa: E402


@cudaq.kernel
def ghz5():
    q = cudaq.qvector(5)
    h(q[0])
    for i in range(4):
        x.ctrl(q[0], q[i + 1])
    mz(q)


def star_device() -> str:
    lines = ["Number of nodes: 10", "Number of edges: 9"]
    lines += [f"{i} --> {{9}}" for i in range(9)]
    lines.append("9 --> {" + ", ".join(str(i) for i in range(9)) + "}")
    f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
    f.write("\n".join(lines) + "\n")
    f.close()
    return f.name


def main() -> None:
    _, mod = ghz5.prepare_call()
    ctx = mod.context
    high = ("canonicalize,hw-jit-prep-pipeline{allow-early-exit=false},"
            "expand-measurements,jit-deploy-pipeline,"
            "func.func(erase-implicit-output)")
    mid = ("decomposition{basis=h,rx,ry,rz,x,z,x(1)},"
           "func.func(add-dealloc,combine-quantum-alloc,canonicalize,"
           "factor-quantum-alloc,dqe,cse,memtoreg),"
           "add-wireset,func.func(assign-wire-indices),"
           f"qubit-mapping{{device=file({star_device()}) "
           "raise-fatal-errors=true},"
           "func.func(delay-measurements),lower-to-cfg,func.func(regtomem),"
           "quake-to-cc-prep,func.func(memtoreg{quantum=0})")
    m = Module.parse(str(mod), ctx)
    PassManager.parse(f"builtin.module({high},{mid})", ctx).run(m.operation)
    text = str(m)
    for attr in ("mapping_v2p", "mapping_reorder_idx"):
        found = re.search(attr + r" = \[[^\]]*\]", text)
        print(found.group(0) if found else f"{attr}: not found")
    print(cudaq_runtime.translate_impl(ghz5.uniqName, m, "openqasm2"))


if __name__ == "__main__":
    main()
