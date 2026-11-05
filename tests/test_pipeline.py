import cudaq

from cudaq_ibm import kernel_to_circuit, simulate_locally, target_from_configuration, to_isa

from .conftest import bell, rotation, x_on_first


def test_kernel_with_arguments_is_synthesized():
    circuit = kernel_to_circuit(rotation, 0.5)
    assert circuit.count_ops()["ry"] == 1
    assert circuit.num_clbits == 1  # implicit measurement added


def test_isa_uses_only_native_gates(fez_configuration):
    target = target_from_configuration(fez_configuration)
    isa = to_isa(kernel_to_circuit(bell), target)
    native = set(fez_configuration["basis_gates"]) | {"measure", "barrier"}
    assert set(isa.count_ops()) <= native
    assert "h" not in isa.count_ops()


def test_local_run_matches_cudaq_bit_order():
    expected = cudaq.sample(x_on_first).most_probable()
    result = simulate_locally(x_on_first, shots=500)
    assert expected == "100"
    assert result.most_probable() == expected


def test_local_bell_is_mostly_correlated():
    counts = simulate_locally(bell, shots=1000).counts
    correlated = counts.get("00", 0) + counts.get("11", 0)
    assert correlated > 900  # noise allows a few 01/10
