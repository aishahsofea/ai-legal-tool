"""Create and seed the dedicated eval database in one explicit command."""
from __future__ import annotations

import os
import subprocess
import sys
from urllib.parse import unquote, urlsplit, urlunsplit

import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql

load_dotenv()


def main() -> int:
    eval_url = os.getenv("EVALS_DATABASE_URL")
    if not eval_url:
        raise SystemExit("EVALS_DATABASE_URL must point to the dedicated eval database")

    parsed = urlsplit(eval_url)
    database_name = unquote(parsed.path.lstrip("/"))
    if not database_name:
        raise SystemExit("EVALS_DATABASE_URL must include a database name")
    if database_name == "postgres":
        raise SystemExit("Refusing to use the postgres maintenance database as the eval corpus")

    maintenance_url = urlunsplit(parsed._replace(path="/postgres"))
    conn = psycopg2.connect(maintenance_url)
    try:
        conn.autocommit = True
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database_name,))
            if cursor.fetchone() is None:
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
                print(f"Created eval database {database_name}.")
            else:
                print(f"Eval database {database_name} already exists.")
    finally:
        conn.close()

    child_env = os.environ.copy()
    child_env["DATABASE_URL"] = eval_url
    child_env["CHECKPOINTER"] = "memory"
    completed = subprocess.run(
        [sys.executable, "-m", "evals.seed_test_corpus", "--clear"],
        env=child_env,
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
