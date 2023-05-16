import chess.engine
from typing import Tuple


class Engine(chess.engine.SimpleEngine):

    def __init__(self, 
                 engine: chess.engine.SimpleEngine, 
                 name: str,
                 depth_parameter: str):
        self.engine = engine
        self.name = name
        self.depth_parameter = depth_parameter

    def standard_limit_constructor(self, depth_value):
        if self.depth_parameter == "depth":
            return chess.engine.Limit(depth=depth_value)
        elif self.depth_parameter == "nodes":
            return chess.engine.Limit(nodes=depth_value)
        else:
            raise NotImplementedError()

    def evaluate_board(self, board: chess.Board, depth_value: int, multipv: int=1):
        """Slightly easier to work with version of chess.engine.SimpleEngine.evaluate"""
        # Check the game isn't over already cos engines bug out if so
        if board.outcome() is not None:
            if board.outcome().winner is None:
                return 0.5  # Draw
            return board.outcome().winner  # 1 for white and 0 for black
        
        if not board.is_valid():
            return None
        
        limit = self.standard_limit_constructor(depth_value=depth_value)

        engine_eval = self.engine.analyse(board, limit, multipv=multipv)

        for i, eval in enumerate(engine_eval):
            engine_eval[i]["score"] = engine_eval[i]["score"].white().wdl().expectation()  # Converting to json friendly format

        return engine_eval
    
    @property
    def evaluations_table(self) -> str:
        return f"{self.name}_evaluations"
    
    def configure(self, options: chess.engine.ConfigMapping) -> None:
         self.engine.configure(options=options)
