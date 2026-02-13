from __future__ import annotations

from types import SimpleNamespace

from core.scanner import MediaScanner


def _fake_media_info(duration_ms: str = "90000", width: str = "1920", height: str = "1080") -> SimpleNamespace:
    general_track = SimpleNamespace(track_type="General", duration=duration_ms)
    video_track = SimpleNamespace(track_type="Video", width=width, height=height)
    return SimpleNamespace(tracks=[general_track, video_track])


def test_scan_folders_reads_multiple_paths_and_filters_non_video_files(tmp_path, monkeypatch) -> None:
    movies_dir = tmp_path / "movies"
    tv_dir = tmp_path / "tv" / "season1"
    movies_dir.mkdir(parents=True)
    tv_dir.mkdir(parents=True)

    movie_file = movies_dir / "movie_one.mkv"
    episode_file = tv_dir / "show_ep01.mp4"
    ignored_file = movies_dir / "notes.txt"

    movie_file.write_bytes(b"movie")
    episode_file.write_bytes(b"episode")
    ignored_file.write_text("ignore me", encoding="utf-8")

    monkeypatch.setattr("core.scanner.MediaInfo.parse", lambda _: _fake_media_info())

    scanner = MediaScanner()
    media_items = scanner.scan_folders([movies_dir, tv_dir.parent])

    assert len(media_items) == 2
    scanned_paths = {item.file_path for item in media_items}
    assert scanned_paths == {str(movie_file), str(episode_file)}

    for item in media_items:
        assert item.duration_seconds == 90.0
        assert item.resolution == "1920x1080"


def test_scan_folders_deduplicates_when_same_root_is_passed_twice(tmp_path, monkeypatch) -> None:
    root = tmp_path / "library"
    root.mkdir()

    video_file = root / "duplicate_check.avi"
    video_file.write_bytes(b"video")

    monkeypatch.setattr("core.scanner.MediaInfo.parse", lambda _: _fake_media_info())

    scanner = MediaScanner()
    media_items = scanner.scan_folders([root, root])

    assert len(media_items) == 1
    assert media_items[0].file_path == str(video_file)
