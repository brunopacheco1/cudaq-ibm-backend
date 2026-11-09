# Docs

The top-level [README](../README.md) is for **users**: what this is, how to install and run it.
This folder is for **contributors**: how the plugin works, why it is built this way, what is
next, and how to work on it.

| Page | What it answers | Kind |
|---|---|---|
| [architecture.md](architecture.md) | How does the C++ plugin work today? (incl. IBM's REST API) | Living: update with the code |
| [decisions/](decisions/) | Why is it built this way? | Records: one per decision, never rewritten |
| [roadmap.md](roadmap.md) | Where are we, what is next, what could go wrong? | Living |
| [development.md](development.md) | How do I build and test it? (Linux dev container) | Living |
| [upstream.md](upstream.md) | What should be fixed in CUDA-Q itself? | Living list |
| [m3-spec.md](m3-spec.md) | What exactly will M3 (routing) build? | Draft, deleted when M3 is done |

## Conventions

- Header block on every page: `Date`, `Status`, `Reader`, and the tags **[V]** verified
  (source given) and **[U]** unverified.
- Numbered sections, cross-referenced with §. Code comments cite `architecture.md` sections,
  so keep those numbers stable.
- Simple, direct language. Say what is unverified.
- No duplication: a fact lives in one page and the others link to it.

## Milestone specs

Before coding a milestone, write a spec: what to build, the facts it relies on, and the test
plan. Keep it as `docs/mN-spec.md` while the milestone is in progress. When the milestone is
done, move the lasting facts into `architecture.md`, the choices into `decisions/`, and delete
the spec. Git history keeps it.

## Decision records

Write one when a choice is hard to reverse or someone will later ask "why?". Name it
`decisions/NNNN-short-title.md` and keep it to about 20-50 lines:

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
| [0006](decisions/0006-send-openqasm3-with-physical-qubits.md) | Send OpenQASM 3 with physical qubits `$k` | 2026-11-06 |
| [0007](decisions/0007-qrmi-later-not-in-v1.md) | QRMI as a later transport, not in v1 | 2026-11-06 |
| [0008](decisions/0008-test-against-a-fake-ibm-server.md) | Test against a fake IBM server | 2026-11-08 |
