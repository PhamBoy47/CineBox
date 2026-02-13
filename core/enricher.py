from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

from core.error_utils import get_exception_location
from models.media_model import Media
from services.tmdb_service import TMDBService, TMDBServiceError

logger = logging.getLogger(__name__)


class MediaEnricher:
    """Enrich Media objects with metadata retrieved from TMDB."""

    def __init__(self, tmdb_service: Optional[TMDBService] = None) -> None:
        """
        Initialize dependencies and in-memory caches for a single run.

        Args:
            tmdb_service: Optional injected TMDB service for testing.
        """
        self.tmdb_service = tmdb_service or TMDBService()
        self._movie_search_cache: dict[str, Optional[dict[str, Any]]] = {}
        self._movie_details_cache: dict[int, Optional[dict[str, Any]]] = {}
        self._tv_search_cache: dict[str, Optional[dict[str, Any]]] = {}
        self._tv_details_cache: dict[int, Optional[dict[str, Any]]] = {}
        self._tv_season_count_cache: dict[int, Optional[int]] = {}
        self._tv_episode_cache: dict[tuple[int, int, int], Optional[dict[str, Any]]] = {}

    def enrich(self, media: Media) -> Media:
        """
        Enrich a Media object using TMDB search/details endpoints.

        On TMDB API failures, mark category as "error" and return media unchanged.
        """
        media.error_message = None
        media.error_location = None
        title_source = self._extract_title_source(media)

        try:
            if self._is_tv_episode(media.file_name):
                self._enrich_tv(media, title_source)
            else:
                self._enrich_movie(media, title_source)
        except TMDBServiceError as exc:
            self._mark_error(media, exc)
            logger.exception("TMDB enrichment failed for '%s'", media.file_name)
        except Exception as exc:
            self._mark_error(media, exc)
            logger.exception("Unexpected enrichment failure for '%s'", media.file_name)

        return media

    @staticmethod
    def _mark_error(media: Media, exc: BaseException) -> None:
        media.category = "error"
        media.error_message = str(exc)
        media.error_location = get_exception_location(exc)

    def _enrich_movie(self, media: Media, title_source: str) -> None:
        search_result = self._cached_search_movie(title_source)
        if not search_result:
            return

        movie_id = search_result.get("id")
        if not isinstance(movie_id, int):
            return

        details = self._cached_movie_details(movie_id)
        if not details:
            return

        media.title = details.get("title")
        media.release_date = details.get("release_date")
        media.runtime_minutes = details.get("runtime")
        media.director = details.get("director")
        media.writers = details.get("writers")
        media.producers = details.get("producers")
        media.imdb_rating = details.get("imdb_rating")

    def _enrich_tv(self, media: Media, title_source: str) -> None:
        search_result = self._cached_search_tv(title_source)
        if not search_result:
            return

        tv_id = search_result.get("id")
        if not isinstance(tv_id, int):
            return

        season, episode = self._extract_season_episode(media)
        if season is None or episode is None:
            return

        available_seasons = self._cached_tv_season_count(tv_id)
        if available_seasons is not None and season > available_seasons:
            logger.info(
                "TMDB season mismatch for '%s': requested S%s but only %s seasons exist",
                media.file_name,
                season,
                available_seasons,
            )
            return

        show_details = self._cached_tv_details(tv_id)
        if show_details:
            media.title = show_details.get("title")
            media.release_date = show_details.get("release_date")
            media.director = show_details.get("director")
            media.writers = show_details.get("writers")
            media.producers = show_details.get("producers")
            media.imdb_rating = show_details.get("imdb_rating")

        episode_details = self._cached_tv_episode_details(tv_id, season, episode)
        if not episode_details:
            return

        media.season_number = season
        media.episode_number = episode
        media.episode_title = episode_details.get("episode_title")
        media.episode_air_date = episode_details.get("air_date")
        media.runtime_minutes = episode_details.get("runtime")

    def _cached_search_movie(self, title: str) -> Optional[dict[str, Any]]:
        if title not in self._movie_search_cache:
            self._movie_search_cache[title] = self.tmdb_service.search_movie(title)
        return self._movie_search_cache[title]

    def _cached_movie_details(self, movie_id: int) -> Optional[dict[str, Any]]:
        if movie_id not in self._movie_details_cache:
            self._movie_details_cache[movie_id] = self.tmdb_service.get_movie_details(movie_id)
        return self._movie_details_cache[movie_id]

    def _cached_search_tv(self, title: str) -> Optional[dict[str, Any]]:
        if title not in self._tv_search_cache:
            self._tv_search_cache[title] = self.tmdb_service.search_tv(title)
        return self._tv_search_cache[title]

    def _cached_tv_details(self, tv_id: int) -> Optional[dict[str, Any]]:
        if tv_id not in self._tv_details_cache:
            self._tv_details_cache[tv_id] = self.tmdb_service.get_tv_details(tv_id)
        return self._tv_details_cache[tv_id]

    def _cached_tv_season_count(self, tv_id: int) -> Optional[int]:
        if tv_id not in self._tv_season_count_cache:
            self._tv_season_count_cache[tv_id] = self.tmdb_service.get_tv_season_count(tv_id)
        return self._tv_season_count_cache[tv_id]

    def _cached_tv_episode_details(
        self, tv_id: int, season: int, episode: int
    ) -> Optional[dict[str, Any]]:
        cache_key = (tv_id, season, episode)
        if cache_key not in self._tv_episode_cache:
            self._tv_episode_cache[cache_key] = self.tmdb_service.get_tv_episode_details(
                tv_id, season, episode
            )
        return self._tv_episode_cache[cache_key]

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
            if len(path.parents) >= 2:
                return path.parents[1].name

        return media.file_name

    @staticmethod
    def _extract_season_episode(media: Media) -> tuple[Optional[int], Optional[int]]:
        filename = media.file_name

        match = re.search(r"S(\d{1,2})[.\-_ ]?E(\d{1,2})", filename, re.IGNORECASE)
        if match:
            return int(match.group(1)), int(match.group(2))

        match = re.search(r"(\d{1,2})x(\d{1,2})", filename, re.IGNORECASE)
        if match:
            return int(match.group(1)), int(match.group(2))

        return None, None
