# Copyright (c) 2026 Bruno Pacheco.
# Licensed under the Apache License 2.0.

"""Save a backend's real /configuration and /properties to two JSON files.

Two GET requests, no job, no QPU time. The files feed the parser check
(docs/architecture.md, section 3.7):

    python experiments/fetch_chip_data.py ibm_fez
    g++ -std=c++20 -I plugin plugin/tests/test_chip_data.cpp -o /tmp/tc
    /tmp/tc chipdata/ibm_fez-configuration.json chipdata/ibm_fez-properties.json

Credentials come from IBM_QUANTUM_API_KEY and IBM_QUANTUM_CRN, or from a
git-ignored .env file. They are never printed. The output folder chipdata/
is git-ignored too.

Needs: pip install requests python-dotenv
"""

import argparse
import json
import os
from pathlib import Path

import requests
from dotenv import find_dotenv, load_dotenv

API_URL = "https://quantum.cloud.ibm.com/api"
IAM_URL = "https://iam.cloud.ibm.com/identity/token"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("backend", nargs="?", default="ibm_fez")
    parser.add_argument("--url", default=API_URL, help="API base URL (tests)")
    parser.add_argument("--iam-url", default=IAM_URL, help="IAM URL (tests)")
    parser.add_argument("--out", default="chipdata", help="output folder")
    args = parser.parse_args()

    load_dotenv(find_dotenv(usecwd=True), override=False)
    try:
        key = os.environ["IBM_QUANTUM_API_KEY"]
        crn = os.environ["IBM_QUANTUM_CRN"]
    except KeyError as missing:
        raise SystemExit(f"Set {missing.args[0]} (environment or .env).")

    token = requests.post(
        args.iam_url,
        data={"grant_type": "urn:ibm:params:oauth:grant-type:apikey",
              "apikey": key},
        headers={"Accept": "application/json"}, timeout=30)
    if not token.ok:
        raise SystemExit(f"IAM login failed: HTTP {token.status_code}")
    headers = {"Authorization": f"Bearer {token.json()['access_token']}",
               "Service-CRN": crn, "Accept": "application/json"}

    out = Path(args.out)
    out.mkdir(exist_ok=True)
    for what in ("configuration", "properties"):
        reply = requests.get(f"{args.url}/v1/backends/{args.backend}/{what}",
                             headers=headers, timeout=60)
        if not reply.ok:
            raise SystemExit(f"GET /{what} failed: HTTP {reply.status_code}")
        path = out / f"{args.backend}-{what}.json"
        path.write_text(json.dumps(reply.json(), indent=1))
        print(f"{path}: {path.stat().st_size} bytes, "
              f"keys {sorted(reply.json())[:12]}")


if __name__ == "__main__":
    main()
