#!/usr/bin/env bash
# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.
#
# Build the wheel of the ibm plugin: one file that `pip install` puts next to
# pip `cudaq`, after which cudaq.set_target("ibm") works.
#
# Usage, from the repository root, in a Python environment with cudaq:
#     plugin/build_wheel.sh [output-dir]          # default: dist
# Output:
#     <output-dir>/cudaq_ibm-<version>-py3-none-<platform>.whl
# Environment: PYTHON (default python3), CXX (default g++),
#     CUDAQ_IBM_CACHE (default build/cache; the downloaded headers),
#     CUDAQ_IBM_REQUIRE_PORTABLE=1: fail if the wheel would only fit this
#     machine (release builds set it).
#
# What is in the wheel (see it with: unzip -l <wheel>):
#     cudaq_ibm_plugin/__init__.py        tells cudaq where the two files below are
#     cudaq_ibm_plugin/__main__.py        --install-nvqpp, for the C++ compiler
#     cudaq_ibm_plugin/lib/libcudaq-serverhelper-ibm.so   the plugin
#     cudaq_ibm_plugin/targets/ibm.yml    the target description
#
# A wheel for other people must be built on an old Linux, or its library
# does not load on older systems (docs/development.md, section 7). The
# release workflow runs this script inside the image the Python community
# keeps for that purpose:
#     docker run --rm -v "$PWD":/io -w /io \
#       -e PYTHON=/opt/python/cp312-cp312/bin/python \
#       -e CUDAQ_IBM_REQUIRE_PORTABLE=1 \
#       quay.io/pypa/manylinux_2_28_x86_64 \
#       bash -c 'git config --global --add safe.directory "*" &&
#                $PYTHON -m pip install cudaq==0.16.0 && plugin/build_wheel.sh'
# Built outside such an image the wheel still works, on this machine: it gets
# the tag linux_<machine> in place of manylinux_2_28_<machine>.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dist="${1:-dist}"
python="${PYTHON:-python3}"
stage="build/wheel"

# 1. One folder with everything the wheel is made of.
rm -rf "$stage"
mkdir -p "$stage" "$dist"
cp "$here/packaging/pyproject.toml" "$here/packaging/setup.py" \
   "$here/packaging/README.md" "$here/../LICENSE" "$here/../NOTICE" "$stage/"
cp -r "$here/packaging/cudaq_ibm_plugin" "$stage/"
find "$stage" -name __pycache__ -prune -exec rm -rf {} +

# 2. The library and the target file, built straight into the package.
PYTHON="$python" "$here/build_against_wheel.sh" "$stage/cudaq_ibm_plugin"

# 3. Which machines may install it?
platform="$("$python" "$here/packaging/wheel_platform.py" \
  "$stage/cudaq_ibm_plugin/lib/libcudaq-serverhelper-ibm.so")"

# 4. The wheel. pip builds it in a fresh environment with setuptools.
CUDAQ_IBM_WHEEL_PLATFORM="$platform" \
  "$python" -m pip wheel --quiet --no-deps --wheel-dir "$dist" "$stage"

echo "built $(ls "$dist"/cudaq_ibm-*-py3-none-"$platform".whl)"
