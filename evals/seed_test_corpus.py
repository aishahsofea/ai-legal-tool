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

from agent.embeddings import corpus_embedding_model, embedding_client
from evals.coverage import case_section_pairs, missing_section_pairs, present_section_pairs

load_dotenv()

ROOT = Path(__file__).resolve().parent
DATASET_PATH = ROOT / "dataset.json"
CHUNKS_DIR = Path("data/chunks/en")
EMBED_MODEL = corpus_embedding_model()
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


def _wanted_pairs(cases: list[dict]) -> set[tuple[str, str]]:
    return {
        pair
        for case in cases
        if case.get("citation_applicable")
        for pair in case_section_pairs(case)
    }


def _load_sections(pairs: set[tuple[str, str]]) -> list[dict]:
    by_act: dict[str, dict[str, dict]] = {}
    for act_number, section_number in pairs:
        path = CHUNKS_DIR / f"{act_number}.json"
        rows = json.loads(path.read_text(encoding="utf-8"))
        by_act[act_number] = {row["section_number"]: row for row in rows}

    rows: list[dict] = []
    for act_number, section_number in sorted(pairs):
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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--clear", action="store_true", help="Truncate chunks before reseeding everything.")
    mode.add_argument(
        "--missing-only",
        action="store_true",
        help="Add only sections the corpus doesn't have yet. Never truncates.",
    )
    args = parser.parse_args()

    cases = _load_dataset(args.dataset)
    wanted = _wanted_pairs(cases)
    database_url = os.environ["DATABASE_URL"]

    if args.missing_only:
        missing = missing_section_pairs(wanted, present_section_pairs(database_url))
        if not missing:
            print("Eval corpus already has every required section.")
            return 0
        pairs = {(entry["act_number"], entry["section_number"]) for entry in missing}
    else:
        pairs = wanted

    rows = _load_sections(pairs)

    client = embedding_client()
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

        verb = "Added" if args.missing_only else "Seeded"
        print(f"{verb} {len(rows)} chunks into the eval corpus.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
