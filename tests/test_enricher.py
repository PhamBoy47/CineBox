from __future__ import annotations

from core.enricher import MediaEnricher
from models.media_model import Media
from services.tmdb_service import TMDBServiceError


class FakeTMDBService:
    def __init__(self) -> None:
        self.search_movie_calls = 0
        self.get_movie_details_calls = 0

    def search_movie(self, title: str) -> dict[str, int]:
        self.search_movie_calls += 1
        return {"id": 101}

    def get_movie_details(self, movie_id: int) -> dict[str, object]:
        self.get_movie_details_calls += 1
        return {
            "title": "Inception",
            "release_date": "2010-07-16",
            "runtime": 148,
            "director": "Christopher Nolan",
            "writers": "Christopher Nolan",
            "producers": "Emma Thomas",
            "imdb_rating": 8.8,
        }

    def search_tv(self, title: str) -> None:
        return None

    def get_tv_details(self, tv_id: int) -> None:
        return None

    def get_tv_season_count(self, tv_id: int) -> None:
        return None

    def get_tv_episode_details(self, tv_id: int, season: int, episode: int) -> None:
        return None


class FailingTMDBService(FakeTMDBService):
    def search_movie(self, title: str) -> dict[str, int]:
        raise TMDBServiceError("network error")


def _media(file_path: str, file_name: str) -> Media:
    return Media(
        file_path=file_path,
        file_name=file_name,
        file_size_mb=100.0,
        duration_seconds=1200.0,
    )


def test_enricher_caches_movie_search_and_details_per_run() -> None:
    fake_service = FakeTMDBService()
    enricher = MediaEnricher(tmdb_service=fake_service)

    media_one = _media("D:/Movies/A/Inception.2010.mkv", "Inception.2010.mkv")
    media_two = _media("D:/Movies/B/Inception.2010.mkv", "Inception.2010.mkv")

    enricher.enrich(media_one)
    enricher.enrich(media_two)

    assert fake_service.search_movie_calls == 1
    assert fake_service.get_movie_details_calls == 1
    assert media_one.title == "Inception"
    assert media_two.title == "Inception"


def test_enricher_marks_category_error_when_tmdb_fails() -> None:
    enricher = MediaEnricher(tmdb_service=FailingTMDBService())
    media = _media("D:/Movies/C/Unknown.mkv", "Unknown.mkv")

    enriched = enricher.enrich(media)

    assert enriched.category == "error"
    assert enriched.error_message == "network error"
    assert enriched.error_location is not None
