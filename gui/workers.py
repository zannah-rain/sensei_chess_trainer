"""Background QThread workers, so slow network/IO work doesn't freeze the GUI."""

from PySide6.QtCore import QThread, Signal

from utils.database import Database


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
