from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

from models.media_model import Media
from services.tmdb_service import TMDBService, TMDBServiceError


class MediaEnricher:
    """Enrich Media objects with metadata retrieved from TMDB."""

    def __init__(self) -> None:
        """Initialize dependencies for metadata enrichment."""
        self.tmdb_service = TMDBService()

    def enrich(self, media: Media) -> Media:
        """
        Enrich a Media object using TMDB search/details endpoints.
        """

        title_source = self._extract_title_source(media)

        try:
            if self._is_tv_episode(media.file_name):
                # --- TV LOGIC ---
                search_result = self.tmdb_service.search_tv(title_source)
                if not search_result:
                    return media

                tv_id = search_result.get("id")
                if not isinstance(tv_id, int):
                    return media

                # Extract season & episode
                season, episode = self._extract_season_episode(media.file_name)

                # Get show-level details
                show_details = self.tmdb_service.get_tv_details(tv_id)
                if not show_details:
                    return media

                # Apply show-level metadata
                media.title = show_details.get("title")
                media.release_date = show_details.get("release_date")
                media.director = show_details.get("director")
                media.writers = show_details.get("writers")
                media.producers = show_details.get("producers")
                media.imdb_rating = show_details.get("imdb_rating")

                # Apply episode-level metadata if available
                if season is not None and episode is not None:
                    episode_details = self.tmdb_service.get_tv_episode_details(
                        tv_id, season, episode
                    )
                    time.sleep(0.2)
                    if episode_details:
                        media.season_number = season
                        media.episode_number = episode
                        media.episode_title = episode_details.get("episode_title")
                        media.episode_air_date = episode_details.get("air_date")
                        media.runtime_minutes = episode_details.get("runtime")

            else:
                # --- MOVIE LOGIC ---
                search_result = self.tmdb_service.search_movie(title_source)
                if not search_result:
                    return media

                movie_id = search_result.get("id")
                if not isinstance(movie_id, int):
                    return media

                details = self.tmdb_service.get_movie_details(movie_id)
                if not details:
                    return media

                media.title = details.get("title")
                media.release_date = details.get("release_date")
                media.runtime_minutes = details.get("runtime")
                media.director = details.get("director")
                media.writers = details.get("writers")
                media.producers = details.get("producers")
                media.imdb_rating = details.get("imdb_rating")

        except TMDBServiceError:
            return media

        return media


    @staticmethod
    def _is_tv_episode(filename: str) -> bool:
        """Detect TV episode patterns like S01E01."""
        return bool(re.search(r"S\d+E\d+", filename, re.IGNORECASE))

    @staticmethod
    def _extract_title_source(media: Media) -> str:
        """
        Extract appropriate title source:
        - For TV: use show folder name
        - For movies: use filename
        """
        path = Path(media.file_path)

        if MediaEnricher._is_tv_episode(media.file_name):
            # Example structure:
            # Solo Leveling/S01/S01E01.mkv
            if path.parent.parent.exists():
                return path.parent.parent.name

        return media.file_name
    @staticmethod
    def _extract_season_episode(filename: str) -> tuple[Optional[int], Optional[int]]:
        # Match S01E01
        match = re.search(r"S(\d{1,2})E(\d{1,2})", filename, re.IGNORECASE)
        if match:
            return int(match.group(1)), int(match.group(2))

        # Match 1x06
        match = re.search(r"(\d{1,2})x(\d{1,2})", filename, re.IGNORECASE)
        if match:
            return int(match.group(1)), int(match.group(2))

        return None, None
