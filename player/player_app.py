"""Frameless PyQt6 CineBox player application entry point."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox, QWidget

try:
    from .controls_overlay import ControlsOverlay
    from .mpv_widget import MpvWidget
    from .settings_panel import AudioPanel, InfoPanel, SpeedPanel, SubtitlePanel
except ImportError:  # pragma: no cover - fallback for direct script execution
    from controls_overlay import ControlsOverlay
    from mpv_widget import MpvWidget
    from settings_panel import AudioPanel, InfoPanel, SpeedPanel, SubtitlePanel


class PlayerWindow(QWidget):
    """Frameless player window with mpv rendering and floating controls."""

    def __init__(self, media_path: Optional[str] = None) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setWindowTitle("CineBox Player")
        self.setMinimumSize(720, 420)
        self.setMouseTracking(True)
        self.setStyleSheet("background-color: black;")
        self.installEventFilter(self)

        self._is_paused = False
        self._drag_active = False
        self._drag_offset = QPoint()
        self._subtitle_track_ids: list[int | None] = [None]
        self._audio_track_ids: list[int] = []
        self._speed_values: list[float] = [0.5, 1.0, 1.25, 1.5, 2.0]

        self.video = MpvWidget(self)
        self.video.setGeometry(self.rect())

        self.overlay = ControlsOverlay(self, video=self.video)
        self.overlay.setGeometry(self.rect())
        self.overlay.show_controls()
        self.overlay.subtitleMenuRequested.connect(self._toggle_subtitle_panel)
        self.overlay.audioMenuRequested.connect(self._toggle_audio_panel)
        self.overlay.speedMenuRequested.connect(self._toggle_speed_panel)
        self.overlay.infoMenuRequested.connect(self._toggle_info_panel)

        # Use popup windows anchored to player window for stable rendering over native video.
        self.subtitle_panel = SubtitlePanel(self)
        self.audio_panel = AudioPanel(self)
        self.speed_panel = SpeedPanel(self)
        self.info_panel = InfoPanel(self)
        self.subtitle_panel.selectionChanged.connect(self._on_subtitle_option_selected)
        self.audio_panel.selectionChanged.connect(self._on_audio_option_selected)
        self.speed_panel.selectionChanged.connect(self._on_speed_option_selected)
        self.subtitle_panel.closed.connect(self._on_settings_panel_closed)
        self.audio_panel.closed.connect(self._on_settings_panel_closed)
        self.speed_panel.closed.connect(self._on_settings_panel_closed)
        self.info_panel.closed.connect(self._on_settings_panel_closed)

        self.video.pauseChanged.connect(self._on_pause_changed)
        self.video.fileLoaded.connect(self._on_file_loaded)
        self.overlay.set_media_info_text("No media loaded")
        self.overlay.set_speed_text(self._format_speed(self.video.playback_speed()))

        if media_path:
            self.open_media(media_path)

    def open_media(self, media_path: str) -> None:
        """Load a media file into mpv."""
        path = Path(media_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Media file does not exist: {path}")
        self.video.load_file(str(path), autoplay=True)
        self.setWindowTitle(f"CineBox Player - {path.name}")
        self.overlay.set_media_info_text(path.name)
        self.overlay.show_controls()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        """Keep video and overlay synced with window geometry."""
        super().resizeEvent(event)
        self.video.setGeometry(self.rect())
        self.overlay.setGeometry(self.rect())

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        """Handle global shortcuts not consumed by overlay."""
        key = event.key()
        if key == Qt.Key.Key_Escape and (
            self.subtitle_panel.isVisible()
            or self.audio_panel.isVisible()
            or self.speed_panel.isVisible()
            or self.info_panel.isVisible()
        ):
            self._hide_settings_panels()
            event.accept()
            return
        if key == Qt.Key.Key_Escape:
            self.close()
            event.accept()
            return
        if key == Qt.Key.Key_F:
            self._toggle_fullscreen()
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        """Toggle fullscreen on double click."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._hide_settings_panels()
            self._toggle_fullscreen()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        """Show overlay on movement and support dragging window in normal mode."""
        if self._drag_active and not self.isFullScreen():
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        """Begin drag for frameless window in normal mode."""
        if event.button() == Qt.MouseButton.LeftButton and not self.isFullScreen():
            self._drag_active = True
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        """End drag state."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = False
        super().mouseReleaseEvent(event)

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        """Keep overlay visible while interacting with controls."""
        if watched is self and event.type() == QEvent.Type.Enter:
            self.overlay.show_controls()
        return super().eventFilter(watched, event)

    def _on_pause_changed(self, paused: bool) -> None:
        """Sync overlay center button and auto-hide rules with playback state."""
        self._is_paused = bool(paused)
        self.overlay.set_paused(self._is_paused)

    def _on_file_loaded(self, _path: str) -> None:
        """Reset overlay timeline state on new file and show controls briefly."""
        self.overlay.set_position(0.0)
        self.overlay.set_duration(0.0)
        self.overlay.show_controls()
        self._refresh_track_option_caches()
        self.overlay.set_media_info_text(self.video.media_info_summary())
        self.overlay.set_speed_text(self._format_speed(self.video.playback_speed()))
        self.info_panel.set_info_rows(self.video.media_info_rows())

    def _toggle_fullscreen(self) -> None:
        """Toggle fullscreen state while preserving overlay behavior."""
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        self.overlay.show_controls()

    def _toggle_subtitle_panel(self) -> None:
        """Show or hide subtitle selector panel."""
        if self.subtitle_panel.isVisible():
            self.subtitle_panel.hide_panel()
            self.overlay.set_menu_open(False)
            return

        self._refresh_subtitle_options()
        self.audio_panel.hide_panel()
        self.speed_panel.hide_panel()
        self.info_panel.hide_panel()
        self.overlay.set_menu_open(True)
        self.subtitle_panel.show_panel(self.overlay.subtitle_button)

    def _toggle_audio_panel(self) -> None:
        """Show or hide audio selector panel."""
        if self.audio_panel.isVisible():
            self.audio_panel.hide_panel()
            self.overlay.set_menu_open(False)
            return

        self._refresh_audio_options()
        self.subtitle_panel.hide_panel()
        self.speed_panel.hide_panel()
        self.info_panel.hide_panel()
        self.overlay.set_menu_open(True)
        self.audio_panel.show_panel(self.overlay.audio_button)

    def _toggle_speed_panel(self) -> None:
        """Show or hide playback speed selector panel."""
        if self.speed_panel.isVisible():
            self.speed_panel.hide_panel()
            self.overlay.set_menu_open(False)
            return

        self._refresh_speed_options()
        self.subtitle_panel.hide_panel()
        self.audio_panel.hide_panel()
        self.info_panel.hide_panel()
        self.overlay.set_menu_open(True)
        self.speed_panel.show_panel(self.overlay.speed_button)

    def _toggle_info_panel(self) -> None:
        """Show or hide media info panel."""
        if self.info_panel.isVisible():
            self.info_panel.hide_panel()
            self.overlay.set_menu_open(False)
            return

        self.info_panel.set_info_rows(self.video.media_info_rows())
        self.subtitle_panel.hide_panel()
        self.audio_panel.hide_panel()
        self.speed_panel.hide_panel()
        self.overlay.set_menu_open(True)
        self.info_panel.show_panel(self.overlay.info_button)

    def _hide_settings_panels(self) -> None:
        """Hide all floating settings panels."""
        self.subtitle_panel.hide_panel()
        self.audio_panel.hide_panel()
        self.speed_panel.hide_panel()
        self.info_panel.hide_panel()
        self.overlay.set_menu_open(False)

    def _on_settings_panel_closed(self) -> None:
        """Unpin controls when no settings panel is open."""
        if (
            not self.subtitle_panel.isVisible()
            and not self.audio_panel.isVisible()
            and not self.speed_panel.isVisible()
            and not self.info_panel.isVisible()
        ):
            self.overlay.set_menu_open(False)

    def _refresh_track_option_caches(self) -> None:
        """Refresh subtitle/audio option maps from mpv."""
        self._refresh_subtitle_options(apply_to_panel=False)
        self._refresh_audio_options(apply_to_panel=False)

    def _refresh_subtitle_options(self, apply_to_panel: bool = True) -> None:
        """Build subtitle menu rows from mpv track metadata."""
        tracks = self.video.subtitle_tracks()
        options: list[str] = ["Off"]
        ids: list[int | None] = [None]

        for track in tracks:
            track_id = track.get("id")
            if track_id is None:
                continue
            try:
                int_id = int(track_id)
            except Exception:
                continue

            title = str(track.get("title") or "").strip()
            lang = str(track.get("lang") or "").strip()
            forced = bool(track.get("forced", False))

            if title and lang:
                label = f"{title} ({lang.upper()})"
            elif title:
                label = title
            elif lang:
                label = lang.upper()
            else:
                label = f"Subtitle {int_id}"

            if forced:
                label = f"{label} [Forced]"

            options.append(label)
            ids.append(int_id)

        selected_id = self.video.current_subtitle_id()
        selected_index = 0
        for idx, track_id in enumerate(ids):
            if track_id == selected_id:
                selected_index = idx
                break

        self._subtitle_track_ids = ids
        if apply_to_panel:
            self.subtitle_panel.set_options(options, selected_index)

    def _refresh_audio_options(self, apply_to_panel: bool = True) -> None:
        """Build audio menu rows from mpv track metadata."""
        tracks = self.video.audio_tracks()
        options: list[str] = []
        ids: list[int] = []

        for track in tracks:
            track_id = track.get("id")
            if track_id is None:
                continue
            try:
                int_id = int(track_id)
            except Exception:
                continue

            title = str(track.get("title") or "").strip()
            lang = str(track.get("lang") or "").strip()

            if title and lang:
                label = f"{title} ({lang.upper()})"
            elif title:
                label = title
            elif lang:
                label = lang.upper()
            else:
                label = f"Audio {int_id}"

            options.append(label)
            ids.append(int_id)

        if not options:
            options = ["Default"]
            ids = []

        selected_id = self.video.current_audio_id()
        selected_index = 0
        for idx, track_id in enumerate(ids):
            if track_id == selected_id:
                selected_index = idx
                break

        self._audio_track_ids = ids
        if apply_to_panel:
            self.audio_panel.set_options(options, selected_index)

    def _refresh_speed_options(self) -> None:
        """Sync speed panel selection with current mpv speed."""
        current_speed = self.video.playback_speed()
        labels = [self._format_speed(value) for value in self._speed_values]
        selected_index = self._nearest_speed_index(current_speed)
        self.speed_panel.set_options(labels, selected_index)

    def _on_subtitle_option_selected(self, index: int, _label: str) -> None:
        """Apply selected subtitle row to mpv sid property."""
        if index < 0 or index >= len(self._subtitle_track_ids):
            return
        self.video.set_subtitle_track(self._subtitle_track_ids[index])
        self.subtitle_panel.hide_panel()
        self.overlay.set_menu_open(False)
        self.overlay.show_controls()

    def _on_audio_option_selected(self, index: int, _label: str) -> None:
        """Apply selected audio row to mpv aid property."""
        if index < 0 or index >= len(self._audio_track_ids):
            return
        self.video.set_audio_track(self._audio_track_ids[index])
        self.audio_panel.hide_panel()
        self.overlay.set_menu_open(False)
        self.overlay.show_controls()

    def _on_speed_option_selected(self, index: int, _label: str) -> None:
        """Apply selected playback speed."""
        if index < 0 or index >= len(self._speed_values):
            return
        speed_value = self._speed_values[index]
        self.video.set_playback_speed(speed_value)
        self.overlay.set_speed_text(self._format_speed(speed_value))
        self.speed_panel.hide_panel()
        self.overlay.set_menu_open(False)
        self.overlay.show_controls()

    def _nearest_speed_index(self, speed: float) -> int:
        if not self._speed_values:
            return 0
        target = float(speed)
        return min(range(len(self._speed_values)), key=lambda idx: abs(self._speed_values[idx] - target))

    @staticmethod
    def _format_speed(speed: float) -> str:
        value = float(speed)
        if abs(value - round(value)) < 1e-9:
            return f"{int(round(value))}x"
        return f"{value:.2f}".rstrip("0").rstrip(".") + "x"

    def closeEvent(self, event):
        self._hide_settings_panels()
        try:
            self.video.close()
        except Exception:
            pass
        super().closeEvent(event)



def _choose_media_file(parent: QWidget) -> Optional[str]:
    """Prompt user for a media file when not provided via CLI."""
    filters = (
        "Media Files (*.mp4 *.mkv *.avi *.mov *.wmv *.webm *.flv *.m4v *.mp3 *.flac *.wav);;"
        "All Files (*.*)"
    )
    path, _ = QFileDialog.getOpenFileName(parent, "Open Media File", "", filters)
    return path or None


def main(argv: Optional[list[str]] = None) -> int:
    """Run the CineBox player application."""
    args = list(sys.argv if argv is None else argv)
    app = QApplication(args)
    app.setApplicationName("CineBox Player")
    app.setOrganizationName("CineBox")

    launch_path = args[1] if len(args) > 1 else None
    window = PlayerWindow()
    window.resize(1280, 720)
    window.show()

    if not launch_path:
        launch_path = _choose_media_file(window)

    if not launch_path:
        return 0

    try:
        window.open_media(launch_path)
    except Exception as exc:
        QMessageBox.critical(window, "Playback Error", str(exc))
        return 1

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
