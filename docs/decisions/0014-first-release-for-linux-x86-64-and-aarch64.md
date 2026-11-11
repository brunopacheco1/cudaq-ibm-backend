# 0014. The first release covers Linux x86_64 and aarch64

Date: 2026-11-10. Status: accepted.
Tags: **[V]** verified (source given), **[U]** unverified.

## Context

pip `cudaq` 0.16.0 exists for Linux x86_64, Linux aarch64 and macOS arm64 (macOS 13+),
Python 3.11 to 3.14 **[V]** PyPI file list, 2026-11-10. The plugin is a compiled library,
so each platform needs its own build and its own test. On 2026-11-10 only Linux x86_64 was
verified. Bruno's Podman machine on his Mac is Linux aarch64.

## Options

- **A.** Linux x86_64 only.
- **B.** A plus Linux aarch64: the plugin then runs in any small Python container on an
  Apple Silicon Mac, without the dev container.
- **C.** B plus macOS arm64: the plugin runs directly on a Mac. Unverified: other
  compiler, other C++ library.

## Decision (Bruno, 2026-11-10)

**B.** macOS is an open item for later, without a time-boxed try now.

## Consequences

- Both wheels are built in the `manylinux_2_28` image and tested in CI on the oldest
  system they claim and on a current one **[V]** workflow `wheels`, 2026-11-11
  ([development.md](../development.md) §7).
- On a Mac the plugin runs only in a Linux container.

## Revisit when

Someone wants to run the plugin directly on macOS.
