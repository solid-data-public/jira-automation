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
import re
import sys
from pathlib import Path

# Load .env from project root
_root = Path(__file__).resolve().parent.parent
_dotenv = _root / ".env"
if _dotenv.exists():
    from dotenv import load_dotenv

    load_dotenv(_dotenv)

REQUIRED_ENV = ["JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"]


def _parse_inline(text: str) -> list[dict]:
    """Parse inline markdown (bold, italic, code) into ADF content nodes."""
    if not text:
        return []
    nodes: list[dict] = []
    i = 0
    plain = []
    while i < len(text):
        # Bold: **...**
        if i + 2 <= len(text) and text[i : i + 2] == "**":
            if plain:
                nodes.append({"type": "text", "text": "".join(plain)})
                plain = []
            end = text.find("**", i + 2)
            if end == -1:
                plain.append(text[i:])
                break
            inner = text[i + 2 : end]
            nodes.append({"type": "text", "text": inner, "marks": [{"type": "strong"}]})
            i = end + 2
            continue
        # Italic: *...* (but not **)
        if i + 1 <= len(text) and text[i] == "*" and (i + 2 > len(text) or text[i + 1] != "*"):
            if plain:
                nodes.append({"type": "text", "text": "".join(plain)})
                plain = []
            end = text.find("*", i + 1)
            if end == -1:
                plain.append(text[i:])
                break
            inner = text[i + 1 : end]
            nodes.append({"type": "text", "text": inner, "marks": [{"type": "em"}]})
            i = end + 1
            continue
        # Code: `...`
        if text[i] == "`":
            if plain:
                nodes.append({"type": "text", "text": "".join(plain)})
                plain = []
            end = text.find("`", i + 1)
            if end == -1:
                plain.append(text[i:])
                break
            inner = text[i + 1 : end]
            nodes.append({"type": "text", "text": inner, "marks": [{"type": "code"}]})
            i = end + 1
            continue
        plain.append(text[i])
        i += 1
    if plain:
        nodes.append({"type": "text", "text": "".join(plain)})
    return nodes if nodes else [{"type": "text", "text": " "}]


def _markdown_to_adf(text: str) -> dict:
    """Convert markdown to Atlassian Document Format for JIRA Cloud API v3."""
    if not text or not text.strip():
        return {"type": "doc", "version": 1, "content": []}
    content: list[dict] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        # Horizontal rule
        if re.match(r"^[-*_]{3,}\s*$", line.strip()):
            content.append({"type": "rule"})
            i += 1
            continue
        # Heading: # ## ### etc
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
        if heading_match:
            level = min(len(heading_match.group(1)), 6)
            content.append(
                {
                    "type": "heading",
                    "attrs": {"level": level},
                    "content": _parse_inline(heading_match.group(2).strip()),
                }
            )
            i += 1
            continue
        # Bullet list
        if re.match(r"^[-*]\s+", line) or re.match(r"^\d+\.\s+", line):
            list_type = "bulletList" if re.match(r"^[-*]\s+", line) else "orderedList"
            list_items: list[dict] = []
            while i < len(lines):
                cur = lines[i]
                bullet = re.match(r"^[-*]\s+(.*)$", cur)
                num = re.match(r"^\d+\.\s+(.*)$", cur)
                if bullet and list_type == "bulletList":
                    list_items.append(
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": _parse_inline(bullet.group(1)),
                                }
                            ],
                        }
                    )
                    i += 1
                elif num and list_type == "orderedList":
                    list_items.append(
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": _parse_inline(num.group(1)),
                                }
                            ],
                        }
                    )
                    i += 1
                elif cur.strip() == "" or not (re.match(r"^[-*]\s+", cur) or re.match(r"^\d+\.\s+", cur)):
                    break
                else:
                    i += 1
            if list_items:
                content.append({"type": list_type, "content": list_items})
            continue
        # Empty line
        if not line.strip():
            i += 1
            continue
        # Paragraph
        content.append(
            {
                "type": "paragraph",
                "content": _parse_inline(line),
            }
        )
        i += 1
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
    payload = {"body": _markdown_to_adf(body)}

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
