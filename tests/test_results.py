import pytest

from cudaq_ibm.results import hex_to_bits, samples_to_counts


def test_hex_to_bits_uses_cudaq_order():
    # IBM: 0x1 means bit 0 is set. CUDA-Q writes qubit 0 first.
    assert hex_to_bits("0x1", 3) == "100"
    assert hex_to_bits("0x4", 3) == "001"
    assert hex_to_bits("0x0", 2) == "00"


def test_counts_join_registers_in_circuit_order():
    data = {"a": {"samples": ["0x1", "0x1"]}, "b": {"samples": ["0x0", "0x1"]}}
    assert samples_to_counts(data, [("a", 2), ("b", 1)]) == {"100": 1, "101": 1}


def test_mismatched_shot_counts_rejected():
    data = {"a": {"samples": ["0x1"]}, "b": {"samples": []}}
    with pytest.raises(ValueError):
        samples_to_counts(data, [("a", 1), ("b", 1)])
