import chess
from utils.square import Square
from typing import List

class Move:
    """
    A single object representing a specific move being made in a specific position.
    Basically an interface to python.chess that makes this sort of data easier to get, and easier to understand.
    """

    @property
    def turn(self) -> int:
        """chess.WHITE or BLACK depending on who's making the move"""
        return self._turn
    
    @property
    def opposing_player(self) -> int:
        """chess.WHITE or BLACK of the OPPOSING player"""
        return 1 - self.turn
    
    @property
    def from_file(self) -> int:
        return chess.square_file(self._from_square)
    
    @property
    def from_rank(self) -> int:
        return chess.square_rank(self._from_square)
    
    @property
    def to_file(self) -> int:
        return chess.square_file(self.to_square)
    
    @property
    def to_rank(self) -> int:
        return chess.square_rank(self.to_square)
    
    @property
    def source_overall_centrality(self) -> int:
        return Square(self.from_square).overall_centrality
    
    @property
    def source_on_edge(self) -> int:
        return Square(self.from_square).on_edge
    
    @property
    def source_file_centrality(self) -> int:
        return Square(self.from_square).file_centrality
    
    @property
    def source_rank_centrality(self) -> int:
        return Square(self.from_square).rank_centrality
    
    @property
    def destination_overall_centrality(self) -> int:
        return Square(self.to_square).overall_centrality
    
    @property
    def destination_on_edge(self) -> int:
        return Square(self.to_square).on_edge
    
    @property
    def destination_file_centrality(self) -> int:
        return Square(self.to_square).file_centrality
    
    @property
    def destination_rank_centrality(self) -> int:
        return Square(self.to_square).rank_centrality

    @property
    def source_activity(self) -> int:
        """How many squares the piece being moved was attacking originally"""
        return len(self.board.attacks(self.from_square))
    
    @property
    def destination_activity(self) -> int:
        """How many squares the piece being moved is attacking now"""
        return len(self.resulting_board.attacks(self.to_square))
    
    @property
    def activity_delta(self) -> int:
        return self.destination_activity - self.source_activity
    
    @property
    def distance_moved(self) -> int:
        return chess.square_distance(self.from_square, self.to_square)
    
    @property
    def source_distance_from_enemy_king(self) -> int:
        return chess.square_distance(self.from_square, [i for i in self.board.pieces(chess.KING, self.opposing_player)][0])
    
    @property
    def destination_distance_from_enemy_king(self) -> int:
        return chess.square_distance(self.to_square, [i for i in self.board.pieces(chess.KING, self.opposing_player)][0])
    
    @property
    def enemy_king_distance_delta(self) -> int:
        return self.destination_distance_from_enemy_king - self.source_distance_from_enemy_king
    
    @property
    def source_distance_from_friendly_king(self) -> int:
        return chess.square_distance(self.from_square, [i for i in self.board.pieces(chess.KING, self.turn)][0])
    
    @property
    def destination_distance_from_friendly_king(self) -> int:
        return chess.square_distance(self.to_square, [i for i in self.board.pieces(chess.KING, self.turn)][0])
    
    @property
    def friendly_king_distance_delta(self) -> int:
        return self.destination_distance_from_friendly_king - self.source_distance_from_friendly_king

    @property
    def source_in_center(self) -> bool:
        return Square(self.from_square).in_center
    
    @property
    def destination_in_center(self) -> bool:
        return Square(self.to_square).in_center
    
    @property
    def source_rank_aggression(self) -> int:
        """0-8, 8 being deep in enemy territory"""
        if self.turn == chess.WHITE:
            return self.from_rank
        else:
            return 8 - self.from_rank
    
    @property
    def destination_rank_aggression(self) -> int:
        """0-8, 8 being deep in enemy territory"""
        if self.turn == chess.WHITE:
            return self.to_rank
        else:
            return 8 - self.to_rank

    def rank_aggression_delta(self) -> int:
        return self.destination_rank_aggression - self.source_rank_aggression
    
    def source_pieces_attacked(self) -> int:
        raise NotImplementedError()
    
    def source_pieces_defended(self) -> int:
        raise NotImplementedError()
    
    def source_pieces_attacked_value(self) -> int:
        raise NotImplementedError()
    
    def source_pieces_defended_value(self) -> int:
        raise NotImplementedError()
    
    def destination_pieces_attacked(self) -> int:
        raise NotImplementedError()
    
    def destination_pieces_defended(self) -> int:
        raise NotImplementedError()
    
    def destination_pieces_attacked_value(self) -> int:
        raise NotImplementedError()
    
    def destination_pieces_defended_value(self) -> int:
        raise NotImplementedError()
    
    def destination_cheapest_enemy_attacker(self) -> int:
        raise NotImplementedError()
    
    def source_cheapest_ally_defended(self) -> int:
        raise NotImplementedError()
    
    @property
    def resulting_board(self) -> chess.Board:
        if self._resulting_board is None:
            self._resulting_board = self.board.copy()
            self._resulting_board.push(self.move)
        return self._resulting_board.copy()
    
    @property
    def from_square(self) -> chess.Square:
        return self.move.from_square
    
    @property
    def to_square(self) -> chess.Square:
        return self.move.to_square
    
    @property
    def capture_square(self) -> chess.Square:
        """to_square except en-passant is where the enemy pawn is"""
        if self._capture_square is None:
            self._capture_square = self.to_square
            if self.is_en_passant:
                s = Square(self._capture_square)
                rank = s.rank
                if rank == 2:
                    self._capture_square = self._capture_square + 8
                elif rank == 7:
                    self._capture_square = self._capture_square - 8
                else:
                    raise ValueError()
        return self._capture_square
    
    @property
    def is_capture(self) -> bool:
        """board.is_capture"""
        return self.board.is_capture(self.move)
    
    @property
    def is_castling(self) -> bool:
        """board.is_castling"""
        return self.board.is_castling(self.move)
    
    @property
    def is_en_passant(self) -> bool:
        """board.is_en_passant"""
        return self.board.is_en_passant(self.move)
    
    @property
    def is_irreversible(self) -> bool:
        """board.is_irreversible"""
        return self.board.is_irreversible(self.move)

    @property
    def is_queenside_castling(self) -> bool:
        """board.is_queenside_castling"""
        return self.board.is_queenside_castling(self.move)
    
    @property
    def is_kingside_castling(self) -> bool:
        """board.is_kingside_castling"""
        return self.board.is_kingside_castling(self.move)
    
    @property
    def is_legal(self) -> bool:
        """board.is_legal"""
        return self.board.is_legal(self.move)
    
    @property
    def is_zeroing(self) -> bool:
        """board.is_zeroing"""
        return self.board.is_zeroing(self.move)
    
    @property
    def piece(self) -> chess.Piece:
        """board.piece_at"""
        return self.board.piece_at(self.from_square)
    
    @property
    def piece_taking(self) -> chess.Piece:
        return self.board.piece_at(self.capture_square)
    
    @property
    def _allied_destination_attackers(self) -> List[chess.Piece]:
        return [self.resulting_board.piece_at(square_with_piece) for square_with_piece in self.resulting_board.attackers(self.turn, self.to_square)]
    @property
    def _enemy_destination_attackers(self) -> List[chess.Piece]:
        return [self.resulting_board.piece_at(square_with_piece) for square_with_piece in self.resulting_board.attackers(self.opposing_player, self.to_square)]
    @property
    def _allied_source_attackers(self) -> List[chess.Piece]:
        return [self.board.piece_at(square_with_piece) for square_with_piece in self.resulting_board.attackers(self.turn, self.from_square)]
    @property
    def _enemy_source_attackers(self) -> List[chess.Piece]:
        return [self.board.piece_at(square_with_piece) for square_with_piece in self.resulting_board.attackers(self.opposing_player, self.from_square)]
    
    @property
    def n_allied_destination_supporters(self) -> int:
        """The number of allied pieces which are also attacking the square we're moving to"""
        return len(self._allied_destination_attackers)
    
    @property
    def n_allied_pawn_destination_supporters(self) -> int:
        """The number of allied pawns which are also attacking the square we're moving to"""
        return len([1 for i in self._allied_destination_attackers if i.piece_type == chess.PAWN])
    
    @property
    def n_allied_knight_destination_supporters(self) -> int:
        """The number of allied knights which are also attacking the square we're moving to"""
        return len([1 for i in self._allied_destination_attackers if i.piece_type == chess.KNIGHT])
    
    @property
    def n_allied_bishop_destination_supporters(self) -> int:
        """The number of allied bishops which are also attacking the square we're moving to"""
        return len([1 for i in self._allied_destination_attackers if i.piece_type == chess.BISHOP])
    
    @property
    def n_allied_rook_destination_supporters(self) -> int:
        """The number of allied rooks which are also attacking the square we're moving to"""
        return len([1 for i in self._allied_destination_attackers if i.piece_type == chess.ROOK])
    
    @property
    def n_allied_queen_destination_supporters(self) -> int:
        """The number of allied queens which are also attacking the square we're moving to"""
        return len([1 for i in self._allied_destination_attackers if i.piece_type == chess.QUEEN])
    
    @property
    def n_allied_king_destination_supporters(self) -> int:
        """The number of allied kings which are also attacking the square we're moving to"""
        return len([1 for i in self._allied_destination_attackers if i.piece_type == chess.KING])

    @property
    def n_enemy_destination_attackers(self) -> int:
        """The number of enemy pieces which are attacking the square we're moving to"""
        return len(self._enemy_destination_attackers)
    
    @property
    def n_enemy_pawn_destination_attackers(self) -> int:
        """The number of enemy pawns which are also attacking the square we're moving to"""
        return len([1 for i in self._enemy_destination_attackers if i.piece_type == chess.PAWN])
    
    @property
    def n_enemy_knight_destination_attackers(self) -> int:
        """The number of enemy knights which are also attacking the square we're moving to"""
        return len([1 for i in self._enemy_destination_attackers if i.piece_type == chess.KNIGHT])
    
    @property
    def n_enemy_bishop_destination_attackers(self) -> int:
        """The number of enemy bishops which are also attacking the square we're moving to"""
        return len([1 for i in self._enemy_destination_attackers if i.piece_type == chess.BISHOP])
    
    @property
    def n_enemy_rook_destination_attackers(self) -> int:
        """The number of enemy rooks which are also attacking the square we're moving to"""
        return len([1 for i in self._enemy_destination_attackers if i.piece_type == chess.ROOK])
    
    @property
    def n_enemy_queen_destination_attackers(self) -> int:
        """The number of enemy queens which are also attacking the square we're moving to"""
        return len([1 for i in self._enemy_destination_attackers if i.piece_type == chess.QUEEN])
    
    @property
    def n_enemy_king_destination_attackers(self) -> int:
        """The number of enemy kings which are also attacking the square we're moving to"""
        return len([1 for i in self._enemy_destination_attackers if i.piece_type == chess.KING])
    
    @property
    def n_allied_source_supporters(self) -> int:
        """The number of allied pieces which are defending the square we moved from"""
        return len(self._allied_source_attackers)
    
    @property
    def n_allied_pawn_source_supporters(self) -> int:
        """The number of allied pawns which are also attacking the square we're moving from"""
        return len([1 for i in self._allied_source_attackers if i.piece_type == chess.PAWN])
    
    @property
    def n_allied_knight_source_supporters(self) -> int:
        """The number of allied knights which are also attacking the square we're moving from"""
        return len([1 for i in self._allied_source_attackers if i.piece_type == chess.KNIGHT])
    
    @property
    def n_allied_bishop_source_supporters(self) -> int:
        """The number of allied bishops which are also attacking the square we're moving from"""
        return len([1 for i in self._allied_source_attackers if i.piece_type == chess.BISHOP])
    
    @property
    def n_allied_rook_source_supporters(self) -> int:
        """The number of allied rooks which are also attacking the square we're moving from"""
        return len([1 for i in self._allied_source_attackers if i.piece_type == chess.ROOK])
    
    @property
    def n_allied_queen_source_supporters(self) -> int:
        """The number of allied queens which are also attacking the square we're moving from"""
        return len([1 for i in self._allied_source_attackers if i.piece_type == chess.QUEEN])
    
    @property
    def n_allied_king_source_supporters(self) -> int:
        """The number of allied kings which are also attacking the square we're moving from"""
        return len([1 for i in self._allied_source_attackers if i.piece_type == chess.KING])
    
    @property
    def n_enemy_source_attackers(self) -> int:
        """The number of enemy pieces which are attacking the square we're moving from"""
        return len(self._enemy_source_attackers)
    
    @property
    def n_enemy_pawn_source_attackers(self) -> int:
        """The number of enemy pawns which are also attacking the square we're moving from"""
        return len([1 for i in self._enemy_source_attackers if i.piece_type == chess.PAWN])
    
    @property
    def n_enemy_knight_source_attackers(self) -> int:
        """The number of enemy knights which are also attacking the square we're moving from"""
        return len([1 for i in self._enemy_source_attackers if i.piece_type == chess.KNIGHT])
    
    @property
    def n_enemy_bishop_source_attackers(self) -> int:
        """The number of enemy bishops which are also attacking the square we're moving from"""
        return len([1 for i in self._enemy_source_attackers if i.piece_type == chess.BISHOP])
    
    @property
    def n_enemy_rook_source_attackers(self) -> int:
        """The number of enemy rooks which are also attacking the square we're moving from"""
        return len([1 for i in self._enemy_source_attackers if i.piece_type == chess.ROOK])
    
    @property
    def n_enemy_queen_source_attackers(self) -> int:
        """The number of enemy queens which are also attacking the square we're moving from"""
        return len([1 for i in self._enemy_source_attackers if i.piece_type == chess.QUEEN])
    
    @property
    def n_enemy_king_source_attackers(self) -> int:
        """The number of enemy kings which are also attacking the square we're moving from"""
        return len([1 for i in self._enemy_source_attackers if i.piece_type == chess.KING])

    def __init__(self, move: chess.Move, board: chess.Board = None):
        """
        Gets a bunch of basically tag info that can be linked to a given move in a given position.
        For example: Does the move give a check? Is it en passant? Does it move onto a back rank?
        Intended for two purposes:
        - To be added to any record of actual moves made as-is
        - To be summed with other moves to get summary data across all moves available in a position
        """

        self.move = move

        if board is not None:
            self.board = board.copy()
        else:
            self.board = None

        self._resulting_board = None
        self._capture_square = None
        