# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""Tests for examples/expectation_from_samples.py, in the order its functions
are written.

    pytest tests/test_expectation_example.py -k step1     # parity
    pytest tests/test_expectation_example.py -k step2     # expectation
    pytest tests/test_expectation_example.py -k step3     # standard_error
    pytest tests/test_expectation_example.py -k step4     # measure_in
    pytest tests/test_expectation_example.py              # everything

Step 4 runs on CUDA-Q's simulator and compares with `cudaq.observe`, which
works there. Nothing here touches IBM.
"""

import importlib.util
import math
from pathlib import Path

import cudaq
import pytest
from cudaq import spin

_path = Path(__file__).parent.parent / "examples" / "expectation_from_samples.py"
_spec = importlib.util.spec_from_file_location("expectation_from_samples", _path)
example = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(example)

SHOTS = 20000
# Shot noise at 20000 shots is at most 0.007 (one standard deviation).
CLOSE = 0.04


# ---- step 1: parity -------------------------------------------------------


def test_step1_one_qubit():
    assert example.parity("0") == 1
    assert example.parity("1") == -1


def test_step1_only_the_number_of_ones_matters():
    assert example.parity("00") == 1 and example.parity("11") == 1
    assert example.parity("01") == -1 and example.parity("10") == -1
    assert example.parity("0110") == 1
    assert example.parity("1110") == -1


# ---- step 2: expectation --------------------------------------------------


def test_step2_all_shots_agree():
    assert example.expectation({"00": 100}) == 1
    assert example.expectation({"01": 100}) == -1
    assert example.expectation({"00": 60, "11": 40}) == 1


def test_step2_a_mix_is_the_average():
    # 80 shots give +1 and 20 give -1: (80 - 20) / 100.
    assert math.isclose(example.expectation({"00": 50, "11": 30, "01": 20}), 0.6)
    assert math.isclose(example.expectation({"0": 500, "1": 500}), 0.0)


def test_step2_the_first_hardware_run_of_this_project():
    # The Bell pair on ibm_fez, 2026-11-09 (docs/roadmap.md).
    counts = {"00": 495, "11": 449, "01": 39, "10": 17}
    assert math.isclose(example.expectation(counts), (944 - 56) / 1000)


# ---- step 3: standard_error -----------------------------------------------


def test_step3_no_spread_when_every_shot_agrees():
    assert example.standard_error({"00": 1000}) == 0


def test_step3_largest_when_the_average_is_zero():
    # E = 0, N = 10000: sqrt(1 / 10000).
    assert math.isclose(example.standard_error({"0": 5000, "1": 5000}), 0.01)


def test_step3_more_shots_less_error():
    few = example.standard_error({"00": 80, "01": 20})
    many = example.standard_error({"00": 8000, "01": 2000})
    assert math.isclose(few, math.sqrt((1 - 0.6 ** 2) / 100))
    assert math.isclose(many, few / 10)


# ---- step 4: measure_in ---------------------------------------------------

LETTER = {"x": spin.x, "y": spin.y, "z": spin.z}


def prepared(state: str):
    """A 2-qubit kernel in one of four states, not measured yet."""
    kernel = cudaq.make_kernel()
    q = kernel.qalloc(2)
    if state in ("bell", "bell minus"):
        kernel.h(q[0])
        kernel.cx(q[0], q[1])
        if state == "bell minus":
            kernel.z(q[0])            # (|00> - |11>)/sqrt(2)
    elif state == "tilted":
        # No symmetry: every term has its own value.
        kernel.ry(0.7, q[0])
        kernel.rx(1.9, q[1])
        kernel.cx(q[0], q[1])
        kernel.t(q[1])
        kernel.ry(-0.4, q[1])
    else:
        assert state == "zero"
    return kernel, q


@pytest.fixture(autouse=True)
def simulator():
    cudaq.set_target("qpp-cpu")
    cudaq.set_random_seed(2026)
    yield
    cudaq.reset_target()


@pytest.mark.parametrize("state", ["zero", "bell", "bell minus", "tilted"])
@pytest.mark.parametrize("basis", ["zz", "xx", "yy", "zx", "xz", "yz", "xy"])
def test_step4_agrees_with_observe_on_the_simulator(state, basis):
    kernel, q = prepared(state)
    want = cudaq.observe(kernel, LETTER[basis[0]](0) * LETTER[basis[1]](1)
                         ).expectation()
    kernel, q = prepared(state)
    example.measure_in(kernel, q, basis)
    counts = dict(cudaq.sample(kernel, shots_count=SHOTS).items())
    assert all(len(bits) == 2 for bits in counts)
    got = example.expectation(counts)
    assert abs(got - want) < CLOSE, f"{state}, <{basis}>: {got} vs {want}"


def test_step4_the_bell_pair_of_the_example():
    for basis, ideal in example.IDEAL.items():
        counts = dict(cudaq.sample(example.bell_kernel(basis),
                                   shots_count=SHOTS).items())
        assert abs(example.expectation(counts) - ideal) < CLOSE


def test_step4_unknown_basis_letter_is_refused():
    kernel, q = prepared("zero")
    with pytest.raises(ValueError):
        example.measure_in(kernel, q, "zw")
