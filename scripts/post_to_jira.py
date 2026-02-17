#!/usr/bin/env python3
"""
Post a comment to a JIRA Cloud issue.

Usage:
  python scripts/post_to_jira.py --issue-key PROJECT-123 --body "Comment text"
  echo "Comment text" | python scripts/post_to_jira.py --issue-key PROJECT-123
  python scripts/post_to_jira.py --issue-key PROJECT-123 --attachments-dir ./queries < body.txt
  python scripts/post_to_jira.py --issue-key PROJECT-123 --reasoning-file reasoning.txt < body.txt

When --attachments-dir is set, all files in that directory are uploaded as issue
attachments before the comment is posted, and the comment body is appended with
a list of the attached SQL query files.

When --reasoning-file is set, that file is uploaded as an attachment and listed under
"Reasoning" in the comment body.

When --append-session is set, appends "Reply to continue the conversation. Session: `uuid`"
so the reply workflow can resume the Cursor conversation.

Requires env vars (or .env): JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN.
"""

import argparse
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
        # Markdown table: | col1 | col2 | col3 |
        if line.strip().startswith("|") and "|" in line.strip()[1:]:
            table_rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                row_line = lines[i]
                cells = [c.strip() for c in row_line.split("|")[1:-1]]
                if not cells:
                    i += 1
                    continue
                # Skip separator row: |---|----|---|
                if all(re.match(r"^[-:]+$", c) for c in cells):
                    i += 1
                    continue
                table_rows.append(cells)
                i += 1
            if table_rows:
                adf_rows: list[dict] = []
                for row_idx, cells in enumerate(table_rows):
                    cell_type = "tableHeader" if row_idx == 0 else "tableCell"
                    adf_cells = [
                        {
                            "type": cell_type,
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": _parse_inline(cell),
                                }
                            ],
                        }
                        for cell in cells
                    ]
                    adf_rows.append({"type": "tableRow", "content": adf_cells})
                content.append({"type": "table", "content": adf_rows})
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


def _upload_file(
    base_url: str,
    auth: tuple[str, str],
    issue_key: str,
    file_path: Path,
) -> str | None:
    """Upload a single file to the JIRA issue. Returns filename if successful."""
    url = f"{base_url}/rest/api/3/issue/{issue_key}/attachments"
    headers = {"X-Atlassian-Token": "no-check"}
    try:
        with open(file_path, "rb") as fp:
            resp = requests.post(
                url,
                auth=auth,
                headers=headers,
                files={"file": (file_path.name, fp, "text/plain")},
                timeout=60,
            )
        if resp.status_code >= 400:
            print(
                f"Warning: failed to upload {file_path.name}: {resp.status_code} {resp.text[:200]!r}",
                file=sys.stderr,
            )
            return None
        print(f"Uploaded {file_path.name}", file=sys.stderr)
        return file_path.name
    except Exception as e:
        print(f"Warning: failed to upload {file_path.name}: {e}", file=sys.stderr)
        return None


def _upload_attachments(
    base_url: str,
    auth: tuple[str, str],
    issue_key: str,
    attachments_dir: Path,
) -> list[str]:
    """Upload all files in attachments_dir to the JIRA issue. Returns list of filenames."""
    files = sorted(f for f in attachments_dir.iterdir() if f.is_file())
    if not files:
        return []
    uploaded: list[str] = []
    url = f"{base_url}/rest/api/3/issue/{issue_key}/attachments"
    headers = {"X-Atlassian-Token": "no-check"}
    for f in files:
        try:
            with open(f, "rb") as fp:
                resp = requests.post(
                    url,
                    auth=auth,
                    headers=headers,
                    files={"file": (f.name, fp, "application/octet-stream")},
                    timeout=60,
                )
            if resp.status_code >= 400:
                print(
                    f"Warning: failed to upload {f.name}: {resp.status_code} {resp.text[:200]!r}",
                    file=sys.stderr,
                )
            else:
                uploaded.append(f.name)
                print(f"Uploaded {f.name}", file=sys.stderr)
        except Exception as e:
            print(f"Warning: failed to upload {f.name}: {e}", file=sys.stderr)
    return uploaded


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
    parser.add_argument(
        "--attachments-dir",
        type=str,
        help="Directory of files to attach to the issue before posting the comment.",
    )
    parser.add_argument(
        "--reasoning-file",
        type=str,
        metavar="PATH",
        help="Path to reasoning/thinking log file to attach (listed under Reasoning in comment).",
    )
    parser.add_argument(
        "--append-session",
        type=str,
        metavar="SESSION_ID",
        help="Append session ID for reply continuation (embeds in comment).",
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

    if requests is None:
        print(
            "Error: requests not installed. Run: pip install requests",
            file=sys.stderr,
        )
        sys.exit(1)

    base_url = os.environ["JIRA_BASE_URL"].rstrip("/")
    auth = (os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"])

    uploaded: list[str] = []
    reasoning_name: str | None = None

    if args.attachments_dir:
        attachments_path = Path(args.attachments_dir).resolve()
        if attachments_path.exists() and attachments_path.is_dir():
            files = list(attachments_path.iterdir())
            print(f"Attachments dir: {attachments_path} ({len(files)} items)", file=sys.stderr)
            uploaded = _upload_attachments(base_url, auth, args.issue_key, attachments_path)
            print(f"Uploaded {len(uploaded)} of {len(files)} files to JIRA", file=sys.stderr)
            if uploaded:
                body += "\n\n---\n\n**SQL queries:**\n"
                for name in sorted(uploaded):
                    body += f"- {name}\n"
        else:
            print(
                f"Attachments dir not found or not a directory: {attachments_path}",
                file=sys.stderr,
            )

    if args.reasoning_file:
        reasoning_path = Path(args.reasoning_file).resolve()
        if reasoning_path.exists() and reasoning_path.is_file():
            name = _upload_file(base_url, auth, args.issue_key, reasoning_path)
            if name:
                reasoning_name = name
        else:
            print(
                f"Reasoning file not found: {reasoning_path}",
                file=sys.stderr,
            )

    if reasoning_name:
        body += "\n\n---\n\n**Reasoning:**\n"
        body += f"- {reasoning_name}\n"

    if args.append_session:
        body += "\n\n---\n\n*Reply to continue the conversation. Session: `" + args.append_session + "`*"

    url = f"{base_url}/rest/api/3/issue/{args.issue_key}/comment"
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
