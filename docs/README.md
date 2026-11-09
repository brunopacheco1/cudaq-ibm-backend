# Docs

The top-level [README](../README.md) is for **users**: what this is, how to install and run it.
This folder is for **contributors**: how the plugin works, why it is built this way, and how
to work on it.

| Page | What it answers | Kind |
|---|---|---|
| [architecture.md](architecture.md) | How does the C++ plugin work today? | Living: update with the code |
| [development.md](development.md) | How do I build and test it? (Linux dev container) | Living |
| [decisions/](decisions/) | Why is it built this way? | Records: one per decision, never rewritten |
| [roadmap.md](roadmap.md) | Where are we, what is next, what could go wrong? | Living |
| [specs/](specs/) | What exactly must a milestone do? | Per milestone; marked done when done |
| [research/](research/) | What did we find before deciding? | Dated notes, frozen; evidence for decisions |
| [upstream.md](upstream.md) | What should be fixed in CUDA-Q itself? | Living list |

## Conventions

- Header block on every page: `Date`, `Status`, `Reader`, and the tags **[V]** verified
  (source given) and **[U]** unverified.
- Numbered sections, cross-referenced with § (code comments cite them, so keep them stable).
- Simple, direct language. Say what is unverified.

## Decision records

Write one when a choice is hard to reverse or someone will later ask "why?". Name it
`decisions/NNNN-short-title.md` and keep it to about 20-40 lines:

```markdown
# NNNN. Title

Date: YYYY-MM-DD. Status: proposed | accepted | superseded by NNNN.

## Context
## Options
## Decision
## Consequences
## Revisit when
```

Never edit an accepted record's decision. If it changes, write a new record and mark the old
one "superseded by NNNN".

| # | Decision | Date |
|---|---|---|
| [0001](decisions/0001-cudaq-routes-helper-rewrites-gates.md) | CUDA-Q routes, the ServerHelper rewrites gates (Option A) | 2026-11-06 |
| [0002](decisions/0002-build-in-linux-dev-container.md) | Build in NVIDIA's Linux dev container, not natively on macOS | 2026-11-08 |
| [0003](decisions/0003-credentials-from-environment.md) | Read IBM credentials from the environment only | 2026-11-08 |
| [0004](decisions/0004-accept-token-expiry-in-v1.md) | Accept token expiry during long polls in v1 | 2026-11-08 |
| [0005](decisions/0005-iam-login-with-libcurl.md) | Call IBM IAM with libcurl directly | 2026-11-08 |

## Specs

| Spec | Milestone | Status |
|---|---|---|
| [m1-spec.md](specs/m1-spec.md) | M1: talk to IBM's REST API | Implemented (PR #1) |

## Research notes

| Note | Content | Supports |
|---|---|---|
| [2026-11-06-phase3-design.md](research/2026-11-06-phase3-design.md) | Options analysis for the C++ plugin (ISA problem, CUDA-Q gaps, QRMI, testing) | [0001](decisions/0001-cudaq-routes-helper-rewrites-gates.md) |
