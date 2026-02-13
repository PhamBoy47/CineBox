from __future__ import annotations

import os
import re
from typing import Any, Optional
from dotenv import load_dotenv

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from requests import Response

load_dotenv()



class TMDBServiceError(Exception):
    """Raised when TMDB requests fail."""


class TMDBService:
    """Service layer for querying TMDB movie metadata."""

    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(self, api_key_env: str = "TMDB_API_KEY", timeout: int = 10) -> None:
        """
        Initialize TMDB service client and in-memory caches for one process run.

        Cache dictionaries:
        - ``_search_movie_cache``: cleaned movie title -> search result
        - ``_search_tv_cache``: cleaned TV title -> search result
        - ``_movie_details_cache``: movie_id -> detailed movie metadata
        - ``_tv_details_cache``: tv_id -> detailed TV metadata
        - ``_tv_episode_cache``: (tv_id, season, episode) -> episode metadata
        """
        self._api_key = os.getenv(api_key_env)
        if not self._api_key:
            raise TMDBServiceError(
                f"Missing TMDB API key in environment variable: {api_key_env}"
            )

        self._timeout = timeout

        # 🔹 Create session with retry logic
        self._session = requests.Session()

        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

        # 🔹 In-memory caches
        self._search_movie_cache: dict[str, Optional[dict[str, Any]]] = {}
        self._search_tv_cache: dict[str, Optional[dict[str, Any]]] = {}
        self._movie_details_cache: dict[int, Optional[dict[str, Any]]] = {}
        self._tv_details_cache: dict[int, Optional[dict[str, Any]]] = {}
        self._tv_episode_cache: dict[tuple[int, int, int], Optional[dict[str, Any]]] = {}




    def clean_movie_title(self, raw_title: str) -> str:
        """
        Clean a filename/title by removing common release tags.

        Args:
            raw_title: Raw filename or title input.

        Returns:
            A normalized title suitable for TMDB search.
        """
        title = raw_title.strip()
        title = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", title)  # remove extension
        title = re.sub(r"[\[\(\{].*?[\]\)\}]", " ", title)  # remove bracket tags
        title = re.sub(r"\b(1080p|720p|2160p)\b", " ", title, flags=re.IGNORECASE)
        title = re.sub(r"\b(x264|x265|h264|h265)\b", " ", title, flags=re.IGNORECASE)
        title = re.sub(r"\b(AAC|DTS)\b", " ", title, flags=re.IGNORECASE)
        title = re.sub(r"[._-]+", " ", title)
        title = re.sub(r"\s+", " ", title).strip()
        return title

    def search_movie(self, title: str) -> Optional[dict[str, Any]]:
        """
        Search TMDB movie by title, with in-memory cache by cleaned title.
        """
        cleaned_title = self.clean_movie_title(title)

        if cleaned_title in self._search_movie_cache:
            return self._search_movie_cache[cleaned_title]

        payload = self._request(
            "/search/movie",
            {"query": cleaned_title, "include_adult": "false"},
        )
        results = payload.get("results", [])
        result = None

        if results:
            movie = results[0]
            result = {
                "id": movie.get("id"),
                "title": movie.get("title"),
                "release_date": movie.get("release_date"),
                "overview": movie.get("overview"),
                "tmdb_rating": movie.get("vote_average"),
            }

        self._search_movie_cache[cleaned_title] = result
        return result

    
    def search_tv(self, title: str) -> Optional[dict[str, Any]]:
        """
        Search TMDB TV by title, with in-memory cache by cleaned title.
        """
        cleaned_title = self.clean_movie_title(title)

        if cleaned_title in self._search_tv_cache:
            return self._search_tv_cache[cleaned_title]

        payload = self._request(
            "/search/tv",
            {"query": cleaned_title, "include_adult": "false"},
        )
        results = payload.get("results", [])
        result = None

        if results:
            tv = results[0]
            result = {
                "id": tv.get("id"),
                "title": tv.get("name"),
                "release_date": tv.get("first_air_date"),
                "tmdb_rating": tv.get("vote_average"),
            }

        self._search_tv_cache[cleaned_title] = result
        return result




    def get_movie_details(self, movie_id: int) -> Optional[dict[str, Any]]:
        """
        Fetch TMDB movie details, cached by movie id.
        """
        if movie_id in self._movie_details_cache:
            return self._movie_details_cache[movie_id]

        payload = self._request(
            f"/movie/{movie_id}",
            {"append_to_response": "credits,external_ids"},
            allow_not_found=True,
        )
        if payload is None:
            self._movie_details_cache[movie_id] = None
            return None

        crew = payload.get("credits", {}).get("crew", [])
        external_ids = payload.get("external_ids", {})
        imdb_id = external_ids.get("imdb_id")

        result = {
            "id": payload.get("id"),
            "title": payload.get("title"),
            "release_date": payload.get("release_date"),
            "director": self._first_name_by_job(crew, {"Director"}),
            "writers": ", ".join(self._names_by_job(crew, {"Writer", "Screenplay", "Story"})) or None,
            "producers": ", ".join(self._names_by_job(crew, {"Producer", "Executive Producer", "Co-Producer"})) or None,
            "runtime": payload.get("runtime"),
            "imdb_rating": payload.get("vote_average") if imdb_id else None,
            "imdb_id": imdb_id,
        }

        self._movie_details_cache[movie_id] = result
        return result

    
    def get_tv_details(self, tv_id: int) -> Optional[dict[str, Any]]:
        """
        Fetch TMDB TV details, cached by TV id.
        """
        if tv_id in self._tv_details_cache:
            return self._tv_details_cache[tv_id]

        payload = self._request(
            f"/tv/{tv_id}",
            {"append_to_response": "credits,external_ids"},
            allow_not_found=True,
        )
        if payload is None:
            self._tv_details_cache[tv_id] = None
            return None

        crew = payload.get("credits", {}).get("crew", [])
        external_ids = payload.get("external_ids", {})
        imdb_id = external_ids.get("imdb_id")

        director = self._first_name_by_job(crew, {"Director"})
        writers = self._names_by_job(crew, {"Writer", "Screenplay", "Story"})
        producers = self._names_by_job(crew, {"Producer", "Executive Producer", "Co-Producer"})

        imdb_rating = payload.get("vote_average") if imdb_id else None

        result = {
            "id": payload.get("id"),
            "title": payload.get("name"),
            "release_date": payload.get("first_air_date"),
            "director": director,
            "writers": ", ".join(writers) if writers else None,
            "producers": ", ".join(producers) if producers else None,
            "imdb_rating": imdb_rating,
        }
        self._tv_details_cache[tv_id] = result
        return result

    def get_tv_season_count(self, tv_id: int) -> Optional[int]:
        payload = self._request(f"/tv/{tv_id}", {}, allow_not_found=True)
        if payload is None:
            return None

        raw_count = payload.get("number_of_seasons")
        try:
            return int(raw_count)
        except (TypeError, ValueError):
            return None
    
    def get_tv_episode_details(self, tv_id: int, season: int, episode: int) -> Optional[dict[str, Any]]:
        """
        Fetch TMDB TV episode details, cached by (tv_id, season, episode).
        """
        cache_key = (tv_id, season, episode)
        if cache_key in self._tv_episode_cache:
            return self._tv_episode_cache[cache_key]

        payload = self._request(
            f"/tv/{tv_id}/season/{season}/episode/{episode}",
            {},
            allow_not_found=True,
        )
        if payload is None:
            self._tv_episode_cache[cache_key] = None
            return None

        result = {
            "episode_title": payload.get("name"),
            "air_date": payload.get("air_date"),
            "runtime": payload.get("runtime"),
            "overview": payload.get("overview"),
        }
        self._tv_episode_cache[cache_key] = result
        return result




    def _request(
        self,
        path: str,
        params: Optional[dict[str, Any]] = None,
        allow_not_found: bool = False,
    ) -> Optional[dict[str, Any]]:

        query = dict(params or {})
        query["api_key"] = self._api_key

        try:
            response: Response = self._session.get(
                f"{self.BASE_URL}{path}",
                params=query,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise TMDBServiceError(f"TMDB request failed for {path}: {exc}") from exc

        if response.status_code == 404 and allow_not_found:
            return None

        if not response.ok:
            raise TMDBServiceError(
                f"TMDB request failed for {path}: {response.status_code} {response.text}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise TMDBServiceError(
                f"Invalid JSON response from TMDB for {path}"
            ) from exc


    @staticmethod
    def _first_name_by_job(crew: list[dict[str, Any]], jobs: set[str]) -> Optional[str]:
        """Return the first crew member name matching any job title."""
        for member in crew:
            if member.get("job") in jobs:
                return member.get("name")
        return None

    @staticmethod
    def _names_by_job(crew: list[dict[str, Any]], jobs: set[str]) -> list[str]:
        """Return unique crew member names matching any job title."""
        names: list[str] = []
        seen: set[str] = set()
        for member in crew:
            if member.get("job") not in jobs:
                continue
            name = member.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
        return names