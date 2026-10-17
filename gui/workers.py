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
    Runs full Stockfish + Leela evaluation coverage on a background thread, so
    the GUI stays responsive and the operation can be stopped or left running
    while the rest of the app is used.

    Opens its own Database connection (see DownloadGamesWorker) and its own
    Stockfish/Leela engine subprocesses, rather than reusing MainWindow's: a
    chess.engine.SimpleEngine wraps a subprocess's stdin/stdout and isn't safe
    to call from two threads at once, and the main thread may make its own
    engine calls (making a move, navigating positions) while this runs.
    """

    progress = Signal(str, int, int)  # phase ("Stockfish"/"Leela"), positions done, positions total
    failed = Signal(str)

    def __init__(self, database_file: str, stockfish_path: str, leela_path: str,
                stockfish_depth: int = 12, leela_depth: int = 100, parent=None) -> None:
        super().__init__(parent)
        self.database_file = database_file
        self.stockfish_path = stockfish_path
        self.leela_path = leela_path
        self.stockfish_depth = stockfish_depth
        self.leela_depth = leela_depth
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

        try:
            worker_database.full_engine_evaluation(
                engine=stockfish, depth_value=self.stockfish_depth,
                progress_callback=lambda done, total: self.progress.emit("Stockfish", done, total),
                should_stop=lambda: self._stop_requested)

            if not self._stop_requested:
                worker_database.full_engine_evaluation(
                    engine=leela, depth_value=self.leela_depth,
                    progress_callback=lambda done, total: self.progress.emit("Leela", done, total),
                    should_stop=lambda: self._stop_requested)
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            stockfish.close()
            leela.close()
            self.stopped = self._stop_requested
