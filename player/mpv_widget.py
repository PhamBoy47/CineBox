"""Qt widget that embeds libmpv video playback for CineBox."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from PyQt6 import sip
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget


# -------------------------------------------------
# Ensure libmpv DLL is discoverable BEFORE import mpv
# -------------------------------------------------

_MPV_BIN_DIR = Path(__file__).resolve().parent / "mpv_bin"
_MPV_DLL_PATH = _MPV_BIN_DIR / "mpv-2.dll"

if not _MPV_DLL_PATH.exists():
    raise FileNotFoundError(
        f"libmpv not found at '{_MPV_DLL_PATH}'. "
        "Place mpv-2.dll inside player/mpv_bin/"
    )

# Add mpv_bin directory to PATH BEFORE importing mpv
os.environ["PATH"] = str(_MPV_BIN_DIR) + os.pathsep + os.environ.get("PATH", "")

import mpv  # import AFTER PATH is modified


class MpvWidget(QWidget):
    """Native Qt widget host for rendering video through libmpv."""

    positionChanged = pyqtSignal(float)
    durationChanged = pyqtSignal(float)
    pauseChanged = pyqtSignal(bool)
    fileLoaded = pyqtSignal(str)
    endFile = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setStyleSheet("background-color: black;")

        self._player: Optional[mpv.MPV] = None
        self._initialized = False
        self._pending_load: Optional[tuple[str, bool]] = None
        self._current_path: str = ""

    # ----------------------------
    # Qt Lifecycle Hooks
    # ----------------------------

    def showEvent(self, event) -> None:  # type: ignore[override]
        """Initialize mpv lazily when the widget gets a native window."""
        super().showEvent(event)

        if not self._initialized:
            self._initialize_player()
            self._initialized = True

            if self._pending_load:
                path, autoplay = self._pending_load
                self._pending_load = None
                self.load_file(path, autoplay=autoplay)

    def closeEvent(self, event):
        self._shutdown_player()
        super().closeEvent(event)

    # ----------------------------
    # MPV Initialization
    # ----------------------------

    def _initialize_player(self) -> None:
        """Create mpv instance and connect property observers."""

        dll_path = (
            Path(__file__).resolve().parent
            / "mpv_bin"
            / "mpv-2.dll"
        )

        if not dll_path.exists():
            raise FileNotFoundError(
                f"libmpv not found at '{dll_path}'. "
                "Make sure mpv-2.dll exists in player/mpv_bin/"
            )

        wid = int(self.winId())

        self._player = mpv.MPV(
            wid=str(wid),
            osc=False,
            input_default_bindings=False,
            input_vo_keyboard=False,
            keep_open="yes",
            hwdec="auto-safe",
            vo="gpu-next",
            loglevel="warn",
        )

        # Property observers are async callbacks from libmpv.
        # Guard each callback with sip.isdeleted(self) so signals are never emitted
        # after Qt destroys this widget.

        @self._player.property_observer("time-pos")
        def _observe_position(_name: str, value: Optional[float]) -> None:
            if not self._can_emit_callbacks():
                return
            if value is not None:
                self.positionChanged.emit(float(value))

        @self._player.property_observer("duration")
        def _observe_duration(_name: str, value: Optional[float]) -> None:
            if not self._can_emit_callbacks():
                return
            if value is not None:
                self.durationChanged.emit(float(value))

        @self._player.property_observer("pause")
        def _observe_pause(_name: str, value: Optional[bool]) -> None:
            if not self._can_emit_callbacks():
                return
            if value is not None:
                self.pauseChanged.emit(bool(value))

        # Event observers also need callback safety checks.

        @self._player.event_callback("file-loaded")
        def _observe_file_loaded(_event) -> None:
            if not self._can_emit_callbacks():
                return
            if self._current_path:
                self.fileLoaded.emit(self._current_path)

        @self._player.event_callback("end-file")
        def _observe_end_file(_event) -> None:
            if not self._can_emit_callbacks():
                return
            self.endFile.emit()

    def _ensure_player(self) -> mpv.MPV:
        if self._player is None:
            raise RuntimeError("MpvWidget is not initialized yet.")
        return self._player

    def _can_emit_callbacks(self) -> bool:
        """Return True only while the Qt object and mpv player are both alive."""
        if sip.isdeleted(self):
            return False
        return self._player is not None

    def _shutdown_player(self) -> None:
        """Stop playback and terminate libmpv safely during widget teardown."""
        player = self._player
        self._player = None
        if player is None:
            return

        try:
            player.command("stop")
        except Exception:
            pass

        try:
            player.terminate()
        except Exception:
            pass

    def _get_property(self, property_name: str, default: Any = None) -> Any:
        """Read an mpv property safely and return default on failure."""
        player = self._player
        if player is None:
            return default
        try:
            value = player.command("get_property", property_name)
        except Exception:
            try:
                value = getattr(player, property_name.replace("-", "_"))
            except Exception:
                return default
        return default if value is None else value

    def _set_property(self, property_name: str, value: Any) -> None:
        """Set an mpv property safely."""
        player = self._player
        if player is None:
            return
        try:
            player.command("set_property", property_name, value)
            return
        except Exception:
            pass

        try:
            setattr(player, property_name.replace("-", "_"), value)
        except Exception:
            pass

    # ----------------------------
    # Public Playback API
    # ----------------------------

    def load_file(self, media_path: str, autoplay: bool = True) -> None:
        """Load media file and optionally autoplay."""
        if not self._initialized:
            self._pending_load = (media_path, autoplay)
            return

        player = self._ensure_player()

        self._current_path = str(
            Path(media_path).expanduser().resolve()
        )

        player.command("loadfile", self._current_path, "replace")
        player.pause = not autoplay

    def play(self) -> None:
        self._ensure_player().pause = False

    def pause(self) -> None:
        self._ensure_player().pause = True

    def toggle_pause(self) -> None:
        player = self._ensure_player()
        player.pause = not bool(player.pause)

    def seek(self, seconds: float) -> None:
        self._ensure_player().command("seek", float(seconds), "relative")

    def set_position(self, seconds: float) -> None:
        self._ensure_player().command(
            "seek", max(float(seconds), 0.0), "absolute"
        )

    def current_position(self) -> float:
        value = self._ensure_player().time_pos
        return float(value) if value is not None else 0.0

    def current_duration(self) -> float:
        value = self._ensure_player().duration
        return float(value) if value is not None else 0.0

    # ----------------------------
    # Track / Language Controls
    # ----------------------------

    def track_list(self) -> list[dict[str, Any]]:
        """Return full mpv track-list as normalized dictionaries."""
        raw = self._get_property("track-list", [])
        if not isinstance(raw, list):
            return []
        return [track for track in raw if isinstance(track, dict)]

    def subtitle_tracks(self) -> list[dict[str, Any]]:
        """Return subtitle tracks from mpv track-list."""
        return [track for track in self.track_list() if str(track.get("type", "")).lower() == "sub"]

    def audio_tracks(self) -> list[dict[str, Any]]:
        """Return audio tracks from mpv track-list."""
        return [track for track in self.track_list() if str(track.get("type", "")).lower() == "audio"]

    def current_subtitle_id(self) -> Optional[int]:
        """Return selected subtitle track id, or None when subtitles are off."""
        sid = self._get_property("sid", "no")
        if sid in (None, "no", "auto"):
            return None
        try:
            return int(sid)
        except Exception:
            return None

    def current_audio_id(self) -> Optional[int]:
        """Return selected audio track id, or None if unavailable."""
        aid = self._get_property("aid", None)
        if aid in (None, "no", "auto"):
            return None
        try:
            return int(aid)
        except Exception:
            return None

    def set_subtitle_track(self, track_id: Optional[int]) -> None:
        """Set subtitle track by id, or disable subtitles with None."""
        if track_id is None:
            self._set_property("sid", "no")
            return
        self._set_property("sid", int(track_id))

    def set_audio_track(self, track_id: int) -> None:
        """Set audio track by id."""
        self._set_property("aid", int(track_id))

    def playback_speed(self) -> float:
        """Return current playback speed multiplier."""
        value = self._get_property("speed", 1.0)
        try:
            return float(value)
        except Exception:
            return 1.0

    def set_playback_speed(self, speed: float) -> None:
        """Set playback speed multiplier."""
        self._set_property("speed", max(float(speed), 0.1))

    # ----------------------------
    # Media Metadata Helpers
    # ----------------------------

    def media_path(self) -> str:
        """Return absolute current media path if available."""
        return self._current_path

    def media_filename(self) -> str:
        """Return current media file name."""
        if not self._current_path:
            return "No media loaded"
        return Path(self._current_path).name

    def media_resolution_text(self) -> str:
        """Return best-effort video resolution string."""
        width = self._to_int(self._get_property("width", 0), 0)
        height = self._to_int(self._get_property("height", 0), 0)
        if width <= 0 or height <= 0:
            width = self._to_int(self._get_property("dwidth", 0), 0)
            height = self._to_int(self._get_property("dheight", 0), 0)
        if width <= 0 or height <= 0:
            return "Unknown resolution"
        return f"{width}x{height}"

    def media_info_summary(self) -> str:
        """Return short one-line summary used in overlay."""
        name = self.media_filename()
        resolution = self.media_resolution_text()
        if name == "No media loaded":
            return name
        return f"{name}  •  {resolution}"

    def media_info_rows(self) -> list[str]:
        """Return rich info rows for info panel."""
        if not self._current_path:
            return ["No media loaded"]

        duration = self.current_duration()
        duration_text = self._format_duration(duration)
        resolution = self.media_resolution_text()
        file_size = self._to_int(self._get_property("file-size", 0), 0)
        file_size_text = self._format_bytes(file_size) if file_size > 0 else "Unknown"

        video_codec = str(self._get_property("video-codec", "Unknown") or "Unknown")
        audio_codec = str(self._get_property("audio-codec-name", "Unknown") or "Unknown")
        fps_raw = self._get_property("container-fps", 0.0)
        try:
            fps = float(fps_raw)
        except Exception:
            fps = 0.0

        return [
            f"File: {self.media_filename()}",
            f"Path: {self._current_path}",
            f"Duration: {duration_text}",
            f"Resolution: {resolution}",
            f"Video Codec: {video_codec}",
            f"Audio Codec: {audio_codec}",
            f"Frame Rate: {fps:.2f} fps" if fps > 0.0 else "Frame Rate: Unknown",
            f"Size: {file_size_text}",
        ]

    @staticmethod
    def _to_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default

    @staticmethod
    def _format_duration(seconds: float) -> str:
        total = max(int(seconds), 0)
        hours = total // 3600
        minutes = (total % 3600) // 60
        secs = total % 60
        if hours > 0:
            return f"{hours}:{minutes:02}:{secs:02}"
        return f"{minutes:02}:{secs:02}"

    @staticmethod
    def _format_bytes(byte_count: int) -> str:
        size = float(max(byte_count, 0))
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024.0 or unit == "TB":
                if unit == "B":
                    return f"{int(size)} {unit}"
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return "Unknown"
