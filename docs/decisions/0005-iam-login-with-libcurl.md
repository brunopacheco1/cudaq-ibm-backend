# 0005. Call IBM IAM with libcurl directly

Date: 2026-11-08. Status: accepted.

## Context

IBM IAM wants a form-encoded body (`grant_type=...&apikey=...`) **[V]**
`src/cudaq_ibm/client.py`, which ran on `ibm_fez`. CUDA-Q's `RestClient::post` always sends
JSON, logs the body at INFO, and turns off TLS certificate checks by default **[V]**
`runtime/common/RestClient.cpp`. Details: [architecture.md](../architecture.md) §2.2.

## Options

- **A.** libcurl directly for this one request.
- **B.** Send JSON through `RestClient` and hope IAM accepts it **[U]** (could not test: the
  cloud environment cannot reach `iam.cloud.ibm.com`).

## Decision

A. libcurl is already linked by CUDA-Q (`CURL::libcurl`), verifies TLS by default, honours
`CURL_CA_BUNDLE`, and never logs the key.

## Consequences

- About 50 lines of plain C curl code in `IBMServerHelper::requestNewToken()`.
- All other calls still go through CUDA-Q (job POST, polling) or `RestClient` with TLS
  checks turned on (`processResults`).

## Revisit when

`RestClient` gains form bodies, safe logging and TLS on by default upstream.
