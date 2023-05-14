"""
Utilities for working with what I currently consider a 'position'.
That is, FEN minus the move counts.
"""

import chess.pgn


def fen_to_position(fen: str) -> str:
    """
    Strips out bits of the FEN that aren't usually relevant for analysis.
    
    - IE no full / halfmove count
    """
    return " ".join(fen.split(" ")[:-2])


def position_to_fen(position: str) -> str:
    return f"{position} 0 0"


def gamenode_position(game_node: chess.pgn.GameNode) -> str:
    return fen_to_position(game_node.board().fen())