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
"""`python -m cudaq_ibm_plugin --install-nvqpp`

Links this package into the folder where the C++ compiler `nvq++` looks for
plugins (`~/.local/share/cudaq/plugins/ibm`). Python users do not need it.
"""

PACKAGE_NAME = "cudaq_ibm_plugin"
PLUGIN_NAME = "ibm"


def main() -> int:
    from cudaq.plugins import install_plugin_for_nvqpp_main
    return install_plugin_for_nvqpp_main(PACKAGE_NAME, PLUGIN_NAME)


if __name__ == "__main__":
    raise SystemExit(main())
