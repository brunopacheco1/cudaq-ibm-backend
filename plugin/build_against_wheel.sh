#!/usr/bin/env bash
# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.
#
# Build the ibm plugin against the pip-installed CUDA-Q. No CUDA-Q source
# build is needed: it takes about a minute (docs/development.md, section 5).
#
# The pip wheel ships the CUDA-Q libraries but no C++ headers. So:
#   - headers:   from the CUDA-Q git commit the wheel was built from (the
#                wheel reports it in cudaq.__version__), plus libcurl's
#                headers in the version the wheel contains;
#   - libraries: libcudaq-common.so and libcudaq-logger.so of the wheel
#                (libcudaq-common.so also exports libcurl).
#
# Usage, from the repository root, in a Python environment with cudaq:
#     plugin/build_against_wheel.sh [output-dir]
# Output (default build/external/ibm, the path the scripts in tests/ use):
#     <output-dir>/lib/libcudaq-serverhelper-ibm.so
#     <output-dir>/targets/ibm.yml
# Environment: PYTHON (default python3), CXX (default g++),
#     CUDAQ_IBM_CACHE (default build/cache; the downloaded headers).
#
# Linux only for now. The library works on systems with a C library at
# least as new as the build machine's; release wheels need an older build
# image (docs/m4-spec.md, F2).

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out="${1:-build/external/ibm}"
python="${PYTHON:-python3}"
cxx="${CXX:-g++}"
cache="${CUDAQ_IBM_CACHE:-build/cache}"

# 1. Ask the installed cudaq where it lives and what it was built from.
#    cudaq.__version__ looks like:
#    "CUDA-Q Version 0.16.0 (https://github.com/NVIDIA/cuda-quantum 9ceceba0...)"
info="$("$python" - <<'EOF' 2>/dev/null
import os
import re
import warnings

warnings.simplefilter("ignore")
import cudaq

found = re.search(r"Version (\S+) \((\S+) ([0-9a-f]{40})\)", cudaq.__version__)
if not found:
    raise SystemExit("cannot read version and commit from: " + cudaq.__version__)
root = os.path.dirname(os.path.dirname(os.path.abspath(cudaq.__file__)))
common = os.path.join(root, "lib", "libcudaq-common.so")
with open(common, "rb") as binary:
    curl = re.search(rb"libcurl/(\d+)\.(\d+)\.(\d+)", binary.read())
if not curl:
    raise SystemExit("no libcurl version found in " + common)
print(found.group(1), found.group(2), found.group(3), root,
      "curl-" + "_".join(part.decode() for part in curl.groups()))
EOF
)" || { echo "error: could not import cudaq with $python" >&2; exit 1; }
read -r version repo commit wheel curl_tag <<<"$info"
echo "cudaq $version (commit ${commit:0:7}) in $wheel, libcurl headers $curl_tag"

# 2. Headers of exactly that commit (kept in the cache between builds).
src="$cache/cuda-quantum-$commit"
if [ ! -f "$src/.complete" ]; then
  rm -rf "$src" && mkdir -p "$src"
  git -C "$src" init -q
  # Only the folders with the headers we include, not the whole repository.
  git -C "$src" sparse-checkout set runtime cudaq/include tpls/json tpls/fmt
  git -C "$src" fetch -q --depth 1 --filter=blob:none "$repo" "$commit"
  git -C "$src" -c advice.detachedHead=false checkout -q FETCH_HEAD
  git -C "$src" submodule update -q --init --depth 1 tpls/fmt
  touch "$src/.complete"
fi
curl_src="$cache/$curl_tag"
if [ ! -f "$curl_src/.complete" ]; then
  rm -rf "$curl_src"
  git -c advice.detachedHead=false clone -q --depth 1 --branch "$curl_tag" \
    https://github.com/curl/curl.git "$curl_src"
  touch "$curl_src/.complete"
fi

# 3. Compile and link. The include paths are the ones CUDA-Q's own build
#    gives a ServerHelper (runtime/common/CMakeLists.txt).
mkdir -p "$out/lib" "$out/targets"
"$cxx" -std=c++20 -fPIC -shared -O2 \
  -I "$here" \
  -I "$src/runtime" -I "$src/runtime/include" -I "$src/runtime/common" \
  -I "$src/cudaq/include" \
  -I "$src/tpls/fmt/include" \
  -I "$src/tpls/json/single_include" -I "$src/tpls/json/single_include_fwd" \
  -I "$curl_src/include" \
  "$here/IBMServerHelper.cpp" \
  -L "$wheel/lib" -lcudaq-common -lcudaq-logger \
  -o "$out/lib/libcudaq-serverhelper-ibm.so"

# 4. The target file, as CMake's configure_file would write it.
sed "s/@CUDA_QUANTUM_VERSION@/$version/" "$here/targets/ibm.yml.in" > "$out/targets/ibm.yml"

echo "built $out (cudaq.register_backend_path(\"$out\"))"
