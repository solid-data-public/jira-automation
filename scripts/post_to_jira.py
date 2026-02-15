#!/usr/bin/env python3
"""
Post a comment to a JIRA Cloud issue.

Usage:
  python scripts/post_to_jira.py --issue-key PROJECT-123 --body "Comment text"
  echo "Comment text" | python scripts/post_to_jira.py --issue-key PROJECT-123

Requires env vars (or .env): JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN.
"""

import argparse
import os
import sys
from pathlib import Path

# Load .env from project root
_root = Path(__file__).resolve().parent.parent
_dotenv = _root / ".env"
if _dotenv.exists():
    from dotenv import load_dotenv

    load_dotenv(_dotenv)

REQUIRED_ENV = ["JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"]


def _text_to_adf(text: str) -> dict:
    """Convert plain text to Atlassian Document Format for JIRA Cloud API v3."""
    if not text or not text.strip():
        return {"type": "doc", "version": 1, "content": []}
    content = []
    for line in text.split("\n"):
        content.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": line or " "}],
            }
        )
    return {"type": "doc", "version": 1, "content": content}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Post a comment to a JIRA Cloud issue."
    )
    parser.add_argument(
        "--issue-key",
        type=str,
        required=True,
        help="JIRA issue key (e.g. PROJECT-123).",
    )
    parser.add_argument(
        "--body",
        type=str,
        help="Comment body. If not provided, reads from stdin.",
    )
    args = parser.parse_args()

    body = args.body
    if body is None:
        if sys.stdin.isatty():
            parser.error("Provide --body or pipe comment via stdin")
        body = sys.stdin.read()

    if not body.strip():
        print("Error: empty comment body", file=sys.stderr)
        sys.exit(1)

    missing = [k for k in REQUIRED_ENV if not os.getenv(k)]
    if missing:
        print(
            f"Error: missing required env vars: {', '.join(missing)}",
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

    base_url = os.environ["JIRA_BASE_URL"].rstrip("/")
    url = f"{base_url}/rest/api/3/issue/{args.issue_key}/comment"
    auth = (os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"])
    payload = {"body": _text_to_adf(body)}

    try:
        resp = requests.post(
            url,
            json=payload,
            auth=auth,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=30,
        )
    except requests.RequestException as e:
        print(f"Error calling JIRA API: {e}", file=sys.stderr)
        sys.exit(1)

    if resp.status_code >= 400:
        print(
            f"Error: JIRA API returned {resp.status_code}",
            file=sys.stderr,
        )
        try:
            err_body = resp.json()
            print(f"Response: {err_body}", file=sys.stderr)
        except Exception:
            print(f"Response body: {resp.text[:500]}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
