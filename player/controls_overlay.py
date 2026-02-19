"""Apple TV+-style floating controls overlay for CineBox."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from PyQt6.QtCore import QEasingCurve, QEvent, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QIcon, QImage, QKeyEvent, QLinearGradient, QMouseEvent, QPainter, QPaintEvent, QPixmap, QPolygonF
from PyQt6.QtWidgets import QLabel, QPushButton, QWidget

try:
    from .seekbar import ThinSeekBar
except ImportError:  # pragma: no cover - fallback for direct script execution
    from seekbar import ThinSeekBar


GRADIENT_BOTTOM_RGBA = (0, 0, 0, 120)
CREAM_RGB = (246, 236, 214)
TIME_LABEL_RGBA = (CREAM_RGB[0], CREAM_RGB[1], CREAM_RGB[2], 200)
PLAY_BUTTON_BG_RGBA = (0, 0, 0, 90)
PLAY_BUTTON_ICON_RGBA = (CREAM_RGB[0], CREAM_RGB[1], CREAM_RGB[2], 245)
ACTION_ICON_SIZE = QSize(20, 20)

SUBTITLE_ICON_PATH = Path(r"D:\Codes\CineBox\assets\subtitle.svg")
AUDIO_ICON_PATH = Path(r"D:\Codes\CineBox\assets\audio_change.svg")
INFO_ICON_PATH = Path(r"D:\Codes\CineBox\assets\Information.svg")


class _CenterPlaybackButton(QPushButton):
    """Custom-drawn circular button so play/pause icon rendering is consistent."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(88, 88)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._paused = True
        self._opacity = 1.0
        self.setStyleSheet("background: transparent; border: none;")

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)
        self.update()

    def set_visual_opacity(self, opacity: float) -> None:
        clamped = min(max(float(opacity), 0.0), 1.0)
        if abs(clamped - self._opacity) < 0.01:
            return
        self._opacity = clamped
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # type: ignore[override]
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)

        if self.isDown():
            bg_base = 126
        elif self.underMouse():
            bg_base = 108
        else:
            bg_base = PLAY_BUTTON_BG_RGBA[3]

        bg_alpha = max(int(bg_base * self._opacity), 0)
        icon_alpha = max(int(PLAY_BUTTON_ICON_RGBA[3] * self._opacity), 0)

        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        radius = rect.width() * 0.5
        painter.setBrush(QColor(0, 0, 0, bg_alpha))
        painter.drawEllipse(rect)

        painter.setBrush(QColor(PLAY_BUTTON_ICON_RGBA[0], PLAY_BUTTON_ICON_RGBA[1], PLAY_BUTTON_ICON_RGBA[2], icon_alpha))
        cx = rect.center().x()
        cy = rect.center().y()
        if self._paused:
            tri_w = rect.width() * 0.24
            tri_h = rect.height() * 0.36
            tri = QPolygonF(
                [
                    QPointF(cx - (tri_w * 0.45), cy - (tri_h * 0.5)),
                    QPointF(cx - (tri_w * 0.45), cy + (tri_h * 0.5)),
                    QPointF(cx + (tri_w * 0.78), cy),
                ]
            )
            painter.drawPolygon(tri)
        else:
            bar_w = rect.width() * 0.08
            bar_h = rect.height() * 0.34
            gap = rect.width() * 0.07
            left = QRectF(cx - gap * 0.5 - bar_w, cy - bar_h * 0.5, bar_w, bar_h)
            right = QRectF(cx + gap * 0.5, cy - bar_h * 0.5, bar_w, bar_h)
            round_r = max(bar_w * 0.25, 1.5)
            painter.drawRoundedRect(left, round_r, round_r)
            painter.drawRoundedRect(right, round_r, round_r)


class ControlsOverlay(QWidget):
    """Floating controls rendered with absolute positioning and subtle fade animation."""

    playPauseRequested = pyqtSignal()
    seekRequested = pyqtSignal(float)
    subtitleMenuRequested = pyqtSignal()
    audioMenuRequested = pyqtSignal()
    speedMenuRequested = pyqtSignal()
    infoMenuRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None, video: Optional[Any] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._duration = 0.0
        self._position = 0.0
        self._is_paused = False
        self._fading_out = False
        self._bound_video: Optional[Any] = None
        self._menu_open = False
        self._overlay_opacity = 1.0
        self._style_alpha_key = -1
        self._controls_block_rect = QRectF()
        self._media_info_text = "No media loaded"
        self._overlay_widgets_visible = True

        self.seekbar = ThinSeekBar(self)
        self.current_time = QLabel("00:00", self)
        self.total_time = QLabel("00:00", self)
        self.center_button = _CenterPlaybackButton(self)
        self.media_info_label = QLabel(self._media_info_text, self)
        self.subtitle_button = QPushButton("", self)
        self.audio_button = QPushButton("", self)
        self.speed_button = QPushButton("1x", self)
        self.info_button = QPushButton("", self)
        self._action_buttons = (
            self.subtitle_button,
            self.audio_button,
            self.speed_button,
            self.info_button,
        )

        self._setup_widgets()
        self._setup_animation()
        self._setup_autohide()

        self.installEventFilter(self)
        self.seekbar.installEventFilter(self)
        self.center_button.installEventFilter(self)
        for button in self._action_buttons:
            button.installEventFilter(self)
        if parent is not None:
            parent.installEventFilter(self)

        if video is not None:
            self.attach_video(video)

        self.set_paused(True)
        self._position_controls()

    def _setup_widgets(self) -> None:
        time_font = QFont("Segoe UI", 9)
        for label in (self.current_time, self.total_time):
            label.setFont(time_font)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        info_font = QFont("Segoe UI", 10)
        info_font.setWeight(QFont.Weight.DemiBold)
        self.media_info_label.setFont(info_font)
        self.media_info_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.media_info_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.current_time.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.total_time.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.center_button.clicked.connect(self.playPauseRequested.emit)
        self.seekbar.seekRequested.connect(self._on_seekbar_requested)

        self._setup_aux_button(self.subtitle_button, "Subtitles", icon_path=SUBTITLE_ICON_PATH, fallback_text="CC")
        self._setup_aux_button(self.audio_button, "Audio", icon_path=AUDIO_ICON_PATH, fallback_text="♪")
        self._setup_aux_button(self.speed_button, "Speed", fallback_text="1x")
        self._setup_aux_button(self.info_button, "Info", icon_path=INFO_ICON_PATH, fallback_text="i")
        self.subtitle_button.clicked.connect(self.subtitleMenuRequested.emit)
        self.audio_button.clicked.connect(self.audioMenuRequested.emit)
        self.speed_button.clicked.connect(self.speedMenuRequested.emit)
        self.info_button.clicked.connect(self.infoMenuRequested.emit)
        self._apply_opacity_styles()
        self._set_overlay_widgets_visible(True)

    def _setup_aux_button(
        self,
        button: QPushButton,
        tooltip: str,
        icon_path: Path | None = None,
        fallback_text: str = "",
    ) -> None:
        button.setFixedHeight(30)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setToolTip(tooltip)
        button.setStyleSheet("background: transparent; border: none;")
        self._apply_button_icon(button, icon_path, fallback_text)

    def _apply_button_icon(self, button: QPushButton, icon_path: Path | None, fallback_text: str) -> None:
        if icon_path is not None and icon_path.exists():
            icon = self._icon_without_dark_background(icon_path, ACTION_ICON_SIZE)
            if not icon.isNull():
                button.setIcon(icon)
                button.setIconSize(ACTION_ICON_SIZE)
                button.setText("")
                button.setProperty("icon_only", True)
                return
        button.setIcon(QIcon())
        button.setText(fallback_text)
        button.setProperty("icon_only", not bool(button.text().strip()))

    def _icon_without_dark_background(self, icon_path: Path, size: QSize) -> QIcon:
        """
        Drop dark background pixels from icon assets (e.g. black square layer)
        while preserving the visible symbol colors.
        """
        source_icon = QIcon(str(icon_path))
        if source_icon.isNull():
            return QIcon()

        source = source_icon.pixmap(size)
        if source.isNull():
            return QIcon()

        image = source.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        dark_threshold = 40  # treat near-black pixels as background

        for y in range(image.height()):
            for x in range(image.width()):
                pixel = image.pixelColor(x, y)
                if pixel.alpha() == 0:
                    continue
                luminance = (pixel.red() * 299 + pixel.green() * 587 + pixel.blue() * 114) // 1000
                if luminance <= dark_threshold:
                    pixel.setAlpha(0)
                    image.setPixelColor(x, y, pixel)

        cleaned = QPixmap.fromImage(image)
        return QIcon(cleaned)

    def _setup_animation(self) -> None:
        self._fade_anim = QPropertyAnimation(self, b"overlayOpacity", self)
        self._fade_anim.setDuration(220)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_anim.finished.connect(self._on_fade_finished)
        self.overlayOpacity = 1.0

    def _setup_autohide(self) -> None:
        self._autohide_timer = QTimer(self)
        self._autohide_timer.setSingleShot(True)
        self._autohide_timer.setInterval(2000)
        self._autohide_timer.timeout.connect(self._on_autohide_timeout)

    @pyqtProperty(float)
    def overlayOpacity(self) -> float:
        return self._overlay_opacity

    @overlayOpacity.setter
    def overlayOpacity(self, value: float) -> None:
        clamped = min(max(float(value), 0.0), 1.0)
        if abs(clamped - self._overlay_opacity) < 0.002:
            return
        self._overlay_opacity = clamped
        self._apply_opacity_styles()
        # Keep icon/text widgets synchronized with glass block fade-out timing.
        if self._fading_out and self._overlay_opacity <= 0.035 and (not self._is_paused) and (not self._menu_open):
            self._set_overlay_widgets_visible(False)
        elif self._overlay_opacity > 0.035:
            self._set_overlay_widgets_visible(True)
        self.update()

        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            self._overlay_opacity <= 0.01 and (not self._is_paused) and (not self._menu_open),
        )

    def _apply_opacity_styles(self) -> None:
        alpha_key = int(self._overlay_opacity * 1000.0)
        if alpha_key == self._style_alpha_key:
            return
        self._style_alpha_key = alpha_key

        time_alpha = max(int(TIME_LABEL_RGBA[3] * self._overlay_opacity), 0)
        time_style = (
            f"color: rgba({TIME_LABEL_RGBA[0]}, {TIME_LABEL_RGBA[1]}, {TIME_LABEL_RGBA[2]}, {time_alpha});"
            "background: transparent;"
        )
        self.current_time.setStyleSheet(time_style)
        self.total_time.setStyleSheet(time_style)
        self.media_info_label.setStyleSheet(
            f"color: rgba({CREAM_RGB[0]}, {CREAM_RGB[1]}, {CREAM_RGB[2]}, {max(int(215 * self._overlay_opacity), 0)});"
            "background: transparent;"
        )

        self.center_button.set_visual_opacity(self._overlay_opacity)

        action_hover_bg = max(int(26 * self._overlay_opacity), 0)
        action_pressed_bg = max(int(42 * self._overlay_opacity), 0)
        icon_hover_bg = max(int(34 * self._overlay_opacity), 0)
        icon_pressed_bg = max(int(50 * self._overlay_opacity), 0)
        action_text = max(int(220 * self._overlay_opacity), 0)
        action_style = (
            "QPushButton {"
            "background-color: rgba(0, 0, 0, 0);"
            "border: 1px solid rgba(255, 255, 255, 0);"
            "border-radius: 14px;"
            f"color: rgba({CREAM_RGB[0]}, {CREAM_RGB[1]}, {CREAM_RGB[2]}, {action_text});"
            "font-size: 11px;"
            "font-weight: 600;"
            "padding: 0px 10px;"
            "}"
            "QPushButton:hover {"
            f"background-color: rgba({CREAM_RGB[0]}, {CREAM_RGB[1]}, {CREAM_RGB[2]}, {action_hover_bg});"
            "border: 1px solid rgba(255, 255, 255, 0);"
            "}"
            "QPushButton:pressed {"
            f"background-color: rgba({CREAM_RGB[0]}, {CREAM_RGB[1]}, {CREAM_RGB[2]}, {action_pressed_bg});"
            "border: 1px solid rgba(255, 255, 255, 0);"
            "}"
            "QPushButton[icon_only=\"true\"] {"
            "background-color: rgba(0, 0, 0, 0);"
            "padding: 0px;"
            "border-radius: 15px;"
            "}"
            "QPushButton[icon_only=\"true\"]:hover {"
            f"background-color: rgba({CREAM_RGB[0]}, {CREAM_RGB[1]}, {CREAM_RGB[2]}, {icon_hover_bg});"
            "border: 1px solid rgba(255, 255, 255, 0);"
            "}"
            "QPushButton[icon_only=\"true\"]:pressed {"
            f"background-color: rgba({CREAM_RGB[0]}, {CREAM_RGB[1]}, {CREAM_RGB[2]}, {icon_pressed_bg});"
            "border: 1px solid rgba(255, 255, 255, 0);"
            "}"
        )
        for button in self._action_buttons:
            button.setStyleSheet(action_style)

        self.seekbar.set_visual_opacity(self._overlay_opacity)

    def _set_overlay_widgets_visible(self, visible: bool) -> None:
        if self._overlay_widgets_visible == visible:
            return
        self._overlay_widgets_visible = visible
        self.seekbar.setVisible(visible)
        self.current_time.setVisible(visible)
        self.total_time.setVisible(visible)
        self.media_info_label.setVisible(visible)
        for button in self._action_buttons:
            button.setVisible(visible)

    def attach_video(self, video: Any) -> None:
        """Wire overlay/video callbacks with the expected Apple TV+ behavior."""
        if self._bound_video is video:
            return

        if self._bound_video is not None:
            try:
                self._bound_video.positionChanged.disconnect(self.set_position)
            except Exception:
                pass
            try:
                self._bound_video.durationChanged.disconnect(self.set_duration)
            except Exception:
                pass
            try:
                self.playPauseRequested.disconnect(self._bound_video.toggle_pause)
            except Exception:
                pass
            try:
                self.seekRequested.disconnect(self._bound_video.set_position)
            except Exception:
                pass

        self._bound_video = video

        # video.positionChanged -> seekbar progress + left time label.
        video.positionChanged.connect(self.set_position)
        # video.durationChanged -> seekbar max + total duration label.
        video.durationChanged.connect(self.set_duration)
        # playPauseRequested -> video.toggle_pause.
        self.playPauseRequested.connect(video.toggle_pause)
        # seekbar interaction -> video.set_position absolute seek.
        self.seekRequested.connect(video.set_position)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._position_controls()

    def paintEvent(self, event: QPaintEvent) -> None:  # type: ignore[override]
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Clear the translucent overlay surface first.
        # Without this, semi-transparent gradient strokes can accumulate and
        # appear as an overly dark black block near the seekbar.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        # Keep most of frame untouched and fade only near the bottom edge.
        gradient = QLinearGradient(0.0, 0.0, 0.0, float(self.height()))
        fade_scale = self._overlay_opacity
        gradient.setColorAt(0.0, QColor(0, 0, 0, 0))
        gradient.setColorAt(0.80, QColor(0, 0, 0, 0))
        gradient.setColorAt(0.93, QColor(0, 0, 0, max(int(44 * fade_scale), 0)))
        gradient.setColorAt(
            1.0,
            QColor(
                GRADIENT_BOTTOM_RGBA[0],
                GRADIENT_BOTTOM_RGBA[1],
                GRADIENT_BOTTOM_RGBA[2],
                max(int(GRADIENT_BOTTOM_RGBA[3] * fade_scale), 0),
            ),
        )
        painter.fillRect(self.rect(), gradient)

        # Unified glassy control block.
        if self._controls_block_rect.width() > 0.0 and self._controls_block_rect.height() > 0.0:
            block = self._controls_block_rect
            painter.setPen(Qt.PenStyle.NoPen)

            block_gradient = QLinearGradient(0.0, block.top(), 0.0, block.bottom())
            block_gradient.setColorAt(0.0, QColor(138, 138, 138, max(int(70 * fade_scale), 0)))
            block_gradient.setColorAt(0.36, QColor(102, 102, 102, max(int(88 * fade_scale), 0)))
            block_gradient.setColorAt(1.0, QColor(34, 34, 34, max(int(150 * fade_scale), 0)))

            painter.setBrush(block_gradient)
            painter.setPen(QColor(255, 255, 255, max(int(6 * fade_scale), 0)))
            painter.drawRoundedRect(self._controls_block_rect, 28.0, 28.0)

            mist_rect = QRectF(block.left() + 4.0, block.top() + 4.0, block.width() - 8.0, block.height() - 8.0)
            mist_gradient = QLinearGradient(0.0, mist_rect.top(), 0.0, mist_rect.bottom())
            mist_gradient.setColorAt(0.0, QColor(196, 196, 196, max(int(20 * fade_scale), 0)))
            mist_gradient.setColorAt(0.45, QColor(150, 150, 150, max(int(10 * fade_scale), 0)))
            mist_gradient.setColorAt(1.0, QColor(96, 96, 96, max(int(4 * fade_scale), 0)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(mist_gradient)
            painter.drawRoundedRect(mist_rect, 24.0, 24.0)

            gloss_rect = QRectF(block.left() + 1.0, block.top() + 1.0, block.width() - 2.0, block.height() * 0.45)
            gloss_gradient = QLinearGradient(0.0, gloss_rect.top(), 0.0, gloss_rect.bottom())
            gloss_gradient.setColorAt(0.0, QColor(230, 230, 230, max(int(42 * fade_scale), 0)))
            gloss_gradient.setColorAt(0.55, QColor(190, 190, 190, max(int(12 * fade_scale), 0)))
            gloss_gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gloss_gradient)
            painter.drawRoundedRect(gloss_rect, 26.0, 26.0)

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        event_type = event.type()

        if event_type in (
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.Wheel,
            QEvent.Type.Enter,
        ):
            self._wake_controls()

        if watched is self.parent() and event_type == QEvent.Type.KeyPress:
            if isinstance(event, QKeyEvent) and self._handle_shortcut(event):
                return True

        return super().eventFilter(watched, event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        self._wake_controls()
        event.ignore()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        self._wake_controls()
        event.ignore()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        if self._handle_shortcut(event):
            return
        super().keyPressEvent(event)

    def show_controls(self) -> None:
        if self.overlayOpacity >= 0.99 and not self._fading_out:
            self._restart_autohide_timer()
            return

        self._set_overlay_widgets_visible(True)
        self._fading_out = False
        self._fade_anim.stop()
        self.center_button.setVisible(self._is_paused)
        self._fade_anim.setStartValue(self.overlayOpacity)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()
        self._restart_autohide_timer()

    def hide_controls(self) -> None:
        if self._is_paused or self._menu_open:
            return
        self._fading_out = True
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self.overlayOpacity)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()
        self._autohide_timer.stop()

    def set_paused(self, paused: bool) -> None:
        self._is_paused = bool(paused)
        self.center_button.set_paused(self._is_paused)
        if self._is_paused:
            self.center_button.show()
            self.center_button.raise_()
            self.center_button.update()
            self.show_controls()
            self._autohide_timer.stop()
        else:
            self.center_button.hide()
            self._restart_autohide_timer()

    def set_menu_open(self, opened: bool) -> None:
        """Pin controls visible while subtitle/audio/speed/info menu is open."""
        self._menu_open = bool(opened)
        if self._menu_open:
            self.show_controls()
            self._autohide_timer.stop()
        else:
            self._restart_autohide_timer()

    def set_media_info_text(self, text: str) -> None:
        """Update media title/info text shown inside the glass control block."""
        content = str(text).strip()
        self._media_info_text = content if content else "No media loaded"
        self._update_media_info_label()

    def set_speed_text(self, text: str) -> None:
        """Reflect playback speed in the speed action button."""
        value = str(text).strip() or "1x"
        self.speed_button.setText(value)
        self._position_controls()

    def set_position(self, seconds: float) -> None:
        self._position = max(float(seconds), 0.0)
        if self._duration > 0.0:
            self._position = min(self._position, self._duration)
        self.seekbar.set_position(self._position)
        self.current_time.setText(self._format_time(self._position))

    def set_duration(self, seconds: float) -> None:
        self._duration = max(float(seconds), 0.0)
        self.seekbar.set_duration(self._duration)
        self.total_time.setText(self._format_time(self._duration))
        if self._duration > 0.0 and self._position > self._duration:
            self.set_position(self._duration)

    def _position_controls(self) -> None:
        width = self.width()
        height = self.height()
        if width <= 0 or height <= 0:
            return

        block_margin_x = max(int(width * 0.055), 24)
        base_block_width = max(width - (block_margin_x * 2), 360)
        block_width = max(int(base_block_width * 0.75), 320)
        block_height = 122
        block_x = (width - block_width) // 2
        block_y = max(height - block_height - 18, 0)
        self._controls_block_rect = QRectF(float(block_x), float(block_y), float(block_width), float(block_height))

        inner_x = block_x + 18
        inner_right = block_x + block_width - 18
        inner_width = max(inner_right - inner_x, 220)

        action_spacing = 8
        metrics = QFontMetrics(self.subtitle_button.font())
        for button in self._action_buttons:
            if bool(button.property("icon_only")):
                button_width = 36
            else:
                button_width = min(max(metrics.horizontalAdvance(button.text()) + 18, 56), 90)
            button.setFixedWidth(button_width)

        total_actions_width = sum(button.width() for button in self._action_buttons) + (
            action_spacing * (len(self._action_buttons) - 1)
        )
        actions_x = max(inner_right - total_actions_width, inner_x)
        actions_y = block_y + 12
        pos_x = actions_x
        for button in self._action_buttons:
            button.move(pos_x, actions_y)
            pos_x += button.width() + action_spacing

        info_width = max(actions_x - inner_x - 12, 96)
        self.media_info_label.setGeometry(inner_x, block_y + 14, info_width, 24)
        self._update_media_info_label()

        # Keep seekbar lower inside the block so actions stay in the same glass row above it.
        seek_x = inner_x
        seek_width = inner_width
        seek_y = block_y + 72
        self.seekbar.setGeometry(seek_x, seek_y, seek_width, 12)

        label_width = 74
        label_height = 16
        label_y = seek_y + 10
        self.current_time.setGeometry(seek_x, label_y, label_width, label_height)
        self.total_time.setGeometry(seek_x + seek_width - label_width, label_y, label_width, label_height)

        button_x = (width - self.center_button.width()) // 2
        button_y = (height - self.center_button.height()) // 2
        self.center_button.move(button_x, button_y)
        self.center_button.raise_()

    def _update_media_info_label(self) -> None:
        if self.media_info_label.width() <= 0:
            return
        metrics = QFontMetrics(self.media_info_label.font())
        text = metrics.elidedText(self._media_info_text, Qt.TextElideMode.ElideRight, self.media_info_label.width())
        self.media_info_label.setText(text)
        self.media_info_label.setToolTip(self._media_info_text)

    def _on_seekbar_requested(self, seconds: float) -> None:
        self.set_position(seconds)
        self.seekRequested.emit(seconds)
        self._wake_controls()

    def _on_autohide_timeout(self) -> None:
        if self._is_paused or self.seekbar.is_dragging() or self._menu_open:
            return
        self.hide_controls()

    def _on_fade_finished(self) -> None:
        if self._fading_out:
            self.overlayOpacity = 0.0
            self.center_button.setVisible(False)
            self._set_overlay_widgets_visible(False)

    def _restart_autohide_timer(self) -> None:
        if self._is_paused or self._menu_open:
            self._autohide_timer.stop()
            return
        self._autohide_timer.start()

    def _wake_controls(self) -> None:
        self.show_controls()

    def _handle_shortcut(self, event: QKeyEvent) -> bool:
        key = event.key()
        if key == Qt.Key.Key_Space:
            self.playPauseRequested.emit()
            self._wake_controls()
            event.accept()
            return True
        if key == Qt.Key.Key_Left:
            self._seek_by(-5.0)
            event.accept()
            return True
        if key == Qt.Key.Key_Right:
            self._seek_by(5.0)
            event.accept()
            return True
        return False

    def _seek_by(self, seconds_delta: float) -> None:
        target = max(self._position + float(seconds_delta), 0.0)
        if self._duration > 0.0:
            target = min(target, self._duration)
        self.seekRequested.emit(target)
        self.set_position(target)
        self._wake_controls()

    @staticmethod
    def _format_time(seconds: float) -> str:
        total = max(int(seconds), 0)
        hours = total // 3600
        minutes = (total % 3600) // 60
        secs = total % 60
        if hours > 0:
            return f"{hours}:{minutes:02}:{secs:02}"
        return f"{minutes:02}:{secs:02}"
