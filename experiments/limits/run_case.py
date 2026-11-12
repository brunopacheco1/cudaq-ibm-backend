# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""Run one probe and print its result as one line of JSON (see run.py)."""
import importlib
import json
import sys

module, case = sys.argv[1], sys.argv[2]
try:
    result = getattr(importlib.import_module(module), case)()
except BaseException as error:  # noqa: BLE001
    text = str(error).strip() or type(error).__name__
    result = {"outcome": "error", "detail": f"{type(error).__name__}: {text}"[:1500]}
print("PROBE " + json.dumps(result), flush=True)
