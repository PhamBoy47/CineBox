from __future__ import annotations

import re

from models.media_model import Media


class MediaCategorizer:
    """Categorize media records as anime, TV, movie, or others."""

    @staticmethod
    def categorize(media: Media) -> Media:
        """
        Categorize a Media object using anime cues, episode markers, and enrichment fields.

        Steps:
        1. If anime indicators are present, mark as anime.
        2. Otherwise, if season and episode numbers are present, mark as TV.
        3. Otherwise, if enriched movie metadata exists, mark as movie.
        4. Otherwise, mark as others.

        Args:
            media: Media object to classify.

        Returns:
            The same Media object with `category` updated.
        """
        if media.category == "error":
            return media

        if MediaCategorizer._is_anime(media):
            media.category = "anime"
            return media

        if media.season_number is not None and media.episode_number is not None:
            media.category = "tv"
            return media

        has_movie_metadata = any(
            value is not None
            for value in (
                media.title,
                media.release_date,
                media.runtime_minutes,
                media.director,
                media.writers,
                media.producers,
                media.imdb_rating,
            )
        )
        if has_movie_metadata:
            media.category = "movie"
            return media

        media.category = "others"
        return media

    @staticmethod
    def _is_anime(media: Media) -> bool:
        """
        Detect anime content using common folder/name conventions.

        Heuristics:
        - Presence of anime-specific keywords in path/title.
        - Fansub-style filename pattern, e.g. "[Group] Title - 07".
        """
        text_parts = [
            media.file_path or "",
            media.file_name or "",
            media.title or "",
        ]
        normalized = " ".join(text_parts).lower()

        keyword_markers = (
            "anime",
            "animedub",
            "anime-dub",
            "crunchyroll",
            "subsplease",
            "erai-raws",
            "horriblesubs",
        )
        if any(marker in normalized for marker in keyword_markers):
            return True

        fansub_pattern = r"^\[[^\]]+\].*?\s-\s\d{1,4}\b"
        if re.search(fansub_pattern, media.file_name, re.IGNORECASE):
            return True

        return False
