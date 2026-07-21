import json
from pathlib import Path
from unittest.mock import Mock

from corpus.models import ActiveDocument, CoordinateSidecar, CorpusDocument, ExtractionRun
from corpus.rollout import (
    EmbeddingBudgetExceeded,
    MAX_EMBEDDING_INPUT_TOKENS,
    OpenAIEmbedder,
    RolloutCandidate,
    rollout_corpus,
)
from corpus.cli import build_parser


def _candidate(act_number: str) -> tuple[CorpusDocument, ExtractionRun]:
    digest = act_number.zfill(64)
    document = CorpusDocument(
        document_id=f"act-{act_number}-en-sha256-{digest}",
        act_number=act_number,
        act_title=f"ACT {act_number}",
        language="en",
        asset_key=f"statutes/sha256/{digest[:2]}/{digest[2:4]}/{digest}.pdf",
        sha256=digest,
        byte_size=100,
        page_count=1,
        source_url=f"https://example.test/{act_number}.pdf",
        timeline_date="",
        timeline_type="REPRINT",
        metadata_scraped_at="2026-01-01T00:00:00Z",
    )
    run = ExtractionRun(
        extraction_id=f"extraction-sha256-{digest}",
        document_id=document.document_id,
        extractor="fixture",
        extractor_version="1",
        configuration_hash="a" * 64,
        chunk_set_hash="b" * 64,
        chunk_count=1,
        status="ready",
        coordinate_sidecar=CoordinateSidecar(
            asset_key=f"statutes/extractions/extraction-sha256-{digest}/{'c' * 64}.words.json.gz",
            sha256="c" * 64,
            byte_size=10,
            local_path=f"extraction-sha256-{digest}.words.json.gz",
        ),
    )
    return document, run


def _registry(*pairs: tuple[CorpusDocument, ExtractionRun]):
    registry = Mock()
    registry.documents = {document.document_id: document for document, _run in pairs}
    registry.extraction_runs = {run.extraction_id: run for _document, run in pairs}
    registry.active_documents = {}
    registry.source_observations = []
    registry.get.side_effect = registry.documents.__getitem__
    return registry


class _Backend:
    def __init__(
        self,
        *,
        schema: bool = True,
        ingested: set[str] | None = None,
        active: dict[tuple[str, str], tuple[str, str]] | None = None,
        register_failures: set[str] | None = None,
    ):
        self.schema = schema
        self.ingested = set(ingested or ())
        self.active = dict(active or {})
        self.register_failures = set(register_failures or ())
        self.migrations = 0
        self.registered: list[str] = []
        self.ingest_calls: list[str] = []
        self.activate_calls: list[str] = []

    def schema_available(self) -> bool:
        return self.schema

    def migrate(self) -> None:
        self.schema = True
        self.migrations += 1

    def register(self, registry, candidate) -> None:
        if candidate.run.extraction_id in self.register_failures:
            raise RuntimeError("registration conflict")
        self.registered.append(candidate.run.extraction_id)

    def ingested_extraction_ids(self, identities) -> set[str]:
        return self.ingested.intersection(identities)

    def active_mappings(self):
        return dict(self.active)

    def ingest(self, candidate, embeddings) -> None:
        self.ingest_calls.append(candidate.run.extraction_id)
        self.ingested.add(candidate.run.extraction_id)

    def activate(self, candidate) -> None:
        self.activate_calls.append(candidate.run.extraction_id)
        self.active[(candidate.document.act_number, candidate.document.language)] = (
            candidate.document.document_id,
            candidate.run.extraction_id,
        )


def test_rollout_dry_run_reports_the_whole_plan_without_mutating(tmp_path: Path):
    first = _candidate("1")
    second = _candidate("2")
    registry = _registry(first, second)
    backend = _Backend(schema=False)
    prepared: list[str] = []

    result = rollout_corpus(
        registry,
        extraction_root=tmp_path / "extractions",
        sidecar_root=tmp_path / "sidecars",
        backend=backend,
        dry_run=True,
        inspect_candidate=lambda candidate: candidate.run == first[1],
        prepare_candidate=lambda candidate: prepared.append(candidate.run.extraction_id),
        embed_candidate=lambda _candidate: [[0.1]],
    )

    assert result["status"] == "dry_run"
    assert result["candidates"] == 2
    assert result["local_ready"] == 1
    assert result["needs_preparation"] == 1
    assert result["database_migration_required"] is True
    assert result["needs_ingestion"] == 2
    assert result["needs_activation"] == 2
    assert prepared == []
    assert backend.registered == []
    assert backend.ingest_calls == []
    assert backend.activate_calls == []


def test_rollout_resumes_and_skips_ingested_and_active_work(tmp_path: Path):
    first = _candidate("1")
    second = _candidate("2")
    registry = _registry(first, second)
    backend = _Backend(
        ingested={first[1].extraction_id},
        active={
            (first[0].act_number, first[0].language): (
                first[0].document_id,
                first[1].extraction_id,
            )
        },
    )
    embedded: list[str] = []

    result = rollout_corpus(
        registry,
        extraction_root=tmp_path / "extractions",
        sidecar_root=tmp_path / "sidecars",
        backend=backend,
        inspect_candidate=lambda _candidate: True,
        prepare_candidate=lambda _candidate: None,
        embed_candidate=lambda candidate: embedded.append(candidate.run.extraction_id) or [[0.1]],
    )

    assert result["status"] == "complete"
    assert result["already_ingested"] == 1
    assert result["ingested"] == 1
    assert result["already_active"] == 1
    assert result["activated"] == 1
    assert embedded == [second[1].extraction_id]
    assert backend.ingest_calls == [second[1].extraction_id]
    assert backend.activate_calls == [second[1].extraction_id]


def test_rollout_does_not_activate_a_failed_ingestion_and_continues(tmp_path: Path):
    first = _candidate("1")
    second = _candidate("2")
    registry = _registry(first, second)
    backend = _Backend()

    def embed(candidate):
        if candidate.run == first[1]:
            raise RuntimeError("embedding unavailable")
        return [[0.1]]

    result = rollout_corpus(
        registry,
        extraction_root=tmp_path / "extractions",
        sidecar_root=tmp_path / "sidecars",
        backend=backend,
        inspect_candidate=lambda _candidate: True,
        prepare_candidate=lambda _candidate: None,
        embed_candidate=embed,
    )

    assert result["status"] == "partial"
    assert result["ingested"] == 1
    assert result["activated"] == 1
    assert backend.activate_calls == [second[1].extraction_id]
    assert result["failures"] == [{
        "stage": "ingest",
        "document_id": first[0].document_id,
        "extraction_id": first[1].extraction_id,
        "reason": "embedding unavailable",
    }]


def test_rollout_isolates_a_registration_conflict(tmp_path: Path):
    first = _candidate("1")
    second = _candidate("2")
    registry = _registry(first, second)
    backend = _Backend(register_failures={first[1].extraction_id})

    result = rollout_corpus(
        registry,
        extraction_root=tmp_path / "extractions",
        sidecar_root=tmp_path / "sidecars",
        backend=backend,
        inspect_candidate=lambda _candidate: True,
        prepare_candidate=lambda _candidate: None,
        embed_candidate=lambda _candidate: [[0.1]],
    )

    assert result["status"] == "partial"
    assert result["registered"] == 1
    assert backend.ingest_calls == [second[1].extraction_id]
    assert backend.activate_calls == [second[1].extraction_id]
    assert result["failures"][0]["stage"] == "register"


def test_rollout_prefers_manifest_active_run_when_versions_are_ambiguous(tmp_path: Path):
    old_document, old_run = _candidate("1")
    new_document = CorpusDocument(
        **{
            **old_document.__dict__,
            "document_id": "act-1-en-sha256-" + "9" * 64,
            "sha256": "9" * 64,
            "asset_key": "statutes/sha256/99/99/" + "9" * 64 + ".pdf",
        }
    )
    new_run = ExtractionRun(
        **{
            **old_run.__dict__,
            "document_id": new_document.document_id,
            "extraction_id": "extraction-sha256-" + "9" * 64,
        }
    )
    registry = _registry((old_document, old_run), (new_document, new_run))
    registry.active_documents = {
        ("1", "en"): ActiveDocument("1", "en", new_document.document_id, new_run.extraction_id)
    }
    backend = _Backend(schema=False)

    result = rollout_corpus(
        registry,
        extraction_root=tmp_path / "extractions",
        sidecar_root=tmp_path / "sidecars",
        backend=backend,
        dry_run=True,
        inspect_candidate=lambda _candidate: True,
        prepare_candidate=lambda _candidate: None,
        embed_candidate=lambda _candidate: [[0.1]],
    )

    assert result["candidates"] == 1
    assert result["selected_extractions"] == [new_run.extraction_id]


def test_rollout_cli_is_one_resumable_command_with_a_dry_run():
    parser = build_parser()

    dry_run = parser.parse_args(["rollout", "--dry-run"])
    live = parser.parse_args(["rollout"])

    assert dry_run.command == "rollout" and dry_run.dry_run is True
    assert live.command == "rollout" and live.dry_run is False
    assert live.activate_ready is True
    assert live.max_embedding_cost_usd == 1.0


def test_openai_embedder_splits_and_pools_oversized_chunks(tmp_path: Path):
    document, run = _candidate("1")
    bundle_path = tmp_path / f"{run.extraction_id}.chunks.json"
    content = "x" * (MAX_EMBEDDING_INPUT_TOKENS + 5)
    bundle_path.write_text(
        json.dumps({"chunks": [{"content": content}]}),
        encoding="utf-8",
    )
    calls: list[list[list[int]]] = []

    class Encoding:
        def encode_ordinary(self, text):
            return list(range(len(text)))

    class Embeddings:
        def create(self, *, model, input):
            calls.append(input)
            return Mock(data=[
                Mock(index=index, embedding=[1.0, float(index)])
                for index, _tokens in enumerate(input)
            ])

    embedder = OpenAIEmbedder(
        embedding_model="text-embedding-3-small",
        batch_size=100,
        max_cost_usd=1,
        client=Mock(embeddings=Embeddings()),
        encoding=Encoding(),
    )
    embeddings = embedder(RolloutCandidate(
        document=document, run=run, bundle_path=bundle_path
    ))

    assert [len(tokens) for tokens in calls[0]] == [MAX_EMBEDDING_INPUT_TOKENS, 5]
    assert len(embeddings) == 1
    assert len(embeddings[0]) == 2
    assert embedder.budget.submitted_tokens == len(content)


def test_rollout_stops_embedding_after_budget_is_exhausted(tmp_path: Path):
    first = _candidate("1")
    second = _candidate("2")
    registry = _registry(first, second)
    backend = _Backend()
    calls: list[str] = []

    def embed(candidate):
        calls.append(candidate.run.extraction_id)
        raise EmbeddingBudgetExceeded("cap reached")

    result = rollout_corpus(
        registry,
        extraction_root=tmp_path / "extractions",
        sidecar_root=tmp_path / "sidecars",
        backend=backend,
        inspect_candidate=lambda _candidate: True,
        prepare_candidate=lambda _candidate: None,
        embed_candidate=embed,
    )

    assert calls == [first[1].extraction_id]
    assert result["status"] == "partial"
    assert result["failures"][0]["stage"] == "budget"
    assert backend.ingest_calls == []
