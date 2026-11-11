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
"""The `ibm` target for CUDA-Q, as an installable package.

Nobody imports this package by hand. `import cudaq` looks for entry points in
the group `cudaq.backends` and calls `register` below, which tells CUDA-Q
where this package's `targets/ibm.yml` and `lib/` are. After that
`cudaq.set_target("ibm", ...)` works.
"""

from importlib.resources import files


def register():
    import cudaq

    cudaq.register_backend_path(str(files(__name__)))


__all__ = ["register"]
