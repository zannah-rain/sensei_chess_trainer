import chess
import chess.svg

# A board object
board = chess.Board()

# A move object
chess.Move.from_uci("a2a4")

chess.svg.piece(chess.Piece.from_symbol("R"))