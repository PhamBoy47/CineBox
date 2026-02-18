"""Thin Apple TV+-style seekbar used by the controls overlay."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
from PyQt6.QtWidgets import QWidget

# Shared style values used by overlay + seekbar.
SEEKBAR_HEIGHT_PX = 3.0
SEEKBAR_TRACK_RGBA = (255, 255, 255, 40)
SEEKBAR_PROGRESS_RGBA = (255, 255, 255, 200)


class ThinSeekBar(QWidget):
    """Custom painted progress bar without handle for Apple TV+-style scrubbing."""

    seekRequested = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._duration = 0.0
        self._position = 0.0
        self._dragging = False
        self._drag_position = 0.0
        self._visual_opacity = 1.0

        self._track_height = SEEKBAR_HEIGHT_PX
        self._track_color = QColor(*SEEKBAR_TRACK_RGBA)
        self._progress_color = QColor(*SEEKBAR_PROGRESS_RGBA)

        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(12)
        self.setStyleSheet("background-color: transparent;")

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(520, 12)

    def set_duration(self, duration_seconds: float) -> None:
        """Set total timeline duration in seconds."""
        self._duration = max(float(duration_seconds), 0.0)
        if self._duration <= 0.0:
            self._position = 0.0
            self._drag_position = 0.0
        else:
            self._position = min(self._position, self._duration)
            self._drag_position = min(self._drag_position, self._duration)
        self.update()

    def set_position(self, position_seconds: float) -> None:
        """Set visible playback position in seconds."""
        clamped = max(float(position_seconds), 0.0)
        if self._duration > 0.0:
            clamped = min(clamped, self._duration)
        if self._dragging:
            self._drag_position = clamped
        else:
            self._position = clamped
        self.update()

    def is_dragging(self) -> bool:
        return self._dragging

    def set_visual_opacity(self, opacity: float) -> None:
        """Set visual opacity for fade animations driven by overlay."""
        clamped = min(max(float(opacity), 0.0), 1.0)
        if abs(clamped - self._visual_opacity) < 0.01:
            return
        self._visual_opacity = clamped
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)

        track_rect = self._track_rect()
        radius = track_rect.height() / 2.0

        track_color = QColor(self._track_color)
        track_color.setAlpha(max(int(SEEKBAR_TRACK_RGBA[3] * self._visual_opacity), 0))
        painter.setBrush(track_color)
        painter.drawRoundedRect(track_rect, radius, radius)

        ratio = self._progress_ratio()
        if ratio > 0.0:
            progress_rect = QRectF(track_rect)
            progress_rect.setWidth(track_rect.width() * ratio)
            progress_color = QColor(self._progress_color)
            progress_color.setAlpha(max(int(SEEKBAR_PROGRESS_RGBA[3] * self._visual_opacity), 0))
            painter.setBrush(progress_color)
            if progress_rect.width() >= 1.0:
                painter.drawRoundedRect(progress_rect, radius, radius)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._set_drag_from_x(event.position().x())
            self.seekRequested.emit(self._drag_position)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._dragging:
            self._set_drag_from_x(event.position().x())
            self.seekRequested.emit(self._drag_position)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._set_drag_from_x(event.position().x())
            self._position = self._drag_position
            self._dragging = False
            self.seekRequested.emit(self._position)
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _track_rect(self) -> QRectF:
        y = (self.height() - self._track_height) / 2.0
        return QRectF(0.0, y, max(float(self.width()), 1.0), self._track_height)

    def _set_drag_from_x(self, x_pos: float) -> None:
        self._drag_position = self._seconds_from_x(x_pos)
        self.update()

    def _seconds_from_x(self, x_pos: float) -> float:
        if self._duration <= 0.0:
            return 0.0
        track = self._track_rect()
        clamped_x = min(max(x_pos, track.left()), track.right())
        ratio = (clamped_x - track.left()) / max(track.width(), 1.0)
        return self._duration * ratio

    def _progress_ratio(self) -> float:
        if self._duration <= 0.0:
            return 0.0
        current = self._drag_position if self._dragging else self._position
        return min(max(current / self._duration, 0.0), 1.0)
