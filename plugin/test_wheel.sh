#!/usr/bin/env bash
# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.
#
# Test a built wheel the way a user gets it: install it next to pip cudaq in
# a fresh environment, then run the fake-server tests with the installed
# plugin. Never touches IBM.
#
# Usage, from the repository root:
#     plugin/test_wheel.sh <wheel> [cudaq-version]
# Environment: PYTHON (default python3).
#
# The four checks:
#   1. after `pip install`, cudaq has the target "ibm" (no register call);
#   2. the eight protocol cases (tests/run_fake_ibm.py);
#   3. the result checks against CUDA-Q's simulator
#      (tests/run_fake_ibm_results.py);
#   4. `python -m cudaq_ibm_plugin --install-nvqpp` links the package into
#      the folder nvq++ reads.

set -euo pipefail

wheel="${1:?usage: plugin/test_wheel.sh <wheel> [cudaq-version]}"
cudaq_version="${2:-}"
python="${PYTHON:-python3}"
port=62455

work="$(mktemp -d)"
server=""
cleanup() {
  # wait: so that bash does not print "Terminated" for the server at the end.
  if [ -n "$server" ]; then
    { kill "$server" && wait "$server"; } 2>/dev/null || true
  fi
  rm -rf "$work"
}
trap cleanup EXIT

"$python" -m venv "$work/venv"
py="$work/venv/bin/python"
"$py" -m pip install --quiet --upgrade pip
"$py" -m pip install --quiet "cudaq${cudaq_version:+==$cudaq_version}" "$wheel" \
  fastapi uvicorn python-multipart

echo "== 1. cudaq has the target 'ibm' after pip install"
"$py" -W ignore -c "
import cudaq
assert cudaq.has_target('ibm'), 'no target ibm'
print('  ', cudaq.__version__)"

# From here on the scripts in tests/ use the installed plugin, not a local
# build (tests/plugin_under_test.py).
export CUDAQ_IBM_PLUGIN=installed

echo "== 2. protocol cases"
"$py" tests/fake_ibm_server.py "$port" > "$work/fake-server.log" 2>&1 &
server=$!
for _ in $(seq 1 60); do
  (echo > "/dev/tcp/127.0.0.1/$port") 2>/dev/null && break
  sleep 0.5
done
"$py" tests/run_fake_ibm.py || { cat "$work/fake-server.log"; exit 1; }

echo "== 3. results against CUDA-Q's simulator"
"$py" tests/run_fake_ibm_results.py

echo "== 4. --install-nvqpp"
CUDAQ_PLUGIN_ROOT="$work/nvqpp" "$py" -W ignore -m cudaq_ibm_plugin --install-nvqpp
test -f "$work/nvqpp/ibm/lib/libcudaq-serverhelper-ibm.so"
test -f "$work/nvqpp/ibm/targets/ibm.yml"

echo "RESULT: the wheel $(basename "$wheel") passes all four checks."
