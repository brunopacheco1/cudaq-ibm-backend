# 0013. Build the plugin against the pip wheel for CI and releases

Date: 2026-11-10. Status: accepted.
Tags: **[V]** verified (source given), **[U]** unverified.

## Context

Until M4 the plugin was built only inside a CUDA-Q source build in NVIDIA's dev container
([decision 0002](0002-build-in-linux-dev-container.md)). That build takes hours, needs an
image pinned by a digest NVIDIA may delete, and only Bruno has it. So CI could not build
the plugin, and nobody else could run it.

Found on 2026-11-10 **[V]** `plugin/build_against_wheel.sh`: the plugin also builds with
one `g++` call, in about a minute, from the headers of the CUDA-Q `0.16.0` git tag and the
libraries inside the pip `cudaq` wheel (`libcudaq-common.so`, `libcudaq-logger.so`; the
wheel also exports libcurl 8.21.0). The result loads into pip `cudaq` 0.16.0 and
0.16.0.post1 and passes the fake-server cases.

## Options

- **A.** Against the pip wheel. Minutes in GitHub's CI, and an agent in the cloud can
  build and run the plugin.
- **B.** Inside the CUDA-Q source build, as before. This is the way NVIDIA documents
  **[V]** `packaging.rst` (tag `0.16.0`).
- **C.** Both: A for CI and releases, B stays Bruno's environment for work on CUDA-Q
  itself.

## Decision (Bruno, 2026-11-10)

**C.**

## Consequences

- A is not the documented way. If headers and wheel differ, the plugin could misbehave at
  run time instead of failing at compile time. Guard: CI builds the plugin and runs the
  end-to-end tests against every `cudaq` release the plugin claims to support.
- The release wheel is built this way, once, against the oldest supported `cudaq`
  ([development.md](../development.md) §6 and §7).
- `plugin/CMakeLists.txt` stays for the source build, but CI does not run it.

## Revisit when

A new `cudaq` release breaks the wheel-based build, or NVIDIA ships the headers in the
wheel or documents another way to build a plugin outside the source tree.
