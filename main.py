from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Iterable

from dotenv import load_dotenv

from core.categorizer import MediaCategorizer
from core.database import DatabaseError, DatabaseManager
from core.enricher import MediaEnricher
from core.error_utils import get_exception_location
from core.scanner import MediaScanner
from models.media_model import Media
from core.display_formatter import DisplayFormatter

logger = logging.getLogger(__name__)


def _parse_scan_paths(raw_paths: str) -> list[str]:
    """
    Parse multiple scan paths from environment text.

    Supports newline, comma, and OS path separator delimited values.
    """
    paths: list[str] = []
    seen: set[str] = set()

    for line in raw_paths.splitlines():
        for comma_part in line.split(","):
            for path_part in comma_part.split(os.pathsep):
                candidate = path_part.strip().strip("\"'")
                if not candidate or candidate in seen:
                    continue
                seen.add(candidate)
                paths.append(candidate)

    return paths


def _load_scan_paths() -> list[str]:
    """Load scan paths from environment variables."""
    multi_paths = os.getenv("MEDIA_PATHS", "").strip()
    if multi_paths:
        return _parse_scan_paths(multi_paths)

    single_path = os.getenv("MEDIA_PATH", "").strip()
    if single_path:
        return [single_path]

    return []


def _is_unchanged(scanned: Media, existing: Media, tolerance_seconds: float = 0.001) -> bool:
    """
    Return True when a file's modification time has not changed.

    Args:
        scanned: Freshly scanned media.
        existing: Existing database media.
        tolerance_seconds: Floating-point comparison tolerance.
    """
    if scanned.file_modified_time is None or existing.file_modified_time is None:
        return False
    return abs(scanned.file_modified_time - existing.file_modified_time) <= tolerance_seconds


def _carry_forward_metadata(scanned: Media, existing: Media) -> Media:
    """Reuse previously enriched metadata when the source file is unchanged."""
    scanned.title = existing.title
    scanned.category = existing.category
    scanned.release_date = existing.release_date
    scanned.director = existing.director
    scanned.writers = existing.writers
    scanned.producers = existing.producers
    scanned.runtime_minutes = existing.runtime_minutes
    scanned.imdb_rating = existing.imdb_rating
    scanned.poster_path = existing.poster_path
    scanned.error_message = existing.error_message
    scanned.error_location = existing.error_location
    scanned.season_number = existing.season_number
    scanned.episode_number = existing.episode_number
    scanned.episode_title = existing.episode_title
    scanned.episode_air_date = existing.episode_air_date
    return scanned


def _process_and_upsert_media(
    db: DatabaseManager,
    enricher: MediaEnricher,
    media_items: Iterable[Media],
    scan_timestamp: datetime,
) -> None:
    """
    Enrich, categorize, and upsert media records.

    Enrichment is skipped when a file's file_modified_time value has not changed.
    """
    for scanned in media_items:
        scanned.last_scanned = scan_timestamp
        try:
            existing = db.get_media_by_path(scanned.file_path)

            if existing and _is_unchanged(scanned, existing):
                media = _carry_forward_metadata(scanned, existing)
                action = "Skipped enrichment (unchanged)"
            else:
                media = MediaCategorizer.categorize(enricher.enrich(scanned))
                action = "Updated" if existing else "Inserted"

            if existing:
                db.update_media(media)
            else:
                db.insert_media(media)

            display_name = DisplayFormatter.format(media)
            print(f"{action}: {display_name}")
        except Exception as exc:
            _handle_media_processing_error(db, scanned, exc)


def _handle_media_processing_error(db: DatabaseManager, media: Media, exc: Exception) -> None:
    """
    Persist processing failures and log stack traces with source locations.
    """
    media.category = "error"
    media.error_message = str(exc)
    media.error_location = get_exception_location(exc)

    logger.exception(
        "Media processing failed for '%s' at %s",
        media.file_path,
        media.error_location,
    )

    try:
        existing = db.get_media_by_path(media.file_path)
        if existing:
            db.update_media(media)
        else:
            db.insert_media(media)
        print(f"Error: {media.file_name} -> {media.error_message} ({media.error_location})")
    except DatabaseError:
        logger.exception(
            "Failed to persist error state for '%s' at %s",
            media.file_path,
            media.error_location,
        )


def _configure_logging() -> None:
    """
    Configure console + file logging with source file and line numbers.
    """
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    log_file = os.getenv("LOG_FILE", "cinebox.log")

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    except OSError:
        print(f"Warning: unable to open log file '{log_file}', using console logging only.")

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(filename)s:%(lineno)d | %(message)s",
        handlers=handlers,
        force=True,
    )

def main():
    load_dotenv()
    _configure_logging()

    scan_paths = _load_scan_paths()
    if not scan_paths:
        raise ValueError(
            "No media scan paths configured. Set MEDIA_PATHS (or MEDIA_PATH) in .env."
        )

    scanner = MediaScanner()
    enricher = MediaEnricher()
    db = DatabaseManager()

    try:
        media_files = scanner.scan_folders(scan_paths)
        scan_timestamp = datetime.now(timezone.utc)
        _process_and_upsert_media(db, enricher, media_files, scan_timestamp)
    finally:
        db.close()


if __name__ == "__main__":
    main()
