/*******************************************************************************
 * Copyright (c) 2022 - 2026 NVIDIA Corporation & Affiliates.                  *
 * All rights reserved.                                                        *
 *                                                                             *
 * This source code and the accompanying materials are made available under    *
 * the terms of the Apache License 2.0 which accompanies this distribution.    *
 ******************************************************************************/

// clang-format off
// RUN: rm -rf %t.xdg
// RUN: test -f %cudaq_example_plugins_dir/ibm/targets/ibm.yml
// RUN: test -f %cudaq_example_plugins_dir/ibm/lib/libcudaq-serverhelper-ibm%cudaq_plugin_ext
// RUN: FileCheck %s --check-prefix=MOCK-YAML --input-file=%cudaq_example_plugins_dir/ibm/targets/ibm.yml
// RUN: env XDG_DATA_HOME=%t.xdg cudaq-install-plugin --copy %cudaq_example_plugins_dir/ibm
// RUN: env XDG_DATA_HOME=%t.xdg cudaq-install-plugin --list | FileCheck %s --check-prefix=LIST
// RUN: env XDG_DATA_HOME=%t.xdg nvq++ --list-targets | FileCheck %s --check-prefix=TARGETS
// RUN: sed -i.bak 's/^cudaq-version:.*/cudaq-version: "mismatched-test-version"/' %t.xdg/cudaq/plugins/ibm/targets/ibm.yml
// RUN: env XDG_DATA_HOME=%t.xdg nvq++ --target ibm %s -o %t.native 2>&1 | FileCheck %s --check-prefix=VERSION-WARNING
// RUN: test -x %t.native
// RUN: env XDG_DATA_HOME=%t.xdg %t.native
// RUN: PYTHONPATH=%cudaq_target_dir/../python python3 -c "import cudaq; cudaq.register_backend_path('%cudaq_example_plugins_dir/ibm'); cudaq.set_target('ibm'); cudaq.reset_target()"
// RUN: rm -rf %t.python %t.pip-cache %t.python-xdg
// RUN: env PIP_CACHE_DIR=%t.pip-cache python3 -m pip install --no-deps --no-build-isolation --target %t.python %cudaq_example_plugins_dir/ibm
// RUN: env PYTHONPATH=%t.python:%cudaq_target_dir/../python python3 -c "import cudaq; assert cudaq.has_target('ibm'); cudaq.set_target('ibm'); cudaq.reset_target()"
// RUN: env PYTHONPATH=%t.python:%cudaq_target_dir/../python XDG_DATA_HOME=%t.python-xdg python3 -m cudaq_example_ibm --install-nvqpp
// RUN: test -L %t.python-xdg/cudaq/plugins/ibm
// RUN: env XDG_DATA_HOME=%t.python-xdg nvq++ --list-targets | FileCheck %s --check-prefix=TARGETS
// clang-format on

// MOCK-YAML: name: ibm
// MOCK-YAML: cudaq-version:
// MOCK-YAML: platform-qpu: remote_rest
// MOCK-YAML-NOT: plugin-libraries

// LIST: user{{[[:space:]]+}}ibm

// TARGETS: ibm

// VERSION-WARNING: warning: target 'ibm'
// VERSION-WARNING-SAME: was built for CUDA-Q mismatched-test-version
// VERSION-WARNING-SAME: compatibility is not guaranteed

#include <cudaq.h>

__qpu__ void ibm_test_kernel() {
  cudaq::qubit q;
  h(q);
  mz(q);
}

int main() { return cudaq::get_platform().is_remote() ? 0 : 1; }
