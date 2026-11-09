# 0002. Build in NVIDIA's Linux dev container, not natively on macOS

Date: 2026-11-08. Status: accepted.

## Context

The plugin must be compiled inside a CUDA-Q source build, because the pip `cudaq` has no
headers or CMake files **[V]** wheel inventory. CUDA-Q documents a native macOS build, but on
Bruno's Mac it failed: LLVM 22's `lld` cannot read the Xcode 27 SDK (`arm64e.x1`) **[V]**
build log, 2026-11-08.

## Options

- **A.** Keep fighting the native build (older Xcode SDK, patched LLVM).
- **B.** NVIDIA's Linux dev container, run with Podman on Apple Silicon.

## Decision

B. It is the setup CUDA-Q's own developers and CI use, so problems are more likely to be ours
and easier to report upstream.

## Consequences

- The image is pinned **by digest**: NVIDIA deleted the arm64 `releases-v0.16.0` tags.
  If the digest disappears too, we must build the image ourselves.
- The first build takes hours and needs `-j 1` with 8 GB RAM (`ConvertExpr.cpp` runs out of
  memory at higher `-j`).
- Two Python worlds: the Mac `.venv` runs the Python prototype; the container runs the C++
  plugin. Do not mix them.

## Revisit when

A newer CUDA-Q or LLVM fixes the macOS link error, or we move to a newer CUDA-Q release
(then pin a new digest).
