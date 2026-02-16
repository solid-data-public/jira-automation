#!/usr/bin/env python3
"""
Fetch JIRA issue comments and extract session_id from bot comments.

Usage:
  python scripts/fetch_jira_comments.py --issue-key SA-1
  python scripts/fetch_jira_comments.py --issue-key SA-1 --user-comment-file comment.txt
  python scripts/fetch_jira_comments.py --issue-key SA-1 --session-file session.txt

Outputs JSON: {"session_id": "...", "user_comment": "..."}
Or writes to files when --session-file and --user-comment-file are provided.

The session_id is extracted from the most recent bot comment (by JIRA_EMAIL author)
that contains "Session: `uuid`" or similar. The user_comment is the most recent
comment NOT by the bot (for reply flows).

Requires env vars (or .env): JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

# Load .env from project root
_root = Path(__file__).resolve().parent.parent
_dotenv = _root / ".env"
if _dotenv.exists():
    from dotenv import load_dotenv

    load_dotenv(_dotenv)

REQUIRED_ENV = ["JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"]

# Regex to extract session ID from comment body (matches Session: `uuid` or Session: uuid)
SESSION_PATTERN = re.compile(
    r"[Ss]ession:\s*[`]?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})[`]?",
    re.IGNORECASE,
)


def _adf_to_text(node: dict) -> str:
    """Convert an ADF node to plain text."""
    if not isinstance(node, dict):
        return ""
    node_type = node.get("type", "")
    content = node.get("content", [])

    if node_type == "doc":
        return "".join(_adf_to_text(c) for c in content)
    if node_type == "paragraph":
        text = "".join(_adf_to_text(c) for c in content)
        return text + "\n" if text else ""
    if node_type == "text":
        return node.get("text", "")
    if node_type == "heading":
        text = "".join(_adf_to_text(c) for c in content)
        return text + "\n" if text else ""
    if node_type == "bulletList":
        return "".join(_adf_to_text(c) for c in content)
    if node_type == "orderedList":
        return "".join(_adf_to_text(c) for c in content)
    if node_type == "listItem":
        text = "".join(_adf_to_text(c) for c in content)
        return text.strip() + "\n"
    if node_type == "rule":
        return "---\n"
    if node_type == "codeBlock":
        text = "".join(_adf_to_text(c) for c in content)
        return text + "\n" if text else ""
    if node_type == "hardBreak":
        return "\n"
    if content:
        return "".join(_adf_to_text(c) for c in content)
    return ""


def _body_to_text(body: dict | None) -> str:
    """Extract plain text from JIRA comment body (ADF)."""
    if body is None:
        return ""
    if isinstance(body, str):
        return body.strip()
    return _adf_to_text(body).strip()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch JIRA comments and extract session_id from bot comments."
    )
    parser.add_argument(
        "--issue-key",
        type=str,
        required=True,
        help="JIRA issue key (e.g. SA-1).",
    )
    parser.add_argument(
        "--session-file",
        type=str,
        help="Write session_id to this file (if found).",
    )
    parser.add_argument(
        "--user-comment-file",
        type=str,
        help="Write the latest user comment body to this file.",
    )
    parser.add_argument(
        "--no-stdout",
        action="store_true",
        help="Do not output JSON to stdout.",
    )
    args = parser.parse_args()

    if requests is None:
        print("Error: requests not installed. Run: pip install requests", file=sys.stderr)
        sys.exit(1)

    missing = [k for k in REQUIRED_ENV if not os.getenv(k)]
    if missing:
        print(
            f"Error: missing required env vars: {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(1)

    base_url = os.environ["JIRA_BASE_URL"].rstrip("/")
    bot_email = os.environ["JIRA_EMAIL"]
    auth = (bot_email, os.environ["JIRA_API_TOKEN"])

    url = f"{base_url}/rest/api/3/issue/{args.issue_key}/comment"
    try:
        resp = requests.get(
            url,
            auth=auth,
            headers={"Accept": "application/json"},
            params={},
            timeout=30,
        )
    except requests.RequestException as e:
        print(f"Error calling JIRA API: {e}", file=sys.stderr)
        sys.exit(1)

    if resp.status_code == 404:
        print(f"Error: issue {args.issue_key} not found", file=sys.stderr)
        sys.exit(1)
    if resp.status_code >= 400:
        print(
            f"Error: JIRA API returned {resp.status_code}: {resp.text[:500]}",
            file=sys.stderr,
        )
        sys.exit(1)

    data = resp.json()
    comments = data.get("comments", [])
    # Sort by created descending (newest first)
    comments = sorted(
        comments,
        key=lambda c: c.get("created", ""),
        reverse=True,
    )

    session_id: str | None = None
    user_comment: str = ""

    for c in comments:
        author = c.get("author", {})
        author_email = author.get("emailAddress", "") or author.get("email", "")
        body_text = _body_to_text(c.get("body"))

        if author_email == bot_email:
            # Bot comment: try to extract session_id
            match = SESSION_PATTERN.search(body_text)
            if match:
                session_id = match.group(1)
                break  # Use most recent bot comment with session
        else:
            # User comment: take the most recent one (first in desc order)
            if not user_comment:
                user_comment = body_text

    result = {"session_id": session_id, "user_comment": user_comment}

    if args.session_file and session_id:
        Path(args.session_file).write_text(session_id, encoding="utf-8")
    if args.user_comment_file:
        Path(args.user_comment_file).write_text(user_comment, encoding="utf-8")

    if not args.no_stdout:
        json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
