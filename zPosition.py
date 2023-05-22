from __future__ import annotations
from typing import List, Optional, Dict, List, Tuple
import chess
import chess.engine
import chess.pgn
import json
import pathlib
import logging
import requests
import time
from datetime import datetime
import pandas as pd
import globals
from globals import username


logging.basicConfig(level=logging.INFO)


class zPosition:
    parents: Optional[List[zPosition]]
    """Positions which are known to lead to this position."""

    children: Optional[Dict[str, zPosition]]
    """Next positions which this position can move into, along with the given move."""

    comment: Optional[str]
    """Description of this position."""

    board: chess.Board
    """The chess module representation of this state. Handles everything that I'm not specifically adding."""

    def __init__(self, parents=None, children=None, comment=None, fen: str = chess.STARTING_FEN):
        self.parents = parents
        self.children = children
        self.comment = comment

        self._cached_engine_evaluation = None  # Stockfish
        self._cached_engine_multidepth_evaluations = None  # List, ith element is a sublist of (best move, evaluation) when analysing at depth i (for sharpness metric)
        self._cached_leela_evaluation = None

        self._cached_lichess_stats = None
        self._cached_lichess_master_stats = None
        self._cached_lichess_engine_evaluation = None

        # For representing internal state of board
        # Can't use a trivial BaseBoard, as we need extra information about whether people can still castle etc.
        self._board = None
        self.fen = fen

        if self.cache_path.exists():
            logging.debug(f"Reloading FEN {self.fen} from cache.")
            with open(self.cache_path, "r") as f:
                try:
                    self.from_dict(json.load(f))
                except json.decoder.JSONDecodeError:
                    logging.warn(f"Couldn't reload {self.fen} from cache, reinitializing...")
        else:
            logging.debug(f"Initialising FEN {self.fen} from scratch.")

    @staticmethod
    def book_stats(engines):
        sharpnesses = []
        for file_id, file in enumerate(pathlib.Path("position_cache/").glob("*.fen")):
            fen = file.name.replace(".fen", "").replace("_", "/")
            position = zPosition(fen=fen)
            children_min_depth = position.children_min_engine_depth()
            if children_min_depth > 0:
                sharpnesses.append(position.sharpness(engine=engines["stockfish"], min_depth=children_min_depth, heuristic="evaluation_depth_analysis"))
            if len(sharpnesses) % 1000 == 1:
                logging.info(f"{len(sharpnesses)} positions: Average sharpness = {sum(sharpnesses) / len(sharpnesses)}")
        return pd.Series(sharpnesses, name="sharpness")
        
    @property
    def lichess_stats(self):
        if self._cached_lichess_stats is None:
            self._cached_lichess_stats = self.call_lichess_api()
            if self._cached_lichess_stats is not None:
                self.save()
                logging.debug(f"Cached lichess stats for FEN: {self.fen}")
        
        return self._cached_lichess_stats
    
    @property
    def lichess_master_stats(self):
        if self._cached_lichess_master_stats is None:
            try:
                self._cached_lichess_master_stats = self.call_lichess_api(master=True)
            except:
                pass
            if self._cached_lichess_master_stats is not None:
                self.save()
                logging.debug(f"Cached lichess master stats for FEN: {self.fen}")
        
        return self._cached_lichess_master_stats
    
    @property
    def lichess_engine_evaluation(self):
        if self._cached_lichess_engine_evaluation is None:
            self._cached_lichess_engine_evaluation = self.call_lichess_api_engine()
            if self._cached_lichess_engine_evaluation is not None:
                self.save()
                logging.info(f"Cached lichess engine evaluation for FEN: {self.fen}")
        
        if self._cached_lichess_engine_evaluation is not None:
            if "error" in self._cached_lichess_engine_evaluation.keys():
                return None
        
        return self._cached_lichess_engine_evaluation
    
    @property
    def lichess_move_frequencies(self):
        if self.lichess_stats is None:
            return None
        return {move["uci"]: (move["white"] + move["black"] + move["draws"]) / self.lichess_game_count
                for move in self.lichess_stats["moves"]}
    
    @property
    def lichess_master_move_frequencies(self):
        if self.lichess_master_stats is None:
            return None
        return {move["uci"]: (move["white"] + move["black"] + move["draws"]) / self.lichess_master_game_count
                for move in self.lichess_master_stats["moves"]}
    
    @property
    def lichess_master_white_evaluation_historic(self):
        if self.lichess_master_game_count == 0:
            return 0.5
        return (self.lichess_master_stats["white"] + self.lichess_master_stats["draws"] / 2) / self.lichess_master_game_count
    
    @property
    def lichess_master_game_count(self):
        if self.lichess_master_stats is None:
            return 0
        return self.lichess_master_stats["white"] + self.lichess_master_stats["black"] + self.lichess_master_stats["draws"]

    @property
    def lichess_white_evaluation_historic(self):
        if self.lichess_game_count == 0:
            return 0.5
        return (self.lichess_stats["white"] + self.lichess_stats["draws"] / 2) / self.lichess_game_count
    
    @property
    def lichess_game_count(self):
        if self.lichess_stats is None:
            return 0
        return (self.lichess_stats["white"] + self.lichess_stats["black"] + self.lichess_stats["draws"])

    @property
    def board(self):
        if self._board is None:
            self._board = chess.Board(fen=self.fen)
        return self._board

    @staticmethod
    def fen_cache_path(fen: str) -> pathlib.Path:
        path_safe_fen = fen.replace("/", "_")
        return pathlib.Path(f"position_cache/{path_safe_fen}.fen")

    @property
    def cache_path(self) -> pathlib.Path:
        return zPosition.fen_cache_path(fen=self.fen)
    
    @property
    def engine_evaluation_depth(self):
        depth = 0

        if self.lichess_engine_evaluation is not None:
            depth = max(depth, self.lichess_engine_evaluation["depth"])
        if self._cached_engine_evaluation is not None:
            depth = max(depth, self._cached_engine_evaluation[0]["depth"])

        return depth
    
    @property
    def engine_evaluation_nodes(self):
        nodes = 0

        if self.lichess_engine_evaluation is not None:
            nodes = max(nodes, self.lichess_engine_evaluation["knodes"])

        if self._cached_engine_evaluation is not None:
            if "nodes" not in self._cached_engine_evaluation[0].keys():
                nodes = max(nodes, 1)  # Seems to happen when the engine found a forced win/loss
            else:
                nodes = max(nodes, self._cached_engine_evaluation[0]["nodes"])

        return nodes
    
    @property
    def leela_evaluation_depth(self):
        depth = 0

        if self._cached_leela_evaluation is not None:
            depth = max(depth, self._cached_leela_evaluation[0]["depth"])

        return depth
    
    @property
    def leela_evaluation_nodes(self):
        nodes = 0

        if self._cached_leela_evaluation is not None:
            nodes = max(nodes, self._cached_leela_evaluation[0]["nodes"])
        
        return nodes
    
    def engine_multidepth_evaluations(self, engine, depths = [1, 2, 3, 4, 5, 10, 15, 20]) -> Dict[List[str, float]]:
        """
        (Intended to help calculate sharpness of the position).
        In the returned dict, the key is the depth evaluated to and the value is [best_move, evaluation].
        So: 
        - You can check if the best move at 2 ply matches that of 20 ply to see how obvious the best move is.
        - When the moves differ, you can tell how important the distinction is by comparing the evaluations.
        - You can evaluate the sharpness of both your own positions and the enemy position as potential targets.
        """
        if self._cached_engine_multidepth_evaluations is None:
            self._cached_engine_multidepth_evaluations = dict()

        for this_depth in depths:
            if this_depth not in self._cached_engine_multidepth_evaluations.keys():
                this_eval = engine.analyse(self.board, chess.engine.Limit(depth=this_depth), multipv=1)
                if "pv" in this_eval[0].keys():
                    this_best_move = this_eval[0]["pv"][0].uci()
                else:
                    this_best_move = "NO_MOVE"

                self._cached_engine_multidepth_evaluations[this_depth] = [this_best_move, this_eval[0]["score"].white().wdl(model="lichess").expectation()]
                self.save()
                logging.info(f"Saved new engine multidepth evaluation of FEN: {self.fen}. Eval: {self._cached_engine_multidepth_evaluations[this_depth]}")

        return {k: self._cached_engine_multidepth_evaluations[k] for k in depths}
    
    def stockfish_evaluation(self, engine: chess.engine.SimpleEngine, depth=35, multipv=1):

        # Check the game isn't over already cos engines bug out if so
        if self.board.outcome() is not None:
            if self.board.outcome().winner is None:
                return 0.5  # Draw
            return self.board.outcome().winner  # 1 for white and 0 for black

        cloud_eval = self.lichess_engine_evaluation
        if cloud_eval is not None:
            if cloud_eval["depth"] >= max(depth, self.engine_evaluation_depth):
                if "cp" in cloud_eval["pvs"][0].keys():
                    return chess.engine.Cp(cloud_eval["pvs"][0]["cp"]).wdl(model="lichess").expectation()

        if (self.engine_evaluation_depth < depth) or (self._cached_engine_evaluation is None):
            engine_eval = engine.analyse(self.board, chess.engine.Limit(depth=depth), multipv=multipv)
            engine_eval[0]["score"] = engine_eval[0]["score"].white().wdl(model="lichess").expectation()  # Converting to json friendly format
            if "pv" in engine_eval[0].keys():
                engine_eval[0]["pv"] = [i.uci() for i in engine_eval[0]["pv"]]  # Converting to json friendly format
            if "currmove" in engine_eval[0].keys():
                engine_eval[0]["currmove"] = engine_eval[0]["currmove"].uci()
            self._cached_engine_evaluation = engine_eval
            self.save()
            stockfish_eval = engine_eval[0]["score"]
            logging.info(f"Saved new stockfish evaluation of FEN: {self.fen}. Eval: {stockfish_eval}")
            logging.debug(f"Full evaluation: {self._cached_engine_evaluation}")

        return self._cached_engine_evaluation[0]["score"]
    
    def leela_evaluation(self, engine: chess.engine.SimpleEngine, nodes=10_000, multipv=1):#

        if self.board.outcome() is not None:
            if self.board.outcome().winner is None:
                return 0.5  # Draw
            return self.board.outcome().winner  # 1 for white and 0 for black

        if self.leela_evaluation_nodes < nodes:
            leela_eval = engine.analyse(self.board, chess.engine.Limit(nodes=nodes), multipv=multipv)
            leela_eval[0]["score"] = leela_eval[0]["score"].white().wdl(model="lichess").expectation()  # Converting to json friendly format
            if "pv" in leela_eval[0].keys():
                leela_eval[0]["pv"] = [i.uci() for i in leela_eval[0]["pv"]]  # Converting to json friendly format
            if "currmove" in leela_eval[0].keys():
                leela_eval[0]["currmove"] = leela_eval[0]["currmove"].uci()
            if "nodes" in leela_eval[0].keys():
                leela_eval[0]["returned_nodes"] = leela_eval[0]["nodes"]
                leela_eval[0]["nodes"] = nodes  # Not sure why leela often seems to do less than requested but no point requesting the same again
            self._cached_leela_evaluation = leela_eval
            self.save()
            leela_eval = leela_eval[0]["score"]
            logging.info(f"Saved new leela evaluation of FEN: {self.fen}. Eval: {leela_eval}")
            logging.debug(f"Full evaluation: {self._cached_leela_evaluation}")
        
        return self._cached_leela_evaluation[0]["score"]

    def engine_evaluation(self, engines: Dict[str, chess.engine.SimpleEngine], depth=35, multipv=1, leela_nodes=10_000):
        
        if self.board.outcome() is not None:
            if self.board.outcome().winner is None:
                return 0.5  # Draw
            return self.board.outcome().winner  # 1 for white and 0 for black
        
        return (self.stockfish_evaluation(engine=engines["stockfish"], depth=depth, multipv=multipv) + 
                self.leela_evaluation(engine=engines["leela"], nodes=leela_nodes, multipv=multipv)) / 2
    
    def best_engine_move(self, engine, depth=35) -> chess.Move:
        """Returns the UCI move recommended by the engine."""
        if self.board.is_game_over():
            raise ValueError(f"Can't find best move when is_game_over() True for FEN: {self.fen}")
        
        self.stockfish_evaluation(engine=engine, depth=depth)
        cloud_eval = self.lichess_engine_evaluation
        if cloud_eval is not None:
            if cloud_eval["depth"] >= max(depth, self.engine_evaluation_depth):
                return chess.Move.from_uci(cloud_eval["pvs"][0]["moves"].split(" ")[0])
        return chess.Move.from_uci(self._cached_engine_evaluation[0]["pv"][0])

    def to_dict(self):
        return {
            "fen": self.fen,
            "parents": self.parents,
            "children": self.children,
            "comment": self.comment,
            "_cached_engine_evaluation": self._cached_engine_evaluation,
            "_cached_leela_evaluation": self._cached_leela_evaluation,
            "_cached_lichess_stats": self._cached_lichess_stats,
            "_cached_lichess_master_stats": self._cached_lichess_master_stats,
            "_cached_engine_multidepth_evaluations": self._cached_engine_multidepth_evaluations,
            "_cached_lichess_engine_evaluation": self._cached_lichess_engine_evaluation
        }
    
    def from_dict(self, x):
        # windows is not case sensitive with file paths!
        if self.fen != x["fen"]:
            logging.warning(f"Can't load {self.fen} from cache due to windows case insensitivity")
            return

        self.parents = x["parents"]
        self.children = x["children"]
        self.comment = x["comment"]
        self.fen = x["fen"]
        self._cached_engine_evaluation = x["_cached_engine_evaluation"]

        if "_cached_lichess_stats" in x.keys():
            self._cached_lichess_stats = x["_cached_lichess_stats"]
        if "_cached_lichess_master_stats" in x.keys():
            self._cached_lichess_master_stats = x["_cached_lichess_master_stats"]
        if "_cached_engine_multidepth_evaluations" in x.keys():
            if x["_cached_engine_multidepth_evaluations"] is not None:
                self._cached_engine_multidepth_evaluations = {int(k): v for k, v in x["_cached_engine_multidepth_evaluations"].items()}
        if "_cached_lichess_engine_evaluation" in x.keys():
            self._cached_lichess_engine_evaluation = x["_cached_lichess_engine_evaluation"]
        if "_cached_leela_evaluation" in x.keys():
            self._cached_leela_evaluation = x["_cached_leela_evaluation"]

    def save(self):
        with open(self.cache_path, "w") as f:
            json.dump(self.to_dict(), fp=f, indent=4)

    @staticmethod
    def load(file):
        with open(file, "r") as f:
            return zPosition.from_dict(json.load(fp=f))
        
    def call_lichess_api_engine(self):
        if globals.engine_rate_limit:
            return None
        
        url = "https://lichess.org/api/cloud-eval?"
        url += f"fen={self.fen}"
        logging.debug(f"Downloading lichess engine evaluation for FEN: {self.fen}")

        r = requests.get(url)
        time.sleep(0.5)
        if r.status_code == 429:
            logging.info(f"Hit Lichess API engine rate limit, not making any more api calls... (And waiting to avoid re-run oopsies)")
            time.sleep(60)
            globals.engine_rate_limit = True
            return None
        else:
            response = r.json()

        return response

    def call_lichess_api(self, master : bool = False):
        if globals.explorer_limit:
            return None
        
        if master == False:
            variant = "standard"
            speeds = ["ultraBullet", "bullet", "blitz", "rapid", "classical", "correspondence"]
            ratings = ["1600", "1800", "2000", "2200", "2500"]
            moves = 50
            recentGames = 0
            topGames = 0
            play = ""
            
            url = 'https://explorer.lichess.ovh/lichess?'
            url += f'variant={variant}&'
            url += f'speeds={",".join(speeds)}&'
            url += f'ratings={",".join(ratings)}&'
            url += f'recentGames={recentGames}&'
            url += f'topGames={topGames}&'
            url += f'moves={moves}&'
            url += f'play={play}&'
            url += f'fen={self.fen}'

            logging.info(f"Downloading lichess stats for FEN: {self.fen}")
        else:
            moves = 50
            recentGames = 0
            topGames = 0
            play = ""
            
            url = 'https://explorer.lichess.ovh/masters?'
            url += f'topGames={topGames}&'
            url += f'moves={moves}&'
            url += f'play={play}&'
            url += f'fen={self.fen}'

            logging.info(f"Downloading lichess master stats for FEN: {self.fen}")

        r = requests.get(url)
        time.sleep(1)
        if r.status_code == 429:
            logging.info(f"Hit Lichess stats API rate limit, making no more requests and waiting to avoid restart oopsies")
            time.sleep(60)
            globals.explorer_limit = True
            return None
        else:
            response = r.json()
            
        return response
    
    def position_from_move(self, uci_move: str) -> zPosition:
        new_board = self.board.copy()
        if isinstance(uci_move, str):
            uci_move = chess.Move.from_uci(uci_move)
        
        new_board.push(uci_move)
        return zPosition(fen=new_board.fen())

    def create_engine_opening_training(self, engine, side=chess.WHITE, min_depth=35, min_likelihood=0.1):
        """
        Pure engine move responses to common moves.
        :param side: Which side to find the optimum moves for. The resulting repertoire will include all common moves from the other side.
        :param min_depth: The minimum analysis depth for the given engine move.
        :param min_likelihood: The minimum likelihood of observing a given variation for it to be included. 0.01 means at least once in 100 games according to lichess stats.
        :param current_likelihood: The current likelihood of observing the variation up until this position. Do not set this manually.
        """

        game = chess.pgn.Game.from_board(self.board)
        total_progress = 0
        
        def iterate_game(game_node: chess.pgn.GameNode, total_progress, current_likelihood=1):
            this_fen = game_node.board().fen()
            this_position = zPosition(fen=this_fen)
            if game_node.turn() == side:
                # Use the engine best move
                logging.info(f"Appending best engine move after FEN: {this_fen} - {game_node.board().san(this_position.best_engine_move(engine=engine, depth=min_depth))}")
                comment=f"Engine move. EE: {this_position.engine_evaluation(engine=engine, depth=min_depth, leela_nodes=leela_nodes)}. D: {this_position.engine_evaluation_depth}. N: {this_position.engine_evaluation_nodes}. F: {current_likelihood}."
                next_node = game_node.add_variation(this_position.best_engine_move(engine=engine, depth=min_depth),
                                                    comment=comment)
                total_progress = iterate_game(next_node, total_progress=total_progress, current_likelihood=current_likelihood)
            else:
                has_subvariations = False
                for move, frequency in this_position.lichess_move_frequencies.items():
                    total_frequency = frequency * current_likelihood
                    if total_frequency >= min_likelihood:
                        has_subvariations = True
                        logging.info(f"Appending common enough response ({total_frequency}) after FEN: {this_fen} - {move}")
                        comment=f"Common response. LE: {this_position.lichess_white_evaluation_historic}. LN: {this_position.lichess_game_count}. F: {total_frequency}."
                        next_node = game_node.add_variation(chess.Move.from_uci(move))
                        total_progress = iterate_game(next_node, total_progress=total_progress, current_likelihood=total_frequency)
                if not has_subvariations:
                    total_progress += current_likelihood
                else:
                    logging.info(f"Total progress: {total_progress*100}%")

            return total_progress

        iterate_game(game, total_progress=total_progress)
        return game
    
    def probabilistic_engine_evaluation(self, 
                                        engines, 
                                        side=chess.WHITE, 
                                        min_depth=20, 
                                        min_likelihood=0.01, 
                                        starting_likelihood=1, 
                                        min_games=200, 
                                        leela_nodes=10_000,
                                        effect_cap=0.01,
                                        master_only: bool = True):
        """
        Expected value of engine evaluation when played against human move probabilities in resulting positions.
        Any subsequent position at least min_likelihood will be included specifically, less frequent positions will be assumed to have the overall evaluation
        :param side: Which side to find the optimum moves for. The resulting repertoire will include all common moves from the other side.
        :param min_depth: The minimum analysis depth for the given engine move.
        :param min_likelihood: The minimum likelihood of observing a given variation for it to be included. 0.01 means at least once in 100 games according to lichess stats.
        :param current_likelihood: The current likelihood of observing the variation up until this position. Do not set this manually.
        """

        game = chess.pgn.Game.from_board(self.board)
        
        def iteratable_evaluation(game_node: chess.pgn.GameNode, current_likelihood=1):
            this_fen = game_node.board().fen()
            this_position = zPosition(fen=this_fen)

            # logging.info(f"Iterable processing fen: {this_fen}")

            if game_node.turn() == side:
                # Use the engine best move
                next_node = game_node.add_variation(this_position.best_engine_move(engine=engines["stockfish"], depth=min_depth))
                return iteratable_evaluation(next_node, current_likelihood=current_likelihood)

            base_eval = this_position.engine_evaluation(engines=engines, depth=min_depth, leela_nodes=leela_nodes)

            if master_only:
                this_position_games = this_position.lichess_master_game_count
                this_position_frequencies = this_position.lichess_master_move_frequencies
            else:
                this_position_games = this_position.lichess_master_game_count + this_position.lichess_game_count
                this_position_frequencies = this_position.lichess_move_frequencies

            if (this_position_games < min_games) or (this_position_frequencies is None):
                return base_eval

            subvariations_accounted_for = 0  # frequency allocation so infrequent children can just be guessed
            expected_eval = 0
            for move, frequency in this_position_frequencies.items():
                this_frequency = frequency * current_likelihood
                if (this_frequency >= min_likelihood) and (this_position_games * frequency >= min_games):
                    next_node = game_node.add_variation(chess.Move.from_uci(move))
                    expected_eval += iteratable_evaluation(next_node, current_likelihood=this_frequency) * frequency
                    subvariations_accounted_for += frequency
            
            expected_eval += (1 - subvariations_accounted_for) * base_eval

            expected_eval = max(expected_eval, base_eval - effect_cap)
            expected_eval = min(expected_eval, base_eval + effect_cap)

            return expected_eval

        return iteratable_evaluation(game, current_likelihood=starting_likelihood)
    
    @property
    def legal_moves(self) -> chess.LegalMoveGenerator:
        return self.board.legal_moves

    @property
    def turn(self) -> int:
        """chess.WHITE or chess.BLACK"""
        return self.board.turn

    def children_min_engine_depth(self) -> int:
        """The minimum engine depth child nodes have already been evaluated to."""
        # Helpful to do some lazy evaluation sometimes
        legal_moves = self.legal_moves
        candidates_positions = {move: self.position_from_move(move.uci()) for move in legal_moves}
        if len(candidates_positions) == 0:
            return 0
        evaluated_depths = [i.engine_evaluation_depth for i in candidates_positions.values()]
        return min(evaluated_depths)
            

    def sharpness(self,
                  engines=None,
                  heuristic="null_model_loss",
                  min_depth=25):
        """
        Estimate the sharpness of the position.

        heuristic=null_model_loss - Sharpness is defined as the average engine evaluation loss when playing a random move rather than the best move.
        So for example:
        - A position with one guaranteed winning move while all others are guaranteed losing has a sharpness of ~1 (which then gets inv logit'd)
        - A position where all moves are exactly the same has a sharpness of 0

        heuristic=evaluation_depth_analysis - Sharpness is defined as the variability of the engine evaluation as depth increases.
        So for example:
        - A position where the max evaluation difference goes from certain loss to certain victory has a sharpness of ~1 (which then gets inv logit'd)
        - A position where the evaluation at all depths is to do the exact same move has a sharpness of 0
        (I think this definition is a bit better than null_model_loss, and is also much easier to calculate!)
        """
        if heuristic == "null_model_loss":
            legal_moves = self.legal_moves
            candidates_positions = {move: self.position_from_move(move.uci()) for move in legal_moves}
            candidates_evaluations = {move: candidates_positions[move].engine_evaluation(engine=engines["stockfish"], depth=min_depth) for move in legal_moves}
            if self.turn == chess.BLACK:
                # Best move is the lowest evaluated
                candidates_evaluations = {move: -evaluation for move, evaluation in candidates_evaluations.items()}
            best_eval = max(candidates_evaluations.values())
            average_eval = sum(candidates_evaluations.values()) / len(candidates_evaluations)
            proportional_sharpness = best_eval - average_eval
            return proportional_sharpness / (1 - proportional_sharpness)
        elif heuristic == "evaluation_depth_analysis":
            depths = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15]

            evaluations = self.engine_multidepth_evaluations(engine=engines["stockfish"], depths=depths)

            if self.engine_evaluation_depth > 15:  # Even more accurate 'best' evaluation easily available
                best_eval = [self.best_engine_move(engine=engines["stockfish"], depth=self.engine_evaluation_depth), self.stockfish_evaluation(engine=engines["stockfish"], depth=self.engine_evaluation_depth)]
            else:
                best_eval = evaluations[max(depths)]
                del evaluations[max(depths)]

            def one_sharpness(this_evaluation):
                if this_evaluation[0] != best_eval[0]:
                    return abs(this_evaluation[1] - best_eval[1])
                return 0

            sharpnesses = [one_sharpness(i) for k, i in evaluations.items() if k <= 10 and k > 3]
            return max(sharpnesses) / (1 - max(sharpnesses))
        else:
            raise ValueError(f"Unknown heuristic {heuristic}")
        
    def recursive_lichess_stats(self, 
                                side, 
                                move_selection_function, 
                                master: bool, 
                                current_frequency, 
                                min_frequency,
                                min_games,
                                effect_cap: float):
        """
        Helper for applying recursive evaluation functions.
        """
        if master:
            base_eval = self.lichess_master_white_evaluation_historic
            game_count = self.lichess_master_game_count
            move_frequencies = self.lichess_master_move_frequencies
        else:
            base_eval = self.lichess_white_evaluation_historic
            game_count = self.lichess_game_count
            move_frequencies = self.lichess_move_frequencies

        if self.board.turn == side:
            # Use the engine best move
            next_node = self.position_from_move(move_selection_function(self, current_frequency))
            return next_node.recursive_lichess_stats(side=side, 
                                                     move_selection_function=move_selection_function, 
                                                     master=master,
                                                     current_frequency=current_frequency,
                                                     min_frequency=min_frequency,
                                                     min_games=min_games,
                                                     effect_cap=effect_cap)

        if (current_frequency < min_frequency) or (game_count < min_games) or (move_frequencies is None):
            return base_eval

        subvariations_accounted_for = 0  # frequency allocation so infrequent children can just be guessed
        expected_eval = 0
        for move, frequency in move_frequencies.items():
            this_frequency = frequency * current_frequency
            if (this_frequency >= min_frequency) and (game_count * frequency >= min_games):
                next_node = self.position_from_move(move)
                expected_eval += next_node.recursive_lichess_stats(side=side, 
                                                                   move_selection_function=move_selection_function, 
                                                                   master=master,
                                                                   current_frequency=this_frequency,
                                                                   min_frequency=min_frequency,
                                                                   min_games=min_games,
                                                                   effect_cap=effect_cap) * frequency
                subvariations_accounted_for += frequency
        
        expected_eval += (1 - subvariations_accounted_for) * base_eval

        expected_eval = max(expected_eval, base_eval - effect_cap)
        expected_eval = min(expected_eval, base_eval + effect_cap)

        return expected_eval
        
    def holistic_best_move(self,
                           engines,
                           min_depth=35,
                           leela_nodes=10_000,
                           engine_node_weight=0.01,
                           lichess_master_game_weight=1,
                           lichess_game_weight=0,
                           min_probabilistic_eval_likelihood=0.1,
                           current_likelihood=1,
                           min_weight=30,
                           debug_positions=None,
                           probabilistic_effect_cap=0.01,
                           engine_weight_capcollar=((30, (1.0, 1.0)), (100, (0.95, 0.99)), (500, (0.97, 0.99)), (1_000, (0.9, 0.95)), (10_000, (0.8, 0.9)), (100_000, (0.75, 0.8)))) -> Dict:
        """
        Combines Stockfish, Leela, Master Stats & Amateur Stats to find an overall best move.
        """

        def move_selection_function_for_recursion(y: zPosition, likelihood: float):
            return y.holistic_best_move(engines=engines,
                                        min_depth=min_depth,
                                        leela_nodes=leela_nodes,
                                        engine_node_weight=engine_node_weight,
                                        lichess_master_game_weight=lichess_master_game_weight,
                                        lichess_game_weight=lichess_game_weight,
                                        min_probabilistic_eval_likelihood=min_probabilistic_eval_likelihood,
                                        current_likelihood=likelihood,
                                        min_weight=min_weight,
                                        debug_positions=debug_positions,
                                        engine_weight_capcollar=engine_weight_capcollar,
                                        probabilistic_effect_cap=probabilistic_effect_cap)["move"]

        side = self.board.turn

        # Loop through each possible move and evaluate it with engine & lichess stats
        # Note: pv never really needs to be >1 with this system, just evaluate on each child node instead
        best_move_so_far = None
        best_move_evaluation = None
        
        ######################if (self.lichess_master_game_count * lichess_master_game_weight) + (self.lichess_game_count * lichess_game_weight) <= 30:

        # Have to evaluate all positions properly and then adjust each evaluation to a 'loss from best' basis
        candidates_moves = self.board.legal_moves
        candidates_moves_uci = {move: move.uci() for move in candidates_moves}
        candidates_positions = {move: self.position_from_move(candidates_moves_uci[move]) for move in candidates_moves}
        
        if engine_node_weight != 0:
            candidates_engine_evaluations = {move: candidates_positions[move].engine_evaluation(engines=engines, depth=min_depth, leela_nodes=leela_nodes) for move in candidates_moves}  # Could be min_depth -1 but this will probably save processing in long run
            candidates_probabilistic_evals = {move: candidates_positions[move].probabilistic_engine_evaluation(engines=engines, side=side, min_likelihood=min_probabilistic_eval_likelihood, starting_likelihood=current_likelihood, leela_nodes=leela_nodes, min_depth=min_depth, effect_cap=probabilistic_effect_cap) for move in candidates_moves}
            candidates_gross_engine_weights = {move: candidates_positions[move].engine_evaluation_nodes * engine_node_weight for move in candidates_moves}
            
            # The engine evaluation delta is measured against the top move, the others against the weighted average. This is to try to avoid outliers in the other two. Min depth guards against engine outliers.
            # engine_evaluation_weighted_average = sum({move: candidates_engine_evaluations[move] * candidates_gross_engine_weights[move] for move in candidates_moves}.values()) / sum(candidates_gross_engine_weights.values())
            if side == chess.WHITE:
                engine_evaluation_best = max(candidates_engine_evaluations.values())
                engine_evaluation_best_prob = max(candidates_probabilistic_evals.values())
            else:
                engine_evaluation_best = min(candidates_engine_evaluations.values())
                engine_evaluation_best_prob = min(candidates_probabilistic_evals.values())
            candidates_engine_evaluations_delta = {move: candidates_engine_evaluations[move] - engine_evaluation_best for move in candidates_moves}
            candidates_engine_evaluations_probabilistic_delta = {move: candidates_probabilistic_evals[move] - engine_evaluation_best_prob for move in candidates_moves}
            # candidates_engine_evaluations_delta = {move: candidates_engine_evaluations[move] - engine_evaluation_weighted_average for move in candidates_moves}
        else:
            candidates_engine_evaluations = {move: 0 for move in candidates_moves}
            candidates_engine_evaluations_delta = {move: 0 for move in candidates_moves}
            candidates_engine_evaluations_probabilistic_delta = {move: 0 for move in candidates_moves}
        
        if (lichess_game_weight != 0) and (self.lichess_game_count * lichess_game_weight >= min_weight):
            candidates_lichess_evaluations = {move: candidates_positions[move].lichess_white_evaluation_historic for move in candidates_moves}
            # candidates_lichess_evaluations_recursive = {move: candidates_positions[move].recursive_lichess_stats(side=side,
            #                                                                                                      move_selection_function=move_selection_function_for_recursion,
            #                                                                                                      master=False,
            #                                                                                                      current_frequency=current_likelihood,
            #                                                                                                      min_frequency=min_probabilistic_eval_likelihood,
            #                                                                                                      min_games=min_weight / lichess_game_weight,
            #                                                                                                      effect_cap=1.5) for move in candidates_moves}
            candidates_gross_lichess_weights = {move: candidates_positions[move].lichess_game_count * lichess_game_weight for move in candidates_moves}
            sum_gross_lichess_weight = sum(candidates_gross_lichess_weights.values())
            if sum_gross_lichess_weight != 0:
                lichess_evaluation_weighted_average = sum({move: candidates_lichess_evaluations[move] * candidates_gross_lichess_weights[move] for move in candidates_moves}.values()) / sum_gross_lichess_weight
                # lichess_evaluation_weighted_average_rec = sum({move: candidates_lichess_evaluations_recursive[move] * candidates_gross_lichess_weights[move] for move in candidates_moves}.values()) / sum_gross_lichess_weight
            else:
                lichess_evaluation_weighted_average = 0.5
                # candidates_lichess_evaluations_recursive = 0.5
            candidates_lichess_evaluations_deltas = {move: candidates_lichess_evaluations[move] - lichess_evaluation_weighted_average for move in candidates_moves}
            # candidates_lichess_evaluations_recursive_deltas = {move: candidates_lichess_evaluations_recursive[move] - lichess_evaluation_weighted_average_rec for move in candidates_moves}
        else:
            candidates_lichess_evaluations = {move: 0 for move in candidates_moves}
            candidates_gross_lichess_weights = {move: 0 for move in candidates_moves}
            candidates_lichess_evaluations_deltas = {move: 0 for move in candidates_moves}
            # candidates_lichess_evaluations_recursive_deltas = {move: 0 for move in candidates_moves}
        
        if (lichess_master_game_weight != 0) and (self.lichess_master_game_count * lichess_master_game_weight >= min_weight):
            candidates_lichess_master_evaluations = {move: candidates_positions[move].lichess_master_white_evaluation_historic for move in candidates_moves}
            # candidates_lichess_master_evaluations_recursive = {move: candidates_positions[move].recursive_lichess_stats(side=side,
            #                                                                                                             move_selection_function=move_selection_function_for_recursion,
            #                                                                                                             master=True,
            #                                                                                                             current_frequency=current_likelihood,
            #                                                                                                             min_frequency=min_probabilistic_eval_likelihood,
            #                                                                                                             min_games=min_weight / lichess_master_game_weight,
            #                                                                                                             effect_cap=1.5) for move in candidates_moves}
            candidates_gross_lichess_master_weights = {move: candidates_positions[move].lichess_master_game_count * lichess_master_game_weight for move in candidates_moves}
            sum_gross_master_weight = sum(candidates_gross_lichess_master_weights.values())
            if sum_gross_master_weight != 0:
                lichess_master_evaluation_weighted_average = sum({move: candidates_lichess_master_evaluations[move] * candidates_gross_lichess_master_weights[move] for move in candidates_moves}.values()) / sum_gross_master_weight
                # lichess_master_evaluation_weighted_average_rec = sum({move: candidates_lichess_master_evaluations_recursive[move] * candidates_gross_lichess_master_weights[move] for move in candidates_moves}.values()) / sum_gross_master_weight
            else:
                lichess_master_evaluation_weighted_average = 0.5
                # lichess_master_evaluation_weighted_average_rec = 0.5
            candidates_lichess_master_evaluations_deltas = {move: candidates_lichess_master_evaluations[move] - lichess_master_evaluation_weighted_average for move in candidates_moves}
            # candidates_lichess_master_evaluations_recursive_deltas = {move: candidates_lichess_master_evaluations_recursive[move] - lichess_master_evaluation_weighted_average_rec for move in candidates_moves}
        else:
            candidates_lichess_master_evaluations = {move: 0 for move in candidates_moves}
            candidates_gross_lichess_master_weights = {move: 0 for move in candidates_moves}
            candidates_lichess_master_evaluations_deltas = {move: 0 for move in candidates_moves}
            # candidates_lichess_master_evaluations_recursive_deltas = {move: 0 for move in candidates_moves}
        
        candidates_gross_total_weights = {move: candidates_gross_engine_weights[move] + candidates_gross_lichess_weights[move] + candidates_gross_lichess_master_weights[move] for move in candidates_moves}
        candidates_gross_all_lichess_weights = {move: candidates_gross_lichess_weights[move] + candidates_gross_lichess_master_weights[move] for move in candidates_moves}

        candidates_initial_weights = dict()
        candidates_final_weights = dict()
        candidates_final_evaluations = dict()
        for candidate_move in candidates_moves:
            for lower_weights, upper_weights in zip(engine_weight_capcollar[:-1], engine_weight_capcollar[1:]):
                if candidates_gross_all_lichess_weights[candidate_move] < upper_weights[0]:
                    this_bounded_game_count = max(candidates_gross_all_lichess_weights[candidate_move], lower_weights[0])
                    game_count_weight_point = (this_bounded_game_count - lower_weights[0]) / (upper_weights[0] - lower_weights[0])
                    this_cap = upper_weights[1][1] * game_count_weight_point + lower_weights[1][1] * (1 - game_count_weight_point)
                    this_collar = upper_weights[1][0] * game_count_weight_point + lower_weights[1][0] * (1 - game_count_weight_point)
                    break
            else:
                # Above the highest band
                this_cap = engine_weight_capcollar[-1][1][1]
                this_collar = engine_weight_capcollar[-1][1][0]
            
            pre_capcol_engine_weight = candidates_gross_engine_weights[candidate_move] / candidates_gross_total_weights[candidate_move]
            this_engine_weight = min(max(pre_capcol_engine_weight, this_collar), this_cap)
            if pre_capcol_engine_weight != 1:
                non_engine_capcol_multiplier = (1 - this_engine_weight) / (1 - pre_capcol_engine_weight)
            else:
                non_engine_capcol_multiplier = 0
            
            this_lichess_weight = candidates_gross_lichess_weights[candidate_move] * non_engine_capcol_multiplier / candidates_gross_total_weights[candidate_move]
            this_lichess_master_weight = candidates_gross_lichess_master_weights[candidate_move] * non_engine_capcol_multiplier / candidates_gross_total_weights[candidate_move]

            candidate_weighted_evaluation = (candidates_engine_evaluations_probabilistic_delta[candidate_move] * this_engine_weight) + (candidates_lichess_evaluations_deltas[candidate_move] * this_lichess_weight) + (candidates_lichess_master_evaluations_deltas[candidate_move] * this_lichess_master_weight)
            candidates_final_evaluations[candidate_move] = candidate_weighted_evaluation
            candidates_initial_weights[candidate_move] = f"(Engine {pre_capcol_engine_weight:.2f})(Lichess {candidates_gross_lichess_weights[candidate_move] / candidates_gross_total_weights[candidate_move]:.2f})(Master {candidates_gross_lichess_master_weights[candidate_move] / candidates_gross_total_weights[candidate_move]:.2f})"
            candidates_final_weights[candidate_move] = f"(Engine {this_engine_weight:.2f})(Lichess {this_lichess_weight:.2f})(Master {this_lichess_master_weight:.2f})"

            if best_move_evaluation is None:
                best_move_so_far = candidate_move
                best_move_evaluation = candidate_weighted_evaluation
                best_engine_weight = this_engine_weight
                best_lichess_weight = this_lichess_weight
                best_lichess_master_weight = this_lichess_master_weight
                continue
            if side == chess.WHITE:
                if best_move_evaluation < candidate_weighted_evaluation:
                    best_move_so_far = candidate_move
                    best_move_evaluation = candidate_weighted_evaluation
                    best_engine_weight = this_engine_weight
                    best_lichess_weight = this_lichess_weight
                    best_lichess_master_weight = this_lichess_master_weight
            else:
                if best_move_evaluation > candidate_weighted_evaluation:
                    best_move_so_far = candidate_move
                    best_move_evaluation = candidate_weighted_evaluation
                    best_engine_weight = this_engine_weight
                    best_lichess_weight = this_lichess_weight
                    best_lichess_master_weight = this_lichess_master_weight
        
        if best_move_so_far is not None:
            if self.fen in debug_positions.keys():
                # Check out:
                # candidates_engine_evaluations_delta
                # candidates_lichess_evaluations_deltas
                # candidates_lichess_master_evaluations_deltas
                # candidates_final_evaluations
                # candidates_final_weights
                eval_frame = pd.concat([pd.Series(candidates_engine_evaluations_delta, name="engine"), 
                                        pd.Series(candidates_engine_evaluations_probabilistic_delta, name="engine_probabilistic"),
                                        pd.Series(candidates_lichess_evaluations_deltas, name="lichess"), 
                                        # pd.Series(candidates_lichess_evaluations_recursive_deltas, name="lichess_recursive"),
                                        pd.Series(candidates_lichess_master_evaluations_deltas, name="master"), 
                                        # pd.Series(candidates_lichess_master_evaluations_recursive_deltas, name="master_recursive"),
                                        pd.Series(candidates_final_evaluations, name="final"), 
                                        pd.Series(candidates_gross_all_lichess_weights, name="lichess_total_weight"),
                                        # pd.Series(candidates_initial_weights, name="initial_weights"),
                                        pd.Series(candidates_final_weights, name="final_weights")], axis=1).sort_values(by="final")
                print(f"Debug position: {self.fen} ({debug_positions[self.fen]})")
                print(eval_frame)
                print("...")
            
        return {
            "move": best_move_so_far,
            "holistic_evaluation": best_move_evaluation,
            "engine_evaluation_delta": candidates_engine_evaluations_delta[best_move_so_far],
            "probabilistic_engine_evaluation_delta": candidates_engine_evaluations_probabilistic_delta[best_move_so_far],
            "lichess_delta": candidates_lichess_evaluations_deltas[best_move_so_far],
            # "lichess_recursive_delta": candidates_lichess_evaluations_recursive_deltas[best_move_so_far],
            "master_delta": candidates_lichess_master_evaluations_deltas[best_move_so_far],
            # "master_recursive_delta": candidates_lichess_master_evaluations_recursive_deltas[best_move_so_far],
            "engine_weight": best_engine_weight,
            "lichess_weight": best_lichess_weight,
            "master_weight": best_lichess_master_weight
        }

    def create_weighted_average_opening_training(self, 
                                                 engines, 
                                                 side=chess.WHITE, 
                                                 min_depth=35, 
                                                 leela_nodes=10_000,
                                                 min_likelihood=0.1,
                                                 min_probabilistic_eval_likelihood=0.1,
                                                 sharpness_baseline=0.033,
                                                 sharpness_frequency_override=0.99,
                                                 min_games=30,
                                                 engine_node_weight=0.01,
                                                 lichess_game_weight=0,
                                                 lichess_master_game_weight=1,
                                                 debug_positions=dict(),
                                                 min_illustrative_depth=5,
                                                 probabilistic_effect_cap=0.01,
                                                 engine_weight_capcollar=((30, (1.0, 1.0)), (100, (0.95, 0.99)), (500, (0.97, 0.99)), (1_000, (0.9, 0.95)), (10_000, (0.8, 0.9)), (100_000, (0.75, 0.8)))):
        """
        Our best move is a weighted average of the engine evaluation and the lichess historic evaluation, depending on how many games & nodes on each side.
        :param side: Which side to find the optimum moves for. The resulting repertoire will include all common moves from the other side.
        :param min_depth: The minimum analysis depth for the given engine move.
        :param min_likelihood: The minimum likelihood of observing a given variation for it to be included. 0.01 means at least once in 100 games according to lichess stats.
        :param current_likelihood: The current likelihood of observing the variation up until this position. Do not set this manually.
        :param engine_node_weight: The weight assigned to the engine evaluation for each node scanned
        :param lichess_game_weight: The weight assigned to the lichess evaluation for each historic lichess game
        :param lichess_master_game_weight: The weight assigned to the lichess master evaluation for each historic lichess master game
        :param engine_weight_capcollar: The minimum and maximum weight given to the engine prediction compared to the lichess evaluation at different amounts of lichess game totals. Linear interp between them.
        :param min_games: The minimum number of games to trust lichess move chance %
        :param sharpness_baseline: Sharpness is approximately (for null model heuristic) ~0.178 for a closed opening like the English, and ~0.221 for the sicilian defence
            Sharper positions will be explored more thoroughly, proportional to the overall sharpness of the line.
        :param sharpness_frequency_override: If a position is at least as sharp as this (ignoring baseline), then it will be explored almost regardless of how frequently the position arises
        """

        game = chess.pgn.Game.from_board(self.board)
        total_progress = 0
        
        def iterate_game(game_node: chess.pgn.GameNode, 
                         total_progress, 
                         current_likelihood=1, 
                         min_depth=15, 
                         current_depth=1,
                         current_illustrative_depth=0) -> float:
            """Returns current progress"""
            initial_progress = total_progress

            this_fen = game_node.board().fen()
            this_position = zPosition(fen=this_fen)

            if this_fen in debug_positions.keys():
                print("Debug pos")
                test_eval = this_position.engine_evaluation(engines=engines, depth=min_depth, leela_nodes=leela_nodes)

            if game_node.turn() == side:
                # Loop through each possible move and evaluate it with engine & lichess stats
                # Note: pv never really needs to be >1 with this system, just evaluate on each child node instead
                best_move = this_position.holistic_best_move(
                    engines=engines,
                    min_depth=min_depth,
                    leela_nodes=leela_nodes,
                    engine_node_weight=engine_node_weight,
                    lichess_master_game_weight=lichess_master_game_weight,
                    lichess_game_weight=lichess_game_weight,
                    min_probabilistic_eval_likelihood=min_probabilistic_eval_likelihood,
                    current_likelihood=current_likelihood,
                    min_weight=min_games,
                    debug_positions=debug_positions,
                    engine_weight_capcollar=engine_weight_capcollar,
                    probabilistic_effect_cap=probabilistic_effect_cap)
                
                logging.info(f"Appending best holistic move after FEN: {this_fen} - {game_node.board().san(best_move['move'])}:")
                logging.info(f"- Sharpness {this_position.sharpness(engines=engines, min_depth=min_depth, heuristic='evaluation_depth_analysis'):.3f}")

                comment=f"Holistic move:"
                comment += f"\nEngine Evaluation: {this_position.engine_evaluation(engines=engines, depth=min_depth, leela_nodes=leela_nodes):.3f}"
                comment += f"\nHolistic Evaluation: {best_move['holistic_evaluation']:.1f}"
                comment += f"\nDepth: {this_position.engine_evaluation_depth}"
                comment += f"\nNodes: {this_position.engine_evaluation_nodes}."
                comment += f"\nFrequency: {current_likelihood:.4f}"
                comment += f"\nEngine Evaluation Delta: {best_move['engine_evaluation_delta']}"
                comment += f"\nProbabilistic Engine Evaluation Delta: {best_move['probabilistic_engine_evaluation_delta']}"
                comment += f"\nLichess Delta: {best_move['lichess_delta']}"
                # comment += f"\nLichess Recursive Delta: {best_move['lichess_recursive_delta']}"
                comment += f"\nMaster Delta: {best_move['master_delta']}"
                # comment += f"\nMaster Recursive Delta: {best_move['master_recursive_delta']}"
                comment += f"\nEngine Weight: {best_move['engine_weight']}"
                comment += f"\nLichess Weight: {best_move['lichess_weight']}"
                comment += f"\nMaster Weight: {best_move['master_weight']}"

                next_node = game_node.add_variation(best_move["move"],
                                                    comment=comment)
                best_position = this_position.position_from_move(best_move["move"].uci())
                
                total_progress = iterate_game(next_node, 
                                              total_progress=total_progress, 
                                              current_likelihood=current_likelihood, 
                                              current_depth=current_depth+1,
                                              current_illustrative_depth=current_illustrative_depth)
            else:
                # Figure out which enemy moves are worth including in training data
                # Typically because their frequency * sharpness is high enough
                has_subvariations = False
                if (this_position.lichess_game_count + this_position.lichess_master_game_count >= min_games) and (current_likelihood != 0) and (this_position.lichess_move_frequencies is not None):
                    for move, frequency in this_position.lichess_move_frequencies.items():
                        total_frequency = frequency * current_likelihood
                        next_position = this_position.position_from_move(move)
                        next_sharpness = next_position.sharpness(engines=engines, heuristic="evaluation_depth_analysis")
                        total_priority = frequency * current_likelihood * max(1, next_sharpness / sharpness_baseline)
                        
                        frequent_enough = total_priority >= min_likelihood
                        if frequent_enough:
                            logging.info(f"Appending common enough response ({total_frequency*100:.2f}%) after FEN: {this_fen} - {game_node.board().san(chess.Move.from_uci(move))} - Sharpness: {next_sharpness} - Priority: {total_priority:.2f}")
                            comment = "Common response. "
                        else:
                            frequent_enough = frequent_enough or (next_sharpness >= sharpness_frequency_override)
                            if frequent_enough:
                                logging.info(f"Appending sharp line response due to override ({next_sharpness:.2f}S) after FEN: {this_fen} - {game_node.board().san(chess.Move.from_uci(move))} - Sharpness: {next_sharpness} - Priority: {total_priority:.2f}")
                                comment = "Sharp line. "

                        if frequent_enough:
                            has_subvariations = True
                            comment = comment + f"LE: {next_position.lichess_white_evaluation_historic*100:.1f}. LM: {next_position.lichess_master_white_evaluation_historic*100:.1f}. LN: {next_position.lichess_game_count}. F%: {total_frequency*100:.2f}."
                            next_node = game_node.add_variation(chess.Move.from_uci(move), comment=comment)
                            total_progress = iterate_game(next_node, 
                                                          total_progress=total_progress, 
                                                          current_likelihood=total_frequency, 
                                                          current_depth=current_depth+1,
                                                          current_illustrative_depth=0)

                if not has_subvariations:
                    total_progress += current_likelihood

                    # Add illustrative moves at the end! At the moment just one in each position
                    if current_illustrative_depth < min_illustrative_depth:
                        logging.info(f"Appending illustrative engine move after FEN: {this_fen} - {game_node.board().san(this_position.best_engine_move(engine=engines['stockfish'], depth=min_depth))}")
                        comment=f"Illustrative engine move. EE: {this_position.engine_evaluation(engines=engines, depth=min_depth, leela_nodes=leela_nodes):.3f}. D: {this_position.engine_evaluation_depth}. N: {this_position.engine_evaluation_nodes}. F: {current_likelihood:.4f}."
                        next_node = game_node.add_variation(this_position.best_engine_move(engine=engines["stockfish"], depth=min_depth),
                                                            comment=comment)
                        total_progress = iterate_game(next_node, 
                                                      total_progress=total_progress, 
                                                      current_likelihood=0, 
                                                      current_depth=current_depth+1,
                                                      current_illustrative_depth=current_illustrative_depth+1)
                else:
                    total_progress = initial_progress + current_likelihood
                    logging.info(f"Total progress: {total_progress*100}%")

            return total_progress

        iterate_game(game, total_progress=total_progress)
        game.headers["Event"] = f"create_weighted_average_opening_training"
        game.headers["Date"] = datetime.now().__str__()
        if side == chess.WHITE:
            game.headers["White"] = username
        else:
            game.headers["Black"] = username

        game.headers["min_depth"] = str(min_depth)
        game.headers["min_likelihood"] = str(min_likelihood)
        game.headers["min_games"] = str(min_games)
        game.headers["engine_node_weight"] = str(engine_node_weight)
        game.headers["lichess_game_weight"] = str(lichess_game_weight)
        game.headers["lichess_master_game_weight"] = str(lichess_master_game_weight)
        game.headers["engine_weight_capcollar"] = engine_weight_capcollar

        return game

if __name__ == "__main__":
    import psutil
    engines = {
        "stockfish": chess.engine.SimpleEngine.popen_uci(r"C:\\Users\\REDACTED_USER\\PycharmProjects\\chess_analysis\\engines\\stockfish_15.1_win_x64_avx2\\stockfish-windows-2022-x86-64-avx2.exe"),
        "leela": chess.engine.SimpleEngine.popen_uci(r"C:\\Users\\REDACTED_USER\\PycharmProjects\\chess_analysis\\engines\\lc0-v0.29.0-windows-gpu-nvidia-cuda\\lc0.exe")
    }
    threads: int = int(psutil.cpu_count(logical=True) - 3)  # almost all logical CPU cores
    hash: int = int(psutil.virtual_memory().available / 1024 / 1024 * 0.3)  # 75% of available RAM
    engines["stockfish"].configure({"Hash": hash})
    engines["stockfish"].configure({"Threads": threads})

    a = zPosition()
 
    # Depth of 21 can hit lichess rate limit, 22 seems like the best 'quick' number
    # Big time increase after 40
    # 35 seems doable for smaller repertoires
    MIN_DEPTH = 25
    LEELA_NODES = 10_000
    MIN_LIKELIHOOD = 0.04
    MIN_PROBABILISTIC_EVALUATION_LIKELIHOOD = 0.01
    PROBABILISTIC_EFFECT_CAP = 0.01
    OUT_POSTFIX = "_repertoire"
    MIN_ILLUSTRATIVE_DEPTH = 0

    # For weighted average repertoire
    STOCKFISH_LEELA_WEIGHT=0.5
    ENGINE_NODE_WEIGHT=0.000002
    LICHESS_GAME_WEIGHT=0.001
    MASTER_GAME_WEIGHT=1
    DEBUG_POSITIONS = {chess.STARTING_FEN: "Starting position",
                       "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2": "Sicilian",
                       "rnbqkbnr/pp1p1ppp/4p3/8/3NP3/8/PPP2PPP/RNBQKB1R b KQkq - 0 4": "French Sicilian",
                       "rnbqkb1r/pp2pppp/3p1n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R b KQkq - 2 5": "Open Sicilian decision point",  # 
                       "rnbqkbnr/1p1p1ppp/p3p3/8/3NP3/2N5/PPP2PPP/R1BQKB1R b KQkq - 1 5": "Kan Sicilian",  # 
    }
    ENGINE_WEIGHT_CAPCOLLAR=((300, (1.0, 0.99)), (1_000, (0.98, 0.99)), (5_000, (0.95, 0.98)), (10_000, (0.70, 0.80)), (100_000, (0.5, 0.65)), (500_000, (0.4, 0.41)))

    black_repertoire = a.create_weighted_average_opening_training(engines=engines, 
                                                                  side=chess.BLACK, 
                                                                  min_depth=MIN_DEPTH, 
                                                                  leela_nodes=LEELA_NODES,
                                                                  min_likelihood=MIN_LIKELIHOOD,
                                                                  min_probabilistic_eval_likelihood=MIN_PROBABILISTIC_EVALUATION_LIKELIHOOD,
                                                                  engine_node_weight=ENGINE_NODE_WEIGHT,
                                                                  lichess_game_weight=LICHESS_GAME_WEIGHT,
                                                                  lichess_master_game_weight=MASTER_GAME_WEIGHT,
                                                                  debug_positions=DEBUG_POSITIONS,
                                                                  engine_weight_capcollar=ENGINE_WEIGHT_CAPCOLLAR,
                                                                  min_illustrative_depth=MIN_ILLUSTRATIVE_DEPTH,
                                                                  probabilistic_effect_cap=PROBABILISTIC_EFFECT_CAP)
    print("Black repertoire:")
    print(black_repertoire)
    print(black_repertoire, file=open(f"black{OUT_POSTFIX}.pgn", "w"), end="\n\n")

    white_repertoire = a.create_weighted_average_opening_training(engines=engines, 
                                                                  min_depth=MIN_DEPTH, 
                                                                  leela_nodes=LEELA_NODES,
                                                                  min_likelihood=MIN_LIKELIHOOD,
                                                                  min_probabilistic_eval_likelihood=MIN_PROBABILISTIC_EVALUATION_LIKELIHOOD,
                                                                  engine_node_weight=ENGINE_NODE_WEIGHT,
                                                                  lichess_game_weight=LICHESS_GAME_WEIGHT,
                                                                  lichess_master_game_weight=MASTER_GAME_WEIGHT,
                                                                  debug_positions=DEBUG_POSITIONS,
                                                                  engine_weight_capcollar=ENGINE_WEIGHT_CAPCOLLAR,
                                                                  min_illustrative_depth=MIN_ILLUSTRATIVE_DEPTH,
                                                                  probabilistic_effect_cap=PROBABILISTIC_EFFECT_CAP)
    print("White repertoire:")
    print(white_repertoire)
    print(white_repertoire, file=open(f"white{OUT_POSTFIX}.pgn", "w"), end="\n\n")

    print("Finished.")
