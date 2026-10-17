"""
A class representing a GUI widget for a square on the board.

Squares can display a piece and have a base colour.
Squares are also clickable, and can be used to move pieces on the board.
Squares can also be highlighted to show possible moves, glow on mouse hover, etc.
Squares have a minimum size, and can be resized to fit the board.
"""

from utils.constants import *
import utils.colours
from PySide6.QtWidgets import QPushButton, QSizePolicy
from PySide6.QtCore import Signal, QSize
import PySide6
from typing import Tuple

import utils.square

# How much of the square's own size the piece icon fills, leaving a small margin
# around the edge rather than touching the border exactly.
ICON_SIZE_FRACTION = 0.85


class Square(QPushButton):

    color_hover = (50, 50, 0, 0.5)
    color_selected = (100, 100, 0, 0.5)

    square_clicked = Signal(int, int)

    def __init__(self, x: int, y: int, parent=None) -> None:
        super(Square, self).__init__(parent)
        self.x = x
        self.y = y
        self.setMinimumSize(20, 20)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._color = (0, 0, 0)
        self._highlight = (0, 0, 0, 0)

        self.clicked.connect(self.button_clicked)
        self.clicked.connect(lambda: self.square_clicked.emit(self.x, self.y))

    def resizeEvent(self, event) -> None:
        """Keeps the piece icon scaled proportionally to the square as it resizes."""
        super().resizeEvent(event)
        side = int(min(self.width(), self.height()) * ICON_SIZE_FRACTION)
        self.setIconSize(QSize(side, side))

    def set_color(self, color: Tuple[int, int, int]) -> None:
        """Sets the colour of the square."""
        self.setStyleSheet(f"background-color: {utils.colours.rgb_to_hex(self.highlighted_color(color))}; border: none;")

    def highlighted_color(self, color: Tuple[int, int, int]) -> Tuple[int, int, int]:
        """Returns the highlighted colour of the square."""
        if self.highlight[3] == 0:
            return color
        else:
            return(
                round(self.color[0]*(1-self.highlight[3]) + self.highlight[0]*self.highlight[3]),
                round(self.color[1]*(1-self.highlight[3]) + self.highlight[1]*self.highlight[3]),
                round(self.color[2]*(1-self.highlight[3]) + self.highlight[2]*self.highlight[3])
            )
    
    @property
    def color(self) -> Tuple[int, int, int]:
        return self._color
    
    @color.setter
    def color(self, value: Tuple[int, int, int]) -> None:
        self._color = value
        self.set_color(value)

    @property
    def highlight(self) -> Tuple[int, int, int, float]:
        return self._highlight
    
    @highlight.setter
    def highlight(self, value: Tuple[int, int, int, float]) -> None:
        self._highlight = value
        self.set_color(self.color)

    def hover_enter(self) -> None:
        """Changes the colour of the square on hover."""
        self.highlight = self.color_hover

    def hover_leave(self) -> None:
        """Resets the colour of the square on hover leave."""
        self.highlight = (0, 0, 0, 0)

    def select(self) -> None:
        """Changes the colour of the square on selection."""
        self.highlight = self.color_selected

    def deselect(self) -> None:
        """Resets the colour of the square on deselection."""
        self.highlight = (0, 0, 0, 0)

    def button_clicked(self) -> None:
        """Handles the button click event."""
        print(f"Square {self.x},{self.y} clicked.")
