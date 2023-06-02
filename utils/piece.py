import chess


basic_values = {
        chess.PAWN: 1,
        chess.KNIGHT: 3,
        chess.BISHOP: 3,
        chess.ROOK: 5,
        chess.QUEEN: 9,
        chess.KING: 0
    }


def basic_piece_value(piece_type: int) -> int:
    """The traditional point value of this piece."""
    if piece_type is None:
        return None
    return basic_values[piece_type]

