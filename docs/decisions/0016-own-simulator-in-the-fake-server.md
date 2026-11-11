# 0016. The fake IBM server simulates circuits with our own small simulator

Date: 2026-11-10. Status: accepted.
Tags: **[V]** verified (source given), **[U]** unverified.

## Context

The fake IBM server ([decision 0008](0008-test-against-a-fake-ibm-server.md)) checked that
IBM would accept our circuits and answered with fixed samples. So CI could not tell a
right result from a wrong one: a gate rule with a wrong sign, or a wrong bit order, still
passed. The server receives the OpenQASM 3 we send to IBM: only `rz`, `sx`, `x`, `cz` and
`measure` on physical qubits. To answer with real samples it must simulate that.

## Options

- **A.** Our own statevector simulator in `tests/`, with numpy. It simulates only the
  qubits the circuit touches, so a 156-qubit chip is no problem. Independent of both
  CUDA-Q and Qiskit.
- **B.** Qiskit Aer. Heavier; whether Qiskit's OpenQASM 3 import accepts physical qubits
  (`$62`) is **[U]**.
- **C.** CUDA-Q's simulator. Then CUDA-Q checks CUDA-Q, and a shared mistake stays hidden.

## Decision (Bruno, 2026-11-10)

**A**, and Bruno writes the simulator himself: it is pure quantum mechanics (statevector,
gates as matrices, bit order, sampling).

## Consequences

- `tests/isa_simulator.py` (Bruno's functions, compared with Qiskit in the unit tests);
  the server answers with it. `tests/run_fake_ibm_results.py` compares each kernel through
  the plugin with the same kernel on CUDA-Q's simulator, in CI
  ([architecture.md](../architecture.md) §7).
- A backend name (`ibm_fixed_samples`) keeps the fixed samples for the bit-order case.
- Limit: the simulator has no noise, and test kernels must be chosen so that a wrong rule
  changes the outcome. Flipping the sign of every `rz` is invisible to any outcome test.
- Risk: the simulator and the plugin share a wrong idea about bit order. Guard: the
  reference is CUDA-Q's simulator on the original kernel, and hardware runs confirmed the
  order on a real chip.

## Revisit when

The tests need noise, or circuits beyond about 24 touched qubits.
