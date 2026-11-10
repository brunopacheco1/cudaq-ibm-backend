# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""Upstream reproduction: a routed kernel loses its device qubit ids.

Uses a target that ships with CUDA-Q, so nothing here is ours: Anyon's
mid-level pipeline (anyon.yml) and its device file (berkeley-25q.txt, in the
pip wheel). A 3-qubit kernel is routed onto device qubits {0, 1, 2, 6}.
`regtomem` then turns the four borrowed wires into four plain allocations,
and the QIR names the qubits 0..3: device qubit 6 has become qubit 3, and
the cz that should run on the coupled pair (6, 0) is sent as (3, 0), which
is not coupled on that device.

Result with cudaq 0.16.0:

    mapping_v2p = [0, 1, 6]
    device qubits after qubit-mapping: [0, 1, 2, 6]
    after regtomem: 0 borrow_wire, 4 alloca
    qubit ids in the QIR: [0, 1, 2, 3]
      swap on qubits [2, 3]
      cz on qubits [3, 0]

Needs: pip install cudaq==0.16.0
Run:   python experiments/upstream_layout_lost.py
"""

import os
import re
import warnings

warnings.filterwarnings("ignore")

import cudaq  # noqa: E402
from cudaq.mlir._mlir_libs._quakeDialects import cudaq_runtime  # noqa: E402
from cudaq.mlir.ir import Module  # noqa: E402
from cudaq.mlir.passmanager import PassManager  # noqa: E402


@cudaq.kernel
def kernel():
    q = cudaq.qvector(3)
    x(q[2])
    x.ctrl(q[2], q[0])
    mz(q)


DEVICE = os.path.join(os.path.dirname(cudaq.__file__), "..", "targets",
                      "mapping", "anyon", "berkeley-25q.txt")
# What the runtime runs before a target's own pipeline.
HIGH = ("canonicalize,hw-jit-prep-pipeline{allow-early-exit=false},"
        "expand-measurements,jit-deploy-pipeline")
# anyon.yml's jit-mid-level-pipeline up to qubit-mapping, placeholders filled.
ROUTING = ("func.func(erase-implicit-output),anyon-pgate-set-mapping,"
           "func.func(add-dealloc,combine-quantum-alloc,canonicalize,"
           "factor-quantum-alloc,dqe,cse,memtoreg),add-wireset,"
           "func.func(assign-wire-indices),"
           f"qubit-mapping{{device=file({DEVICE})}}")
QUBIT = r"(?:%Qubit\*|ptr) (?:inttoptr \(i64 (\d+) to (?:%Qubit\*|ptr)\)|null)"


def main() -> None:
    _, mod = kernel.prepare_call()
    m = Module.parse(str(mod), mod.context)
    PassManager.parse(f"builtin.module({HIGH},{ROUTING})",
                      mod.context).run(m.operation)
    text = str(m)
    print(re.search(r"mapping_v2p = \[[^\]]*\]", text).group(0))
    wires = {int(i) for i in re.findall(r"borrow_wire @\w+\[(\d+)\]", text)}
    print("device qubits after qubit-mapping:", sorted(wires))

    # The rest of anyon.yml's pipeline.
    PassManager.parse("builtin.module(func.func(regtomem))",
                      mod.context).run(m.operation)
    text = str(m)
    print(f"after regtomem: {text.count('quake.borrow_wire')} borrow_wire, "
          f"{text.count('quake.alloca')} alloca")

    qir = cudaq_runtime.translate_impl(kernel.uniqName, m, "qir-adaptive")
    gates = []
    for line in qir.splitlines():
        call = re.search(r"call void @__quantum__qis__(\w+?)__", line)
        if call:
            ids = [int(i or 0) for i in re.findall(QUBIT, line)]
            gates.append((call.group(1), ids))
    print("qubit ids in the QIR:", sorted({i for _, ids in gates for i in ids}))
    for name, ids in gates:
        if len(ids) == 2 and name != "mz":
            print(f"  {name} on qubits {ids}")


if __name__ == "__main__":
    main()
