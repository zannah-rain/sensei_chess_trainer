"""Background QThread workers, so slow network/IO work doesn't freeze the GUI."""

import psutil
import chess.engine
from PySide6.QtCore import QThread, Signal

from utils.database import Database
from utils.engine import Engine


class DownloadGamesWorker(QThread):
    """
    Downloads games from Lichess on a background thread.

    Opens its own Database connection to the same file rather than reusing the
    caller's: sqlite3 connections can only be used from the thread that created
    them, and this one runs on its own thread so the GUI stays responsive while
    it downloads. Both connections see each other's committed writes, since
    they point at the same on-disk (WAL-mode) database file.
    """

    progress = Signal(int)  # games added so far
    failed = Signal(str)

    def __init__(self, database_file: str, max_new_games: int = None, parent=None) -> None:
        super().__init__(parent)
        self.database_file = database_file
        self.max_new_games = max_new_games

    def run(self) -> None:
        try:
            worker_database = Database(file=self.database_file)
            worker_database.download_latest_games(max_new_games=self.max_new_games,
                                                   progress_callback=self.progress.emit)
        except Exception as e:
            self.failed.emit(str(e))


class BuildPuzzlesWorker(QThread):
    """
    Runs a two-stage Stockfish + Leela evaluation pass on a background thread, so
    the GUI stays responsive and the operation can be stopped or left running
    while the rest of the app is used.

    Stage 1 ("quick scan") evaluates every known position at a cheap, shallow
    depth/node count, broadly enough for move_attempt_analysis's eval-loss figures
    to exist. Stage 2 ("refine") re-evaluates every position again at a much
    higher, expensive depth/node count, but in priority order - positions with
    the biggest estimated eval loss (the most promising puzzle candidates, see
    Database.puzzle_candidates_by_priority) go first - so stopping (or being
    interrupted) partway through stage 2 still means the positions most likely to
    actually matter got the expensive treatment, even though the whole list, run
    to completion, covers everything. (Stage 2 only refines each candidate's own
    starting position, not its resulting/practice positions - the starting
    position's evaluation is what's shown as a puzzle's own "best move"
    reference value during solving.)

    Both stages alternate between Stockfish and Leela per position (see
    Database.full_multi_engine_evaluation) rather than running one engine through
    the whole list before the other starts - otherwise, especially in stage 2's
    priority order, the least important position would get evaluated by one
    engine long before the other engine even looked at the most important one.

    Opens its own Database connection (see DownloadGamesWorker) and its own
    Stockfish/Leela engine subprocesses, rather than reusing MainWindow's: a
    chess.engine.SimpleEngine wraps a subprocess's stdin/stdout and isn't safe
    to call from two threads at once, and the main thread may make its own
    engine calls (making a move, navigating positions) while this runs.
    """

    progress = Signal(str, int, int)  # phase, units done, units total
    failed = Signal(str)

    def __init__(self, database_file: str, stockfish_path: str, leela_path: str,
                stockfish_quick_depth: int, leela_quick_nodes: int,
                stockfish_refine_depth: int, leela_refine_nodes: int,
                parent=None) -> None:
        super().__init__(parent)
        self.database_file = database_file
        self.stockfish_path = stockfish_path
        self.leela_path = leela_path
        self.stockfish_quick_depth = stockfish_quick_depth
        self.leela_quick_nodes = leela_quick_nodes
        self.stockfish_refine_depth = stockfish_refine_depth
        self.leela_refine_nodes = leela_refine_nodes
        self.stopped = False
        self._stop_requested = False

    def request_stop(self) -> None:
        """Cooperative stop: honored as soon as the position currently being evaluated finishes."""
        self._stop_requested = True

    def run(self) -> None:
        worker_database = Database(file=self.database_file)

        stockfish = Engine(engine=chess.engine.SimpleEngine.popen_uci(self.stockfish_path),
                           name="stockfish", depth_parameter="depth")
        stockfish.configure({"Hash": int(psutil.virtual_memory().available / 1024 / 1024 * 0.3)})
        stockfish.configure({"Threads": int(psutil.cpu_count(logical=True) - 3)})
        leela = Engine(engine=chess.engine.SimpleEngine.popen_uci(self.leela_path),
                       name="leela", depth_parameter="nodes")

        def report(phase):
            return lambda engine_name, done, total: self.progress.emit(f"{phase} ({engine_name})", done, total)

        try:
            # Stage 1: quick scan, broad coverage
            worker_database.full_multi_engine_evaluation(
                engine_depth_pairs=[(stockfish, self.stockfish_quick_depth), (leela, self.leela_quick_nodes)],
                progress_callback=report("Quick scan"),
                should_stop=lambda: self._stop_requested)

            if self._stop_requested:
                return

            # Stage 2: refine every position at much higher depth/nodes, but in
            # priority order (biggest estimated eval loss first)
            candidates = worker_database.puzzle_candidates_by_priority()

            worker_database.full_multi_engine_evaluation(
                engine_depth_pairs=[(stockfish, self.stockfish_refine_depth), (leela, self.leela_refine_nodes)],
                positions=candidates,
                progress_callback=report("Refine"),
                should_stop=lambda: self._stop_requested)
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            stockfish.close()
            leela.close()
            self.stopped = self._stop_requested
