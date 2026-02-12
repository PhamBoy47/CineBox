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
        Search TMDB for a movie by title and return the best match.

        Args:
            title: Raw movie title or filename text.

        Returns:
            A structured movie dictionary or None when no match is found.
        """
        cleaned_title = self.clean_movie_title(title)
        payload = self._request(
            "/search/movie",
            {"query": cleaned_title, "include_adult": "false"},
        )
        results = payload.get("results", [])
        if not results:
            return None

        movie = results[0]
        return {
            "id": movie.get("id"),
            "title": movie.get("title"),
            "release_date": movie.get("release_date"),
            "overview": movie.get("overview"),
            "tmdb_rating": movie.get("vote_average"),
        }
    
    def search_tv(self, title: str) -> Optional[dict[str, Any]]:
        cleaned_title = self.clean_movie_title(title)
        payload = self._request(
            "/search/tv",
            {"query": cleaned_title, "include_adult": "false"},
        )
        results = payload.get("results", [])
        if not results:
            return None

        tv = results[0]
        return {
            "id": tv.get("id"),
            "title": tv.get("name"),
            "release_date": tv.get("first_air_date"),
            "tmdb_rating": tv.get("vote_average"),
        }



    def get_movie_details(self, movie_id: int) -> Optional[dict[str, Any]]:
        """
        Fetch detailed metadata for a TMDB movie id.

        Args:
            movie_id: TMDB movie identifier.

        Returns:
            A structured dictionary with requested metadata, or None if not found.
        """
        payload = self._request(
            f"/movie/{movie_id}",
            {"append_to_response": "credits,external_ids"},
            allow_not_found=True,
        )
        if payload is None:
            return None

        crew = payload.get("credits", {}).get("crew", [])
        external_ids = payload.get("external_ids", {})
        imdb_id = external_ids.get("imdb_id")

        director = self._first_name_by_job(crew, {"Director"})
        writers = self._names_by_job(crew, {"Writer", "Screenplay", "Story"})
        producers = self._names_by_job(crew, {"Producer", "Executive Producer", "Co-Producer"})

        # TMDB does not expose IMDb rating directly. Use TMDB score when IMDb id is available.
        imdb_rating = payload.get("vote_average") if imdb_id else None

        return {
            "id": payload.get("id"),
            "title": payload.get("title"),
            "release_date": payload.get("release_date"),
            "director": director,
            "writers": ", ".join(writers) if writers else None,
            "producers": ", ".join(producers) if producers else None,
            "runtime": payload.get("runtime"),
            "imdb_rating": imdb_rating,
            "imdb_id": imdb_id,
        }
    
    def get_tv_details(self, tv_id: int) -> Optional[dict[str, Any]]:
        payload = self._request(
            f"/tv/{tv_id}",
            {"append_to_response": "credits,external_ids"},
            allow_not_found=True,
        )
        if payload is None:
            return None

        crew = payload.get("credits", {}).get("crew", [])
        external_ids = payload.get("external_ids", {})
        imdb_id = external_ids.get("imdb_id")

        director = self._first_name_by_job(crew, {"Director"})
        writers = self._names_by_job(crew, {"Writer", "Screenplay", "Story"})
        producers = self._names_by_job(crew, {"Producer", "Executive Producer", "Co-Producer"})

        imdb_rating = payload.get("vote_average") if imdb_id else None

        return {
            "id": payload.get("id"),
            "title": payload.get("name"),
            "release_date": payload.get("first_air_date"),
            "director": director,
            "writers": ", ".join(writers) if writers else None,
            "producers": ", ".join(producers) if producers else None,
            "imdb_rating": imdb_rating,
        }
    
    def get_tv_episode_details(self, tv_id: int, season: int, episode: int) -> Optional[dict[str, Any]]:
        payload = self._request(
            f"/tv/{tv_id}/season/{season}/episode/{episode}",
            {},
            allow_not_found=True,
        )
        if payload is None:
            return None

        return {
            "episode_title": payload.get("name"),
            "air_date": payload.get("air_date"),
            "runtime": payload.get("runtime"),
            "overview": payload.get("overview"),
        }




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
