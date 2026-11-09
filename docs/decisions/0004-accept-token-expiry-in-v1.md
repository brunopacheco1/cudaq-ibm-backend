# 0004. Accept token expiry during long polls in v1

Date: 2026-11-08. Status: accepted. Decided by: Bruno.

## Context

CUDA-Q's `Future::get` calls `getHeaders()` **once** per job and reuses those headers for the
whole poll loop, while `getCookies()` is called on every poll **[V]**
`runtime/common/Future.cpp`. IBM tokens last about 60 minutes, and Open-plan jobs can wait
longer than that in the queue. Then polling fails with an expired token.

## Options

- **A.** Document the limit in v1, fix it upstream: call `getHeaders()` inside the poll loop.
- **B.** Do our own polling inside `processResults()`, refreshing the token as needed.
- **C.** Smuggle the token through `getCookies()`.

## Decision

A, with B as the fallback only if upstream rejects the PR. C is a hack that would confuse
anyone reading the code.

## Consequences

- Long queue waits can fail in v1. The job still runs on IBM; its results can be fetched
  later with the Python prototype.
- The upstream PR is listed in [upstream.md](../upstream.md).

## Revisit when

The upstream PR is merged (remove the limit from the docs) or rejected (implement B).
