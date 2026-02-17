#!/usr/bin/env python3
"""
Merge multiple SQL files into a single file for JIRA attachment.

Reads all .sql files from a directory, sorts by modification time (execution order),
and writes a single merged file with clear separators between queries.

Usage:
  python scripts/merge_sql_queries.py --input-dir ./analysis_queries --output-file ./jira_attachments/initial_analysis_queries.sql
  python scripts/merge_sql_queries.py --input-dir ./analysis_queries --output-file ./jira_attachments/reply_analysis_queries.sql
"""

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge SQL files into one for JIRA attachment."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help="Directory containing .sql files.",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        required=True,
        help="Path for merged output file.",
    )
    args = parser.parse_args()

    input_dir = args.input_dir.resolve()
    output_path = args.output_file.resolve()

    if not input_dir.exists() or not input_dir.is_dir():
        print(f"Input dir not found: {input_dir}", flush=True)
        return

    sql_files = sorted(
        [f for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() == ".sql"],
        key=lambda f: f.stat().st_mtime,
    )

    if not sql_files:
        print("No .sql files to merge", flush=True)
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)

    parts: list[str] = []
    for i, f in enumerate(sql_files, 1):
        content = f.read_text(encoding="utf-8", errors="replace").strip()
        header = f"-- ===== Query {i}: {f.name} =====\n\n"
        parts.append(header + content)

    merged = "\n\n\n".join(parts)
    output_path.write_text(merged, encoding="utf-8")
    print(f"Merged {len(sql_files)} queries into {output_path}", flush=True)


if __name__ == "__main__":
    main()
