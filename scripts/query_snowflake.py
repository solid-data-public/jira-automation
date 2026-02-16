#!/usr/bin/env python3
"""
Execute SQL against Snowflake and output results as JSON.

Usage:
  python scripts/query_snowflake.py --sql "SELECT 1 AS n"
  echo "SELECT 1 AS n" | python scripts/query_snowflake.py

When SAVE_QUERIES_DIR env is set, each query is saved to a .sql file in that directory
(query_001.sql, query_002.sql, ...). Optional --name uses that for the filename
(sanitized). Optional --description (e.g. from Solid MCP generation_notes) is written
as SQL comments (-- line) at the top of each saved file.

Requires env vars (or .env): SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD,
SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE, SNOWFLAKE_SCHEMA.
"""

import argparse
import json
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

REQUIRED_ENV = [
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_PASSWORD",
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_DATABASE",
]


def _save_query(
    sql: str, queries_dir: Path, name: str | None, description: str | None = None
) -> Path | None:
    """Save SQL to a file in queries_dir. Returns path if saved, else None."""
    queries_dir.mkdir(parents=True, exist_ok=True)
    if name:
        safe = re.sub(r"[^\w\-]", "_", name)[:60].strip("_") or "query"
        base = f"{safe}.sql"
        path = queries_dir / base
        if path.exists():
            n = 1
            while (queries_dir / f"{safe}_{n}.sql").exists():
                n += 1
            path = queries_dir / f"{safe}_{n}.sql"
    else:
        existing = list(queries_dir.glob("query_*.sql"))
        nums = []
        for f in existing:
            m = re.match(r"query_(\d+)\.sql", f.name)
            if m:
                nums.append(int(m.group(1)))
        next_n = max(nums, default=0) + 1
        path = queries_dir / f"query_{next_n:03d}.sql"
    content = sql
    if description and description.strip():
        lines = description.strip().splitlines()
        header = "\n".join(f"-- {line}" for line in lines) + "\n\n"
        content = header + sql
    path.write_text(content, encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Execute SQL against Snowflake and output results as JSON."
    )
    parser.add_argument(
        "--sql",
        type=str,
        help="SQL to execute. If not provided, reads from stdin.",
    )
    parser.add_argument(
        "--name",
        type=str,
        help="Optional descriptive name for saved query file (when SAVE_QUERIES_DIR is set).",
    )
    parser.add_argument(
        "--description",
        type=str,
        help="Optional description of what the query does (from Solid MCP generation_notes). Saved as SQL comments at top of file.",
    )
    args = parser.parse_args()

    sql = args.sql
    if not sql:
        if sys.stdin.isatty():
            parser.error("Provide --sql or pipe SQL via stdin")
        sql = sys.stdin.read().strip()

    if not sql:
        print("Error: no SQL provided", file=sys.stderr)
        sys.exit(1)

    queries_dir = os.getenv("SAVE_QUERIES_DIR")
    if queries_dir:
        saved = _save_query(
            sql, Path(queries_dir), args.name, description=args.description
        )
        if saved:
            print(f"Saved query to {saved}", file=sys.stderr)

    missing = [k for k in REQUIRED_ENV if not os.getenv(k)]
    if missing:
        print(f"Error: missing required env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    try:
        import snowflake.connector
    except ImportError:
        print(
            "Error: snowflake-connector-python not installed. Run: pip install snowflake-connector-python",
            file=sys.stderr,
        )
        sys.exit(1)

    conn_params = {
        "account": os.environ["SNOWFLAKE_ACCOUNT"],
        "user": os.environ["SNOWFLAKE_USER"],
        "password": os.environ["SNOWFLAKE_PASSWORD"],
        "warehouse": os.environ["SNOWFLAKE_WAREHOUSE"],
        "database": os.environ["SNOWFLAKE_DATABASE"],
    }
    if os.getenv("SNOWFLAKE_SCHEMA"):
        conn_params["schema"] = os.environ["SNOWFLAKE_SCHEMA"]

    try:
        conn = snowflake.connector.connect(**conn_params)
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        columns = [d[0] for d in cur.description]
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error executing SQL: {e}", file=sys.stderr)
        sys.exit(1)

    result = [dict(zip(columns, row)) for row in rows]
    json.dump(result, sys.stdout, default=str)


if __name__ == "__main__":
    main()
