"""Seed a tiny eval-only pgvector corpus from the validation dataset."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

ROOT = Path(__file__).resolve().parent
DATASET_PATH = ROOT / "dataset.json"
CHUNKS_DIR = Path("data/chunks/en")
EMBED_MODEL = "text-embedding-3-small"
BATCH_SIZE = 64


def _connect():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def _ensure_schema(cur) -> None:
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
          id BIGSERIAL PRIMARY KEY,
          act_number TEXT NOT NULL,
          act_title TEXT,
          section_number TEXT,
          content TEXT,
          page_number INT,
          language TEXT DEFAULT 'en',
          embedding vector(1536)
        );
        """
    )


def _load_dataset(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def _load_sections(cases: list[dict]) -> list[dict]:
    wanted = {
        (case["expected_act_number"], case["expected_section"])
        for case in cases
        if case.get("citation_applicable")
        and case.get("expected_act_number")
        and case.get("expected_section")
    }

    by_act: dict[str, dict[str, dict]] = {}
    for act_number, section_number in wanted:
        path = CHUNKS_DIR / f"{act_number}.json"
        rows = json.loads(path.read_text(encoding="utf-8"))
        by_act[act_number] = {row["section_number"]: row for row in rows}

    rows: list[dict] = []
    for act_number, section_number in sorted(wanted):
        row = by_act[act_number].get(section_number)
        if not row:
            raise RuntimeError(f"Missing chunk for Act {act_number} section {section_number}")
        rows.append(row)
    return rows


def _embed_batch(client: OpenAI, texts: list[str]) -> list[list[float]]:
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [item.embedding for item in resp.data]


def _insert_rows(cur, rows: list[dict], embeddings: list[list[float]]) -> None:
    records = [
        (
            row["act_number"],
            row.get("act_title"),
            row["section_number"],
            row["content"],
            row.get("page_number"),
            row.get("language", "en"),
            embedding,
        )
        for row, embedding in zip(rows, embeddings)
    ]
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO chunks
          (act_number, act_title, section_number, content, page_number, language, embedding)
        VALUES %s
        """,
        records,
        template="(%s, %s, %s, %s, %s, %s, %s::vector)",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the eval corpus with only the validation sections.")
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--clear", action="store_true")
    args = parser.parse_args()

    cases = _load_dataset(args.dataset)
    rows = _load_sections(cases)

    client = OpenAI()
    conn = _connect()
    try:
        with conn:
            with conn.cursor() as cur:
                _ensure_schema(cur)
                if args.clear:
                    cur.execute("TRUNCATE TABLE chunks RESTART IDENTITY;")

        for start in range(0, len(rows), BATCH_SIZE):
            batch = rows[start : start + BATCH_SIZE]
            embeddings = _embed_batch(client, [row["content"] for row in batch])
            with conn:
                with conn.cursor() as cur:
                    _insert_rows(cur, batch, embeddings)

        print(f"Seeded {len(rows)} chunks into the eval corpus.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
