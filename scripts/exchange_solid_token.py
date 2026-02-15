#!/usr/bin/env python3
"""
Exchange SOLIDDATA_MANAGEMENT_KEY for an access token.

Usage:
  python scripts/exchange_solid_token.py

Reads SOLIDDATA_MANAGEMENT_KEY from env (or .env). Outputs the token to stdout.
Exits with code 1 on auth failure.
"""

import os
import sys
from pathlib import Path

# Load .env from project root
_root = Path(__file__).resolve().parent.parent
_dotenv = _root / ".env"
if _dotenv.exists():
    from dotenv import load_dotenv

    load_dotenv(_dotenv)

AUTH_ENDPOINT = "https://backend.production.soliddata.io/api/v1/auth/exchange_user_access_key"


def main() -> None:
    key = os.getenv("SOLIDDATA_MANAGEMENT_KEY")
    if not key or not key.strip():
        print(
            "Error: SOLIDDATA_MANAGEMENT_KEY not set in environment",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        import requests
    except ImportError:
        print(
            "Error: requests not installed. Run: pip install requests",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        resp = requests.post(
            AUTH_ENDPOINT,
            json={"management_key": key.strip()},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
    except requests.RequestException as e:
        print(f"Error calling Solid auth endpoint: {e}", file=sys.stderr)
        sys.exit(1)

    if resp.status_code == 401:
        print(
            "Error: SolidData returned 401 Unauthorized. "
            "Check that SOLIDDATA_MANAGEMENT_KEY is correct, not expired, "
            "and valid for the auth endpoint (e.g. dev vs prod).",
            file=sys.stderr,
        )
        sys.exit(1)

    resp.raise_for_status()
    data = resp.json()

    if not data:
        print(
            f"Error: Auth endpoint returned empty response. Status {resp.status_code}",
            file=sys.stderr,
        )
        sys.exit(1)

    if isinstance(data, str):
        token = data.strip()
    elif isinstance(data, dict):
        token = (
            data.get("token")
            or data.get("access_token")
            or data.get("accessToken")
        )
        if not token or not isinstance(token, str):
            print(
                "Error: Auth endpoint returned a JSON object but no "
                "'token' or 'access_token' field.",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        print(
            f"Error: Unexpected auth response type: {type(data)}",
            file=sys.stderr,
        )
        sys.exit(1)

    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    print(token)


if __name__ == "__main__":
    main()
