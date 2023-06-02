"""
Utilities for working with what I currently consider a 'position'.
That is, FEN minus the move counts.
"""

import chess.pgn
from utils.square import Square
from utils.piece import basic_piece_value


def fen_to_position(fen: str) -> str:
    """
    Strips out bits of the FEN that aren't usually relevant for analysis.
    
    - IE no full / halfmove count
    """
    return " ".join(fen.split(" ")[:-2])


def position_to_fen(position: str) -> str:
    return f"{position} 0 0"


def gamenode_position(game_node: chess.pgn.GameNode) -> str:
    return board_position(game_node.board())


def board_position(board: chess.Board) -> str:
    return fen_to_position(board.fen())


class Position:
        
    def __init__(self, board: chess.Board):

        self.board = board

        self._piece_map = self.board.piece_map()

    def king_location(self, colour):
        return [i for i in self.board.pieces(chess.KING, colour)][0]
    
    def rank_aggression(self, rank, colour) -> int:
        """0-8, 8 being deep in enemy territory"""
        if colour is None:
            return None
        if colour == chess.WHITE:
            return rank
        else:
            return 8 - rank
        
    def activity(self, square) -> int:
        """The number of squares influenced by the piece on this square"""
        return len(self.board.attacks(square.id))
    
    def piece_at(self, square) -> chess.Piece:
        return self.board.piece_at(square.id)
    
    def piece_present(self, square) -> bool:
        return self.piece_at(square) is not None
    
    def piece_value_at(self, square) -> int:
        x = self.piece_at(square)
        if x is None:
            return 0
        return basic_piece_value(x.piece_type)
    
    def square_attacker_stats(self, square, colour) -> dict:
        x = dict()

        attackers = self.board.attackers(color=colour, square=square)
        x["n_attackers"] = len(attackers)

        attacker_values = [self.piece_value_at(sq) for sq in attackers]
        x["attacker_total_value"] = sum(attacker_values)
        x["attacker_max_value"] = max(attacker_values)
        x["attacker_min_value"] = min(attacker_values)

    def square_stats(self, square: Square):
        rank_id = square.rank_id
        file_id = square.file_id

        x = square.dict

        x["distance_to_white_king"] = chess.square_distance(square.id, self.king_location(chess.WHITE))
        x["distance_to_black_king"] = chess.square_distance(square.id, self.king_location(chess.BLACK))
        x["distance_to_nearest_king"] = min(x["distance_to_white_king"], x["distance_to_black_king"])
        x["activity"] = self.activity(square.id)
        x["piece_present"] = self.piece_present(square.id)
        x["piece_value"] = self.piece_value_at(square.id)

        white_attackers = self.square_attacker_stats(square.id, chess.WHITE)
        black_attackers = self.square_attacker_stats(square.id, chess.BLACK)
        def parse_in_attackers(attacker_dict, attacker_side):
            for k, v in attacker_dict:
                x[f"{attacker_side}_{k}"] = v
        parse_in_attackers(white_attackers, "white")
        parse_in_attackers(black_attackers, "black")

        # Add perspective aware version of 'white' and 'black' stats
        piece_at = self.piece_at(square.id)
        if piece_at is not None:
            x["side"] = piece_at.color
            x["opposing_side"] = 1 - x["side"]

            if x["side"] == chess.WHITE:
                side_name = "white"
                enemy_name = "black"
            elif x["side"] == chess.BLACK:
                side_name = "black"
                enemy_name = "white"
            else:
                raise ValueError()

            for k, v in list(x.keys()):
                if side_name in k:
                    x[k.replace(side_name, "friendly")] = v
                elif enemy_name in k:
                    x[k.replace(enemy_name, "enemy")] = v
            
            x["rank_aggression"] = self.rank_aggression(rank=x["rank"], colour=x["side"])
        else:
            x["side"] = None
            x["opposing_side"] = None

            for k, v in list(x.keys()):
                if "white" in k:
                    x[k.replace("white", "friendly")] = None
                if "black" in k:
                    x[k.replace("black", "enemy")] = None

            x["rank_aggression"] = None

        return x
    

    def piece_map_stats(self, 
                        side=[None, chess.WHITE, chess.BLACK],
                        piece_type=[None, chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.KING]) -> dict:
        x = dict()

        filtered_pieces = {Square(k): v for k, v in self._piece_map.items()}
        if side is not None:
            filtered_pieces = {k: v for k, v in filtered_pieces.items() if (v.color == side)}
        if piece_type is not None:
            filtered_pieces = {k: v for k, v in filtered_pieces.items() if (v.piece_type == piece_type)}

        x["piece_count"] = len(filtered_pieces)
        x["piece_value"] = sum([basic_piece_value(i.piece_type) for i in filtered_pieces.values()])

        individual_stats = [self.square_stats(sq.id) for sq in filtered_pieces.keys()]

        # def min_max_rank
        # def min_max_file
        # def min_max_centrality
        # def min_max_defender_value
        # squares controlled
        # n defenders
        # n attackers
        # pinned

        # x["piece_"]


    # total number of pieces alive on each side
    # isolated pawn indicators
    # rook on open file indicators
    # bishop pair indicators
        # total of each type alive
        # specific location of the kings
        # number of squares attacked by each side
        # number of squares controlled by each side (ie: more attackers than defenders)
        # number of hanging pieces on each side
        # number of under-defended pieces on each side
        # number of attacked pieces on each side
        # number of pieces attacking an enemy piece on each side
        # number of pins on each side
        # whether it's in check
        # king centrality
        # queen centrality
        # average rook centrality
        # average knight centrality etc
        # average number of squares being attacked by knights
        # average number of squares being attacked by bishops etc
        # number of valid moves
        # castling rights
        # side value of hanging pieces
        # side value of underdefended pieces
        # side value of attacked pieces
        # are rooks connected (pos)
        # are pieces developed (not on starting square) (pos)
        # average piece distance from your king, enemy king

        # Which pieces of the given colour are attacking the given square
        # board.attackers_mask(color, square)

        # Output needs processing
        # board.castling_rights  # The raw ones
        # board.clean_castling_rights  # The ones that are valid moves right now
        # board.generate_castling_moves  # Iterator of moves

        # board.pieces(prawn, white)
        # board.pieces(prawn, black)
        # board.pieces(bishop, white)
        #etc

        # Which pieces & where are giving check
        # board.checkers_mask

        # board.bishops  # The number of bishops on the board?

        # board.color_at(square)

        # board.generate_legal_captures  # Iterator of moves
        # board.gives_check  # Check if the above gives check

        # board.generate_legal_ep  # Iterator of en passant moves
        # board.gives_check  # Check if the above gives check

        # board.generate_legal_moves  # Iterator of legal moves
        # board.gives_check  # Check if the above gives check
        # Count
        # What sort of pieces can move

        # board.has_castling_rights
        # board.has_queenside_castling_rights
        # board.has_insufficient_material(color)

        # A bunch of these checks can be applied to moves
        # I want to apply these not only to each move available, but human and best moves when they are played / suggested / calculated
        # board.is_check  # bool if the current side to move is in check rn
        # board.is_valid
        # board.is_checkmate
        # board.is_stalemate
        # board.is_attacked_by
        # board.is_queenside_castling
        # board.is_en_passant
        # board.is_pinned(color, square)
        # board.is_game_over
        # board.is_castling
        # board.is_irreversible

        # board.king(color)
        # board.knights
        # board.rooks
        # board.occupied
        # board.outcome
        # board.pawns
        # board.piece_type_at
        # board.piece_map
        # board.promoted
        # board.pieces_mask
        # board.pin_mask
        # board.queens
        # board.has_queenside_castling_rights
        # board.result
        # board.turn
        # board

        # board.has_legal_en_passant
        # next_position_board.has_legal_en_passant

        # board.clean_castling_rights()
        # next_position_board.clean_castling_right()

        # distance to enemy king before & after
        # distance to friend king before & after
        # square centrality before & after

        # board.is_check

        # total controlled squares before & after

        # @property
        # def pins_something(self) -> bool:
        #     """Will be true if it's just maintaining a prior pin too, not just for brand new ones"""
        #     return [self.board.is_pinned(self.opposing_player, i) for i in self.resulting_board.attacks()] 
# 
        #     @property
        # def gives_insufficient_material(self) -> bool:
        #     return (not self.board.has_insufficient_material(self.opposing_player)) and (self.resulting_board.has_insufficient_material(self.opposing_player))
# 
        # @property
        # def interrupts_all_castling_rights(self) -> bool:
        #     """True if the opponent goes from having castling rights to not"""
        #     return self.board.has_castling_rights(self.opposing_player) and (not self.resulting_board.has_castling_rights(self.opposing_player))
# 
        # @property
        # def interrupts_queenside_castling_rights(self) -> bool:
        #     """True if the opponent goes from having queenside castling rights to not"""
        #     return self.board.has_queenside_castling_rights(self.opposing_player) and (not self.resulting_board.has_queenside_castling_rights(self.opposing_player))
# 
        # @property
        # def interrupts_kingside_castling_rights(self) -> bool:
        #     """True if the opponent goes from having kingside castling rights to not"""
        #     return self.board.has_kingside_castling_rights(self.opposing_player) and (not self.resulting_board.has_kingside_castling_rights(self.opposing_player))
        
        