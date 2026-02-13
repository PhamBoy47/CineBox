# tests/test_tmdb_service_cache.py
from __future__ import annotations

from services.tmdb_service import (
    TMDBInvalidResponseError,
    TMDBNetworkError,
    TMDBRateLimitError,
    TMDBService,
)

import pytest
import requests

def test_tmdb_service_caches_requests(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TMDB_API_KEY", "dummy")
    service = TMDBService(cache_db_path=str(tmp_path / "media.db"))

    calls: dict[str, int] = {}

    def fake_request(path: str, params=None, allow_not_found: bool = False):
        calls[path] = calls.get(path, 0) + 1

        if path == "/search/movie":
            return {"results": [{"id": 1, "title": "Inception", "release_date": "2010-07-16", "overview": "", "vote_average": 8.7}]}
        if path == "/search/tv":
            return {"results": [{"id": 10, "name": "Dark", "first_air_date": "2017-12-01", "vote_average": 8.8}]}
        if path == "/movie/1":
            return {"id": 1, "title": "Inception", "release_date": "2010-07-16", "runtime": 148, "vote_average": 8.7, "credits": {"crew": []}, "external_ids": {"imdb_id": "tt1375666"}}
        if path == "/tv/10":
            return {"id": 10, "name": "Dark", "first_air_date": "2017-12-01", "vote_average": 8.8, "credits": {"crew": []}, "external_ids": {"imdb_id": "tt5753856"}}
        if path == "/tv/10/season/1/episode/1":
            return {"name": "Secrets", "air_date": "2017-12-01", "runtime": 52, "overview": ""}
        return {"results": []}

    monkeypatch.setattr(service, "_request", fake_request)

    service.search_movie("Inception.2010.1080p.x264")
    service.search_movie("Inception 2010")
    assert calls["/search/movie"] == 1

    service.search_tv("Dark.S01.1080p")
    service.search_tv("Dark S01")
    assert calls["/search/tv"] == 1

    service.get_movie_details(1)
    service.get_movie_details(1)
    assert calls["/movie/1"] == 1

    service.get_tv_details(10)
    service.get_tv_details(10)
    assert calls["/tv/10"] == 1

    service.get_tv_episode_details(10, 1, 1)
    service.get_tv_episode_details(10, 1, 1)
    assert calls["/tv/10/season/1/episode/1"] == 1


def test_tmdb_service_uses_persistent_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TMDB_API_KEY", "dummy")
    db_path = tmp_path / "media.db"

    service = TMDBService(cache_db_path=str(db_path))

    calls: dict[str, int] = {}

    def fake_request(path: str, params=None, allow_not_found: bool = False):
        calls[path] = calls.get(path, 0) + 1
        if path == "/movie/7":
            return {
                "id": 7,
                "title": "Se7en",
                "release_date": "1995-09-22",
                "runtime": 127,
                "vote_average": 8.4,
                "credits": {"crew": []},
                "external_ids": {"imdb_id": "tt0114369"},
            }
        return {"results": []}

    monkeypatch.setattr(service, "_request", fake_request)

    details = service.get_movie_details(7)
    assert details is not None
    assert calls["/movie/7"] == 1
    service.close()

    service2 = TMDBService(cache_db_path=str(db_path))

    def fail_request(path: str, params=None, allow_not_found: bool = False):
        raise AssertionError("network should not be called when persistent cache exists")

    monkeypatch.setattr(service2, "_request", fail_request)
    cached_details = service2.get_movie_details(7)
    assert cached_details == details
    service2.close()
