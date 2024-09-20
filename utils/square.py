import chess


class Square:

    def __init__(self, square_id: chess.Square = None, rank_id: int = None, file_id: int = None):
        """Just a mini class to signpost useful functionality in chess"""

        if square_id is not None:
            self.id = square_id
        elif rank_id is not None and file_id is not None:
            self.id = chess.square(rank_index=rank_id, file_index=file_id)

    def __repr__(self):
        return f"Square({self.id}) {self.file}{self.rank}"
    
    def __str__(self):
        return f"{self.file}{self.rank}"
    
    def __eq__(self, other):
        if isinstance(other, Square):
            return self.id == other.id
        elif isinstance(other, int):
            return self.id == other
        else:
            return False
    
    def __hash__(self):
        return hash(self.id)
    
    def move_to(self, square) -> chess.Move:
        return chess.Move(from_square=self.id, to_square=square.id)
    
    @property
    def internal_square(self) -> int:
        """0-63"""
        return self.id
    
    @property
    def tuple(self) -> tuple:
        """(rank_id, file_id)"""
        return (self.rank_id, self.file_id)

    @property
    def file_id(self) -> int:
        """0-7"""
        return chess.square_file(self.id)
    
    @property
    def file(self) -> str:
        """'a'-'h'"""
        return ["a", "b", "c", "d", "e", "f", "g", "h"][self.file_id]
    
    @property
    def rank_id(self) -> int:
        """0-7"""
        return chess.square_rank(self.id)
    
    @property
    def rank(self) -> int:
        return self.rank_id + 1
    
    @property
    def on_edge(self) -> bool:
        if self.file_id in [0, 7]:
            return True
        if self.rank_id in [0, 7]:
            return True
        return False
    
    @property
    def in_center(self) -> bool:
        """True if in the middle 4 squares of the board"""
        return (self.file_id in [3, 4]) and (self.rank_id in [3, 4])
    
    @property
    def rank_centrality(self) -> int:
        """0-3, maximised in the center and 0 on the edge"""
        return 3 - (abs((3.5 - self.rank_id)) - 0.5)
    
    @property
    def file_centrality(self) -> int:
        """0-3, maximised in the center and 0 on the edge"""
        return 3 - (abs((3.5 - self.file_id)) - 0.5)
    
    @property
    def overall_centrality(self) -> int:
        """rank + file centrality"""
        return self.rank_centrality + self.file_centrality
    
    @property
    def dict(self) -> dict:
        return {
            "file_id": self.file_id,
            "rank_id": self.rank_id,
            "on_edge": self.on_edge,
            "in_center": self.in_center,
            "rank_centrality": self.rank_centrality,
            "file_centrality": self.file_centrality,
            "overall_centrality": self.overall_centrality
        }
