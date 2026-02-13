from __future__ import annotations

import os
import re
import json
import sqlite3
from datetime import datetime, timezone
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

    def __init__(
        self,
        api_key_env: str = "TMDB_API_KEY",
        timeout: int = 10,
        cache_db_path: str = "media.db",
    ) -> None:
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
        self._cache_db_path = cache_db_path

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
        self._cache_connection = self._create_cache_connection()
        self._ensure_cache_tables()




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

        cached_result = self._read_persistent_cache(
            "tmdb_movie_search",
            {"query_key": cleaned_title},
        )
        if cleaned_title in self._search_movie_cache:
            return self._search_movie_cache[cleaned_title]
        if cached_result is not None:
            return cached_result

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
        self._write_persistent_cache(
            "tmdb_movie_search",
            {"query_key": cleaned_title},
            result,
        )
        return result

    
    def search_tv(self, title: str) -> Optional[dict[str, Any]]:
        """
        Search TMDB TV by title, with in-memory cache by cleaned title.
        """
        cleaned_title = self.clean_movie_title(title)

        if cleaned_title in self._search_tv_cache:
            return self._search_tv_cache[cleaned_title]

        cached_result = self._read_persistent_cache(
            "tmdb_tv_search",
            {"query_key": cleaned_title},
        )
        if cleaned_title in self._search_tv_cache:
            return self._search_tv_cache[cleaned_title]
        if cached_result is not None:
            return cached_result

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
        self._write_persistent_cache(
            "tmdb_tv_search",
            {"query_key": cleaned_title},
            result,
        )
        return result




    def get_movie_details(self, movie_id: int) -> Optional[dict[str, Any]]:
        """
        Fetch TMDB movie details, cached by movie id.
        """
        if movie_id in self._movie_details_cache:
            return self._movie_details_cache[movie_id]

        cached_result = self._read_persistent_cache(
            "tmdb_movie_details",
            {"movie_id": movie_id},
        )
        if movie_id in self._movie_details_cache:
            return self._movie_details_cache[movie_id]
        if cached_result is not None:
            return cached_result

        payload = self._request(
            f"/movie/{movie_id}",
            {"append_to_response": "credits,external_ids"},
            allow_not_found=True,
        )
        if payload is None:
            self._movie_details_cache[movie_id] = None
            self._write_persistent_cache(
                "tmdb_movie_details",
                {"movie_id": movie_id},
                None,
            )
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
        self._write_persistent_cache(
            "tmdb_movie_details",
            {"movie_id": movie_id},
            result,
        )
        return result

    
    def get_tv_details(self, tv_id: int) -> Optional[dict[str, Any]]:
        """
        Fetch TMDB TV details, cached by TV id.
        """
        if tv_id in self._tv_details_cache:
            return self._tv_details_cache[tv_id]

        cached_result = self._read_persistent_cache(
            "tmdb_tv_details",
            {"tv_id": tv_id},
        )
        if tv_id in self._tv_details_cache:
            return self._tv_details_cache[tv_id]
        if cached_result is not None:
            return cached_result

        payload = self._request(
            f"/tv/{tv_id}",
            {"append_to_response": "credits,external_ids"},
            allow_not_found=True,
        )
        if payload is None:
            self._tv_details_cache[tv_id] = None
            self._write_persistent_cache(
                "tmdb_tv_details",
                {"tv_id": tv_id},
                None,
            )
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
        self._write_persistent_cache(
            "tmdb_tv_details",
            {"tv_id": tv_id},
            result,
        )
        return result

    def get_tv_season_count(self, tv_id: int) -> Optional[int]:
        """Return the season count for a TV show, or ``None`` if unknown."""
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

        cached_result = self._read_persistent_cache(
            "tmdb_episode_details",
            {
                "tv_id": tv_id,
                "season_number": season,
                "episode_number": episode,
            },
        )
        if cache_key in self._tv_episode_cache:
            return self._tv_episode_cache[cache_key]
        if cached_result is not None:
            return cached_result

        payload = self._request(
            f"/tv/{tv_id}/season/{season}/episode/{episode}",
            {},
            allow_not_found=True,
        )
        if payload is None:
            self._tv_episode_cache[cache_key] = None
            self._write_persistent_cache(
                "tmdb_episode_details",
                {
                    "tv_id": tv_id,
                    "season_number": season,
                    "episode_number": episode,
                },
                None,
            )
            return None

        result = {
            "episode_title": payload.get("name"),
            "air_date": payload.get("air_date"),
            "runtime": payload.get("runtime"),
            "overview": payload.get("overview"),
        }
        self._tv_episode_cache[cache_key] = result
        self._write_persistent_cache(
            "tmdb_episode_details",
            {
                "tv_id": tv_id,
                "season_number": season,
                "episode_number": episode,
            },
            result,
        )
        return result

    def _create_cache_connection(self) -> sqlite3.Connection:
        """Create and configure the SQLite connection used for persistent TMDB cache."""
        connection = sqlite3.connect(self._cache_db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_cache_tables(self) -> None:
        """Create persistent TMDB cache tables when they are missing."""
        cursor = self._cache_connection.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tmdb_movie_search (
                query_key TEXT PRIMARY KEY,
                response_json TEXT NOT NULL,
                cached_at TEXT NOT NULL
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tmdb_tv_search (
                query_key TEXT PRIMARY KEY,
                response_json TEXT NOT NULL,
                cached_at TEXT NOT NULL
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tmdb_movie_details (
                movie_id INTEGER PRIMARY KEY,
                response_json TEXT NOT NULL,
                cached_at TEXT NOT NULL
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tmdb_tv_details (
                tv_id INTEGER PRIMARY KEY,
                response_json TEXT NOT NULL,
                cached_at TEXT NOT NULL
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tmdb_episode_details (
                tv_id INTEGER NOT NULL,
                season_number INTEGER NOT NULL,
                episode_number INTEGER NOT NULL,
                response_json TEXT NOT NULL,
                cached_at TEXT NOT NULL,
                PRIMARY KEY (tv_id, season_number, episode_number)
            );
            """
        )
        self._cache_connection.commit()

    def _read_persistent_cache(
        self,
        table: str,
        key_columns: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Read and deserialize a cached TMDB payload from SQLite into memory."""
        where_clause = " AND ".join(f"{column} = ?" for column in key_columns)
        query = f"SELECT response_json FROM {table} WHERE {where_clause};"
        cursor = self._cache_connection.cursor()
        cursor.execute(query, tuple(key_columns.values()))
        row = cursor.fetchone()
        if row is None:
            return None

        payload = json.loads(row["response_json"])
        table_cache = self._get_memory_cache(table)
        normalized_key = self._normalize_cache_key(table, key_columns)
        table_cache[normalized_key] = payload
        return payload

    def _write_persistent_cache(
        self,
        table: str,
        key_columns: dict[str, Any],
        payload: Optional[dict[str, Any]],
    ) -> None:
        """Insert or update a TMDB cache record in SQLite with a fresh timestamp."""
        columns = list(key_columns.keys()) + ["response_json", "cached_at"]
        placeholders = ", ".join("?" for _ in columns)
        update_clause = ", ".join(
            f"{column}=excluded.{column}"
            for column in columns
            if column not in key_columns
        )
        conflict_columns = ", ".join(key_columns.keys())
        query = (
            f"INSERT INTO {table} ({', '.join(columns)}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT({conflict_columns}) DO UPDATE SET {update_clause};"
        )
        values = tuple(key_columns.values()) + (
            json.dumps(payload),
            datetime.now(tz=timezone.utc).isoformat(),
        )

        cursor = self._cache_connection.cursor()
        cursor.execute(query, values)
        self._cache_connection.commit()

    def _get_memory_cache(self, table: str) -> dict[Any, Optional[dict[str, Any]]]:
        """Map a cache table name to its corresponding in-memory cache dictionary."""
        if table == "tmdb_movie_search":
            return self._search_movie_cache
        if table == "tmdb_tv_search":
            return self._search_tv_cache
        if table == "tmdb_movie_details":
            return self._movie_details_cache
        if table == "tmdb_tv_details":
            return self._tv_details_cache
        if table == "tmdb_episode_details":
            return self._tv_episode_cache
        raise TMDBServiceError(f"Unsupported cache table: {table}")

    def _normalize_cache_key(self, table: str, key_columns: dict[str, Any]) -> Any:
        """Normalize SQLite key columns into the in-memory dictionary key format."""
        if table in {"tmdb_movie_search", "tmdb_tv_search"}:
            return key_columns["query_key"]
        if table == "tmdb_movie_details":
            return int(key_columns["movie_id"])
        if table == "tmdb_tv_details":
            return int(key_columns["tv_id"])
        if table == "tmdb_episode_details":
            return (
                int(key_columns["tv_id"]),
                int(key_columns["season_number"]),
                int(key_columns["episode_number"]),
            )
        raise TMDBServiceError(f"Unsupported cache table: {table}")

    def close(self) -> None:
        """Close underlying HTTP and SQLite resources held by this service."""
        self._session.close()
        self._cache_connection.close()

    def __del__(self) -> None:
        """Best-effort cleanup when the service instance is garbage collected."""
        try:
            self.close()
        except Exception:
            pass




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
