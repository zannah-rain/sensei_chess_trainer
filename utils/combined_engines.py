"""Encapsulating the use of multiple engines for evaluation."""
import psutil
from typing import Dict

import chess

from utils.settings import Settings
from utils.database import Database
from utils.engine import Engine, EngineEvaluationResult

class CombinedEngines:

    def __init__(self, settings: Settings, database: Database) -> None:
        self._settings = settings
        self._database = database

        self._stockfish = None
        self._leela = None

    def stockfish(self) -> Engine:
        if self._stockfish is None:
            print("Starting Stockfish")
            self._stockfish = Engine(engine=chess.engine.SimpleEngine.popen_uci(self._settings["Stockfish Executable"]), 
                                     name="stockfish",
                                     depth_parameter="depth")
            self._stockfish.configure({"Hash": int(psutil.virtual_memory().available / 1024 / 1024 * 0.3)})  # 75% of available ram
            self._stockfish.configure({"Threads": int(psutil.cpu_count(logical=True) - 3)})
        
        return self._stockfish

    def leela(self) -> Engine:
        if self._leela is None:
            print("Starting Leela")
            self._leela = Engine(engine=chess.engine.SimpleEngine.popen_uci(self._settings["Leela Executable"]), 
                                 name="leela",
                                 depth_parameter="nodes")
        
        return self._leela

    def engines(self) -> Dict[str, Engine]:
        return {"stockfish": self.stockfish(), "leela": self.leela()}

    def stockfish_evaluation(self, depth, board) -> EngineEvaluationResult:
        return self._database.engine_evaluation(board=board, engine=self.stockfish(), depth_value=depth)
    
    def leela_evaluation(self, nodes, board) -> EngineEvaluationResult:
        return self._database.engine_evaluation(board=board, engine=self.leela(), depth_value=nodes)
    
    def combined_evaluation(self, depth, nodes, board) -> float:
        self.stockfish_evaluation(depth, board=board)
        self.leela_evaluation(nodes, board=board)
        return self._database.read_combined_engine_evaluation(board=board)
    
    def stable_evaluation(self, min_depth, min_nodes, max_depth, max_instability: float, board) -> float:
        """
        To help in situations where evaluation is very unstable (and can move a lot from one ply to the next).
        Keeps increasing depth until the difference in evaluation from one step to another is less than max_instability.
        """
        current_depth = min_depth
        current_nodes = min_nodes

        while current_depth < max_depth:
            current_eval = self.combined_evaluation(depth=current_depth, nodes=current_nodes, board=board)

            engine_move = self._database.engine_move(board=board, engine=self.stockfish(), depth_value=current_depth, multipv=1)
            engine_next_position = board.copy()
            engine_next_position.push(engine_move)
            next_eval = self.combined_evaluation(depth=current_depth, nodes=current_nodes, board=engine_next_position)

            if abs(next_eval - current_eval) > max_instability:
                current_depth += 4
                current_nodes += 5000
                print(f"Unstable engine evaluation, increasing depth to {current_depth}")
                continue

            return next_eval
        
        return next_eval
    
    def close(self) -> None:
        if self._stockfish is not None:
            self._stockfish.close()
        if self._leela is not None:
            self._leela.close()
