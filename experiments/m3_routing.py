# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""M3 experiment: route kernels on ibm_fez with the plugin's real pipeline.

Numbers the ibm_fez wiring (tests/data/ibm_fez_coupling.txt) breadth-first
from a root qubit, as plugin/Layout.h does, writes the device file, and runs
the jit-mid-level-pipeline from plugin/targets/ibm.yml.in on GHZ and random
kernels. For each combination of router options it prints:

- qreg: how many labels CUDA-Q emits. More than n means routing borrowed a
  qubit outside 0..n-1 (so labels are not device qubits; m3-spec §2.4).
- 2q: number of 2-qubit gates after routing (swaps are 3 cx each).

Needs only the pip wheel: `pip install cudaq==0.16.0`, then, from the
repository root, `python experiments/m3_routing.py [root]`.
"""

import importlib.util
import re
import sys
import tempfile
import warnings
from collections import defaultdict
from pathlib import Path

warnings.filterwarnings("ignore")

import cudaq  # noqa: E402,F401
from cudaq.mlir._mlir_libs._quakeDialects import cudaq_runtime  # noqa: E402
from cudaq.mlir.ir import Module  # noqa: E402
from cudaq.mlir.passmanager import PassManager  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OPTIONS = ["placement=identity search=none",   # CUDA-Q's default
           "placement=identity search=sabre",
           "placement=auto search=none",
           "placement=auto search=sabre"]      # what ibm.yml.in uses


def fez_device(root: int) -> str:
    adj = defaultdict(set)
    for line in (ROOT / "tests/data/ibm_fez_coupling.txt").read_text().splitlines():
        if line and line[0].isdigit():
            a, b = map(int, line.split())
            adj[a].add(b)
            adj[b].add(a)
    order, label = [root], {root: 0}
    for u in order:  # breadth-first, neighbours in ascending id
        for v in sorted(adj[u]):
            if v not in label:
                label[v] = len(order)
                order.append(v)
    lines = [f"Number of nodes: {len(order)}",
             f"Number of edges: {sum(map(len, adj.values())) // 2}"]
    for k, q in enumerate(order):
        lines.append(f"{k} --> {{{', '.join(str(n) for n in sorted(label[v] for v in adj[q]))}}}")
    f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
    f.write("\n".join(lines) + "\n")
    f.close()
    return f.name


def kernel(name: str, n: int, body: list[str]):
    # @cudaq.kernel needs real source, so write each kernel to a file.
    src = ["import cudaq", "@cudaq.kernel", f"def {name}():",
           f"    q = cudaq.qvector({n})"] + ["    " + b for b in body] + ["    mz(q)"]
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text("\n".join(src) + "\n")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, name)


def route(k, device: str, options: str) -> str:
    yml = (ROOT / "plugin/targets/ibm.yml.in").read_text()
    mid = re.search(r'jit-mid-level-pipeline: "([^"]*)"', yml).group(1)
    mid = re.sub(r"qubit-mapping\{[^}]*\}",
                 f"qubit-mapping{{device=file('{device}') {options}}}", mid)
    # What the runtime runs before the target's own pipeline.
    high = ("canonicalize,hw-jit-prep-pipeline{allow-early-exit=false},"
            "expand-measurements,jit-deploy-pipeline")
    _, mod = k.prepare_call()
    m = Module.parse(str(mod), mod.context)
    PassManager.parse(f"builtin.module({high},{mid})", mod.context).run(m.operation)
    return cudaq_runtime.translate_impl(k.uniqName, m, "openqasm2")


def main() -> None:
    root = int(sys.argv[1]) if len(sys.argv) > 1 else 62
    device = fez_device(root)
    cases = {
        "ghz5": (5, ["h(q[0])"] + [f"x.ctrl(q[{i}], q[{i + 1}])" for i in range(4)]),
        "ghz20": (20, ["h(q[0])"] + [f"x.ctrl(q[{i}], q[{i + 1}])" for i in range(19)]),
        "ring12": (12, [f"x.ctrl(q[{i}], q[{(i + 1) % 12}])" for i in range(12)]),
        "star6": (6, ["h(q[0])"] + [f"x.ctrl(q[0], q[{i}])" for i in range(1, 6)]),
    }
    for name, (n, body) in cases.items():
        for options in OPTIONS:
            qasm = route(kernel(name, n, body), device, options)
            qreg = int(re.search(r"qreg \w+\[(\d+)\]", qasm).group(1))
            twoq = len(re.findall(r"^cx ", qasm, re.M))
            print(f"{name:7s} n={n:2d}  {options:32s} qreg={qreg:2d}"
                  f"{' (borrowed)' if qreg > n else '           '}  2q={twoq}")


if __name__ == "__main__":
    main()
