#!/usr/bin/env python3
"""
Fetch a JIRA issue by key and output summary and description as plain text.

Usage:
  python scripts/fetch_jira_issue.py --issue-key SA-1
  python scripts/fetch_jira_issue.py --issue-key SA-1 --summary-file summary.txt --description-file description.txt

Outputs to stdout as JSON by default: {"summary": "...", "description": "..."}
Or writes to files when --summary-file and --description-file are provided.

Requires env vars (or .env): JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN.
"""

import argparse
import json
import os
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


def _adf_to_text(node: dict) -> str:
    """Convert an ADF node to plain text. Handles nested structure."""
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
        level = node.get("attrs", {}).get("level", 1)
        prefix = "#" * level + " " if text else ""
        return prefix + text + "\n" if text else ""

    if node_type == "bulletList":
        return _adf_list_to_text(content, bullet="- ")

    if node_type == "orderedList":
        return _adf_ordered_list_to_text(content)

    if node_type == "listItem":
        text = "".join(_adf_to_text(c) for c in content)
        return text.strip() + "\n"

    if node_type == "rule":
        return "---\n"

    if node_type == "codeBlock":
        text = "".join(_adf_to_text(c) for c in content)
        return text + "\n" if text else ""

    if node_type == "blockquote":
        text = "".join(_adf_to_text(c) for c in content)
        return "".join("> " + line for line in text.splitlines(keepends=True)) if text else ""

    if node_type == "table":
        return _adf_table_to_text(content)

    if node_type == "tableRow":
        cells = []
        for c in content:
            if c.get("type") in ("tableCell", "tableHeader"):
                cells.append(_adf_to_text(c).strip())
        return " | ".join(cells) + "\n"

    if node_type in ("tableCell", "tableHeader"):
        return "".join(_adf_to_text(c) for c in content)

    if node_type == "hardBreak":
        return "\n"

    # Unknown node: recurse into content
    if content:
        return "".join(_adf_to_text(c) for c in content)
    return ""


def _adf_list_to_text(items: list, bullet: str = "- ") -> str:
    """Convert bullet list items to text."""
    lines = []
    for item in items:
        if item.get("type") == "listItem":
            text = "".join(_adf_to_text(c) for c in item.get("content", []))
            text = text.strip()
            if text:
                lines.append(bullet + text.replace("\n", "\n  "))
    return "\n".join(lines) + "\n" if lines else ""


def _adf_ordered_list_to_text(items: list) -> str:
    """Convert ordered list items to text."""
    lines = []
    for i, item in enumerate(items, 1):
        if item.get("type") == "listItem":
            text = "".join(_adf_to_text(c) for c in item.get("content", []))
            text = text.strip()
            if text:
                lines.append(f"{i}. " + text.replace("\n", "\n   "))
    return "\n".join(lines) + "\n" if lines else ""


def _adf_table_to_text(rows: list) -> str:
    """Convert table rows to text (one row per line)."""
    return "".join(_adf_to_text(r) for r in rows)


def _extract_description(description_field: dict | None) -> str:
    """Extract plain text from JIRA description field (ADF or legacy)."""
    if description_field is None:
        return ""
    # JIRA Cloud returns description as ADF
    if isinstance(description_field, dict):
        return _adf_to_text(description_field).strip()
    # Legacy plain text
    if isinstance(description_field, str):
        return description_field.strip()
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch JIRA issue summary and description."
    )
    parser.add_argument(
        "--issue-key",
        type=str,
        required=True,
        help="JIRA issue key (e.g. SA-1).",
    )
    parser.add_argument(
        "--summary-file",
        type=str,
        help="Write summary to this file.",
    )
    parser.add_argument(
        "--description-file",
        type=str,
        help="Write description to this file.",
    )
    parser.add_argument(
        "--no-stdout",
        action="store_true",
        help="Do not output JSON to stdout (use with --summary-file/--description-file).",
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
    url = f"{base_url}/rest/api/3/issue/{args.issue_key}"
    auth = (os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"])

    try:
        resp = requests.get(
            url,
            auth=auth,
            headers={"Accept": "application/json"},
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
    fields = data.get("fields", {})
    summary = fields.get("summary") or ""
    description_raw = fields.get("description")
    description = _extract_description(description_raw)

    result = {"summary": summary, "description": description}

    if args.summary_file:
        Path(args.summary_file).write_text(summary, encoding="utf-8")
    if args.description_file:
        Path(args.description_file).write_text(description, encoding="utf-8")

    if not args.no_stdout:
        json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
