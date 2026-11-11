# ============================================================================ #
# Copyright (c) 2022 - 2026 NVIDIA Corporation & Affiliates.                   #
# All rights reserved.                                                         #
#                                                                              #
# Modifications copyright (c) 2026 Bruno Pacheco.                              #
# Adapted from the CUDA-Q mock_rest plugin example for IBM Quantum.            #
#                                                                              #
# This source code and the accompanying materials are made available under     #
# the terms of the Apache License 2.0 which accompanies this distribution.     #
# ============================================================================ #

# Builds the plugin inside a CUDA-Q source build, as an external project
# (docs/development.md, section 4). It writes lib/ and targets/ into
# build/external/ibm, the folder cudaq.register_backend_path() takes.
# The wheel is not built here: plugin/build_wheel.sh builds it against the
# pip-installed cudaq.

set(plugin_root ${CMAKE_CURRENT_BINARY_DIR})
set(plugin_lib_dir ${plugin_root}/lib)
set(plugin_target_dir ${plugin_root}/targets)
file(MAKE_DIRECTORY ${plugin_lib_dir} ${plugin_target_dir})
configure_file(targets/ibm.yml.in
               ${plugin_target_dir}/ibm.yml
               @ONLY)

add_library(cudaq-example-serverhelper-ibm EXCLUDE_FROM_ALL SHARED
  IBMServerHelper.cpp)
set_target_properties(cudaq-example-serverhelper-ibm
  PROPERTIES
    OUTPUT_NAME cudaq-serverhelper-ibm
    LIBRARY_OUTPUT_DIRECTORY ${plugin_lib_dir}
    RUNTIME_OUTPUT_DIRECTORY ${plugin_lib_dir}
    ARCHIVE_OUTPUT_DIRECTORY ${plugin_lib_dir})
target_include_directories(cudaq-example-serverhelper-ibm
  PRIVATE ${PROJECT_SOURCE_DIR}/runtime)
target_link_libraries(cudaq-example-serverhelper-ibm
  PRIVATE cudaq-common cudaq-logger CURL::libcurl)
