"""
A persistent, background-thread engine-evaluation service.

Every Stockfish/Leela call the GUI needs - puzzle/review move scoring, the
"Engine Move" button, and the Position Info panel's live evaluation - used to
run synchronously on the GUI thread, which is why the app visibly locked up
after every move. EvaluationWorker moves all of that onto one persistent
background QThread instead.

Unlike the one-shot workers in gui/workers.py (which start fresh engine
subprocesses for a single long operation and then exit), this worker is
created once at app startup and stays alive for the whole session, with one
persistent Database connection and one persistent Stockfish/Leela pair - the
whole point is to avoid paying engine-subprocess-startup cost on every move.
"""

import chess

from utils.database import Database
from utils.combined_engines import CombinedEngines
from PySide6.QtCore import QObject, Signal, Slot


class StaticEngineSettings:
    """
    A minimal read-only stand-in for utils.settings.Settings, exposing just the
    two keys CombinedEngines needs. Settings.__getitem__ would construct a Qt
    settings dialog (via .prompt()) if a key were ever missing, which is illegal
    off the GUI thread - so the real Settings object is never passed here. The
    caller resolves both paths on the GUI thread first and passes plain strings.
    """

    def __init__(self, stockfish_path: str, leela_path: str) -> None:
        self._values = {"Stockfish Executable": stockfish_path, "Leela Executable": leela_path}

    def __getitem__(self, key: str):
        return self._values[key]


class EvaluationWorker(QObject):
    """
    Lives on its own QThread (see MainWindow.__init__: constructed here on the
    GUI thread, then moved via moveToThread() before the thread starts). Its
    Database connection and CombinedEngines pair are created lazily, in
    _ensure_started(), so they're actually constructed on the worker thread
    (whichever thread first calls one of the slots below) rather than on the
    GUI thread - sqlite3 connections can't be used from a different thread than
    the one that created them.

    Every request/result signal carries a plain int id (a position "generation"
    or a review-move "request id", depending on which MainWindow uses for that
    request type - see MainWindow._eval_generation/_review_request_id) that the
    caller uses to discard stale results; this worker doesn't attempt to cancel
    or deduplicate anything itself, since chess.engine.SimpleEngine.analyse()
    can't be interrupted mid-call anyway.
    """

    puzzle_move_evaluated = Signal(int, bool, float)  # generation, engine_agreed, new_eval
    review_move_evaluated = Signal(int, bool, float, float, float, bool, float)
    # request_id, engine_agreed, current_eval, current_eval_2, new_eval, has_original_game_eval, original_game_eval
    engine_move_ready = Signal(int, str)  # generation, move_uci
    position_info_evaluated = Signal(int, float, float)  # generation, stockfish_eval, leela_eval (unmirrored)
    next_puzzle_selected = Signal(int, object)  # generation, Puzzle - plain Python object, not a Qt type, but
                                                 # PySide6 Signal(object) passes any Python object safely by reference
    stats_computed = Signal(int, object)  # request_id, stats dict (from the move_stats view)
    failed = Signal(int, str)  # id, message

    def __init__(self, database_file: str, stockfish_path: str, leela_path: str) -> None:
        super().__init__()  # deliberately unparented - moveToThread() silently no-ops on a parented QObject
        self._database_file = database_file
        self._stockfish_path = stockfish_path
        self._leela_path = leela_path
        self._database = None
        self._combined_engines = None

    def _ensure_started(self) -> None:
        if self._database is None:
            self._database = Database(file=self._database_file)
            self._combined_engines = CombinedEngines(
                settings=StaticEngineSettings(self._stockfish_path, self._leela_path),
                database=self._database)

    @Slot(int, str, str)
    def evaluate_puzzle_move(self, generation: int, pre_move_fen: str, move_uci: str) -> None:
        try:
            self._ensure_started()
            board = chess.Board(pre_move_fen)
            move = chess.Move.from_uci(move_uci)

            engine_move = self._database.engine_move(board=board, engine=self._combined_engines.stockfish(),
                                                       depth_value=23, multipv=1)
            if engine_move == move:
                # Matches the engine's own top move - no need to also score it (the
                # result would be computed but never used, same as today's code).
                self.puzzle_move_evaluated.emit(generation, True, 0.0)
                return

            next_board = board.copy()
            next_board.push(move)
            new_eval = self._combined_engines.stable_evaluation(min_depth=20, min_nodes=10_000, max_depth=30,
                                                                 max_instability=0.009, board=next_board)
            self.puzzle_move_evaluated.emit(generation, False, new_eval)
        except Exception as e:
            self.failed.emit(generation, str(e))

    @Slot(int, str, str, str)
    def evaluate_review_move(self, request_id: int, pre_move_fen: str, move_uci: str, original_next_fen: str) -> None:
        try:
            self._ensure_started()
            board = chess.Board(pre_move_fen)
            move = chess.Move.from_uci(move_uci)

            engine_move = self._database.engine_move(board=board, engine=self._combined_engines.stockfish(),
                                                       depth_value=23, multipv=1)
            engine_agreed = (engine_move == move)

            # new_eval and original_game_eval are needed by game_review_success() even
            # when the engine agreed (to decide whether to *also* red-highlight the
            # real game's own move), so - unlike puzzle mode - they can't be skipped
            # in that case. current_eval/current_eval_2 are only used for the goal-eval
            # decision, which IS skipped once the engine's agreed, so those still are.
            this_attempt_next_board = board.copy()
            this_attempt_next_board.push(move)
            new_eval = self._combined_engines.stable_evaluation(min_depth=23, min_nodes=5000, max_depth=30,
                                                                 max_instability=0.009, board=this_attempt_next_board)

            if original_next_fen:
                original_game_eval = self._combined_engines.stable_evaluation(
                    min_depth=23, min_nodes=5000, max_depth=30, max_instability=0.009,
                    board=chess.Board(original_next_fen))
                has_original_game_eval = True
            else:
                original_game_eval = 0.0
                has_original_game_eval = False

            if engine_agreed:
                self.review_move_evaluated.emit(request_id, True, 0.0, 0.0, new_eval,
                                                has_original_game_eval, original_game_eval)
                return

            engine_move_board = board.copy()
            engine_move_board.push(engine_move)
            current_eval = self._combined_engines.stable_evaluation(min_depth=23, min_nodes=5000, max_depth=30,
                                                                     max_instability=0.009, board=board)
            current_eval_2 = self._combined_engines.stable_evaluation(min_depth=23, min_nodes=5000, max_depth=30,
                                                                       max_instability=0.009, board=engine_move_board)
            self.review_move_evaluated.emit(request_id, False, current_eval, current_eval_2, new_eval,
                                            has_original_game_eval, original_game_eval)
        except Exception as e:
            self.failed.emit(request_id, str(e))

    @Slot(int, str)
    def compute_engine_move(self, generation: int, fen: str) -> None:
        try:
            self._ensure_started()
            board = chess.Board(fen)
            move = self._database.engine_move(board=board, engine=self._combined_engines.stockfish(),
                                               depth_value=20, multipv=1)
            self.engine_move_ready.emit(generation, move.uci())
        except Exception as e:
            self.failed.emit(generation, str(e))

    @Slot(int, str)
    def evaluate_position_info(self, generation: int, fen: str) -> None:
        try:
            self._ensure_started()
            board = chess.Board(fen)
            stockfish_eval = self._combined_engines.stockfish_evaluation(depth=25, board=board)
            leela_eval = self._combined_engines.leela_evaluation(nodes=100_000, board=board)
            self.position_info_evaluated.emit(generation, stockfish_eval, leela_eval)
        except Exception as e:
            self.failed.emit(generation, str(e))

    @Slot(int)
    def select_next_puzzle(self, generation: int) -> None:
        """
        Picks the highest-priority due puzzle (Database.highest_priority_puzzle()) -
        a pure database query, no engine involved, but one that scans/aggregates
        every known position's move-attempt history and was slow enough to
        visibly freeze the GUI on "Next Puzzle" before being moved here.
        """
        try:
            self._ensure_started()
            puzzle = self._database.highest_priority_puzzle()
            self.next_puzzle_selected.emit(generation, puzzle)
        except Exception as e:
            self.failed.emit(generation, str(e))

    @Slot(int)
    def compute_stats(self, request_id: int) -> None:
        """
        Queries the move_stats view - a scan/aggregate over every known
        position's move-attempt history, same flavour of query as
        highest_priority_puzzle() and similarly too slow (~0.5s) to run on the
        GUI thread, which is why it lives here rather than in
        MainWindow.refresh_stats_tab() directly.
        """
        try:
            self._ensure_started()
            stats = dict(self._database.con.execute("SELECT * FROM move_stats").fetchall()[0])
            stats.update(self._database.practice_streak())
            self.stats_computed.emit(request_id, stats)
        except Exception as e:
            self.failed.emit(request_id, str(e))

    @Slot()
    def shutdown(self) -> None:
        if self._combined_engines is not None:
            self._combined_engines.close()
        self.thread().quit()
