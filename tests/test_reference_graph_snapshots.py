import json
from hashlib import sha256
from pathlib import Path

import fitz
import pytest

from reference_graph.snapshots import (
    SnapshotCatalogError,
    acquire_snapshots,
    catalog_snapshots,
)

ROOT = Path(__file__).resolve().parents[1]


def _pdf_bytes(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    payload = document.tobytes()
    document.close()
    return payload


class _Response:
    def __init__(self, payload: bytes, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code

    def iter_content(self, _size):
        yield self.payload

    def close(self):
        pass


class _Session:
    def __init__(self, payload: bytes, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response(self.payload, self.status_code)


def _fixture(tmp_path: Path):
    metadata_path = tmp_path / "265.json"
    metadata_path.write_text(json.dumps({
        "act_number": "265",
        "scraped_at": "2026-07-23T00:00:00+00:00",
        "detail_url": "https://example.test/act=265&lang=BI",
        "timeline": [
            {
                "date": "02/09/2023", "project_id": "new", "log_type": "REPRINT",
                "pdf_url": "https://example.test/september.pdf",
            },
            {
                "date": "01/02/2023", "project_id": "old", "log_type": "REPRINT ONLINE",
                "pdf_url": "https://example.test/february.pdf",
            },
            {
                "date": "03/09/2023", "project_id": "amend", "log_type": "AMENDMENTS",
                "pdf_url": "https://example.test/amendment.pdf",
            },
        ],
    }), encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 2,
        "identity_algorithm": "sha256",
        "documents": [],
        "extraction_runs": [],
        "active_documents": [],
        "aliases": {},
        "source_observations": [],
    }), encoding="utf-8")
    return metadata_path, manifest_path


def test_snapshot_catalog_is_strict_chronological_and_preserves_february_alias():
    entries = catalog_snapshots(
        ROOT / "data" / "acts_metadata" / "265.json",
        ROOT / "data" / "pdfs" / "manifest.json",
        asset_root=ROOT / "data" / "pdfs",
    )
    assert [entry.snapshot_date for entry in entries] == [
        "1975-01-10", "2001-08-20", "2006-01-24",
        "2012-05-26", "2023-02-01", "2023-09-02",
    ]
    february = next(entry for entry in entries if entry.snapshot_date == "2023-02-01")
    assert february.graph_document_id == "act-265-reprint-2023-6fec2f07"
    assert february.registered_document_id.endswith(
        "6fec2f07b49d8f381851906781259b1e09a2152db8dcf1599ab77a592eae100b"
    )


def test_snapshot_catalog_rejects_non_strict_dates(tmp_path: Path):
    metadata_path, manifest_path = _fixture(tmp_path)
    metadata = json.loads(metadata_path.read_text())
    metadata["timeline"][0]["date"] = "2/9/2023"
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(SnapshotCatalogError, match="invalid_snapshot_date"):
        catalog_snapshots(metadata_path, manifest_path, asset_root=tmp_path)


def test_snapshot_acquisition_is_immutable_idempotent_and_never_changes_active_mapping(tmp_path: Path):
    metadata_path, manifest_path = _fixture(tmp_path)
    payload = _pdf_bytes("Employment Act 1955 " + ("explicit legal text " * 20))
    session = _Session(payload)
    entries = catalog_snapshots(metadata_path, manifest_path, asset_root=tmp_path)

    first = acquire_snapshots(
        entries,
        metadata_path=metadata_path,
        manifest_path=manifest_path,
        asset_root=tmp_path,
        staging_root=tmp_path / "staging",
        act_title="EMPLOYMENT ACT 1955",
        selected_dates={"2023-09-02"},
        session=session,
    )
    assert first["active_documents_unchanged"]
    assert first["snapshots"][0]["acquisition_status"] == "downloaded"
    assert first["snapshots"][0]["readiness_status"] == "ready"
    document_id = first["snapshots"][0]["document_id"]
    assert first["snapshots"][0]["registered_document_id"] == document_id
    assert first["snapshots"][0]["graph_document_id"] == document_id
    manifest = json.loads(manifest_path.read_text())
    assert manifest["active_documents"] == []
    assert len(manifest["documents"]) == 1
    assert manifest["source_observations"] == [{
        "document_id": document_id,
        "source_url": "https://example.test/september.pdf",
        "observed_at": "2026-07-23T00:00:00+00:00",
        "timeline_date": "02/09/2023",
        "timeline_type": "REPRINT",
    }]
    assert (tmp_path / manifest["documents"][0]["local_path"]).is_file()

    refreshed = catalog_snapshots(metadata_path, manifest_path, asset_root=tmp_path)
    second = acquire_snapshots(
        refreshed,
        metadata_path=metadata_path,
        manifest_path=manifest_path,
        asset_root=tmp_path,
        staging_root=tmp_path / "staging",
        act_title="EMPLOYMENT ACT 1955",
        selected_dates={"2023-09-02"},
        session=session,
    )
    assert second["snapshots"][0]["acquisition_status"] == "already_registered"
    assert second["snapshots"][0]["document_id"] == document_id
    assert second["snapshots"][0]["registered_document_id"] == document_id
    assert second["snapshots"][0]["graph_document_id"] == document_id
    assert len(session.calls) == 1
    assert len(json.loads(manifest_path.read_text())["source_observations"]) == 1


def test_snapshot_acquisition_resumes_an_exact_partial_download_with_http_range(tmp_path: Path):
    metadata_path, manifest_path = _fixture(tmp_path)
    payload = _pdf_bytes("Employment Act 1955 " + ("resumable legal text " * 30))
    split = len(payload) // 2
    staging_root = tmp_path / "staging"
    staged = staging_root / "act-265-2023-09-02-new.pdf.part"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(payload[:split])
    session = _Session(payload[split:], status_code=206)
    entries = catalog_snapshots(metadata_path, manifest_path, asset_root=tmp_path)

    report = acquire_snapshots(
        entries,
        metadata_path=metadata_path,
        manifest_path=manifest_path,
        asset_root=tmp_path,
        staging_root=staging_root,
        act_title="EMPLOYMENT ACT 1955",
        selected_dates={"2023-09-02"},
        session=session,
    )

    assert session.calls[0][1]["headers"] == {"Range": f"bytes={split}-"}
    row = report["snapshots"][0]
    assert row["acquisition_status"] == "downloaded"
    assert row["readiness_status"] == "ready"
    assert row["sha256"] == sha256(payload).hexdigest()
    assert staged.read_bytes() == payload


@pytest.mark.parametrize(
    ("session", "acquisition_status", "reason"),
    [
        (_Session(b"", status_code=503), "unavailable", "http_503"),
        (_Session(b"<html>not a PDF</html>"), "integrity_failure", "response_is_not_pdf"),
    ],
)
def test_snapshot_acquisition_reports_blocked_sources_without_registering_guessed_data(
    tmp_path: Path,
    session: _Session,
    acquisition_status: str,
    reason: str,
):
    metadata_path, manifest_path = _fixture(tmp_path)
    entries = catalog_snapshots(metadata_path, manifest_path, asset_root=tmp_path)
    report = acquire_snapshots(
        entries,
        metadata_path=metadata_path,
        manifest_path=manifest_path,
        asset_root=tmp_path,
        staging_root=tmp_path / "staging",
        act_title="EMPLOYMENT ACT 1955",
        selected_dates={"2023-09-02"},
        session=session,
    )
    row = report["snapshots"][0]
    assert row["acquisition_status"] == acquisition_status
    assert row["readiness_status"] == "blocked"
    assert row["reason"] == reason
    assert json.loads(manifest_path.read_text())["documents"] == []
    assert report["active_documents_unchanged"]


def test_snapshot_acquisition_reports_a_low_text_pdf_as_scanned_unparseable(tmp_path: Path):
    metadata_path, manifest_path = _fixture(tmp_path)
    entries = catalog_snapshots(metadata_path, manifest_path, asset_root=tmp_path)
    report = acquire_snapshots(
        entries,
        metadata_path=metadata_path,
        manifest_path=manifest_path,
        asset_root=tmp_path,
        staging_root=tmp_path / "staging",
        act_title="EMPLOYMENT ACT 1955",
        selected_dates={"2023-09-02"},
        session=_Session(_pdf_bytes("scan")),
    )
    row = report["snapshots"][0]
    assert row["acquisition_status"] == "downloaded"
    assert row["readiness_status"] == "scanned_unparseable"
    assert row["reason"] == "text_layer_below_threshold"
    assert row["document_id"]
    refreshed = catalog_snapshots(metadata_path, manifest_path, asset_root=tmp_path)
    repeated = acquire_snapshots(
        refreshed,
        metadata_path=metadata_path,
        manifest_path=manifest_path,
        asset_root=tmp_path,
        staging_root=tmp_path / "staging",
        act_title="EMPLOYMENT ACT 1955",
        selected_dates={"2023-09-02"},
        session=_Session(b"must not download"),
    )
    assert repeated["snapshots"][0]["acquisition_status"] == "already_registered"
    assert repeated["snapshots"][0]["readiness_status"] == "scanned_unparseable"
