# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.
"""Print the platform tag for the wheel of the built plugin library.

    python wheel_platform.py path/to/libcudaq-serverhelper-ibm.so

The plugin is useful only next to pip `cudaq`, so the best tag it can have is
cudaq's own, for example "manylinux_2_28_x86_64": Linux on x86_64 with glibc
2.28 or newer. That tag is only true if our library was built on a system
that old. A library built on a newer system asks the C library for newer
functions and does not load on an older one.

So this script reads what the library asks for (`objdump -T` lists entries
such as "GLIBC_2.38") and compares the highest glibc version with the one in
cudaq's tag:

- not newer: print cudaq's tag;
- newer: print "linux_<machine>", the tag for "this machine only", and say
  why on stderr. With CUDAQ_IBM_REQUIRE_PORTABLE=1 (release builds) this case
  is an error.
"""

import os
import platform
import re
import subprocess
import sys
from importlib import metadata


def cudaq_platform_tag() -> str:
    """The platform part of the tag of the installed cudaq wheel."""
    # pip `cudaq` is a small package that pulls in the real one
    # (cuda-quantum-cu12 or -cu13). Other packages add files to the folder
    # `cudaq` too, so look for the one that owns cudaq/__init__.py.
    for name in metadata.packages_distributions().get("cudaq", []):
        distribution = metadata.distribution(name)
        if not any(str(file) == "cudaq/__init__.py"
                   for file in distribution.files or []):
            continue
        wheel_file = distribution.read_text("WHEEL") or ""
        for tag in re.findall(r"^Tag: \S+-\S+-(\S+)$", wheel_file, re.M):
            if tag != "any":
                return tag
    raise SystemExit("cannot find the platform tag of the installed cudaq")


def highest_glibc(library: str) -> tuple[int, int]:
    """The newest glibc version whose functions the library asks for."""
    symbols = subprocess.run(["objdump", "-T", library], check=True,
                             capture_output=True, text=True).stdout
    versions = {(int(major), int(minor))
                for major, minor in re.findall(r"GLIBC_(\d+)\.(\d+)", symbols)}
    if not versions:
        raise SystemExit(f"no glibc versions found in {library}")
    return max(versions)


def main() -> int:
    library = sys.argv[1]
    tag = cudaq_platform_tag()
    needs = highest_glibc(library)
    found = re.fullmatch(r"manylinux_(\d+)_(\d+)_(\w+)", tag)
    if found and needs <= (int(found[1]), int(found[2])):
        print(tag)
        return 0
    local = f"linux_{platform.machine()}"
    reason = (f"the library needs glibc {needs[0]}.{needs[1]}, cudaq's tag "
              f"is {tag}")
    if os.environ.get("CUDAQ_IBM_REQUIRE_PORTABLE") == "1":
        print(f"error: {reason}. Build in a manylinux image "
              "(plugin/build_wheel.sh says how).", file=sys.stderr)
        return 1
    print(f"note: {reason}. The wheel gets the tag {local}: for this "
          "machine, not for a release.", file=sys.stderr)
    print(local)
    return 0


if __name__ == "__main__":
    sys.exit(main())
