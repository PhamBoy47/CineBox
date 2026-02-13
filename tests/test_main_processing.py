from __future__ import annotations

from datetime import datetime, timezone

import main as app_main
from models.media_model import Media


class FakeDB:
    def __init__(self, existing_by_path: dict[str, Media] | None = None) -> None:
        self._existing_by_path = existing_by_path or {}
        self.updated: list[Media] = []
        self.inserted: list[Media] = []

    def get_media_by_path(self, file_path: str) -> Media | None:
        return self._existing_by_path.get(file_path)

    def update_media(self, media: Media) -> None:
        self.updated.append(media)

    def insert_media(self, media: Media) -> None:
        self.inserted.append(media)


class FakeEnricher:
    def __init__(self) -> None:
        self.calls = 0

    def enrich(self, media: Media) -> Media:
        self.calls += 1
        media.title = "Fresh Metadata"
        return media


class FailingEnricher:
    def enrich(self, media: Media) -> Media:
        raise ValueError("enrichment exploded")


def _media(file_path: str, file_name: str, *, file_modified_time: float | None = None) -> Media:
    return Media(
        file_path=file_path,
        file_name=file_name,
        file_size_mb=100.0,
        duration_seconds=1200.0,
        file_modified_time=file_modified_time,
    )


def test_is_unchanged_uses_file_modified_time_with_tolerance() -> None:
    existing = _media("D:/A.mkv", "A.mkv", file_modified_time=100.0)
    scanned = _media("D:/A.mkv", "A.mkv", file_modified_time=100.0005)

    assert app_main._is_unchanged(scanned, existing)


def test_process_skips_enrichment_when_file_is_unchanged() -> None:
    path = "D:/Movies/Inception.mkv"
    existing = _media(path, "Inception.mkv", file_modified_time=200.0)
    existing.title = "Cached Title"
    existing.category = "movie"
    existing.director = "Cached Director"

    scanned = _media(path, "Inception.mkv", file_modified_time=200.0)
    db = FakeDB(existing_by_path={path: existing})
    enricher = FakeEnricher()
    scan_timestamp = datetime.now(timezone.utc)

    app_main._process_and_upsert_media(db, enricher, [scanned], scan_timestamp)

    assert enricher.calls == 0
    assert len(db.updated) == 1
    assert db.updated[0].title == "Cached Title"
    assert db.updated[0].category == "movie"
    assert db.updated[0].last_scanned == scan_timestamp


def test_process_enriches_when_file_has_changed() -> None:
    path = "D:/Movies/Inception.mkv"
    existing = _media(path, "Inception.mkv", file_modified_time=100.0)
    scanned = _media(path, "Inception.mkv", file_modified_time=200.0)

    db = FakeDB(existing_by_path={path: existing})
    enricher = FakeEnricher()
    scan_timestamp = datetime.now(timezone.utc)

    app_main._process_and_upsert_media(db, enricher, [scanned], scan_timestamp)

    assert enricher.calls == 1
    assert len(db.updated) == 1
    assert db.updated[0].title == "Fresh Metadata"
    assert db.updated[0].category == "movie"


def test_process_persists_error_metadata_when_processing_fails() -> None:
    path = "D:/Movies/Broken.mkv"
    scanned = _media(path, "Broken.mkv", file_modified_time=300.0)
    db = FakeDB()
    scan_timestamp = datetime.now(timezone.utc)

    app_main._process_and_upsert_media(db, FailingEnricher(), [scanned], scan_timestamp)

    assert len(db.inserted) == 1
    failed = db.inserted[0]
    assert failed.category == "error"
    assert failed.error_message == "enrichment exploded"
    assert failed.error_location is not None
