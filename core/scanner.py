from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, Optional

from pymediainfo import MediaInfo

from models.media_model import Media

logger = logging.getLogger(__name__)


class MediaScanner:
    """Scan folders for video files and map them into Media objects."""

    VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi"}

    def scan_folders(self, folder_paths: Iterable[str | Path]) -> list[Media]:
        """
        Recursively scan multiple folders and return unique Media objects.

        Args:
            folder_paths: Folder paths to scan.

        Returns:
            A deduplicated list of Media objects based on file path.
        """
        media_items: list[Media] = []
        seen_paths: set[str] = set()

        for folder_path in folder_paths:
            for media in self.scan_folder(folder_path):
                if media.file_path in seen_paths:
                    continue
                seen_paths.add(media.file_path)
                media_items.append(media)

        return media_items

    def scan_folder(self, folder_path: str | Path) -> list[Media]:
        """
        Recursively scan a folder for supported video files.

        Args:
            folder_path: Root directory to scan.

        Returns:
            A list of Media objects for successfully processed files.
        """
        root = Path(folder_path).expanduser()
        if not root.exists() or not root.is_dir():
            logger.warning("Scan path does not exist or is not a directory: %s", root)
            return []

        media_items: list[Media] = []
        for file_path in root.rglob("*"):
            try:
                if not self._is_supported_video(file_path):
                    continue

                media = self._build_media(file_path)
                if media is not None:
                    media_items.append(media)
            except OSError as exc:
                logger.warning(
                    "Skipping path due filesystem error at %s: %s",
                    file_path,
                    exc,
                )
            except Exception:
                logger.exception("Unexpected scanner error while processing %s", file_path)

        return media_items

    def _is_supported_video(self, file_path: Path) -> bool:
        """Return True if the path is a file with a supported video extension."""
        return file_path.is_file() and file_path.suffix.lower() in self.VIDEO_EXTENSIONS

    def _build_media(self, file_path: Path) -> Optional[Media]:
        """
        Build a Media object for a single file.

        Returns None if the file cannot be read safely.
        """
        try:
            stat_info = file_path.stat()
            file_size_mb = round(stat_info.st_size / (1024 * 1024), 2)
        except OSError as exc:
            logger.warning("Unable to read file metadata for %s: %s", file_path, exc)
            return None

        duration_seconds, resolution = self._extract_media_info(file_path)
        return Media(
            file_path=str(file_path.resolve()),
            file_name=file_path.name,
            file_size_mb=file_size_mb,
            duration_seconds=duration_seconds,
            resolution=resolution,
            file_modified_time=stat_info.st_mtime,
        )

    def _extract_media_info(self, file_path: Path) -> tuple[float, Optional[str]]:
        """
        Extract duration (seconds) and resolution (widthxheight) using pymediainfo.

        Returns default values when metadata cannot be parsed.
        """
        try:
            media_info = MediaInfo.parse(str(file_path))
        except Exception:
            logger.exception("Unable to parse media info for %s", file_path)
            return 0.0, None

        duration_seconds = self._extract_duration_seconds(media_info)
        resolution = self._extract_resolution(media_info)
        return duration_seconds, resolution

    def _extract_duration_seconds(self, media_info: MediaInfo) -> float:
        """Extract duration from media tracks and convert to seconds."""
        for track in media_info.tracks:
            if track.track_type not in {"General", "Video"}:
                continue

            raw_duration = getattr(track, "duration", None)
            if raw_duration is None:
                continue

            try:
                duration_ms = float(raw_duration)
                return round(duration_ms / 1000, 2)
            except (TypeError, ValueError):
                continue

        return 0.0

    def _extract_resolution(self, media_info: MediaInfo) -> Optional[str]:
        """Extract resolution from the first available video track."""
        for track in media_info.tracks:
            if track.track_type != "Video":
                continue

            width = self._to_int(getattr(track, "width", None))
            height = self._to_int(getattr(track, "height", None))
            if width is not None and height is not None:
                return f"{width}x{height}"

        return None

    @staticmethod
    def _to_int(value: object) -> Optional[int]:
        """Safely convert MediaInfo values to integers."""
        if value is None:
            return None

        try:
            cleaned = str(value).replace(" ", "")
            return int(float(cleaned))
        except (TypeError, ValueError):
            return None
