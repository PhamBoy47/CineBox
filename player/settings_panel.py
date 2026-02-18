"""Reusable Apple TV-style floating settings panels for CineBox."""

from __future__ import annotations

from typing import Sequence
from PyQt6.QtWidgets import QStyle
from PyQt6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QRect,
    QSize,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QKeyEvent, QMouseEvent, QPainter
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)


class _OptionRowDelegate(QStyledItemDelegate):
    """Paint minimal Apple TV-style rows with highlight and checkmark."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index,
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        row_rect = option.rect.adjusted(6, 3, -6, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        # Keep rows clean and borderless; selection is conveyed by text/checkmark.

        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        text_font = QFont("Segoe UI Variable", 12)
        text_font.setWeight(QFont.Weight.Medium if not selected else QFont.Weight.DemiBold)
        painter.setFont(text_font)
        painter.setPen(QColor(255, 255, 255, 228) if selected else QColor(255, 255, 255, 178))
        painter.drawText(
            row_rect.adjusted(14, 0, -32, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            text,
        )

        if selected:
            check_font = QFont("Segoe UI Variable", 11)
            check_font.setWeight(QFont.Weight.Bold)
            painter.setFont(check_font)
            painter.setPen(QColor(255, 255, 255, 196))
            painter.drawText(
                row_rect.adjusted(0, 0, -12, 0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                "✓",
            )

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        """Keep row height comfortable for mouse + keyboard navigation."""
        _ = option, index
        return QSize(0, 42)


class _OptionList(QListWidget):
    """List widget with keyboard activation and clean default styling."""

    optionActivated = pyqtSignal(int, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setItemDelegate(_OptionRowDelegate(self))
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setUniformItemSizes(True)
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(
            """
            QListWidget {
                background: transparent;
                border: none;
                outline: none;
                padding: 0px;
            }
            QListWidget::item {
                border: none;
                margin: 0px;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 2px 0 2px 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 80);
                min-height: 28px;
                border-radius: 4px;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
                border: none;
                height: 0px;
            }
            """
        )
        self.itemActivated.connect(self._emit_current)
        self.itemClicked.connect(self._emit_current)

    def set_options(self, options: Sequence[str], selected_index: int = 0) -> None:
        """Populate options and select requested row."""
        self.clear()
        for option in options:
            self.addItem(QListWidgetItem(str(option)))
        if self.count() > 0:
            safe_index = min(max(selected_index, 0), self.count() - 1)
            self.setCurrentRow(safe_index)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        """Support Enter/Space activation in addition to arrow navigation."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._emit_current()
            event.accept()
            return
        super().keyPressEvent(event)

    def _emit_current(self, *_args) -> None:
        """Emit currently selected option."""
        row = self.currentRow()
        if row < 0:
            return
        item = self.item(row)
        if item is None:
            return
        self.optionActivated.emit(row, item.text())


class GlassPanel(QWidget):
    """Base floating panel with lightweight slide animation (effect-free)."""

    closed = pyqtSignal()

    def __init__(
        self,
        parent: QWidget,
        panel_width: int = 356,
        panel_height: int = 300,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Popup
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self._corner_radius = 24
        self._edge_margin = 24
        self._overlay_scale = 1.0
        self._anchor_widget: QWidget | None = None

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedWidth(panel_width)
        self.setFixedHeight(panel_height)
        self.setStyleSheet("background: transparent;")

        # Single lightweight surface avoids heavy graphics effects that can
        # conflict with native video rendering and spam QPainter warnings.
        self._surface = QFrame(self)
        self._surface.setStyleSheet(
            f"background-color: rgba(8, 8, 8, 198);"
            "border: none;"
            f"border-radius: {self._corner_radius}px;"
        )

        self.content_layout = QVBoxLayout(self._surface)
        self.content_layout.setContentsMargins(22, 20, 22, 20)
        self.content_layout.setSpacing(10)

        self.hide()

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        parent.installEventFilter(self)
        self.installEventFilter(self)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        """Keep visual layers aligned to panel geometry."""
        super().resizeEvent(event)
        self._surface.setGeometry(self.rect())

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Close on outside click and stay docked on parent resize."""
        if watched is self.parentWidget() and event.type() in (QEvent.Type.Resize, QEvent.Type.Move):
            if self.isVisible():
                self.move(self._anchor_position())

        if not self.isVisible():
            return super().eventFilter(watched, event)

        if event.type() == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            global_pos = event.globalPosition().toPoint()
            if not self.rect().contains(self.mapFromGlobal(global_pos)):
                self.hide_panel()
        elif event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if event.key() == Qt.Key.Key_Escape:
                self.hide_panel()
                return True
        elif watched is self and event.type() == QEvent.Type.WindowDeactivate:
            self.hide_panel()

        return super().eventFilter(watched, event)

    def show_panel(self, anchor_widget: QWidget | None = None) -> None:
        """Show panel anchored to a control, with fallback to right-side docking."""
        self._anchor_widget = anchor_widget
        self.move(self._anchor_position())
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.PopupFocusReason)

    def hide_panel(self) -> None:
        """Hide panel immediately."""
        if not self.isVisible():
            return
        self.hide()

    def hideEvent(self, event) -> None:  # type: ignore[override]
        super().hideEvent(event)
        self.closed.emit()

    def _anchor_position(self) -> QPoint:
        """Return anchored panel position constrained to parent bounds."""
        parent = self.parentWidget()
        if parent is None:
            return self.pos()
        parent_top_left = parent.mapToGlobal(QPoint(0, 0))
        parent_rect = QRect(parent_top_left, parent.size())

        if self._anchor_widget is not None and self._anchor_widget.isVisible():
            anchor_top_left = self._anchor_widget.mapToGlobal(QPoint(0, 0))
            anchor_center_x = anchor_top_left.x() + (self._anchor_widget.width() // 2)
            x = anchor_center_x - (self.width() // 2)
            y = anchor_top_left.y() - self.height() - 12

            min_x = parent_rect.left() + self._edge_margin
            max_x = parent_rect.right() - self.width() - self._edge_margin
            x = min(max(x, min_x), max_x)

            if y < parent_rect.top() + self._edge_margin:
                y = anchor_top_left.y() + self._anchor_widget.height() + 12
            max_y = parent_rect.bottom() - self.height() - self._edge_margin
            y = min(max(y, parent_rect.top() + self._edge_margin), max_y)
            return QPoint(x, y)

        x = parent_top_left.x() + parent.width() - self.width() - self._edge_margin
        y = parent_top_left.y() + max(self._edge_margin, (parent.height() - self.height()) // 2)
        return QPoint(x, y)

    @pyqtProperty(float)
    def overlayScale(self) -> float:
        """Reserved scale property for optional external animation control."""
        return self._overlay_scale

    @overlayScale.setter
    def overlayScale(self, value: float) -> None:
        self._overlay_scale = max(0.8, min(float(value), 1.2))


class _OptionPanel(GlassPanel):
    """Shared option panel structure: title + selectable list."""

    selectionChanged = pyqtSignal(int, str)

    def __init__(
        self,
        parent: QWidget,
        title: str,
        options: Sequence[str],
        selected_index: int = 0,
    ) -> None:
        panel_height = max(240, min(520, 92 + (len(options) * 44)))
        super().__init__(parent, panel_width=340, panel_height=panel_height)

        self.title_label = QLabel(title, self._surface)
        self.title_label.setStyleSheet("color: rgba(255, 255, 255, 192); background: transparent;")
        title_font = QFont("Segoe UI", 9)
        title_font.setWeight(QFont.Weight.DemiBold)
        title_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 125.0)
        self.title_label.setFont(title_font)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.option_list = _OptionList(self._surface)
        self.option_list.set_options(options, selected_index)
        self.option_list.optionActivated.connect(self._emit_selection)

        self.content_layout.addWidget(self.title_label)
        self.content_layout.addWidget(self.option_list, 1)

        if self.option_list.count() > 0:
            self.option_list.setCurrentRow(min(max(selected_index, 0), self.option_list.count() - 1))

    def set_options(self, options: Sequence[str], selected_index: int = 0) -> None:
        """Replace list options at runtime."""
        self.option_list.set_options(options, selected_index)

    def set_selected_index(self, index: int) -> None:
        """Programmatically select an option row."""
        if self.option_list.count() == 0:
            return
        safe = min(max(index, 0), self.option_list.count() - 1)
        self.option_list.setCurrentRow(safe)

    def selected_index(self) -> int:
        """Return currently selected row index."""
        return self.option_list.currentRow()

    def selected_text(self) -> str:
        """Return currently selected option text."""
        item = self.option_list.currentItem()
        return item.text() if item is not None else ""

    def _emit_selection(self, *_args) -> None:
        """Emit unified selection signal for mouse + keyboard actions."""
        row = self.option_list.currentRow()
        if row < 0:
            return
        item = self.option_list.item(row)
        if item is None:
            return
        self.selectionChanged.emit(row, item.text())


class SubtitlePanel(_OptionPanel):
    """Subtitle selection panel."""

    def __init__(
        self,
        parent: QWidget,
        options: Sequence[str] | None = None,
        selected_index: int = 0,
    ) -> None:
        super().__init__(
            parent=parent,
            title="SUBTITLES",
            options=options or ("Off", "English", "Spanish", "French"),
            selected_index=selected_index,
        )


class AudioPanel(_OptionPanel):
    """Audio track selection panel."""

    def __init__(
        self,
        parent: QWidget,
        options: Sequence[str] | None = None,
        selected_index: int = 0,
    ) -> None:
        super().__init__(
            parent=parent,
            title="AUDIO",
            options=options or ("English 5.1", "Hindi 5.1", "Japanese Stereo"),
            selected_index=selected_index,
        )


class SpeedPanel(_OptionPanel):
    """Playback speed selection panel."""

    def __init__(self, parent: QWidget, selected_index: int = 1) -> None:
        super().__init__(
            parent=parent,
            title="PLAYBACK SPEED",
            options=("0.5x", "1x", "1.25x", "1.5x", "2x"),
            selected_index=selected_index,
        )


class InfoPanel(GlassPanel):
    """Read-only media info panel."""

    def __init__(self, parent: QWidget, rows: Sequence[str] | None = None) -> None:
        super().__init__(parent, panel_width=430, panel_height=290)

        self.title_label = QLabel("MEDIA INFO", self._surface)
        self.title_label.setStyleSheet("color: rgba(255, 255, 255, 192); background: transparent;")
        title_font = QFont("Segoe UI", 9)
        title_font.setWeight(QFont.Weight.DemiBold)
        title_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 125.0)
        self.title_label.setFont(title_font)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.info_label = QLabel(self._surface)
        self.info_label.setWordWrap(True)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.info_label.setStyleSheet("color: rgba(255, 255, 255, 210); background: transparent;")
        body_font = QFont("Segoe UI", 10)
        body_font.setWeight(QFont.Weight.Medium)
        self.info_label.setFont(body_font)

        self.content_layout.addWidget(self.title_label)
        self.content_layout.addWidget(self.info_label, 1)
        self.set_info_rows(rows or ("No media loaded",))

    def set_info_rows(self, rows: Sequence[str]) -> None:
        lines = [str(line).strip() for line in rows if str(line).strip()]
        self.info_label.setText("\n".join(lines) if lines else "No media loaded")
