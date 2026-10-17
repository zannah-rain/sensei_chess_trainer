import chess

from utils.square import Square


def test_square_from_rank_and_file_matches_square_from_square_id():
    # Given a1, built two different ways
    from_square_id = Square(square_id=chess.A1)
    from_rank_file = Square(rank_id=0, file_id=0)

    # When comparing them
    # Then they're the same square
    assert from_square_id == from_rank_file


def test_square_file_and_rank_round_trip_through_tuple():
    # Given e4
    square = Square(square_id=chess.E4)

    # When reading its rank/file and its tuple form
    # Then they agree with each other and with python-chess's own notion of e4
    assert square.file == "e"
    assert square.rank == 4
    assert square.tuple == (square.rank_id, square.file_id)
    assert square.rank_id == chess.square_rank(chess.E4)
    assert square.file_id == chess.square_file(chess.E4)


def test_corner_square_is_on_edge_not_in_center():
    # Given a1, a board corner
    square = Square(square_id=chess.A1)

    # When checking its position
    # Then it's on the edge and not in the center
    assert square.on_edge is True
    assert square.in_center is False


def test_center_square_is_in_center_not_on_edge():
    # Given e4, one of the four center squares
    square = Square(square_id=chess.E4)

    # When checking its position
    # Then it's in the center and not on the edge
    assert square.in_center is True
    assert square.on_edge is False


def test_move_to_builds_a_move_between_the_two_squares():
    # Given a starting square and a destination square
    from_square = Square(square_id=chess.E2)
    to_square = Square(square_id=chess.E4)

    # When building a move between them
    move = from_square.move_to(to_square)

    # Then it's the move python-chess would also produce
    assert move == chess.Move.from_uci("e2e4")
