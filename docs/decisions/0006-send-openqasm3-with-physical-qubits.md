# 0006. Send OpenQASM 3 with physical qubits `$k`

Date: 2026-11-06. Status: accepted.
Tags: **[V]** verified (source given), **[U]** unverified.

## Context

CUDA-Q can emit OpenQASM 2 (`codegen-emission: qasm2`, as Braket and Infleqtion do) **[V]**
their target YAML. Its output is `OPENQASM 2.0; include "qelib1.inc"` with a virtual
`qreg var0[n]` and one 1-bit `creg` per measurement.

IBM's Sampler REST docs show OpenQASM 3 with `include "stdgates.inc"` **[V]**
https://quantum.cloud.ibm.com/docs/guides/sampler-rest-api. Whether IBM also parses QASM2 is
**[U]**. Qiskit's ISA check accepts both `$k` physical qubits and a `qubit[156] q;` declaration
**[V]** `is_isa_circuit` experiment, qiskit-ibm-runtime 0.51.0.

## Options

- **A.** Send CUDA-Q's QASM2 as is.
- **B.** Rewrite to OpenQASM 3 with physical qubits `$k` and one `bit[n] c` register.
- **C.** Rewrite to OpenQASM 3 with a full-size `qubit[156] q;` register.

## Decision

B. We rewrite the gates anyway ([0001](0001-cudaq-routes-helper-rewrites-gates.md)), and B is
the exact form the Python prototype ran on `ibm_fez` on 2026-11-05 **[V]**.

## Consequences

- One result register `c`: the 1-bit `creg`s are merged in program order, so IBM returns
  `results[0].data.c.samples` and decoding stays simple.
- The circuit text names physical qubits, so routing (M3) must produce the final ids.

## Revisit when

IBM changes the accepted input formats, or we need several result registers.
