import chess.engine
from typing import List


class PrincipalVariation:
    handleable_keys = ("string", "depth", "seldepth", "multipv", "score", "nodes", "nps", "hashfull", "tbhits", "time", "pv", "currmove", "currmovenumber", "lowerbound")
    def __init__(self,
                    info_dict: chess.engine.InfoDict) -> None:
        assert len(set(info_dict.keys()) - set(self.handleable_keys)) == 0, "Unhandled key in engine evaluation InfoDict"

        self.raw_info_dict: chess.engine.InfoDict = info_dict

    @property
    def lowerbound(self) -> bool:
        if "lowerbound" not in self.raw_info_dict.keys():
            return None
        return self.raw_info_dict["lowerbound"]

    @property
    def pv(self) -> List[chess.Move]:
        """List of moves from this principal variation."""
        if "pv" not in self.raw_info_dict.keys():
            return None
        return self.raw_info_dict["pv"]
    
    @property
    def currmove(self) -> chess.Move:
        """Don't know, not returned very often at all"""
        if "currmove" not in self.raw_info_dict.keys():
            return None
        return self.raw_info_dict["currmove"]
    
    @property
    def currmovenumber(self) -> chess.Move:
        """Don't know, not returned very often at all"""
        if "currmovenumber" not in self.raw_info_dict.keys():
            return None
        return self.raw_info_dict["currmovenumber"]

    @property
    def time(self) -> float:
        """Seconds? Or minutes?"""
        if "time" not in self.raw_info_dict.keys():
            return None
        return self.raw_info_dict["time"]

    @property
    def tbhits(self) -> int:
        if "tbhits" not in self.raw_info_dict.keys():
            return None
        return self.raw_info_dict["tbhits"]

    @property
    def hashfull(self) -> int:
        """?"""
        if "hashfull" not in self.raw_info_dict.keys():
            return None
        return self.raw_info_dict["hashfull"]

    @property
    def nps(self) -> float:
        """Nodes per second?"""
        if "nps" not in self.raw_info_dict.keys():
            return None
        return self.raw_info_dict["nps"]

    @property
    def nodes(self) -> int:
        if "nodes" not in self.raw_info_dict.keys():
            return None
        return self.raw_info_dict["nodes"]

    @property
    def centipawns_white(self) -> chess.engine.Cp:
        relative_centipawns = self.centipawns_relative
        if relative_centipawns is not None:
            return relative_centipawns.white()
        return None
        
    @property
    def centipawns_relative(self) -> chess.engine.PovScore:
        if "score" in self.raw_info_dict.keys():
            return self.raw_info_dict["score"]
        return None
        
    @property
    def lichess_evaluation(self) -> float:
        """How lichess would evaluate whites winrate (not as hot as stockfish)"""
        white_centipawns = self.centipawns_white
        if white_centipawns is None:
            return None
        return white_centipawns.wdl(model="lichess").expectation()

    @property
    def multipv(self) -> int:
        """The number of principal variations returned."""
        if "multipv" in self.raw_info_dict.keys():
            return self.raw_info_dict["multipv"]
        return None

    @property
    def string(self) -> str:
        if "string" in self.raw_info_dict.keys():
            return self.raw_info_dict["string"]
        return None
    
    @property
    def depth(self) -> int:
        """The base depth of the analysis (might not be as deep as seldepth)."""
        if "depth" in self.raw_info_dict.keys():
            return self.raw_info_dict["depth"]
        return None
        
    @property
    def seldepth(self) -> int:
        """The depth of the deepest principal variation line in the search. Defaults to depth."""
        if "seldepth" in self.raw_info_dict.keys():
            return self.raw_info_dict["seldepth"]
        return self.depth


class EngineEvaluationResult:

    evaluation_cp: int
    """The centipawn evaluation from white's perspective"""
    
    evaluation_expectation: float
    """The float evaluation from white's perspective"""


    def __init__(self,
                 info_dicts: List[chess.engine.InfoDict] = None,
                 certain_evaluation: float = None) -> None:
        assert certain_evaluation is None or info_dicts is None

        self.raw_info_dicts = info_dicts
        self.certain_evaluation = certain_evaluation
        if info_dicts is not None:
            self.principal_variations = [PrincipalVariation(i) for i in info_dicts]
        else:
            self.principal_variations = None

        if certain_evaluation is not None:
            assert certain_evaluation in [0, 0.5, 1]
            self.evaluation_expectation = certain_evaluation
            self.evaluation_cp = (certain_evaluation - 0.5) * 2 * 1_000_000

    @property
    def pv(self) -> List[chess.Move]:
        """List of moves from the mainline principal variation."""
        return self.best_principal_variation.pv
    
    @property
    def best_move(self) -> chess.Move:
        if self.principal_variations is None:
            return None
        return self.principal_variations[0].pv[0]
    
    @property
    def best_principal_variation(self) -> PrincipalVariation:
        return self.principal_variations[0]

    @property
    def time(self) -> float:
        """Seconds? Or minutes?"""
        return self.best_principal_variation.time

    @property
    def tbhits(self) -> int:
        return self.best_principal_variation.tbhits

    @property
    def hashfull(self) -> int:
        """?"""
        return self.best_principal_variation.hashfull

    @property
    def nps(self) -> float:
        """Nodes per second?"""
        return self.best_principal_variation.nps

    @property
    def nodes(self) -> int:
        """Total nodes scanned across all principal variations"""
        return sum([i.nodes for i in self.principal_variations])

    @property
    def centipawns_white(self) -> chess.engine.Cp:
        """Evaluation of the mainline move"""
        return self.best_principal_variation.centipawns_white
        
    @property
    def centipawns_relative(self) -> chess.engine.PovScore:
        return self.best_principal_variation.centipawns_relative
        
    @property
    def lichess_evaluation(self) -> float:
        """How lichess would evaluate whites winrate (not as hot as stockfish)"""
        if self.certain_evaluation is not None:
            return self.certain_evaluation
        return self.best_principal_variation.lichess_evaluation

    @property
    def multipv(self) -> int:
        """The number of principal variations returned."""
        return self.best_principal_variation.multipv
    
    @property
    def depth(self) -> int:
        """The base depth of the analysis (might not be as deep as seldepth)."""
        return self.best_principal_variation.depth
        
    @property
    def seldepth(self) -> int:
        """The depth of the deepest principal variation line in the search. Defaults to depth."""
        return self.best_principal_variation.seldepth

def certain_white_win() -> EngineEvaluationResult:
    return EngineEvaluationResult(certain_evaluation=1)
def certain_black_win() -> EngineEvaluationResult:
    return EngineEvaluationResult(certain_evaluation=0)
def certain_draw() -> EngineEvaluationResult:
    return EngineEvaluationResult(certain_evaluation=0.5)

class Engine:

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

    def evaluate_board(self, board: chess.Board, depth_value: int, multipv: int=1) -> EngineEvaluationResult:
        """Slightly easier to work with version of chess.engine.SimpleEngine.evaluate"""
        # Check the game isn't over already cos engines bug out if so
        if board.outcome() is not None:
            if board.outcome().winner is None:
                return certain_draw()
            elif board.outcome().winner == 0:
                return certain_black_win()
            elif board.outcome().winner == 1:
                return certain_white_win()
            else:
                raise ValueError()
        
        if not board.is_valid():
            return None
        
        limit: chess.engine.Limit = self.standard_limit_constructor(depth_value=depth_value)

        engine_eval: List[chess.engine.InfoDict] = self.engine.analyse(board, limit, multipv=multipv)

        return EngineEvaluationResult(info_dicts=engine_eval)
    
    @property
    def evaluations_table(self) -> str:
        return f"{self.name}_evaluations"
    
    def configure(self, options: chess.engine.ConfigMapping) -> None:
         self.engine.configure(options=options)
