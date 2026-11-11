# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.
"""Give the wheel the right file name.

The package holds a compiled library and no Python extension module, so
setuptools would call the wheel "py3-none-any": installable anywhere. That
would be wrong: the library runs on one kind of machine only. This file sets
the tag to "py3-none-<platform>", for example
"py3-none-manylinux_2_28_x86_64": any Python 3, this platform.

plugin/build_wheel.sh passes the platform in CUDAQ_IBM_WHEEL_PLATFORM.
"""

import os

from setuptools import Distribution, setup
from setuptools.command.bdist_wheel import bdist_wheel

PLATFORM = os.environ.get("CUDAQ_IBM_WHEEL_PLATFORM")
if not PLATFORM:
    raise SystemExit("Build this wheel with plugin/build_wheel.sh "
                     "(CUDAQ_IBM_WHEEL_PLATFORM is not set).")


class WithCompiledLibrary(Distribution):
    """Tell setuptools the package is not pure Python."""

    def has_ext_modules(self):
        return True


class PlatformWheel(bdist_wheel):

    def get_tag(self):
        return "py3", "none", PLATFORM


setup(distclass=WithCompiledLibrary, cmdclass={"bdist_wheel": PlatformWheel})
