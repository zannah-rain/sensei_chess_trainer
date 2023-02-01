from __future__ import annotations
from typing import List, Optional, Dict
import chess
import chess.engine
import chess.pgn
import json
import pathlib
import logging
import requests
import time
from datetime import datetime


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

        self._cached_engine_evaluation = None

        self._cached_lichess_stats = None
        self._cached_lichess_master_stats = None

        # For representing internal state of board
        # Can't use a trivial BaseBoard, as we need extra information about whether people can still castle etc.
        self._board = None
        self.fen = fen

        if self.cache_path.exists():
            logging.debug(f"Reloading FEN {self.fen} from cache.")
            with open(self.cache_path, "r") as f:
                self.from_dict(json.load(f))
        else:
            logging.debug(f"Initialising FEN {self.fen} from scratch.")
        
    @property
    def lichess_stats(self):
        if self._cached_lichess_stats is None:
            self._cached_lichess_stats = self.call_lichess_api()
            self.save()
            logging.debug(f"Cached lichess stats for FEN: {self.fen}")
        
        return self._cached_lichess_stats
    
    @property
    def lichess_master_stats(self):
        if self._cached_lichess_master_stats is None:
            self._cached_lichess_master_stats = self.call_lichess_api(master=True)
            self.save()
            logging.debug(f"Cached lichess master stats for FEN: {self.fen}")
        
        return self._cached_lichess_master_stats
    
    @property
    def lichess_move_frequencies(self):
        return {move["uci"]: (move["white"] + move["black"] + move["draws"]) / self.lichess_game_count
                for move in self.lichess_stats["moves"]}
    
    @property
    def lichess_master_white_evaluation_historic(self):
        if self.lichess_master_game_count == 0:
            return 0.5
        return (self.lichess_master_stats["white"] + self.lichess_master_stats["draws"] / 2) / self.lichess_master_game_count
    
    @property
    def lichess_master_game_count(self):
        return self.lichess_master_stats["white"] + self.lichess_master_stats["black"] + self.lichess_master_stats["draws"]

    @property
    def lichess_white_evaluation_historic(self):
        if self.lichess_game_count == 0:
            return 0.5
        return (self.lichess_stats["white"] + self.lichess_stats["draws"] / 2) / self.lichess_game_count
    
    @property
    def lichess_game_count(self):
        return (self.lichess_stats["white"] + self.lichess_stats["black"] + self.lichess_stats["draws"])

    @property
    def board(self):
        if self._board is None:
            self._board = chess.Board(fen=self.fen)
        return self._board

    @property
    def cache_path(self) -> pathlib.Path:
        path_safe_fen = self.fen.replace("/", "_")
        return pathlib.Path(f"position_cache/{path_safe_fen}.fen")
    
    @property
    def engine_evaluation_depth(self):
        if self._cached_engine_evaluation is None:
            return 0
        
        return self._cached_engine_evaluation[0]["depth"]
    
    @property
    def engine_evaluation_nodes(self):
        if self._cached_engine_evaluation is None:
            return 0

        if "nodes" not in self._cached_engine_evaluation[0].keys():
            return 1  # Seems to happen when the engine found a forced win/loss

        return self._cached_engine_evaluation[0]["nodes"]

    def engine_evaluation(self, engine, depth=35, multipv=1):
        if self.engine_evaluation_depth < depth:
            engine_eval = engine.analyse(self.board, chess.engine.Limit(depth=depth), multipv=multipv)
            engine_eval[0]["score"] = engine_eval[0]["score"].white().wdl().expectation()  # Converting to json friendly format
            if "pv" in engine_eval[0].keys():
                engine_eval[0]["pv"] = [i.uci() for i in engine_eval[0]["pv"]]  # Converting to json friendly format
            if "currmove" in engine_eval[0].keys():
                engine_eval[0]["currmove"] = engine_eval[0]["currmove"].uci()
            self._cached_engine_evaluation = engine_eval
            self.save()
            this_score = engine_eval[0]["score"]
            logging.info(f"Saved new engine evaluation of FEN: {self.fen}. Eval: {this_score}")
            logging.debug(f"Full evaluation: {self._cached_engine_evaluation}")
        
        return self._cached_engine_evaluation[0]["score"]
    
    def best_engine_move(self, engine, depth=35) -> str:
        """Returns the UCI move recommended by the engine."""
        self.engine_evaluation(engine=engine, depth=depth)
        return self._cached_engine_evaluation[0]["pv"][0]

    def to_dict(self):
        return {
            "fen": self.fen,
            "parents": self.parents,
            "children": self.children,
            "comment": self.comment,
            "_cached_engine_evaluation": self._cached_engine_evaluation,
            "_cached_lichess_stats": self._cached_lichess_stats,
            "_cached_lichess_master_stats": self._cached_lichess_master_stats
        }
    
    def from_dict(self, x):
        self.parents = x["parents"]
        self.children = x["children"]
        self.comment = x["comment"]
        self.fen = x["fen"]
        self._cached_engine_evaluation = x["_cached_engine_evaluation"]

        if "_cached_lichess_stats" in x.keys():
            self._cached_lichess_stats = x["_cached_lichess_stats"]
        if "_cached_lichess_master_stats" in x.keys():
            self._cached_lichess_master_stats = x["_cached_lichess_master_stats"]

    def save(self):
        with open(self.cache_path, "w") as f:
            json.dump(self.to_dict(), fp=f, indent=4)

    @staticmethod
    def load(file):
        with open(file, "r") as f:
            return zPosition.from_dict(json.load(fp=f))

    def call_lichess_api(self, master : bool = False):
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

        logging.debug(f"Downloading lichess stats for FEN: {self.fen}")
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

            logging.debug(f"Downloading lichess master stats for FEN: {self.fen}")

        while True:
            r = requests.get(url)
            if r.status_code == 429:
                logging.info(f"Hit Lichess API rate limit, waiting for 60 seconds")
                print('Rate limited - waiting 60s...')
                time.sleep(60)
            else:
                try:
                    response = r.json()
                    break
                except requests.JSONDecodeError:
                    pass

        return response
    
    def position_from_move(self, uci_move: str) -> zPosition:
        new_board = self.board.copy()
        new_board.push(chess.Move.from_uci(uci_move))
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
                logging.info(f"Appending best engine move after FEN: {this_fen} - {this_position.best_engine_move(engine=engine, depth=min_depth)}")
                comment=f"Engine move. EE: {this_position.engine_evaluation(engine=engine, depth=min_depth)}. D: {this_position.engine_evaluation_depth}. N: {this_position.engine_evaluation_nodes}. F: {current_likelihood}."
                next_node = game_node.add_variation(chess.Move.from_uci(this_position.best_engine_move(engine=engine, depth=min_depth)),
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

    def create_weighted_average_opening_training(self, 
                                                 engine, 
                                                 side=chess.WHITE, 
                                                 min_depth=35, 
                                                 min_likelihood=0.1,
                                                 min_games=250,
                                                 engine_node_weight=0.01,
                                                 lichess_game_weight=1,
                                                 engine_weight_capcollar=((1_000, (1.0, 1.0)), (10_000, (0.75, 1.0)), (100_000, (0.35, 0.65)), (1_000_000, (0.1, 0.2)), (1_000_000_000, (0.005, 0.01)))):
        """
        Our best move is a weighted average of the engine evaluation and the lichess historic evaluation, depending on how many games & nodes on each side.
        :param side: Which side to find the optimum moves for. The resulting repertoire will include all common moves from the other side.
        :param min_depth: The minimum analysis depth for the given engine move.
        :param min_likelihood: The minimum likelihood of observing a given variation for it to be included. 0.01 means at least once in 100 games according to lichess stats.
        :param current_likelihood: The current likelihood of observing the variation up until this position. Do not set this manually.
        :param engine_node_weight: The weight assigned to the engine evaluation for each node scanned
        :param lichess_game_weight: The weight assigned to the lichess evaluation for each historic lichess game
        :param engine_weight_capcollar: The minimum and maximum weight given to the engine prediction compared to the lichess evaluation at different amounts of lichess game totals. Linear interp between them.
        :param min_games: The minimum number of games to trust lichess move chance %
        """

        game = chess.pgn.Game.from_board(self.board)
        total_progress = 0
        
        def iterate_game(game_node: chess.pgn.GameNode, total_progress, current_likelihood=1):
            initial_progress = total_progress

            this_fen = game_node.board().fen()
            this_position = zPosition(fen=this_fen)
            if game_node.turn() == side:
                # Loop through each possible move and evaluate it with engine & lichess stats
                # Note: pv never really needs to be >1 with this system, just evaluate on each child node instead
                best_move_so_far = None
                best_move_evaluation = None
                for candidate_move in game_node.board().legal_moves:
                    candidate_position = this_position.position_from_move(candidate_move.uci())
                    candidate_engine_evaluation = candidate_position.engine_evaluation(engine=engine, depth=min_depth)  # Could be min_depth -1 but this will probably save processing in long run
                    candidate_lichess_evaluation = candidate_position.lichess_white_evaluation_historic
                    
                    for lower_weights, upper_weights in zip(engine_weight_capcollar[:-1], engine_weight_capcollar[1:]):
                        if candidate_position.lichess_game_count < upper_weights[0]:
                            this_bounded_game_count = max(candidate_position.lichess_game_count, lower_weights[0])
                            game_count_weight_point = (this_bounded_game_count - lower_weights[0]) / (upper_weights[0] - lower_weights[0])
                            this_cap = upper_weights[1][1] * game_count_weight_point + lower_weights[1][1] * (1 - game_count_weight_point)
                            this_collar = upper_weights[1][0] * game_count_weight_point + lower_weights[1][0] * (1 - game_count_weight_point)
                            break
                    else:
                        # Above the highest band
                        this_cap = engine_weight_capcollar[-1][1][1]
                        this_collar = engine_weight_capcollar[-1][1][0]

                    this_engine_weight = candidate_position.engine_evaluation_nodes * engine_node_weight / (candidate_position.engine_evaluation_nodes * engine_node_weight + candidate_position.lichess_game_count * lichess_game_weight)
                    this_engine_weight = min(max(this_engine_weight, this_collar), this_cap)

                    candidate_weighted_evaluation = (candidate_engine_evaluation * this_engine_weight) + (candidate_lichess_evaluation * (1 - this_engine_weight))

                    if best_move_evaluation is None:
                        best_move_so_far = candidate_move
                        best_move_evaluation = candidate_weighted_evaluation
                        best_engine_weight = this_engine_weight
                        continue
                    if side == chess.WHITE:
                        if best_move_evaluation < candidate_weighted_evaluation:
                            best_move_so_far = candidate_move
                            best_move_evaluation = candidate_weighted_evaluation
                            best_engine_weight = this_engine_weight
                    else:
                        if best_move_evaluation > candidate_weighted_evaluation:
                            best_move_so_far = candidate_move
                            best_move_evaluation = candidate_weighted_evaluation
                            best_engine_weight = this_engine_weight
                
                if best_move_so_far is not None:
                    best_position = this_position.position_from_move(best_move_so_far.uci())
                    logging.info(f"Appending best weighted move after FEN: {this_fen} - {best_move_so_far.uci()}")
                    comment=f"Weighted move. E: {best_move_evaluation}. EE: {best_position.engine_evaluation(engine=engine, depth=min_depth)}. D: {best_position.engine_evaluation_depth}. "
                    comment+=f"Node weight @{engine_node_weight}: {best_position.engine_evaluation_nodes * engine_node_weight}. Games: {best_position.lichess_game_count}. EW: {best_engine_weight} F: {current_likelihood}."
                    next_node = game_node.add_variation(best_move_so_far,
                                                        comment=comment)
                    total_progress = iterate_game(next_node, total_progress=total_progress, current_likelihood=current_likelihood)
            else:
                if this_position.lichess_game_count < min_games:
                    total_progress += current_likelihood
                    logging.info(f"No longer exploring after FEN: {this_fen} as only {this_position.lichess_game_count} games (< min_games of {min_games})")
                    return total_progress

                has_subvariations = False
                for move, frequency in this_position.lichess_move_frequencies.items():
                    total_frequency = frequency * current_likelihood
                    if total_frequency >= min_likelihood:
                        has_subvariations = True
                        logging.info(f"Appending common enough response ({total_frequency}) after FEN: {this_fen} - {move}")
                        comment=f"Common response. LE: {this_position.lichess_white_evaluation_historic}. LN: {this_position.lichess_game_count}. F: {total_frequency}."
                        next_node = game_node.add_variation(chess.Move.from_uci(move), comment=comment)
                        total_progress = iterate_game(next_node, total_progress=total_progress, current_likelihood=total_frequency)
                if not has_subvariations:
                    total_progress += current_likelihood
                else:
                    total_progress = initial_progress + current_likelihood
                    logging.info(f"Total progress: {total_progress*100}%")

            return total_progress

        iterate_game(game, total_progress=total_progress)
        game.headers["Event"] = f"create_weighted_average_opening_training"
        game.headers["Date"] = datetime.now().__str__()
        if side == chess.WHITE:
            game.headers["White"] = "ZannahRain"
        else:
            game.headers["Black"] = "ZannahRain"

        game.headers["min_depth"] = str(min_depth)
        game.headers["min_likelihood"] = str(min_likelihood)
        game.headers["min_games"] = str(min_games)
        game.headers["engine_node_weight"] = str(engine_node_weight)
        game.headers["lichess_game_weight"] = str(lichess_game_weight)
        game.headers["engine_weight_capcollar"] = engine_weight_capcollar

        return game

if __name__ == "__main__":
    import psutil
    engine = chess.engine.SimpleEngine.popen_uci(r"E:\\chess\\stockfish_15_win_x64_popcnt\\stockfish_15_x64_popcnt.exe")
    threads: int = int(psutil.cpu_count(logical=True) - 1)  # almost all logical CPU cores
    hash: int = int(psutil.virtual_memory().available / 1024 / 1024 * 0.75)  # 75% of available RAM
    engine.configure({"Hash": hash})
    engine.configure({"Threads": threads})

    a = zPosition()

    # Depth of 15 can hit lichess rate limit, 20 seems like the best 'quick' number
    # Big time increase after 40
    # 35 seems doable for smaller repertoires
    MIN_DEPTH = 20
    MIN_LIKELIHOOD = 0.009
    OUT_POSTFIX = "_repertoire"

    # For weighted average repertoire
    ENGINE_NODE_WEIGHT=0.01
    LICHESS_GAME_WEIGHT=1

    white_repertoire = a.create_weighted_average_opening_training(engine=engine, 
                                                                  min_depth=MIN_DEPTH, 
                                                                  min_likelihood=MIN_LIKELIHOOD,
                                                                  engine_node_weight=ENGINE_NODE_WEIGHT,
                                                                  lichess_game_weight=LICHESS_GAME_WEIGHT)
    print("White repertoire:")
    print(white_repertoire)
    print(white_repertoire, file=open(f"white{OUT_POSTFIX}.pgn", "w"), end="\n\n")

    black_repertoire = a.create_weighted_average_opening_training(engine=engine, 
                                                                  side=chess.BLACK, 
                                                                  min_depth=MIN_DEPTH, 
                                                                  min_likelihood=MIN_LIKELIHOOD,
                                                                  engine_node_weight=ENGINE_NODE_WEIGHT,
                                                                  lichess_game_weight=LICHESS_GAME_WEIGHT)
    print("Black repertoire:")
    print(black_repertoire)
    print(black_repertoire, file=open(f"black{OUT_POSTFIX}.pgn", "w"), end="\n\n")

