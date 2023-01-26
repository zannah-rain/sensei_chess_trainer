"""Convenience functions for chess analysis"""
import pickle
from pathlib import Path
import chess
import chess.svg
import chess.engine
import chess.pgn
from chess import WHITE, BLACK
import ipywidgets as widgets
from IPython.display import display


class zGame:
    """
    Convenience wrapper around python chess objects.
    """
    def __init__(self, game: chess.pgn.Game = None):
        if game is None:
            self.game = chess.pgn.Game()
        else:
            self.game = game

        self.display_game = None
        self.eval_cache = dict()

    def next(self):
        return zGame(game=self.game.next())

    def eval(self, depth=chess.engine.Limit(time=0.1), engine=None, multipv=1, evaluation=False):
        if depth.__str__() not in self.eval_cache.keys():
            if engine is None:
                started_engine = True
                engine = chess.engine.SimpleEngine.popen_uci(r"E:\\chess\\stockfish_15_win_x64_popcnt\\stockfish_15_x64_popcnt.exe")
            else:
                started_engine = False

            scores = list()
            scores.append(engine.analyse(self.board, depth, multipv=multipv)[0]["score"])
            if not self.game.is_end():
                scores.extend(self.next().eval(depth=depth, engine=engine, multipv=multipv))

            if started_engine:
                engine.quit()

            self.eval_cache[depth.__str__()] = scores

        if evaluation:
            return [i.wdl().relative.expectation() for i in self.eval_cache[depth.__str__()]]
        else:
            return self.eval_cache[depth.__str__()]

    def save(self, file: Path) -> None:
        pickle.dump(self, file=file)

    @staticmethod
    def load(file: Path):
        return pickle.load(file=file)

    @staticmethod
    def read_pgn(file: Path):
        with open(file, "r") as f:
            pgn = chess.pgn.read_game(f)

        return zGame(game=pgn)

    @property
    def board(self) -> chess.Board:
        return self.game.board()

    def draw(self,
             orientation=chess.WHITE,
             fill=None,
             arrows=None,
             lastmove=None,
             check=None,
             squares=None,
             size=None,
             coordinates=True,
             colors=None,
             flipped=False,
             style=None):
        if fill is None:
            fill = {}
        if arrows is None:
            arrows = []
        if colors is None:
            colors = {}
        return chess.svg.board(self.board,
                               orientation=orientation,
                               lastmove=lastmove,
                               check=check,
                               coordinates=coordinates,
                               colors=colors,
                               flipped=flipped,
                               style=style,
                               fill=fill,
                               arrows=arrows,
                               squares=squares,
                               size=size)

    def draw_analysis(self):
        engine = chess.engine.SimpleEngine.popen_uci(r"E:\\chess\\stockfish_15_win_x64_popcnt\\stockfish_15_x64_popcnt.exe")
        info = engine.analyse(self.board, chess.engine.Limit(time=10), multipv=3)

        threat_board = self.board.copy()
        if threat_board.turn == WHITE:
            threat_board.turn = BLACK
        else:
            threat_board.turn = WHITE
        threat_info = engine.analyse(threat_board, chess.engine.Limit(time=10), multipv=1)[0]
        engine.quit()
        arrows = list()
        for i in info:
            game = chess.pgn.Game().from_board(self.board)
            game.add_line(i["pv"])
            print(f"{i['score']}: {game.__str__().splitlines()[-1]}")
            arrows.append(chess.svg.Arrow(tail=i["pv"][0].from_square, head=i["pv"][0].to_square))
        arrows.append(chess.svg.Arrow(tail=threat_info["pv"][0].from_square, head=threat_info["pv"][0].to_square, color="red"))
        return (chess.svg.board(self.board,
                                arrows=arrows,
                                size=350))

    def interact(self):
        self.display_game = self.game.game()
        forwards_button = widgets.Button(description="Forwards")
        output = widgets.Output()

        display(forwards_button)
        display(output)

        def click_forwards(x):
            with output:
                output.clear_output()
                self.display_game = self.display_game.next()
                display(chess.svg.board(self.display_game.board(), size=350))

        forwards_button.on_click(click_forwards)

    def player_centipawn_loss(self, depth=chess.engine.Limit(time=0.1), player: str = "ZannahRain"):
        scores = self.eval(depth=depth)
        if self.game.headers["White"] == player:
            scores = [i.white().score(mate_score=100) for i in scores]  # Scores from white's perspective
            first_player_move = 0
        elif self.game.headers["Black"] == player:
            scores = [i.black().score(mate_score=100) for i in scores]  # Scores from white's perspective
            first_player_move = 1

        scores = [max(min(i, 500), -500) for i in scores]  # Bounds
        scores = [scores[i] - scores[i - 1] for i in range(1, len(scores))]  # Difference in score from one move to the next
        scores = [max(min(i, 500), -500) for i in scores]  # Bounds
        scores = [-i for i in scores]  # centipawn LOSS, not gain

        scores = scores[first_player_move::2]
        return scores

    def player_evaluation_loss(self, depth=chess.engine.Limit(time=0.1), player: str = "ZannahRain"):
        scores = self.eval(depth=depth)
        scores = [i.white() for i in scores]
        scores = [i.wdl().expectation() for i in scores]

        if self.game.headers["White"] == player:
            first_player_move = 0
        else:
            first_player_move = 1

        scores = [scores[i] - scores[i - 1] for i in range(1, len(scores))]  # Difference in wdl evaluation from one move to the next

        if self.game.headers["White"] == player:
            scores = [-i for i in scores]  # LOSS, not GAIN

        scores = scores[first_player_move::2]
        return scores
