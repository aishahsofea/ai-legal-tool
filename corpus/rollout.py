"""Idempotent end-to-end rollout for verified corpus receipts.

The low-level lifecycle commands remain available for incident response and
reviewed one-off changes. This module composes them into the normal operator
path: prepare missing immutable assets, migrate/register metadata, ingest only
missing extraction rows, and activate only successfully verified runs.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
import logging
import math
from pathlib import Path
from typing import Any, Protocol

import psycopg2

from corpus.db import (
    activate,
    apply_migration,
    ingest_extraction,
    load_bundle,
    register_document,
    register_extraction,
    register_source_observation,
    validate_bundle,
)
from corpus.extraction import extract_document
from corpus.models import CorpusDocument, ExtractionRun
from corpus.registry import CorpusRegistry

logger = logging.getLogger(__name__)

EMBEDDING_PRICES_PER_MILLION_USD = {
    "text-embedding-3-small": Decimal("0.02"),
    "text-embedding-3-large": Decimal("0.13"),
    "text-embedding-ada-002": Decimal("0.10"),
}
MAX_EMBEDDING_INPUT_TOKENS = 8191
MAX_EMBEDDING_BATCH_TOKENS = 250_000


@dataclass(frozen=True)
class RolloutCandidate:
    document: CorpusDocument
    run: ExtractionRun
    bundle_path: Path


class EmbeddingBudgetExceeded(RuntimeError):
    """Raised before an embedding request would exceed the configured budget."""


@dataclass
class EmbeddingBudget:
    price_per_million_usd: Decimal
    max_cost_usd: Decimal | None = None
    submitted_tokens: int = 0

    @classmethod
    def for_model(
        cls, model: str, max_cost_usd: float | Decimal | None
    ) -> EmbeddingBudget:
        price = EMBEDDING_PRICES_PER_MILLION_USD.get(model)
        if price is None:
            raise ValueError(
                f"embedding price is unknown for {model!r}; cannot enforce a dollar budget"
            )
        maximum = Decimal(str(max_cost_usd)) if max_cost_usd is not None else None
        if maximum is not None and maximum <= 0:
            raise ValueError("max_embedding_cost_usd must be greater than zero")
        return cls(price_per_million_usd=price, max_cost_usd=maximum)

    @property
    def token_limit(self) -> int | None:
        if self.max_cost_usd is None:
            return None
        return int(
            (
                self.max_cost_usd
                * Decimal(1_000_000)
                / self.price_per_million_usd
            ).to_integral_value(rounding=ROUND_FLOOR)
        )

    @property
    def estimated_cost_usd(self) -> Decimal:
        return (
            Decimal(self.submitted_tokens)
            * self.price_per_million_usd
            / Decimal(1_000_000)
        )

    def ensure_affordable(self, token_count: int) -> None:
        limit = self.token_limit
        if limit is not None and self.submitted_tokens + token_count > limit:
            raise EmbeddingBudgetExceeded(
                "embedding budget exhausted before the next document "
                f"(submitted ${self.estimated_cost_usd:.6f} of "
                f"${self.max_cost_usd:.2f})"
            )

    def record_submission(self, token_count: int) -> None:
        self.ensure_affordable(token_count)
        self.submitted_tokens += token_count


class RolloutBackend(Protocol):
    def schema_available(self) -> bool: ...

    def migrate(self) -> None: ...

    def register(self, registry: CorpusRegistry, candidate: RolloutCandidate) -> None: ...

    def ingested_extraction_ids(self, identities: Iterable[str]) -> set[str]: ...

    def active_mappings(self) -> dict[tuple[str, str], tuple[str, str]]: ...

    def ingest(
        self, candidate: RolloutCandidate, embeddings: Sequence[Sequence[float]]
    ) -> None: ...

    def activate(self, candidate: RolloutCandidate) -> None: ...


class PostgresRolloutBackend:
    def __init__(self, database_url: str):
        self.connection = psycopg2.connect(database_url)

    def close(self) -> None:
        self.connection.close()

    def schema_available(self) -> bool:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT (
                  to_regclass('public.corpus_documents') IS NOT NULL
                  AND to_regclass('public.extraction_runs') IS NOT NULL
                  AND to_regclass('public.active_corpus_documents') IS NOT NULL
                  AND EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'chunks'
                      AND column_name = 'document_id'
                  )
                )
                """
            )
            row = cursor.fetchone()
        return bool(row and row[0])

    def migrate(self) -> None:
        apply_migration(self.connection)

    def register(self, registry: CorpusRegistry, candidate: RolloutCandidate) -> None:
        with self.connection:
            with self.connection.cursor() as cursor:
                register_document(cursor, candidate.document)
                for observation in registry.source_observations:
                    if observation["document_id"] == candidate.document.document_id:
                        register_source_observation(cursor, observation)
                register_extraction(cursor, candidate.run)

    def ingested_extraction_ids(self, identities: Iterable[str]) -> set[str]:
        values = sorted(set(identities))
        if not values:
            return set()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT e.extraction_id
                FROM extraction_runs e
                LEFT JOIN chunks c ON c.extraction_id = e.extraction_id
                WHERE e.extraction_id = ANY(%s)
                GROUP BY e.extraction_id, e.status, e.chunk_count
                HAVING e.status = 'ready' AND COUNT(c.extraction_id) = e.chunk_count
                """,
                (values,),
            )
            return {row[0] for row in cursor.fetchall()}

    def active_mappings(self) -> dict[tuple[str, str], tuple[str, str]]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT act_number, language, document_id, extraction_id
                FROM active_corpus_documents
                """
            )
            return {
                (row[0], row[1]): (row[2], row[3])
                for row in cursor.fetchall()
            }

    def ingest(
        self, candidate: RolloutCandidate, embeddings: Sequence[Sequence[float]]
    ) -> None:
        bundle = load_bundle(candidate.bundle_path)
        ingest_extraction(
            self.connection, candidate.document, candidate.run, bundle, embeddings
        )

    def activate(self, candidate: RolloutCandidate) -> None:
        activate(self.connection, candidate.document, candidate.run)


def _failure(stage: str, candidate: RolloutCandidate, exc: Exception) -> dict[str, str]:
    return {
        "stage": stage,
        "document_id": candidate.document.document_id,
        "extraction_id": candidate.run.extraction_id,
        "reason": str(exc),
    }


def _select_candidates(
    registry: CorpusRegistry,
    extraction_root: Path,
    document_ids: Iterable[str] | None,
) -> tuple[list[RolloutCandidate], list[dict[str, str]]]:
    requested = {
        registry.get(identity).document_id
        for identity in (document_ids or ())
    }

    grouped: dict[tuple[str, str], list[ExtractionRun]] = defaultdict(list)
    for run in registry.extraction_runs.values():
        if run.status != "ready" or run.coordinate_sidecar is None:
            continue
        document = registry.get(run.document_id)
        if requested and document.document_id not in requested:
            continue
        grouped[(document.act_number, document.language)].append(run)

    candidates: list[RolloutCandidate] = []
    failures: list[dict[str, str]] = []
    for key in sorted(grouped):
        runs = sorted(grouped[key], key=lambda item: item.extraction_id)
        manifest_active = registry.active_documents.get(key)
        if manifest_active:
            selected = next(
                (run for run in runs if run.extraction_id == manifest_active.extraction_id),
                None,
            )
        else:
            selected = runs[0] if len(runs) == 1 else None
        if selected is None:
            document = registry.get(runs[0].document_id)
            failures.append({
                "stage": "select",
                "document_id": document.document_id,
                "extraction_id": "",
                "reason": "multiple ready extraction versions require an explicit manifest active mapping",
            })
            continue
        document = registry.get(selected.document_id)
        candidates.append(RolloutCandidate(
            document=document,
            run=selected,
            bundle_path=Path(extraction_root) / f"{selected.extraction_id}.chunks.json",
        ))

    if requested:
        selected_documents = {candidate.document.document_id for candidate in candidates}
        missing = requested - selected_documents
        for identity in sorted(missing):
            document = registry.get(identity)
            failures.append({
                "stage": "select",
                "document_id": document.document_id,
                "extraction_id": "",
                "reason": "document has no unambiguous ready extraction",
            })
    return candidates, failures


def _inspect_candidate(registry: CorpusRegistry, candidate: RolloutCandidate) -> bool:
    registry.validate(candidate.document)
    try:
        registry.validate_sidecar(candidate.run)
        bundle = load_bundle(candidate.bundle_path)
        validate_bundle(bundle, candidate.document, candidate.run)
    except (OSError, ValueError, RuntimeError):
        return False
    return True


def _prepare_candidate(
    registry: CorpusRegistry,
    candidate: RolloutCandidate,
    *,
    extraction_root: Path,
    sidecar_root: Path,
) -> None:
    generated, bundle_path = extract_document(
        registry,
        candidate.document,
        extraction_root=extraction_root,
        sidecar_root=sidecar_root,
    )
    if generated != candidate.run or bundle_path != candidate.bundle_path:
        raise ValueError("generated extraction does not match the registered immutable run")
    registry.validate_sidecar(candidate.run)
    validate_bundle(load_bundle(candidate.bundle_path), candidate.document, candidate.run)


def _pool_embeddings(
    values: Sequence[Sequence[float]], weights: Sequence[int]
) -> list[float]:
    if len(values) != len(weights) or not values:
        raise ValueError("embedding segments and weights must be non-empty and aligned")
    if len(values) == 1:
        return list(values[0])
    dimensions = len(values[0])
    if any(len(value) != dimensions for value in values):
        raise ValueError("embedding segments have inconsistent dimensions")
    total_weight = sum(weights)
    pooled = [
        sum(value[index] * weight for value, weight in zip(values, weights))
        / total_weight
        for index in range(dimensions)
    ]
    norm = math.sqrt(sum(value * value for value in pooled))
    if norm == 0:
        raise ValueError("pooled embedding has zero magnitude")
    return [value / norm for value in pooled]


class OpenAIEmbedder:
    """Token-aware, budgeted OpenAI embedder for immutable corpus chunks."""

    def __init__(
        self,
        *,
        embedding_model: str,
        batch_size: int,
        max_cost_usd: float | Decimal | None,
        client: Any | None = None,
        encoding: Any | None = None,
    ):
        if batch_size < 1:
            raise ValueError("batch_size must be greater than zero")
        self.embedding_model = embedding_model
        self.batch_size = batch_size
        self.budget = EmbeddingBudget.for_model(embedding_model, max_cost_usd)
        self._client = client
        self._encoding = encoding

    def _ensure_dependencies(self) -> None:
        if self._client is None:
            from openai import OpenAI

            # A retry could resubmit a successfully processed request and make a
            # strict client-side dollar cap impossible to guarantee.
            self._client = OpenAI(max_retries=0)
        if self._encoding is None:
            import tiktoken

            self._encoding = tiktoken.encoding_for_model(self.embedding_model)

    def _batches(
        self, segments: Sequence[tuple[int, list[int]]]
    ) -> Iterable[list[tuple[int, list[int]]]]:
        batch: list[tuple[int, list[int]]] = []
        batch_tokens = 0
        for segment in segments:
            token_count = len(segment[1])
            if batch and (
                len(batch) >= self.batch_size
                or batch_tokens + token_count > MAX_EMBEDDING_BATCH_TOKENS
            ):
                yield batch
                batch = []
                batch_tokens = 0
            batch.append(segment)
            batch_tokens += token_count
        if batch:
            yield batch

    def __call__(self, candidate: RolloutCandidate) -> list[list[float]]:
        self._ensure_dependencies()
        chunks = load_bundle(candidate.bundle_path).get("chunks", [])
        segments: list[tuple[int, list[int]]] = []
        for chunk_index, chunk in enumerate(chunks):
            tokens = self._encoding.encode_ordinary(chunk["content"])
            if not tokens:
                raise ValueError(f"chunk {chunk_index} has no embedding tokens")
            segments.extend(
                (chunk_index, tokens[offset:offset + MAX_EMBEDDING_INPUT_TOKENS])
                for offset in range(0, len(tokens), MAX_EMBEDDING_INPUT_TOKENS)
            )

        candidate_tokens = sum(len(tokens) for _index, tokens in segments)
        # Preflight the whole document so the budget never pays for a partial
        # document that cannot be completed under the cap.
        self.budget.ensure_affordable(candidate_tokens)
        grouped: list[list[tuple[list[float], int]]] = [[] for _chunk in chunks]
        for batch in self._batches(segments):
            batch_tokens = sum(len(tokens) for _index, tokens in batch)
            self.budget.record_submission(batch_tokens)
            response = self._client.embeddings.create(
                model=self.embedding_model,
                input=[tokens for _index, tokens in batch],
            )
            data = sorted(response.data, key=lambda item: item.index)
            if len(data) != len(batch):
                raise ValueError("embedding response count does not match request")
            for (chunk_index, tokens), item in zip(batch, data):
                grouped[chunk_index].append((list(item.embedding), len(tokens)))

        return [
            _pool_embeddings(
                [value for value, _weight in parts],
                [weight for _value, weight in parts],
            )
            for parts in grouped
        ]

    def usage_report(self) -> dict[str, Any]:
        return {
            "embedding_model": self.embedding_model,
            "embedding_tokens_submitted": self.budget.submitted_tokens,
            "estimated_embedding_cost_usd": float(self.budget.estimated_cost_usd),
            "max_embedding_cost_usd": (
                float(self.budget.max_cost_usd)
                if self.budget.max_cost_usd is not None
                else None
            ),
        }


def _default_embedder(
    *,
    embedding_model: str,
    batch_size: int,
    max_cost_usd: float | Decimal | None,
) -> OpenAIEmbedder:
    return OpenAIEmbedder(
        embedding_model=embedding_model,
        batch_size=batch_size,
        max_cost_usd=max_cost_usd,
    )


def rollout_corpus(
    registry: CorpusRegistry,
    *,
    extraction_root: Path,
    sidecar_root: Path,
    database_url: str | None = None,
    embedding_model: str = "text-embedding-3-small",
    batch_size: int = 100,
    max_embedding_cost_usd: float | Decimal | None = None,
    document_ids: Iterable[str] | None = None,
    dry_run: bool = False,
    activate_ready: bool = True,
    backend: RolloutBackend | None = None,
    inspect_candidate: Callable[[RolloutCandidate], bool] | None = None,
    prepare_candidate: Callable[[RolloutCandidate], None] | None = None,
    embed_candidate: Callable[[RolloutCandidate], Sequence[Sequence[float]]] | None = None,
) -> dict[str, Any]:
    """Roll out every unambiguous ready extraction, safely and resumably."""
    extraction_root = Path(extraction_root).resolve()
    sidecar_root = Path(sidecar_root).resolve()
    candidates, failures = _select_candidates(registry, extraction_root, document_ids)
    logger.info("Corpus rollout selected %d verified extraction candidates", len(candidates))
    inspect = inspect_candidate or (lambda candidate: _inspect_candidate(registry, candidate))
    prepare = prepare_candidate or (
        lambda candidate: _prepare_candidate(
            registry,
            candidate,
            extraction_root=extraction_root,
            sidecar_root=sidecar_root,
        )
    )
    embed = embed_candidate or _default_embedder(
        embedding_model=embedding_model,
        batch_size=batch_size,
        max_cost_usd=max_embedding_cost_usd,
    )

    def embedding_usage() -> dict[str, Any]:
        reporter = getattr(embed, "usage_report", None)
        return reporter() if callable(reporter) else {}

    local_ready: list[RolloutCandidate] = []
    needs_preparation: list[RolloutCandidate] = []
    blocked_ids = {failure["document_id"] for failure in failures}
    for candidate in candidates:
        try:
            if inspect(candidate):
                local_ready.append(candidate)
            else:
                needs_preparation.append(candidate)
        except Exception as exc:
            failures.append(_failure("prepare", candidate, exc))
            blocked_ids.add(candidate.document.document_id)

    owned_backend = backend is None
    if backend is None:
        if not database_url:
            raise ValueError("database_url is required")
        backend = PostgresRolloutBackend(database_url)

    try:
        schema_available = backend.schema_available()
        if schema_available:
            ingested = backend.ingested_extraction_ids(
                candidate.run.extraction_id for candidate in candidates
            )
            active = backend.active_mappings()
        else:
            ingested = set()
            active = {}

        already_active = sum(
            active.get((candidate.document.act_number, candidate.document.language))
            == (candidate.document.document_id, candidate.run.extraction_id)
            for candidate in candidates
        )
        if dry_run:
            return {
                "status": "dry_run",
                "candidates": len(candidates),
                "selected_extractions": [candidate.run.extraction_id for candidate in candidates],
                "local_ready": len(local_ready),
                "needs_preparation": len(needs_preparation),
                "database_migration_required": not schema_available,
                "already_ingested": len(ingested),
                "needs_ingestion": len(candidates) - len(ingested),
                "already_active": already_active,
                "needs_activation": len(candidates) - already_active if activate_ready else 0,
                "failures": failures,
                **embedding_usage(),
            }

        prepared = list(local_ready)
        generated = 0
        if needs_preparation:
            logger.info("Preparing %d missing local extraction assets", len(needs_preparation))
        for index, candidate in enumerate(needs_preparation, 1):
            try:
                prepare(candidate)
                if not inspect(candidate):
                    raise ValueError("prepared extraction failed local verification")
                prepared.append(candidate)
                generated += 1
                if index % 25 == 0 or index == len(needs_preparation):
                    logger.info(
                        "Prepared local extraction assets %d/%d",
                        index,
                        len(needs_preparation),
                    )
            except Exception as exc:
                failures.append(_failure("prepare", candidate, exc))
                blocked_ids.add(candidate.document.document_id)

        logger.info("Applying corpus migration and registering %d candidates", len(prepared))
        backend.migrate()
        registered: list[RolloutCandidate] = []
        for index, candidate in enumerate(prepared, 1):
            try:
                backend.register(registry, candidate)
                registered.append(candidate)
            except Exception as exc:
                failures.append(_failure("register", candidate, exc))
                blocked_ids.add(candidate.document.document_id)
            if index % 50 == 0 or index == len(prepared):
                logger.info("Processed registrations %d/%d", index, len(prepared))
        ingested = backend.ingested_extraction_ids(
            candidate.run.extraction_id for candidate in registered
        )
        already_ingested = len(ingested)
        newly_ingested: set[str] = set()
        ingestion_queue = [
            candidate for candidate in registered
            if candidate.run.extraction_id not in ingested
        ]
        if ingestion_queue:
            logger.info("Embedding and ingesting %d missing extractions", len(ingestion_queue))
        for index, candidate in enumerate(ingestion_queue, 1):
            try:
                embeddings = embed(candidate)
                backend.ingest(candidate, embeddings)
                newly_ingested.add(candidate.run.extraction_id)
                if index % 25 == 0 or index == len(ingestion_queue):
                    logger.info("Ingested extractions %d/%d", index, len(ingestion_queue))
            except EmbeddingBudgetExceeded as exc:
                failures.append(_failure("budget", candidate, exc))
                blocked_ids.add(candidate.document.document_id)
                break
            except Exception as exc:
                failures.append(_failure("ingest", candidate, exc))
                blocked_ids.add(candidate.document.document_id)

        available = ingested | newly_ingested
        activated = 0
        active = backend.active_mappings()
        already_active = 0
        if activate_ready:
            activation_queue = [
                candidate for candidate in registered
                if candidate.run.extraction_id in available
            ]
            if activation_queue:
                logger.info("Activating %d verified corpus mappings", len(activation_queue))
            for index, candidate in enumerate(activation_queue, 1):
                key = (candidate.document.act_number, candidate.document.language)
                target = (candidate.document.document_id, candidate.run.extraction_id)
                if active.get(key) == target:
                    already_active += 1
                    continue
                try:
                    backend.activate(candidate)
                    active[key] = target
                    activated += 1
                except Exception as exc:
                    failures.append(_failure("activate", candidate, exc))
                    blocked_ids.add(candidate.document.document_id)
                if index % 50 == 0 or index == len(activation_queue):
                    logger.info("Processed activations %d/%d", index, len(activation_queue))

        return {
            "status": "partial" if failures else "complete",
            "candidates": len(candidates),
            "selected_extractions": [candidate.run.extraction_id for candidate in candidates],
            "local_ready": len(local_ready),
            "needs_preparation": len(needs_preparation),
            "generated": generated,
            "registered": len(registered),
            "already_ingested": already_ingested,
            "ingested": len(newly_ingested),
            "already_active": already_active,
            "activated": activated,
            "blocked": len(blocked_ids),
            "failures": failures,
            **embedding_usage(),
        }
    finally:
        if owned_backend:
            assert isinstance(backend, PostgresRolloutBackend)
            backend.close()
