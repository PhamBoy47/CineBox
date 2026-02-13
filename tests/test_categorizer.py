from __future__ import annotations

from core.categorizer import MediaCategorizer
from models.media_model import Media


def _media(**overrides) -> Media:
    base = Media(
        file_path="D:/Media/sample.mkv",
        file_name="sample.mkv",
        file_size_mb=100.0,
        duration_seconds=1200.0,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_categorize_marks_anime_from_path_keyword() -> None:
    media = _media(file_path="D:/Entertainment/Anime/Naruto/S01E01.mkv")

    categorized = MediaCategorizer.categorize(media)

    assert categorized.category == "anime"


def test_categorize_marks_anime_from_fansub_filename() -> None:
    media = _media(file_name="[SubsPlease] Solo Leveling - 07 [1080p].mkv")

    categorized = MediaCategorizer.categorize(media)

    assert categorized.category == "anime"


def test_categorize_marks_tv_when_episode_markers_exist() -> None:
    media = _media(file_name="Show.S01E02.mkv", season_number=1, episode_number=2)

    categorized = MediaCategorizer.categorize(media)

    assert categorized.category == "tv"


def test_categorize_marks_movie_when_movie_metadata_exists() -> None:
    media = _media(file_name="Inception.2010.mkv", title="Inception")

    categorized = MediaCategorizer.categorize(media)

    assert categorized.category == "movie"


def test_categorize_marks_others_when_no_signals_match() -> None:
    media = _media(file_name="Unknown.Video.File.mkv")

    categorized = MediaCategorizer.categorize(media)

    assert categorized.category == "others"


def test_categorize_preserves_error_category() -> None:
    media = _media(file_name="Broken.File.mkv", category="error")

    categorized = MediaCategorizer.categorize(media)

    assert categorized.category == "error"
