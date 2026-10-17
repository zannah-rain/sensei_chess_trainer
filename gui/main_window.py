#!/usr/bin/env python3

import sys
import chess
import chess.pgn
import chess.engine
import chess.polyglot
import logging
import platform as sys_plat
from utils.constants import *
from utils.position import *
from utils.puzzle import Puzzle
from utils.scoring import puzzle_goal_eval, review_goal_eval
from zPosition import zPosition
from pathlib import Path
from typing import Dict
from utils.database import Database, position_to_fen
from utils.settings import Settings
from globals import username
import datetime
import pandas as pd
from textwrap import dedent
from io import StringIO
import utils.colours
from utils.square import Square
from utils.move import Move
from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QFileDialog, QVBoxLayout, QHBoxLayout, QWidget
import PySide6.QtWidgets as QtWidgets
from PySide6.QtGui import QAction
from gui.board import Board
from PySide6.QtMultimedia import QSoundEffect, QMediaPlayer, QAudioOutput
from PySide6.QtCore import QUrl, Signal, QObject, Qt, QTimer, QThread
from gui.popups import TextboxPopup, TablePopup, DownloadProgressDialog, BuildPuzzlesProgressDialog
from gui.workers import DownloadGamesWorker, BuildPuzzlesWorker
from gui.eval_worker import EvaluationWorker
from gui.position_info_widget import PositionInfoWidget


logging.basicConfig(level=logging.INFO)

platform = sys.platform
sys_os = sys_plat.system()


menu_def_neutral = [
        ["File", ["Open .pgn", "Import .pgn"]],
        ["Data", ["Time Controls", "Games", "Prioritised Games", "Showcase Games", "Stats", "Puzzles"]],
        ['&Time', ['User::tc_k', 'Engine::tc_k']],
        ['&Settings', ['Game::settings_game_k']],
        ['&Help', ['About']],
]


def ifnone(x, y):
    if x is None:
        return y
    return x


class _ConsoleStream(QObject):
    """A minimal stdout/stderr-like object that emits each write as a Qt signal, so a
    QPlainTextEdit can show console output (replacing PySimpleGUI's reroute_stdout)."""

    written = Signal(str)

    def write(self, text: str) -> None:
        if text:
            self.written.emit(text)

    def flush(self) -> None:
        pass


class MainWindow(QMainWindow):

    game_node_change_signal = Signal(chess.pgn.GameNode)

    # Requests to the background EvaluationWorker (see gui/eval_worker.py) - connecting
    # a signal to a slot that lives on a different thread auto-queues the call there.
    puzzle_move_requested = Signal(int, str, str)  # generation, pre_move_fen, move_uci
    review_move_requested = Signal(int, str, str, str)  # request_id, pre_move_fen, move_uci, original_next_fen
    engine_move_requested = Signal(int, str)  # generation, fen
    position_info_requested = Signal(int, str)  # generation, fen
    next_puzzle_requested = Signal(int)  # generation
    shutdown_requested = Signal()

    def __init__(self) -> None:
        super(MainWindow, self).__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")

        self.settings = Settings(schema={"Stockfish Executable": "Path",
                                    "Leela Executable": "Path",
                                    "Stockfish Puzzle Quick Scan Depth": "int",
                                    "Leela Puzzle Quick Scan Nodes": "int",
                                    "Stockfish Puzzle Refine Depth": "int",
                                    "Leela Puzzle Refine Nodes": "int"},
                            save_file=Path("EasyChessGuiSettings.json"),
                            settings_screen_title="Sensei Settings:")
        # Sensible out-of-the-box defaults for Build Puzzles' two-stage evaluation
        # pass (see BuildPuzzlesWorker), so it works without forcing a settings
        # prompt on first use. Stage 1 ("quick scan") is cheap and runs over every
        # known position; stage 2 ("refine") is expensive and re-evaluates every
        # position too, but in priority order (biggest estimated real-game mistake
        # first), so stopping it early still covers the positions most likely to
        # matter as puzzles.
        self.settings.set_default("Stockfish Puzzle Quick Scan Depth", 8)
        self.settings.set_default("Leela Puzzle Quick Scan Nodes", 1_000)
        self.settings.set_default("Stockfish Puzzle Refine Depth", 20)
        self.settings.set_default("Leela Puzzle Refine Nodes", 10_000)

        horizontal_layout = QHBoxLayout()
        vertical_layout_1 = QVBoxLayout()
        vertical_layout_2 = QVBoxLayout()
        vertical_layout_3 = QVBoxLayout()
        horizontal_layout.addLayout(vertical_layout_1)
        horizontal_layout.addLayout(vertical_layout_2)
        horizontal_layout.addLayout(vertical_layout_3)

        self.gui_board = Board()
        self.gui_board.move_signal.connect(self.on_board_move)
        vertical_layout_1.addWidget(self.gui_board)

        self.init_menu()

        self.database = Database()

        # A persistent background thread for every engine call the GUI needs (puzzle/
        # review scoring, "Engine Move", Position Info's live eval), so moves and
        # navigation never block on Stockfish/Leela. See gui/eval_worker.py.
        self._eval_generation = 0
        self._review_request_id = 0
        self._eval_thread = QThread(self)
        self._eval_worker = EvaluationWorker(database_file=self.database.file,
                                             stockfish_path=self.settings["Stockfish Executable"],
                                             leela_path=self.settings["Leela Executable"])
        self._eval_worker.moveToThread(self._eval_thread)
        self.puzzle_move_requested.connect(self._eval_worker.evaluate_puzzle_move)
        self.review_move_requested.connect(self._eval_worker.evaluate_review_move)
        self.engine_move_requested.connect(self._eval_worker.compute_engine_move)
        self.position_info_requested.connect(self._eval_worker.evaluate_position_info)
        self.next_puzzle_requested.connect(self._eval_worker.select_next_puzzle)
        self.shutdown_requested.connect(self._eval_worker.shutdown)
        self._eval_worker.puzzle_move_evaluated.connect(self._on_puzzle_move_evaluated)
        self._eval_worker.review_move_evaluated.connect(self._on_review_move_evaluated)
        self._eval_worker.engine_move_ready.connect(self._on_engine_move_ready)
        self._eval_worker.position_info_evaluated.connect(self._on_position_info_evaluated)
        self._eval_worker.next_puzzle_selected.connect(self._on_next_puzzle_selected)
        self._eval_worker.failed.connect(self._on_eval_worker_failed)
        self._eval_thread.start()

        self._current_puzzle: Puzzle = None
        self._current_puzzle_start_time: datetime.datetime = None
        self.puzzle_attempt = 0
        self.review_attempt = 0
        self.game_review_mode = False
        self._current_game_review_position_start_time: datetime.datetime = None

        # Snapshots for whichever puzzle/review move evaluation is currently
        # pending in the background (see _handle_puzzle_move/_handle_review_move
        # and their _on_*_evaluated callbacks)
        self._pending_puzzle_move: chess.Move = None
        self._pending_puzzle_snapshot: Puzzle = None
        self._pending_review_move: chess.Move = None
        self._pending_review_node: chess.pgn.GameNode = None
        self._pending_review_turn: bool = None
        self._pending_review_is_mainline: bool = None
        self._pending_review_original_next: chess.pgn.ChildNode = None

        self._build_puzzles_worker: BuildPuzzlesWorker = None
        self._build_puzzles_dialog: BuildPuzzlesProgressDialog = None
        self._build_puzzles_failure: str = None
        self.init_build_puzzles_status_bar()
        self.init_next_puzzle_status_bar()

        self._game = chess.pgn.Game()
        self._game_node = self.game

        self.audio_player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.audio_player.setAudioOutput(self.audio_output)

        self.position_info_widget = PositionInfoWidget(database=self.database)
        vertical_layout_2.addWidget(self.position_info_widget)

        self.game_node_change_signal.connect(self._refresh_position_info)
        # Deliberately not calling _refresh_position_info here: it triggers live
        # Stockfish/Leela evaluation, and engines should stay lazy (not started
        # just from opening the window). The widget stays blank until the first
        # real position change (a move, Next Puzzle, opening a game, etc).

        layout_widget = QWidget()
        layout_widget.setLayout(horizontal_layout)
        self.setCentralWidget(layout_widget)

        self.turn_label = QtWidgets.QLabel()
        vertical_layout_3.addWidget(self.turn_label)

        tab_widget = QtWidgets.QTabWidget()
        vertical_layout_3.addWidget(tab_widget)

        self.puzzle_widget = QtWidgets.QWidget()
        tab_widget.addTab(self.puzzle_widget, "Puzzles")
        self.init_puzzle_widget()

        self.today_widget = QtWidgets.QWidget()
        tab_widget.addTab(self.today_widget, "Today")
        self.init_today_widget()

        self.alltime_widget = QtWidgets.QWidget()
        tab_widget.addTab(self.alltime_widget, "All-Time")
        self.init_alltime_widget()

        self.opening_book_widget = QtWidgets.QWidget()
        tab_widget.addTab(self.opening_book_widget, "Opening Book")
        self.init_opening_book_widget()

        self.console_widget = QtWidgets.QWidget()
        tab_widget.addTab(self.console_widget, "Console")
        self.init_console_widget()

        self.engine_move_button = QtWidgets.QPushButton("Engine Move")
        self.engine_move_button.clicked.connect(self.on_engine_move_clicked)
        vertical_layout_3.addWidget(self.engine_move_button)

        nav_layout = QHBoxLayout()
        back_button = QtWidgets.QPushButton("<-")
        back_button.clicked.connect(self.nav_backward)
        forward_button = QtWidgets.QPushButton("->")
        forward_button.clicked.connect(self.nav_forward)
        nav_layout.addWidget(back_button)
        nav_layout.addWidget(forward_button)
        vertical_layout_3.addLayout(nav_layout)

        self.refresh_stats_tab()

        self.setFocusPolicy(Qt.StrongFocus)
        self.setFocus()

        self.redirect_console_output()  # last: keep startup errors/prints on the real terminal

    def init_puzzle_widget(self) -> None:
        """Initialise the puzzle widget."""
        layout = QVBoxLayout(self.puzzle_widget)

        self.next_puzzle_button = QtWidgets.QPushButton("Next Puzzle")
        self.next_puzzle_button.clicked.connect(self.next_puzzle)

        layout.addWidget(self.next_puzzle_button)

    def init_next_puzzle_status_bar(self) -> None:
        """A persistent "Selecting puzzle..." indicator, visible while
        highest_priority_puzzle() is being computed in the background - it scans
        every known position's move-attempt history and can take a couple of
        seconds, which used to freeze the whole app with no feedback at all."""
        self.next_puzzle_status_label = QtWidgets.QLabel("Selecting puzzle…")
        self.next_puzzle_progress_bar = QtWidgets.QProgressBar()
        self.next_puzzle_progress_bar.setRange(0, 0)  # indeterminate - this is one query, not a multi-step process
        self.next_puzzle_progress_bar.setMaximumWidth(120)

        for widget in (self.next_puzzle_status_label, self.next_puzzle_progress_bar):
            widget.setVisible(False)
            self.statusBar().addPermanentWidget(widget)

    def next_puzzle(self) -> None:
        self.next_puzzle_button.setEnabled(False)
        self.next_puzzle_status_label.setVisible(True)
        self.next_puzzle_progress_bar.setVisible(True)
        generation = self._eval_generation
        self.next_puzzle_requested.emit(generation)

    def _on_next_puzzle_selected(self, generation: int, puzzle: Puzzle) -> None:
        self.next_puzzle_button.setEnabled(True)
        self.next_puzzle_status_label.setVisible(False)
        self.next_puzzle_progress_bar.setVisible(False)
        if generation != self._eval_generation:
            return  # the board moved on while this was being computed - discard

        self.current_puzzle = puzzle
        # Randomise perspective to hopefully help learning
        self.gui_board.randomise_perspective_and_mirroring()
        self.game = chess.pgn.Game().from_board(chess.Board(fen=position_to_fen(puzzle.position)))
        self.game_review_mode = False

    def init_today_widget(self) -> None:
        layout = QVBoxLayout(self.today_widget)

        self.today_games_label = QtWidgets.QLabel()
        self.today_progress_bar = QtWidgets.QProgressBar()
        self.today_progress_bar.setRange(0, 100)
        self.today_puzzles_label = QtWidgets.QLabel()
        refresh_button = QtWidgets.QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh_stats_tab)

        layout.addWidget(self.today_games_label)
        layout.addWidget(self.today_progress_bar)
        layout.addWidget(self.today_puzzles_label)
        layout.addWidget(refresh_button)

    def init_alltime_widget(self) -> None:
        layout = QVBoxLayout(self.alltime_widget)

        self.alltime_games_label = QtWidgets.QLabel()
        self.alltime_puzzles_label = QtWidgets.QLabel()

        layout.addWidget(self.alltime_games_label)
        layout.addWidget(self.alltime_puzzles_label)

    def refresh_stats_tab(self) -> None:
        stats = dict(self.database.con.execute("SELECT * FROM move_stats").fetchall()[0])

        total_eval_improvement_today = stats["sum_real_eval_loss_today"] - stats["sum_practice_eval_loss_today"]

        average_eval_loss_per_day = ifnone(stats["this_month_total_real_eval_loss"], 0) / 30
        average_eval_loss_per_game = ifnone(stats["average_real_eval_loss_alltime"], 0) * ifnone(stats["average_game_halfmoves_alltime"], 0) / 2

        daily_eval_improvement_target = 2 * max(average_eval_loss_per_day, average_eval_loss_per_game)

        progress_percent = max(0, min(100, round(100 * total_eval_improvement_today / daily_eval_improvement_target)))
        self.today_progress_bar.setValue(progress_percent)

        self.today_games_label.setText(dedent(text=f"""\
            Games played: {stats["total_games_played_today"]}
            New puzzles: {stats["total_half_moves_from_real_games_today"] // 2}"""))
        self.today_puzzles_label.setText(dedent(text=f"""\
            Puzzles done: {stats["positions_practiced_today"]}
            Average original eval loss: {ifnone(stats["average_real_eval_loss_today"], 0):.3f}
            Average new eval loss: {ifnone(stats["average_practice_eval_loss_today"], 0):.3f}
            Improvement: {(1 - ifnone(stats["average_practice_eval_loss_today"], 0) / max(ifnone(stats["average_real_eval_loss_today"], 0), .0001)) * 100:.1f}%
            Total Improvement vs Target: {total_eval_improvement_today:2f} vs {daily_eval_improvement_target:2f}
            """))
        self.alltime_games_label.setText(dedent(f"""\
            Total games played: {stats["total_games_played"]}
            Average game length: {ifnone(stats["average_game_halfmoves_alltime"], 0) // 2}
            Average eval loss: {ifnone(stats["average_real_eval_loss_alltime"], 0):.3f}
            Average eval loss per game: {average_eval_loss_per_game:.2f}
            Average eval loss per day: {average_eval_loss_per_day:.2f}
            This month average eval loss: {ifnone(stats["this_month_average_real_eval_loss"], 0):.3f}
            Average time per move: {ifnone(stats["average_real_time_per_move_alltime"], 0):.1f}
            Total unique positions played: {stats["total_unique_real_positions_played_alltime"]}"""))
        self.alltime_puzzles_label.setText(dedent(f"""\
            Puzzles done: {stats["total_positions_practiced_alltime"]}
            Average puzzle original eval loss: {ifnone(stats["average_real_eval_loss_in_practiced_positions"], 0):.3f}
            Average puzzle new eval loss: {ifnone(stats["average_practice_eval_loss_alltime"], 0):.3f}
            Times a practiced positions has occurred in a real game: {stats["times_practiced_positions_seen_in_real_games"]}"""))

    def init_opening_book_widget(self) -> None:
        layout = QVBoxLayout(self.opening_book_widget)
        self.opening_book_table = QtWidgets.QTableWidget()
        self.opening_book_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.opening_book_table)
        self.game_node_change_signal.connect(self._refresh_moves_table)

    def _refresh_moves_table(self, _game_node: chess.pgn.GameNode) -> None:
        table = self.moves_table
        self.opening_book_table.setRowCount(len(table))
        self.opening_book_table.setColumnCount(len(table.columns))
        self.opening_book_table.setHorizontalHeaderLabels(list(table.columns))
        for row_i in range(len(table)):
            for col_i, col in enumerate(table.columns):
                self.opening_book_table.setItem(row_i, col_i, QtWidgets.QTableWidgetItem(str(table.iloc[row_i][col])))

    def init_console_widget(self) -> None:
        layout = QVBoxLayout(self.console_widget)
        self.console_output = QtWidgets.QPlainTextEdit()
        self.console_output.setReadOnly(True)
        layout.addWidget(self.console_output)

    def redirect_console_output(self) -> None:
        """
        Redirects stdout/stderr into the Console tab (replacing PySimpleGUI's
        reroute_stdout). Called as the very last step of __init__ so startup
        errors/prints still reach the real terminal for debugging.
        """
        self._console_stream = _ConsoleStream()
        self._console_stream.written.connect(self.console_output.insertPlainText)
        sys.stdout = self._console_stream
        sys.stderr = self._console_stream

    def nav_forward(self) -> None:
        next_node = self.game_node.next()
        if next_node is not None:
            self.game_node = next_node
        else:
            print("End of game")

    def nav_backward(self) -> None:
        if not isinstance(self.game_node, chess.pgn.ChildNode):
            print("Can't get parent node of non-ChildNode game_node")
            return
        if self.game_node.parent is not None:
            self.game_node = self.game_node.parent

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Right:
            self.nav_forward()
        elif event.key() == Qt.Key_Left:
            self.nav_backward()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        """Cleanly shuts down the background evaluation thread (and its engine
        subprocesses) before the app exits. Note: wait() blocks until whatever
        the worker is doing finishes - acceptable only here, at app close."""
        self.shutdown_requested.emit()
        self._eval_thread.wait()
        super().closeEvent(event)

    def init_menu(self) -> None:
        self.menu = self.menuBar()

        def add_menu_action(menu, name, callback):
            action = QAction(name, self)
            action.triggered.connect(callback)
            menu.addAction(action)

        menu_data = [
            ("File", [("Open .pgn", self.open_pgn),
                      ("Import .pgn", self.import_pgn),
                      ("Build Puzzles", self.build_puzzles)]),
            ("Board", [("Flip", self.gui_board.flip),
                       ("Mirror", self.gui_board.mirror)]),
            ("Data", [("Time Controls", self.show_time_controls_popup),
                      ("Games", self.show_games_popup),
                      ("Prioritised Games", self.show_prioritised_games_popup),
                      ("Showcase Games", self.show_showcase_games_popup),
                      ("Puzzles", self.show_puzzles_popup),
                      ("Stats", self.show_stats_popup)]),
            ("Lichess", [("Download one lichess .pgn", lambda: self.download_lichess_games(max_new_games=1, title="Downloading 1 game")),
                         ("Download all lichess .pgn's", lambda: self.download_lichess_games(max_new_games=None, title="Downloading games")),
                         ("Download this positions lichess stats", lambda: self.database._populate_lichess_stats(fen=self.fen))]),
            ("Settings", [("Preferences...", self.open_settings_dialog)])
        ]
        
        for menu_name, actions in menu_data:
            menu = self.menu.addMenu(menu_name)
            for action_name, callback in actions:
                add_menu_action(menu, action_name, callback)

    def init_build_puzzles_status_bar(self) -> None:
        """A persistent "Build Puzzles" progress indicator in the status bar, visible
        whenever the build is running - even if its dialog has been hidden/closed."""
        self.build_puzzles_status_label = QtWidgets.QLabel()
        self.build_puzzles_progress_bar = QtWidgets.QProgressBar()
        self.build_puzzles_progress_bar.setMaximumWidth(200)
        self.build_puzzles_stop_button = QtWidgets.QPushButton("Stop")
        self.build_puzzles_stop_button.clicked.connect(self.stop_building_puzzles)

        for widget in (self.build_puzzles_status_label, self.build_puzzles_progress_bar, self.build_puzzles_stop_button):
            widget.setVisible(False)
            self.statusBar().addPermanentWidget(widget)

    def open_settings_dialog(self) -> None:
        """Lets the user review/edit every setting (engine paths, puzzle-eligibility
        depth/nodes thresholds) at any time, not just when a missing one is first needed."""
        self.settings.prompt()

    def build_puzzles(self) -> None:
        """
        Runs a two-stage Stockfish + Leela evaluation pass in the background (see
        BuildPuzzlesWorker: a cheap broad "quick scan" followed by an expensive
        "refine" pass over everything again, biggest estimated real-game mistakes
        first), showing progress both in a dedicated dialog and in a persistent
        status-bar indicator. If a build is already running, clicking this again
        just re-shows its dialog rather than starting a second one.
        """
        if self._build_puzzles_worker is not None and self._build_puzzles_worker.isRunning():
            self._build_puzzles_dialog.show()
            self._build_puzzles_dialog.raise_()
            self._build_puzzles_dialog.activateWindow()
            return

        worker = BuildPuzzlesWorker(database_file=self.database.file,
                                    stockfish_path=self.settings["Stockfish Executable"],
                                    leela_path=self.settings["Leela Executable"],
                                    stockfish_quick_depth=int(self.settings["Stockfish Puzzle Quick Scan Depth"]),
                                    leela_quick_nodes=int(self.settings["Leela Puzzle Quick Scan Nodes"]),
                                    stockfish_refine_depth=int(self.settings["Stockfish Puzzle Refine Depth"]),
                                    leela_refine_nodes=int(self.settings["Leela Puzzle Refine Nodes"]),
                                    parent=self)
        worker.progress.connect(self.on_build_puzzles_progress)
        worker.failed.connect(self.on_build_puzzles_failed)
        worker.finished.connect(self.on_build_puzzles_finished)
        self._build_puzzles_worker = worker
        self._build_puzzles_failure: str = None

        self.build_puzzles_status_label.setText("Building puzzles: starting…")
        for widget in (self.build_puzzles_status_label, self.build_puzzles_progress_bar, self.build_puzzles_stop_button):
            widget.setVisible(True)

        dialog = BuildPuzzlesProgressDialog(parent=self)
        dialog.stop_requested.connect(self.stop_building_puzzles)
        self._build_puzzles_dialog = dialog
        dialog.show()

        worker.start()

    def stop_building_puzzles(self) -> None:
        if self._build_puzzles_worker is not None:
            self.build_puzzles_status_label.setText("Building puzzles: stopping…")
            self._build_puzzles_worker.request_stop()

    def on_build_puzzles_progress(self, phase: str, done: int, total: int) -> None:
        self.build_puzzles_status_label.setText(f"Building puzzles ({phase}): {done} / {total}")
        self.build_puzzles_progress_bar.setRange(0, total)
        self.build_puzzles_progress_bar.setValue(done)
        if self._build_puzzles_dialog is not None:
            self._build_puzzles_dialog.update_progress(phase, done, total)

    def on_build_puzzles_failed(self, message: str) -> None:
        self._build_puzzles_failure = message
        self.build_puzzles_status_label.setText(f"Build puzzles failed: {message}")
        if self._build_puzzles_dialog is not None:
            self._build_puzzles_dialog.show_failure(message)

    def on_build_puzzles_finished(self) -> None:
        worker = self._build_puzzles_worker
        self._build_puzzles_worker = None

        if self._build_puzzles_failure is not None:
            # on_build_puzzles_failed already set the (more specific) message - leave
            # it showing rather than overwriting it with a generic "Finished"/"Stopped"
            return

        final_text = "Stopped building puzzles." if (worker is not None and worker.stopped) else "Finished building puzzles."
        self.build_puzzles_status_label.setText(final_text)
        if self._build_puzzles_dialog is not None:
            self._build_puzzles_dialog.show_finished(final_text)
        QTimer.singleShot(4000, self.hide_build_puzzles_status)

    def hide_build_puzzles_status(self) -> None:
        for widget in (self.build_puzzles_status_label, self.build_puzzles_progress_bar, self.build_puzzles_stop_button):
            widget.setVisible(False)

    def download_lichess_games(self, max_new_games, title: str) -> None:
        """
        Downloads games from Lichess on a background thread (so the GUI stays
        responsive) behind a visible progress dialog: a filling bar when the
        target count is known (downloading a fixed number of games), or a
        busy/marquee bar with a running tally otherwise (Lichess streams games
        one at a time with no upfront total when downloading "all" of them).
        """
        dialog = DownloadProgressDialog(title=title, maximum=max_new_games, parent=self)
        worker = DownloadGamesWorker(database_file=self.database.file, max_new_games=max_new_games, parent=self)
        worker.progress.connect(dialog.update_progress)

        failure = {"happened": False}

        def on_failed(message: str) -> None:
            failure["happened"] = True
            dialog.show_failure(message)

        def on_finished() -> None:
            if not failure["happened"]:
                dialog.accept()
            self.refresh_stats_tab()

        worker.failed.connect(on_failed)
        worker.finished.connect(on_finished)
        worker.start()
        dialog.exec()

    def file_picker(self, prompt) -> Path:
        dialog = QFileDialog()
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter("All Files (*)")
        dialog.setWindowTitle(prompt)
        dialog.exec()
        return dialog.selectedFiles()[0]
    
    def import_pgn(self) -> None:
        pgn_file = self.file_picker("Select a .pgn file to import")

        with open(pgn_file, "r") as f:
            this_game = chess.pgn.read_game(f)
            self.database.add_game(this_game)

        self.game = this_game
        self.game_review_mode = True

    def open_pgn(self) -> None:
        """Like import_pgn, but doesn't add the game to the database (it's assumed to already be there, or not wanted there)."""
        pgn_file = self.file_picker("Select a .pgn file to open")

        with open(pgn_file, "r") as f:
            self.game = chess.pgn.read_game(f)

        self.game_review_mode = True

    def _load_game_for_review(self, row: pd.Series) -> None:
        """Shared row-picked callback for the Games/Prioritised Games/Showcase Games popups."""
        self.game = chess.pgn.read_game(StringIO(row["pgn"]))
        self.game_review_mode = True

    def show_time_controls_popup(self) -> None:
        time_control_table = pd.DataFrame(self.database.con.execute(
            "SELECT time_control, total_games, average_n_moves, average_total_time_seconds, "
            "average_seconds_per_move, bank_seconds, increment_seconds FROM time_controls_summary").fetchall(),
            columns=["time_control", "total_games", "average_n_moves", "average_total_time_seconds",
                     "average_seconds_per_move", "bank_seconds", "increment_seconds"]).sort_values("total_games", ascending=False)
        time_control_percentiles = pd.DataFrame(self.database.con.execute(
            "SELECT time_control, length/2 AS half_moves FROM games").fetchall(),
            columns=["time_control", "95%_n_moves"]).groupby("time_control")["95%_n_moves"].quantile(.95)
        time_control_table = pd.merge(time_control_table, time_control_percentiles, how="left", on="time_control")
        time_control_table["95%_total_time_seconds"] = time_control_table["bank_seconds"].replace("", "0").astype(int) + time_control_table["increment_seconds"].replace("-", "0").astype(int) * time_control_table["95%_n_moves"]
        time_control_table["95%_seconds_per_move"] = time_control_table["95%_total_time_seconds"] / time_control_table["95%_n_moves"]
        time_control_table[["average_n_moves", "average_total_time_seconds", "average_seconds_per_move", "95%_n_moves", "95%_total_time_seconds", "95%_seconds_per_move"]] = \
            time_control_table[["average_n_moves", "average_total_time_seconds", "average_seconds_per_move", "95%_n_moves", "95%_total_time_seconds", "95%_seconds_per_move"]].round(2)
        TablePopup(title="Time Control Data", dataframe=time_control_table).exec()

    def _games_query(self) -> pd.DataFrame:
        return pd.DataFrame(data=self.database.con.execute(
            "SELECT white, black, timestamp, link, result, time_control, variant, length, pgn, "
            "unique_positions, positions_reviewed, proportion_reviewed, avg_eval_loss, avg_times_practiced, "
            "min_times_practiced, avg_time_since_practice, training_priority FROM game_stats").fetchall(),
            columns=["white", "black", "timestamp", "link", "result", "time_control", "variant", "length", "pgn",
                     "unique_positions", "positions_reviewed", "proportion_reviewed", "avg_eval_loss",
                     "avg_times_practiced", "min_times_practiced", "avg_time_since_practice", "priority"])

    @staticmethod
    def _format_games_table(game_table: pd.DataFrame) -> pd.DataFrame:
        game_table["avg_eval_loss"] = game_table["avg_eval_loss"].apply(lambda x: f"{x*100:.1f}%")
        game_table["priority"] = game_table["priority"].apply(lambda x: f"{x:.2f}")
        game_table["avg_times_practiced"] = game_table["avg_times_practiced"].apply(lambda x: f"{x:.2f}")
        game_table["min_times_practiced"] = game_table["min_times_practiced"].apply(lambda x: f"{x:.0f}")
        game_table["avg_time_since_practice"] = game_table["avg_time_since_practice"].apply(lambda x: f"{x:.1f}")
        game_table["proportion_reviewed"] = game_table["proportion_reviewed"].apply(lambda x: f"{x*100:.1f}%")
        return game_table

    def show_games_popup(self) -> None:
        game_table = self._format_games_table(self._games_query().sort_values(by="timestamp", ascending=False))
        TablePopup(title="Games", dataframe=game_table, on_row_picked=self._load_game_for_review,
                  hidden_columns=("pgn",)).exec()

    def show_prioritised_games_popup(self) -> None:
        game_table = self._games_query()
        game_table["due"] = (game_table["avg_time_since_practice"] > (game_table["min_times_practiced"] ** 2)).astype(int) * 2
        game_table.loc[game_table["min_times_practiced"] == 0, "due"] = 1
        game_table.loc[(game_table["min_times_practiced"] == 0) & (game_table["white"] != username) & (game_table["black"] != username), "due"] = 2
        game_table["priority"] = game_table["priority"] * game_table["avg_times_practiced"] / game_table["avg_time_since_practice"]
        game_table = game_table.sort_values(by=["due", "priority"], ascending=[False, False])
        game_table = self._format_games_table(game_table)
        TablePopup(title="Prioritised Games", dataframe=game_table, on_row_picked=self._load_game_for_review,
                  hidden_columns=("pgn",)).exec()

    def show_showcase_games_popup(self) -> None:
        game_table = self._games_query()
        game_table["quality"] = game_table["avg_eval_loss"] / game_table["length"]
        game_table = game_table.sort_values(by=["quality"], ascending=True)
        game_table = self._format_games_table(game_table)
        TablePopup(title="Showcase Games", dataframe=game_table, on_row_picked=self._load_game_for_review,
                  hidden_columns=("pgn",)).exec()

    def show_puzzles_popup(self) -> None:
        puzzle_table = pd.DataFrame(data=self.database.con.execute("""
                                                                    SELECT
                                                                         position,
                                                                         latest_real_time_control,
                                                                         initial_eval,
                                                                         latest_real_eval_loss,
                                                                         latest_practice_eval_loss,
                                                                         times_seen_in_real_games,
                                                                         days_since_last_seen,
                                                                         days_since_last_practiced,
                                                                         latest_real_time_taken_seconds,
                                                                         latest_practice_time_taken_seconds,
                                                                         times_practiced,
                                                                         priority
                                                                    FROM move_attempt_analysis
                                                                    LIMIT 5000""").fetchall(),
                                     columns=["position",
                                              "latest_real_time_control",
                                              "initial_eval",
                                              "latest_real_eval_loss",
                                              "latest_practice_eval_loss",
                                              "times_seen_in_real_games",
                                              "days_since_last_seen",
                                              "days_since_last_practiced",
                                              "latest_real_time_taken_seconds",
                                              "latest_practice_time_taken_seconds",
                                              "times_practiced",
                                              "priority"])
        TablePopup(title="Puzzles", dataframe=puzzle_table).exec()

    def show_stats_popup(self) -> None:
        stats = pd.DataFrame(dict(self.database.con.execute("SELECT * FROM move_stats").fetchall()[0]),
                             index=["Values"]).transpose().reset_index()
        TablePopup(title="Stats", dataframe=stats).exec()

    @property
    def game(self) -> chess.pgn.Game:
        return self._game
    
    @game.setter
    def game(self, value: chess.pgn.Game) -> None:
        self._game = value
        self.game_node = self.game

    @property
    def game_node(self) -> chess.pgn.GameNode:
        return self._game_node
    
    @property
    def turn(self) -> bool:
        if self.game_node is None:
            return None
        return self.game_node.turn()  # Does NOT account for mirroring, this is the underlying value that can be fed to engines etc
    
    @property
    def review_comment(self) -> str:
        """The review comment of the current position"""
        return self.database.get_position_comment(position=self.position)
    
    @property
    def position_name(self) -> str:
        """The name of the current position"""
        x = self.database.get_position_name(position=self.position)
        if x is None:
            return ""
        return x
    
    @property
    def review_evaluation(self) -> str:
        """The manual evaluation of the current position"""
        x = self.database.get_position_manual_evaluation(position=self.position)
        return x

    @property
    def position(self) -> str:
        if self.board is None:
            return None
        return board_position(board=self.board)
    
    @property
    def board(self) -> chess.Board:
        # Accessor as changes to this board should prompt re-drawing and stuff like that
        # Don't want in general to directly modify it
        if self.game_node is None:
            return None
        return self.game_node.board().copy()
    
    @property
    def zpos(self) -> zPosition:
        return zPosition(fen=self.fen)

    @property
    def fen(self) -> str:
        return self.board.fen()
    
    @property
    def legal_moves(self) -> chess.LegalMoveGenerator:
        if self.board is None:
            return list()
        return self.board.legal_moves
    
    @property
    def legal_next_boards(self) -> Dict[chess.Move, chess.Board]:
        """A dictionary of all legal moves, the key is the chess.Move and the value is the resulting Board."""
        x = dict()
        for this_move in self.legal_moves:
            x[this_move] = self.board
            x[this_move].push(this_move)
        return x
    
    @property
    def moves(self) -> Dict[chess.Move, chess.pgn.ChildNode]:
        """Return a dict of all sub-variations from this position, keyed by the move that results in them."""
        return {i.move: i for i in self.game_node.variations}
    
    @property
    def mirrored(self) -> bool:
        """Whether the board is mirrored or not"""
        return self.gui_board.mirrored

    @property
    def move_from(self) -> Square:
        return self._move_from
    
    @move_from.setter
    def move_from(self, value: Square) -> None:
        assert isinstance(value, Square) or value is None
        self._move_from = value

    @property
    def current_puzzle(self) -> Puzzle:
        return self._current_puzzle
    
    @current_puzzle.setter
    def current_puzzle(self, value: Puzzle) -> None:
        self._current_puzzle = value
        self._current_puzzle_start_time = datetime.datetime.now()
        self.puzzle_attempt = 0

    @property
    def current_puzzle_start_time(self):
        """The time the current puzzle was started"""
        return self._current_puzzle_start_time

    @property
    def mirror_aware_turn(self) -> bool:
        return (self.turn + self.mirrored) % 2
    
    @property
    def moves_table(self) -> pd.DataFrame:
        # Get stats for each possible resulting position
        x = []
        for this_move, this_board in self.legal_next_boards.items():
            this_position = board_position(this_board)
            this_move_san = self.board.san(this_move)
            this_move_data = self.database.con.execute(f"""SELECT position,
                                                                  times_seen
                                                           FROM summarised_positions_seen_in_games
                                                           WHERE position = '{this_position}'""").fetchall()
            this_move_evaluation = self.database.con.execute(f"""SELECT manual_evaluation, name FROM positions WHERE position='{this_position}'""").fetchall()
            this_move_extra_data = self.database.con.execute(f"""SELECT quality,
                                                                        comment,
                                                                        in_repertoire
                                                                 FROM moves
                                                                 WHERE position = '{self.position}'
                                                                 AND resulting_position = '{this_position}'""").fetchall()

            if len(this_move_data) == 0:
                this_move_data = [this_move_san, 0]
            else:
                this_move_data = [this_move_san, tuple(this_move_data[0])[1]]
            
            if len(this_move_evaluation) == 0:
                this_move_evaluation = [None, None]
            else:
                this_move_evaluation = [*tuple(this_move_evaluation[0])]

            if len(this_move_extra_data) == 0:
                this_move_extra_data = ["", "", False]
            else:
                this_move_extra_data = [*tuple(this_move_extra_data[0])]
            
            x.append(this_move_data+this_move_evaluation+this_move_extra_data)

        output = pd.DataFrame(x, columns=["move", "times_seen", "my_evaluation", "name", "quality", "comment", "in_repertoire"])
        output = output[["move", "quality", "my_evaluation", "name", "comment", "in_repertoire", "times_seen"]]
        if self.turn is not None:
            output = output.sort_values("my_evaluation", ascending=bool(1 - self.turn))
        output["my_evaluation"] = output["my_evaluation"].astype(str).fillna("").replace("nan", "")
        output["name"] = output["name"].fillna("")

        return output
    
    def play_sound(self, sound_file: str) -> None:
        self.audio_player.setSource(QUrl.fromLocalFile(sound_file))
        self.audio_player.play()

    def on_board_move(self, move: chess.Move) -> None:
        """Dispatches a move made on the board to puzzle-mode scoring, review-mode
        scoring, or just plays it, depending on the current mode."""
        if self.current_puzzle is not None:
            if self.position == self.current_puzzle.position:
                self._handle_puzzle_move(move)
            else:
                # Wandered off the puzzle's starting position (e.g. via nav buttons) -
                # just play it, still count the attempt
                self.puzzle_attempt += 1
                self.play_move(move)
        elif self.game_review_mode:
            self._handle_review_move(move)
        else:
            self.play_move(move)

    def _handle_puzzle_move(self, move: chess.Move) -> None:
        self.puzzle_attempt += 1
        if self.puzzle_attempt != 1:
            self.play_move(move)
            return

        # Capture the board BEFORE play_move advances game_node/board - the engine's
        # best move must be computed from the position the player was actually in.
        pre_move_board = self.board
        self.database.log_human_move(
            board=pre_move_board, timestamp=datetime.datetime.now(), player=username, move=move,
            is_real=False,
            time_taken_seconds=(datetime.datetime.now() - self.current_puzzle_start_time).total_seconds())

        self.play_move(move)  # advances game_node, plays move sound, yellow-highlights the move - instantly,
                               # no engine calls on this thread

        generation = self._eval_generation  # captured AFTER play_move, so a stale result can be detected
        self._pending_puzzle_move = move
        self._pending_puzzle_snapshot = self.current_puzzle
        self.gui_board.start_pending_highlight(move)
        self.puzzle_move_requested.emit(generation, pre_move_board.fen(), move.uci())

    def _on_puzzle_move_evaluated(self, generation: int, engine_agreed: bool, new_eval: float) -> None:
        if generation != self._eval_generation:
            return  # the board has moved on since this request was made - discard
        self.gui_board.stop_pending_highlight()
        move = self._pending_puzzle_move
        puzzle = self._pending_puzzle_snapshot

        def puzzle_fail() -> None:
            self.play_sound("sounds\\error-when-entering-the-game-menu-132111.mp3")
            self.popup_display_text("Puzzle Result",
                f"Not Quite!\n"
                f"Best Move Eval: {puzzle.evaluation}\n"
                f"Goal Eval: {goal_eval}\n"
                f"Your Original Eval: {puzzle.latest_real_eval}\n"
                f"Your Last Try: {puzzle.latest_practice_eval}\n"
                f"This Try: {new_eval}")
            self.gui_board.highlight_moves(((move, red),))

        def puzzle_success() -> None:
            self.play_sound("sounds\\success-1-6297.mp3")
            highlights = [(move, green)]
            if puzzle.latest_attempt_move is not None:
                highlights.append((puzzle.latest_attempt_move_object, red))
            self.gui_board.highlight_moves(tuple(highlights))

        if engine_agreed:
            puzzle_success()
            return

        goal_eval = puzzle_goal_eval(whose_turn=puzzle.whose_turn,
                                     latest_practice_eval=puzzle.latest_practice_eval,
                                     latest_real_eval=puzzle.latest_real_eval,
                                     puzzle_evaluation=puzzle.evaluation)
        if puzzle.whose_turn == chess.WHITE:
            if new_eval >= goal_eval:
                puzzle_success()
            else:
                puzzle_fail()
        else:
            if new_eval <= goal_eval:
                puzzle_success()
            else:
                puzzle_fail()

    def _handle_review_move(self, move: chess.Move) -> None:
        if self.review_attempt == 0:
            self.database.log_human_move(
                board=self.board, timestamp=datetime.datetime.now(), player=username, move=move,
                is_real=False,
                time_taken_seconds=(datetime.datetime.now() - self._current_game_review_position_start_time).total_seconds())
        self.review_attempt += 1

        # Unlike puzzle mode, the move isn't played yet: today's resolution logic
        # (see _on_review_move_evaluated) sometimes shows the real game's own next
        # move instead of what the player typed, or nothing at all, or pops back to
        # the parent node - which node ends up showing depends on the scoring
        # outcome, so playing the attempted move optimistically here could show the
        # wrong thing. Everything the resolution needs is captured now instead.
        self._review_request_id += 1
        request_id = self._review_request_id
        pre_move_board = self.board
        self._pending_review_move = move
        self._pending_review_node = self.game_node
        self._pending_review_turn = self.turn
        self._pending_review_is_mainline = self.game_node.is_mainline()
        self._pending_review_original_next = self.game_node.next()

        self.gui_board.start_pending_highlight(move)
        original_next_fen = (self._pending_review_original_next.board().fen()
                             if self._pending_review_original_next is not None else "")
        self.review_move_requested.emit(request_id, pre_move_board.fen(), move.uci(), original_next_fen)

    def _on_review_move_evaluated(self, request_id: int, engine_agreed: bool, current_eval: float,
                                  current_eval_2: float, new_eval: float, has_original_game_eval: bool,
                                  original_game_eval: float) -> None:
        if request_id != self._review_request_id:
            return  # a newer review-move request has superseded this one - discard
        self.gui_board.stop_pending_highlight()
        move = self._pending_review_move
        pre_move_node = self._pending_review_node
        pre_move_turn = self._pending_review_turn
        is_mainline_before_move = self._pending_review_is_mainline
        original_next_position = self._pending_review_original_next

        def game_review_fail() -> None:
            self.play_sound("sounds\\error-when-entering-the-game-menu-132111.mp3")
            # Let's try to find a refutation to understand properly why it's not a good move
            if original_next_position is not None and original_next_position.move != move:
                # If it was the actual next move, we'll find the refutation later!
                self.play_move(move)
                self.review_attempt = 0
            self.gui_board.highlight_moves(((move, red),))

        def game_review_success() -> None:
            self.play_sound("sounds\\success-1-6297.mp3")

            if is_mainline_before_move:
                self.review_attempt = 0
                if original_next_position is not None:
                    # Proceed to the next actual position from the game
                    original_move = original_next_position.move
                    self.play_move(original_move)
                    if pre_move_turn != chess.WHITE:
                        worse_for_mover = new_eval > original_game_eval
                    else:
                        worse_for_mover = new_eval < original_game_eval
                    if worse_for_mover:
                        self.gui_board.highlight_moves(((original_move, red), (move, green)))
                    else:
                        self.gui_board.highlight_moves(((move, green),))
                else:
                    self.play_move(move)
            else:
                # Ok, we have found the "refutation" for the current board state which we got
                # ourselves into by making a bad move. Now we go back up a step, hopefully
                # until we get back to the actual mainline of the game!
                self.game_node = pre_move_node.parent
                self.review_attempt = 999

        if engine_agreed:
            game_review_success()
            return

        if original_next_position is not None:
            # There is a next move in the game already (either a mainline move or an
            # already explored sub-variation)
            goal_eval = review_goal_eval(turn=pre_move_turn, current_eval=current_eval, current_eval_2=current_eval_2,
                                        original_game_eval=original_game_eval if has_original_game_eval else None)
        else:
            # There is not a next move already (either the game is over or we are going
            # down a new sub-variation)
            goal_eval = review_goal_eval(turn=pre_move_turn, current_eval=current_eval, current_eval_2=current_eval_2)

        if pre_move_turn == chess.WHITE:
            if new_eval >= goal_eval:
                game_review_success()
            else:
                game_review_fail()
        else:
            if new_eval <= goal_eval:
                game_review_success()
            else:
                game_review_fail()

    def on_engine_move_clicked(self) -> None:
        self.puzzle_attempt += 1
        generation = self._eval_generation
        self.engine_move_button.setEnabled(False)
        self.engine_move_requested.emit(generation, self.board.fen())

    def _on_engine_move_ready(self, generation: int, move_uci: str) -> None:
        self.engine_move_button.setEnabled(True)
        if generation != self._eval_generation:
            return
        self.play_move(chess.Move.from_uci(move_uci))

    def _on_eval_worker_failed(self, request_id: int, message: str) -> None:
        print(f"Background evaluation failed: {message}")
        self.gui_board.stop_pending_highlight()
        self.engine_move_button.setEnabled(True)
        self.next_puzzle_button.setEnabled(True)
        self.next_puzzle_status_label.setVisible(False)
        self.next_puzzle_progress_bar.setVisible(False)

    def play_move(self, move: Move):
        """Update the current board state with the given move, highlighting what's changed."""
        self.play_sound("sounds\\move-self.mp3")
        if move in self.moves.keys():
            self.game_node = self.moves[move]
            return None
        self.game_node = self.game_node.add_variation(move=move)
        return None
    
    def popup_display_text(self, popup_title: str, text: str) -> None:
        """Display a pop up window with a message"""
        popup = TextboxPopup(title=popup_title, message=text)
        popup.exec()
    
    @game_node.setter
    def game_node(self, value: chess.pgn.GameNode):
        # Every position change invalidates any pending background evaluation -
        # bump this before anything else so requests captured after this point
        # (even later in this same setter call) are correctly considered "current".
        self._eval_generation += 1

        # Update Board
        self._game_node = value
        self.game_node_change_signal.emit(value)

        self._current_game_review_position_start_time = datetime.datetime.now()

        self.gui_board.board = self.board

    def _refresh_position_info(self, game_node: chess.pgn.GameNode) -> None:
        """
        Recomputes everything PositionInfoWidget shows for the current position.
        The Stockfish/Leela eval shown is whatever was last computed for this exact
        position - instantly, but possibly stale/placeholder - with the real
        (possibly updated) numbers patched in by _on_position_info_evaluated()
        once the background evaluation finishes.
        """
        self.turn_label.setText("White to move" if self.mirror_aware_turn == chess.WHITE else "Black to move")

        if self.current_puzzle is not None:
            puzzle_summary = (f"Priority: {self.current_puzzle.priority}\n"
                               f"Seen in real games: {self.current_puzzle.times_seen_in_real_games}\n"
                               f"Last practiced: {self.current_puzzle.latest_practiced_timestamp}")
        else:
            puzzle_summary = "No puzzle loaded."

        self.position_info_widget.update_position(
            position=self.position,
            last_seen=self.database.position_last_played(self.position),
            name=self.position_name,
            comment=self.review_comment,
            manual_evaluation=self.review_evaluation,
            puzzle_summary=puzzle_summary)

        generation = self._eval_generation
        self.position_info_requested.emit(generation, self.board.fen())

    def _on_position_info_evaluated(self, generation: int, stockfish_eval: float, leela_eval: float) -> None:
        if generation != self._eval_generation:
            return
        if self.mirrored:  # a pure display transform, read fresh here rather than captured at request time
            stockfish_eval, leela_eval = 1 - stockfish_eval, 1 - leela_eval
        self.position_info_widget.update_evals(stockfish_eval, leela_eval)



if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    import sys

    # Create the Qt Application
    app = QApplication(sys.argv)

    main = MainWindow()
    main.show()

    # Run the main Qt loop
    sys.exit(app.exec())

