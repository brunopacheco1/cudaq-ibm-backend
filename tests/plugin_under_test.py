# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""Which build of the 'ibm' plugin the run_*.py scripts test.

The environment variable CUDAQ_IBM_PLUGIN chooses:

- not set: the local build in build/external/ibm, written by
  plugin/build_against_wheel.sh (or by the CUDA-Q source build);
- "installed": the pip-installed wheel. cudaq found it by itself at import,
  so there is nothing to register;
- anything else: that folder.

The two ways must not mix: with the wheel installed and a local build
registered on top, nobody could say which of the two a test ran.
"""

import os

LOCAL_BUILD = "build/external/ibm"


def register(cudaq) -> None:
    """Make the target 'ibm' of the chosen build known to `cudaq`."""
    where = os.environ.get("CUDAQ_IBM_PLUGIN", LOCAL_BUILD)
    installed = cudaq.has_target("ibm")
    if where == "installed":
        if not installed:
            raise SystemExit("CUDAQ_IBM_PLUGIN=installed, but this cudaq has "
                             "no target 'ibm'. pip install the wheel first.")
        return
    if installed:
        raise SystemExit("A pip-installed 'ibm' plugin is present. Set "
                         "CUDAQ_IBM_PLUGIN=installed to test it, or "
                         "pip uninstall cudaq-ibm to test the local build.")
    cudaq.register_backend_path(where)
