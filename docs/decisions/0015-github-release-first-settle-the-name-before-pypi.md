# 0015. Wheels on a GitHub Release first; settle the name before PyPI

Date: 2026-11-10. Status: accepted.
Tags: **[V]** verified (source given), **[U]** unverified.

## Context

The wheels need a place and a name. `cudaq-ibm` was free on PyPI on 2026-11-10 **[V]** (so
were `cudaq-ibm-backend` and `cudaq-ibm-plugin`). The Python prototype in `src/` already
uses the names `cudaq-ibm-backend` and `cudaq_ibm`. The project is unofficial, and "IBM"
would be part of the package name.

What IBM's trademark page says **[V]** https://www.ibm.com/legal/copyright-trademark (read
2026-11-10): text-only references that are truthful and do not mislead are fair use; "Do
not incorporate any IBM product names into your company's product names"; "You must be
clear and accurate as to the nature of the relationship between IBM and your company"; the
first mention needs an attribution line; "Always consult a local attorney". It names no
contact for a question like ours. NVIDIA's packaging guide names its example plugin
`my-backend-cudaq` **[V]** `packaging.rst:137`. Other vendors publish packages named after
someone else's product (`pennylane-qiskit`, `pytket-qiskit`, `qiskit-ionq` **[V]** PyPI):
that shows a habit, not a permission.

## Options

- **A.** A GitHub Release of this repository: wheel files to download.
- **B.** PyPI: `pip install <name>` for everyone. An uploaded file cannot be replaced; a
  fix needs a new version number **[U]** (PyPI's long-standing rule, not reread).
- **C.** No wheels, only build instructions.

## Decision (Bruno, 2026-11-10)

**A now, PyPI later.** Working name: `cudaq-ibm` for the distribution. The name is settled
(ask IBM, or pick a name without "IBM") **before PyPI**, where a name is hard to change.
The README carries IBM's attribution line and a "not affiliated" sentence.

## Consequences

- The import package is `cudaq_ibm_plugin`, so it does not collide with the prototype's
  `cudaq_ibm`. The prototype stays unpublished.
- Users install by URL from the release page. `pip install cudaq-ibm` does not work.
- On a GitHub Release a rename costs little: a new release under the new name.
- Only Bruno creates tags and releases (`AGENTS.md`).

## Revisit when

Someone other than Bruno has used the plugin, or before any upload to PyPI.
