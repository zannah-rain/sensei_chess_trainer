import itertools

import chess
import pytest

from gui.board import Board
from utils.square import Square


def test_unflipped_unmirrored_board_maps_xy_origin_to_a1(qapp):
    # Given a freshly created board (White's perspective, not mirrored - the defaults)
    board = Board()

    # When converting the bottom-left grid cell to a square
    square = board.xy_to_square(x=0, y=0)

    # Then it's a1
    assert square == Square(square_id=chess.A1)


def test_flipping_the_perspective_twice_returns_the_original_square(qapp):
    # Given a board showing White's perspective
    board = Board()
    original_square = board.xy_to_square(x=3, y=6)

    # When flipping the perspective twice
    board.perspective = chess.BLACK
    board.perspective = chess.WHITE

    # Then the same grid cell maps back to the original square
    assert board.xy_to_square(x=3, y=6) == original_square


def test_mirroring_changes_file_but_never_rank(qapp):
    # Given a board at a known grid cell, unmirrored
    board = Board()
    unmirrored_square = board.xy_to_square(x=2, y=5)

    # When mirroring the board
    board.mirrored = True
    mirrored_square = board.xy_to_square(x=2, y=5)

    # Then only the file changed - the rank (and thus which row it's displayed in)
    # is unaffected by mirroring
    assert mirrored_square.rank_id == unmirrored_square.rank_id
    assert mirrored_square.file_id != unmirrored_square.file_id


@pytest.mark.parametrize("x,y", list(itertools.product(range(8), range(8))))
def test_square_to_xy_is_the_inverse_of_xy_to_square(qapp, x, y):
    # Given a board with a non-default perspective and mirroring, so the inverse
    # relationship is actually exercised rather than trivially true
    board = Board()
    board.perspective = chess.BLACK
    board.mirrored = True

    # When converting a grid cell to a square and back
    square = board.xy_to_square(x=x, y=y)
    round_tripped_x, round_tripped_y = board.square_to_xy(square)

    # Then it returns the same grid cell it started from
    assert (round_tripped_x, round_tripped_y) == (x, y)
