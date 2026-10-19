"""Named board colour themes: each maps to a (light_square, dark_square) RGB pair."""

from typing import Dict, Tuple

Theme = Tuple[Tuple[int, int, int], Tuple[int, int, int]]

BOARD_THEMES: Dict[str, Theme] = {
    "Classic Gray": ((224, 224, 224), (158, 158, 158)),
    "Lichess Green": ((238, 238, 210), (118, 150, 86)),
    "Chess.com Brown": ((240, 217, 181), (181, 136, 99)),
    "Lichess Blue": ((222, 227, 230), (140, 162, 173)),
    "Walnut": ((222, 184, 135), (139, 90, 43)),
    "Purple": ((230, 220, 240), (149, 112, 173)),
}

DEFAULT_BOARD_THEME = "Classic Gray"

BOARD_THEME_NAMES = list(BOARD_THEMES.keys())
