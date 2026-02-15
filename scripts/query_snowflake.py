#!/usr/bin/env python3
"""
Execute SQL against Snowflake and output results as JSON.

Usage:
  python scripts/query_snowflake.py --sql "SELECT 1 AS n"
  echo "SELECT 1 AS n" | python scripts/query_snowflake.py

Requires env vars (or .env): SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD,
SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE, SNOWFLAKE_SCHEMA.
"""

import argparse
import json
import os
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Execute SQL against Snowflake and output results as JSON."
    )
    parser.add_argument(
        "--sql",
        type=str,
        help="SQL to execute. If not provided, reads from stdin.",
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
