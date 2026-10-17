"""A small semicircular "speed dial" gauge widget, used in place of plain
"Average eval loss: n" text - green zone near zero (good), red zone at/above
max_value (bad), with a needle that animates to its new position rather than
jumping, consistent with the rest of the app's animated-feedback style."""

import math

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, Property
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

GOOD_COLOR = QColor("#4caf7d")
WARN_COLOR = QColor("#ffc107")
BAD_COLOR = QColor("#e55353")
NEEDLE_COLOR = QColor("#e8eaed")
TITLE_COLOR = QColor("#9aa4b2")


class SpeedDialGauge(QWidget):
    def __init__(self, title: str, max_value: float = 1.0, parent=None) -> None:
        super().__init__(parent)
        self._title = title
        self._max_value = max_value
        self._value = 0.0
        self._animation: QPropertyAnimation = None
        self.setMinimumWidth(120)
        self.setFixedHeight(130)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def getValue(self) -> float:
        return self._value

    def setValue(self, value: float) -> None:
        self._value = max(0.0, value)
        self.update()

    value = Property(float, getValue, setValue)

    def animate_to(self, value: float) -> None:
        """Smoothly moves the needle to its new value instead of snapping."""
        animation = QPropertyAnimation(self, b"value", self)
        animation.setDuration(500)
        animation.setStartValue(self._value)
        animation.setEndValue(max(0.0, value))
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.start()
        self._animation = animation  # keep a reference so it isn't GC'd mid-animation

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        width, height = self.width(), self.height()
        top_margin = 8
        text_space = 46  # fixed pixel room below the arc's equator for the value + title lines
        diameter = max(20, min(width - 16, 2 * (height - top_margin - text_space)))
        rect = QRectF((width - diameter) / 2, top_margin, diameter, diameter)
        pen_width = max(5, diameter // 11)

        # Background zones, swept clockwise (negative span, Qt's convention)
        # from 9 o'clock (180deg, value=0, good) through 12 o'clock down to
        # 3 o'clock (0deg, value=max, bad).
        for color, start_angle in ((GOOD_COLOR, 180), (WARN_COLOR, 120), (BAD_COLOR, 60)):
            painter.setPen(QPen(color, pen_width, Qt.SolidLine, Qt.FlatCap))
            painter.drawArc(rect, start_angle * 16, -60 * 16)

        # Needle
        fraction = min(1.0, self._value / self._max_value) if self._max_value else 0.0
        angle_rad = math.radians(180 - fraction * 180)
        center = rect.center()
        needle_length = diameter / 2 - pen_width
        tip = QPointF(center.x() + needle_length * math.cos(angle_rad),
                       center.y() - needle_length * math.sin(angle_rad))
        painter.setPen(QPen(NEEDLE_COLOR, 3))
        painter.drawLine(center, tip)
        painter.setBrush(NEEDLE_COLOR)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(center, 4, 4)

        # Value + title - fixed pixel offsets from the arc's equator (not
        # diameter-relative), so the text layout stays correct regardless of
        # how wide/narrow the gauge ends up being in its layout.
        equator_y = rect.center().y()
        painter.setPen(NEEDLE_COLOR)
        font = painter.font()
        font.setBold(True)
        font.setPointSize(max(9, diameter // 10))
        painter.setFont(font)
        value_rect = QRectF(0, equator_y + 2, width, 22)
        painter.drawText(value_rect, Qt.AlignHCenter | Qt.AlignTop, f"{self._value:.3f}")

        painter.setPen(TITLE_COLOR)
        font.setBold(False)
        font.setPointSize(max(8, diameter // 15))
        painter.setFont(font)
        title_rect = QRectF(0, equator_y + 24, width, 18)
        painter.drawText(title_rect, Qt.AlignHCenter | Qt.AlignTop, self._title)
