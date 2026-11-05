"""Step 3: talk to IBM Quantum over plain HTTP.

We do not use ``qiskit-ibm-runtime`` here on purpose. The future C++ plugin
must make these same HTTP calls itself, so writing them by hand now shows
exactly what the plugin will need to do.

Flow:

1. Trade your IBM Cloud API key for a short-lived access token (IAM).
2. ``GET  /v1/backends/{name}/configuration``: gate set and wiring.
3. ``POST /v1/jobs``: submit a Sampler job (OpenQASM 3 circuits).
4. ``GET  /v1/jobs/{id}``: poll until the job finishes.
5. ``GET  /v1/jobs/{id}/results``: fetch the samples.

Reference: https://quantum.cloud.ibm.com/docs/guides/sampler-rest-api
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

DEFAULT_API_URL = "https://quantum.cloud.ibm.com/api/v1"
DEFAULT_IAM_URL = "https://iam.cloud.ibm.com/identity/token"

# Terminal job states reported in ``state.status``.
_DONE = "COMPLETED"
_FAILED = {"FAILED", "CANCELLED"}


class IBMJobError(RuntimeError):
    """The job ended in a failed or cancelled state."""


@dataclass
class IBMQuantumClient:
    """Minimal client for the IBM Quantum REST API.

    ``api_key`` is your IBM Cloud API key. ``crn`` is the Cloud Resource
    Name of your IBM Quantum instance (shown on the instance page). Never
    hard-code either one: read them from environment variables.
    """

    api_key: str
    crn: str
    api_url: str = DEFAULT_API_URL
    iam_url: str = DEFAULT_IAM_URL
    session: requests.Session = field(default_factory=requests.Session)
    timeout: float = 30.0
    _token: str | None = field(default=None, init=False, repr=False)
    _token_expires: float = field(default=0.0, init=False, repr=False)

    # -- auth ---------------------------------------------------------------
    def _access_token(self) -> str:
        """Return a cached IAM token, refreshing it a minute before expiry."""
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        resp = self.session.post(
            self.iam_url,
            data={
                "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                "apikey": self.api_key,
            },
            headers={"Accept": "application/json"},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self._token_expires = time.time() + float(body.get("expires_in", 3600))
        return self._token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token()}",
            "Service-CRN": self.crn,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _get(self, path: str) -> dict[str, Any]:
        resp = self.session.get(
            f"{self.api_url}{path}", headers=self._headers(), timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    # -- API calls ----------------------------------------------------------
    def backend_configuration(self, backend: str) -> dict[str, Any]:
        return self._get(f"/backends/{backend}/configuration")

    def submit_sampler(
        self, backend: str, qasm3_circuits: list[str], shots: int
    ) -> str:
        """Submit one Sampler PUB per circuit and return the job id.

        A PUB ("primitive unified bloc") is ``[circuit, parameter_values,
        shots]``. Our circuits have no free parameters, so the middle entry
        is ``None``. ``version: 2`` selects the Sampler V2 interface, the
        same value the official Python client sends.
        """
        payload = {
            "program_id": "sampler",
            "backend": backend,
            "params": {
                "pubs": [[qasm, None, shots] for qasm in qasm3_circuits],
                "version": 2,
            },
        }
        resp = self.session.post(
            f"{self.api_url}/jobs",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["id"]

    def job_status(self, job_id: str) -> str:
        job = self._get(f"/jobs/{job_id}")
        return str(job["state"]["status"]).upper()

    def wait(
        self,
        job_id: str,
        poll_seconds: float = 5.0,
        timeout: float = 3600.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Block until the job completes. Raise if it fails or times out.

        Real QPU jobs can queue for minutes or hours. Polling is fine for a
        prototype; the C++ plugin gets this loop from CUDA-Q's
        ``remote_rest`` machinery.
        """
        waited = 0.0
        while True:
            status = self.job_status(job_id)
            if status == _DONE:
                return
            if status in _FAILED:
                raise IBMJobError(f"job {job_id} ended with status {status}")
            if waited >= timeout:
                raise TimeoutError(f"job {job_id} still {status} after {timeout}s")
            sleep(poll_seconds)
            waited += poll_seconds

    def results(self, job_id: str) -> dict[str, Any]:
        return self._get(f"/jobs/{job_id}/results")
