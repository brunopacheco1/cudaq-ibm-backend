# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""tests/run_ibm_hardware_limits.py: how it words and keeps a result. No
CUDA-Q, no server, no IBM."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import run_ibm_hardware_limits as limits  # noqa: E402


def test_short_results_are_printed_as_they_are():
    assert limits.describe("0110") == "0110"


def test_long_results_are_named_by_how_they_differ_from_all_0_or_all_1():
    assert limits.describe("0" * 20) == "all 0"
    assert limits.describe("1" * 20) == "all 1"
    assert limits.describe("1" * 6 + "0" + "1" * 13) == "all 1 but qubit 6"
    assert (limits.describe("0" * 2 + "1" + "0" * 36 + "1")
            == "all 0 but qubits 2 39")


def test_two_different_results_never_get_the_same_words():
    # Run 6 printed both of these as 11111..11111.
    a = "1" * 20
    b = "1" * 6 + "0" + "1" * 13
    assert limits.describe(a) != limits.describe(b)
    # Far from both: the ends and the number of ones.
    assert (limits.describe("11111" + "01" * 5 + "00000")
            == "11111..00000 with 10 ones")


def test_ones_per_qubit():
    counts = {"000": 50, "111": 30, "101": 20}
    assert limits.ones_per_qubit(counts) == [0.5, 0.3, 0.5]


def test_keep_writes_one_file_with_all_counts(tmp_path):
    jobs = limits.Jobs(None, 0.0, tmp_path / "runs", "ibm_x")
    jobs.keep("width-3", 100, {"000": 60, "111": 40}, {"cz": [[0, 1]]})
    (path,) = (tmp_path / "runs").iterdir()
    assert path.name.endswith("-ibm_x-width-3.json")
    saved = json.loads(path.read_text())
    assert saved["counts"] == {"000": 60, "111": 40}
    assert saved["shots"] == 100 and saved["trace"] == {"cz": [[0, 1]]}


def test_keep_does_nothing_without_a_folder_and_never_raises(tmp_path, capsys):
    limits.Jobs(None, 0.0).keep("width-3", 100, {"000": 100})
    blocked = tmp_path / "file"
    blocked.write_text("not a folder")
    limits.Jobs(None, 0.0, blocked, "ibm_x").keep("width-3", 100, {"0": 1})
    assert "was not saved" in capsys.readouterr().out
