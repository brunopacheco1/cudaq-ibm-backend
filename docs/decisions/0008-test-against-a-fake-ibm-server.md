# 0008. Test against a fake IBM server

Date: 2026-11-08. Status: accepted.
Tags: **[V]** verified (source given), **[U]** unverified.

## Context

Real IBM runs cost QPU time (Open plan: about 10 minutes per 28 days), need credentials, and
reject anything that is not ISA. CUDA-Q tests its in-tree backends with a FastAPI mock per
backend under `python/tests/utils/mock_qpu/<name>/` **[V]** `python/tests/backends/test_IQM.py:36-60`.

## Options

- **A.** Test only against real IBM.
- **B.** A FastAPI fake of IBM's IAM and jobs API, in the same style as CUDA-Q's mocks.

## Decision

B: `tests/fake_ibm_server.py`, driven by `tests/run_fake_ibm.py`. It checks the form-encoded
IAM body, the auth headers and that every gate is native, so it catches the same mistakes the
real service would.

## Consequences

- Every change can be tested in seconds with no account.
- The fake can drift from the real API; the first hardware run per milestone is the check.
- Still to add: `GET /backends/{name}/configuration` (M3) and automated failure tests.

## Revisit when

IBM's API changes, or CUDA-Q would accept the fake as an in-tree mock ([upstream.md](../upstream.md) #6).
