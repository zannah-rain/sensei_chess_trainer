#!/usr/bin/env python3

import sys
import queue
import chess
import chess.pgn
import chess.engine
import chess.polyglot
import logging
import platform as sys_plat
from utils.constants import *
from utils.position import *
from utils.puzzle import Puzzle
from zPosition import zPosition
from pathlib import Path
from typing import Dict
from utils.database import Database, position_to_fen
from utils.settings import Settings
from globals import username
import datetime
import pandas as pd
from utils.promotion_select_window import select_promotion_piece
from textwrap import dedent
from io import StringIO
import utils.combined_engines
import utils.colours
from utils.square import Square
from utils.move import Move
from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QFileDialog, QVBoxLayout, QHBoxLayout, QWidget
import PySide6.QtWidgets as QtWidgets
from PySide6.QtGui import QAction
from gui.board import Board
from PySide6.QtMultimedia import QSoundEffect, QMediaPlayer, QAudioOutput
from PySide6.QtCore import QUrl, Signal
from gui.popups import TextboxPopup
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
    return 


class MainWindow(QMainWindow):

    game_node_change_signal = Signal(chess.pgn.GameNode)

    def __init__(self) -> None:
        super(MainWindow, self).__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")

        self.settings = Settings(schema={"Stockfish Executable": "Path",
                                    "Leela Executable": "Path"},
                            save_file=Path("EasyChessGuiSettings.json"),
                            settings_screen_title="Sensei Settings:")

        horizontal_layout = QHBoxLayout()
        vertical_layout_1 = QVBoxLayout()
        vertical_layout_2 = QVBoxLayout()
        vertical_layout_3 = QVBoxLayout()
        horizontal_layout.addLayout(vertical_layout_1)
        horizontal_layout.addLayout(vertical_layout_2)
        horizontal_layout.addLayout(vertical_layout_3)

        self.gui_board = Board()
        vertical_layout_1.addWidget(self.gui_board)

        self.init_menu()

        self.database = Database()
        self.combined_engines = utils.combined_engines.CombinedEngines(settings=self.settings, database=self.database)

        self._game = chess.pgn.Game()
        self._game_node = self.game

        self.audio_player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.audio_player.setAudioOutput(self.audio_output)

        self.popup_display_text("Welcome", f"Welcome to {APP_NAME} {APP_VERSION}!")

        self.position_info_widget = PositionInfoWidget(database=self.database)
        vertical_layout_2.addWidget(self.position_info_widget)

        layout_widget = QWidget()
        layout_widget.setLayout(horizontal_layout)
        self.setCentralWidget(layout_widget)

        tab_widget = QtWidgets.QTabWidget()
        vertical_layout_3.addWidget(tab_widget)

        self.puzzle_widget = QtWidgets.QWidget()
        tab_widget.addTab(self.puzzle_widget, "Puzzles")
        self.init_puzzle_widget()

        self.game_review_widget = QtWidgets.QWidget()
        tab_widget.addTab(self.game_review_widget, "Game Review")

        self.settings_widget = QtWidgets.QWidget()
        tab_widget.addTab(self.settings_widget, "Settings")

    def init_puzzle_widget(self) -> None:
        """Initialise the puzzle widget."""
        layout = QVBoxLayout(self.puzzle_widget)
        
        next_puzzle_button = QtWidgets.QPushButton("Next Puzzle")
        next_puzzle_button.clicked.connect(self.next_puzzle)

        layout.addWidget(next_puzzle_button)

    def next_puzzle(self) -> None:
        self.current_puzzle = self.database.highest_priority_puzzle()
        # Randomise perspective to hopefully help learning
        self.gui_board.randomise_perspective_and_mirroring()
        self.game = chess.pgn.Game().from_board(chess.Board(fen=position_to_fen(self.current_puzzle.position)))
        self.game_review_mode = False
    
    def init_menu(self) -> None:
        self.menu = self.menuBar()

        def add_menu_action(menu, name, callback):
            action = QAction(name, self)
            action.triggered.connect(callback)
            menu.addAction(action)

        menu_data = [
            ("File", [("Build Puzzles", self.build_puzzles)]),
            ("Lichess", [("Download one lichess .pgn", lambda: self.database.download_latest_games(max_new_games=1)),
                         ("Download all lichess .pgn's", lambda: self.database.download_latest_games(max_new_games=None)),
                         ("Download this positions lichess stats", lambda: self.database._populate_lichess_stats(fen=self.fen))])
        ]
        
        for menu_name, actions in menu_data:
            menu = self.menu.addMenu(menu_name)
            for action_name, callback in actions:
                add_menu_action(menu, action_name, callback)

    def build_puzzles(self) -> None:
        self.database.full_engine_evaluation(engine=self.combined_engines.stockfish(), depth_value=12)
        self.database.full_engine_evaluation(engine=self.combined_engines.leela(), depth_value=100)
    
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
        # Update Board
        self._game_node = value
        self.game_node_change_signal.emit(value)

        self._current_game_review_position_start_time = datetime.datetime.now()

        self.gui_board.board = self.board

        # stockfish_eval = self.combined_engines.stockfish_evaluation(depth=25, board=self.board)
        # leela_eval = self.combined_engines.leela_evaluation(nodes=100_000, board=self.board)
        # if self.mirrored:
        #     stockfish_eval = 1 - stockfish_eval
        #     leela_eval = 1 - leela_eval
        # 
        # self.text_output_board_eval_stockfish.update(f"Stockfish evaluation: {stockfish_eval}")
        # self.text_output_board_eval_leela.update(f"Leela evaluation: {leela_eval}")
        #      
        # if self.current_puzzle is not None:
        #     self.text_output_puzzle_priority.update(f"Review Priority: {self.current_puzzle.priority}")
        #     self.text_output_puzzle_times_seen_in_real_games.update(f"Times seen in real games: {self.current_puzzle.times_seen_in_real_games}")
        #     self.text_output_puzzle_last_practiced_date.update(f"Time last practiced: {self.current_puzzle.latest_practiced_timestamp}")
        #     if self.puzzle_attempt == 0:
        #         self.text_output_puzzle_latest_real_attempt_evaluation.update(f"Latest real game eval: -hidden-")
        #         self.text_output_puzzle_latest_real_attempt_evaluation_loss.update(f"Latest real game eval loss: -hidden-")
        #         self.text_output_puzzle_real_time_control.update(f"Latest real game time control: -hidden-")
        #         self.text_output_puzzle_latest_attempt_move.update(f"Last try: -hidden-")
        #         self.text_output_puzzle_latest_attempt_evaluation.update(f"Last eval: -hidden-")
        #         self.text_output_puzzle_latest_evaluation_loss.update(f"Last eval loss: -hidden-")
        #         self.text_output_puzzle_latest_time_taken.update(f"Last time taken: -hidden-")
        #     else:
        #         latest_real_eval = self.current_puzzle.latest_real_eval
        #         last_practice_eval = self.current_puzzle.latest_practice_eval
        #         if self.mirrored:
        #             latest_real_eval = 1 - latest_real_eval
        #             last_practice_eval = 1 - last_practice_eval
        #         self.text_output_puzzle_latest_real_attempt_evaluation.update(f"Latest real game eval: {latest_real_eval}")
        #         self.text_output_puzzle_latest_real_attempt_evaluation_loss.update(f"Latest real game eval loss: {self.current_puzzle.latest_real_eval_loss}")
        #         self.text_output_puzzle_real_time_control.update(f"Latest real game time control: {self.current_puzzle.latest_time_control}")
        #         self.text_output_puzzle_latest_attempt_move.update(f"Last try: {self.current_puzzle.latest_attempt_move}")
        #         self.text_output_puzzle_latest_attempt_evaluation.update(f"Last eval: {last_practice_eval}")
        #         self.text_output_puzzle_latest_evaluation_loss.update(f"Last eval loss: {self.current_puzzle.latest_practice_eval_loss}")
        #         self.text_output_puzzle_latest_time_taken.update(f"Last time taken: {self.current_puzzle.latest_practice_time_taken_seconds}")
        # else:
        #     self.text_output_puzzle_priority.update(f"No puzzle loaded.")
# 
        # self.text_io_review_comment.update(self.review_comment)
        # self.table_output_moves.update(values=self.moves_table.values.tolist())
        # 
        # if self.review_evaluation is not None:
        #     review_eval_str = str(self.review_evaluation)
        # else:
        #     review_eval_str = ""
# 
        # self.text_io_review_evaluation.update(review_eval_str, select=False)
# 
        # if self.position_name is not None:
        #     position_name_str = self.position_name
        # else:
        #     position_name_str = ""
# 
        # self.text_io_review_name.update(position_name_str, select=False)



if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    import sys

    # Create the Qt Application
    app = QApplication(sys.argv)

    main = MainWindow()
    main.show()

    # Run the main Qt loop
    sys.exit(app.exec())



class Old:
    queue = queue.Queue()
    
    def __init__(self) -> None:
        self.text_output_board_date_seen = None
        self.text_output_board_eval_stockfish = None
        self.text_output_board_eval_leela = None
        self.text_output_puzzle_priority = None
        self.text_output_puzzle_times_seen_in_real_games = None
        self.text_output_puzzle_last_practiced_date = None
        self.text_output_puzzle_latest_attempt_move = None
        self.text_output_puzzle_latest_attempt_evaluation = None
        self.text_output_puzzle_latest_evaluation_loss = None
        self.text_output_puzzle_real_time_control = None
        self.text_output_puzzle_latest_time_taken = None
        self.progress_output_today_study = None
        self.progress_output_puzzles_study = None
        self.text_output_today_games = None
        self.text_output_today_puzzles = None
        self.text_output_alltime_games = None
        self.text_output_alltime_puzzles = None
        self.tab_container = None
        self.text_io_review_comment = None
        self.text_io_review_evaluation = None
        self.table_output_moves = None
        self.console_output = None

        # Puzzle stuff
        self._current_puzzle: Puzzle = None
        self._current_puzzle_start_time: datetime.datetime = None
        """"""
        self.puzzle_attempt = 0
        """Tracks attempts at the current puzzle, at the moment only the first attempt is recorded."""
        self.review_attempt = 0
        """Same again for game review moves"""

        self._game_node = None
        
        self.game_review_mode = False
        self._current_game_review_position_start_time: datetime.datetime = None

        # Tracking any short term variables in between window reads
        self.move_state = 0
        self.move_from = None
    
    @game_node.setter
    def game_node(self, value: chess.pgn.GameNode):
        # Update Board
        self._game_node = value
        self.redraw_board()

        self._current_game_review_position_start_time = datetime.datetime.now()

        if isinstance(self._game_node, chess.pgn.ChildNode):
            # Has a parent node and 'move' that we can highlight
            move = self._game_node.move
            if move is not None:
                self.highlight_moves(((move, yellow),))

        last_seen = self.database.position_last_played(gamenode_position(value))
        if last_seen is not None:
            self.text_output_board_date_seen.update(f"Position last played at {last_seen}")
        else:
            self.text_output_board_date_seen.update(f"Position not seen in a real game")

        stockfish_eval = self.combined_engines.stockfish_evaluation(depth=25, board=self.board)
        leela_eval = self.combined_engines.leela_evaluation(nodes=100_000, board=self.board)
        if self.mirrored:
            stockfish_eval = 1 - stockfish_eval
            leela_eval = 1 - leela_eval
        
        self.text_output_board_eval_stockfish.update(f"Stockfish evaluation: {stockfish_eval}")
        self.text_output_board_eval_leela.update(f"Leela evaluation: {leela_eval}")
             
        if self.current_puzzle is not None:
            self.text_output_puzzle_priority.update(f"Review Priority: {self.current_puzzle.priority}")
            self.text_output_puzzle_times_seen_in_real_games.update(f"Times seen in real games: {self.current_puzzle.times_seen_in_real_games}")
            self.text_output_puzzle_last_practiced_date.update(f"Time last practiced: {self.current_puzzle.latest_practiced_timestamp}")
            if self.puzzle_attempt == 0:
                self.text_output_puzzle_latest_real_attempt_evaluation.update(f"Latest real game eval: -hidden-")
                self.text_output_puzzle_latest_real_attempt_evaluation_loss.update(f"Latest real game eval loss: -hidden-")
                self.text_output_puzzle_real_time_control.update(f"Latest real game time control: -hidden-")
                self.text_output_puzzle_latest_attempt_move.update(f"Last try: -hidden-")
                self.text_output_puzzle_latest_attempt_evaluation.update(f"Last eval: -hidden-")
                self.text_output_puzzle_latest_evaluation_loss.update(f"Last eval loss: -hidden-")
                self.text_output_puzzle_latest_time_taken.update(f"Last time taken: -hidden-")
            else:
                latest_real_eval = self.current_puzzle.latest_real_eval
                last_practice_eval = self.current_puzzle.latest_practice_eval
                if self.mirrored:
                    latest_real_eval = 1 - latest_real_eval
                    last_practice_eval = 1 - last_practice_eval
                self.text_output_puzzle_latest_real_attempt_evaluation.update(f"Latest real game eval: {latest_real_eval}")
                self.text_output_puzzle_latest_real_attempt_evaluation_loss.update(f"Latest real game eval loss: {self.current_puzzle.latest_real_eval_loss}")
                self.text_output_puzzle_real_time_control.update(f"Latest real game time control: {self.current_puzzle.latest_time_control}")
                self.text_output_puzzle_latest_attempt_move.update(f"Last try: {self.current_puzzle.latest_attempt_move}")
                self.text_output_puzzle_latest_attempt_evaluation.update(f"Last eval: {last_practice_eval}")
                self.text_output_puzzle_latest_evaluation_loss.update(f"Last eval loss: {self.current_puzzle.latest_practice_eval_loss}")
                self.text_output_puzzle_latest_time_taken.update(f"Last time taken: {self.current_puzzle.latest_practice_time_taken_seconds}")
        else:
            self.text_output_puzzle_priority.update(f"No puzzle loaded.")

        self.text_io_review_comment.update(self.review_comment)
        self.table_output_moves.update(values=self.moves_table.values.tolist())
        
        if self.review_evaluation is not None:
            review_eval_str = str(self.review_evaluation)
        else:
            review_eval_str = ""

        self.text_io_review_evaluation.update(review_eval_str, select=False)

        if self.position_name is not None:
            position_name_str = self.position_name
        else:
            position_name_str = ""

        self.text_io_review_name.update(position_name_str, select=False)
    
    def refresh_stats_tab(self) -> None:
        stats = dict(self.database.con.execute("SELECT * FROM move_stats").fetchall()[0])

        total_eval_improvement_today = stats["sum_real_eval_loss_today"] - stats["sum_practice_eval_loss_today"]
        average_eval_loss_per_day = stats["this_month_total_real_eval_loss"] / 30
        daily_eval_improvement_target = average_eval_loss_per_day * 2

        self.progress_output_today_study.update(total_eval_improvement_today / daily_eval_improvement_target)
        self.progress_output_puzzles_study.update(total_eval_improvement_today / daily_eval_improvement_target)

        self.text_output_today_games.update(dedent(text=f"""\
            Games played: {stats["total_games_played_today"]}
            New puzzles: {stats["total_half_moves_from_real_games_today"] // 2}"""))
        self.text_output_today_puzzles.update(dedent(text=f"""\
            Puzzles done: {stats["positions_practiced_today"]}
            Average original eval loss: {ifnone(stats["average_real_eval_loss_today"], 0):.3f}
            Average new eval loss: {ifnone(stats["average_practice_eval_loss_today"], 0):.3f}
            Improvement: {(1 - ifnone(stats["average_practice_eval_loss_today"], 0) / ifnone(stats["average_real_eval_loss_today"], 1)) * 100:.1f}%
            Total Improvement vs Target: {total_eval_improvement_today:2f} vs {daily_eval_improvement_target:2f}
            """))
        self.text_output_alltime_games.update(dedent(f"""\
            Total games played: {stats["total_games_played"]}
            Average game length: {ifnone(stats["average_game_halfmoves_alltime"], 0) // 2}
            Average eval loss: {ifnone(stats["average_real_eval_loss_alltime"], 0):.3f}
            Average eval loss per game: {ifnone(stats["average_real_eval_loss_alltime"], 0) * ifnone(stats["average_game_halfmoves_alltime"], 0) / 2:.2f}
            This month average eval loss: {ifnone(stats["this_month_average_real_eval_loss"], 0):.3f}
            Average time per move: {ifnone(stats["average_real_time_per_move_alltime"], 0):.1f}
            Total unique positions played: {stats["total_unique_real_positions_played_alltime"]}"""))
        self.text_output_alltime_puzzles.update(dedent(f"""\
            Puzzles done: {stats["total_positions_practiced_alltime"]}
            Average puzzle original eval loss: {ifnone(stats["average_real_eval_loss_in_practiced_positions"], 0):.3f}
            Average puzzle new eval loss: {ifnone(stats["average_practice_eval_loss_alltime"], 0):.3f}
            Times a practiced positions has occurred in a real game: {stats["times_practiced_positions_seen_in_real_games"]}"""))

    def popup_display_table(self, popup_title: str, data: pd.DataFrame) -> None:
        """Display a table of data in a pop up window"""

        popup_layout = [[sg.Table(values=data.values.tolist(), headings=data.columns.tolist(), def_col_width=10, auto_size_columns=False)],
                               [sg.Ok()]]

        popup_window = sg.Window(title=popup_title,
                                 layout=popup_layout).read(close=True)
        
        return popup_window

    def relative_row(self, s: Square | chess.Square, stm):
        """
        The board can be viewed, as white at the bottom and black at the
        top. If stm is white the row 0 is at the bottom. If stm is black
        row 0 is at the top.
        :param s: square
        :param stm: side to move
        :return: relative row
        """
        if isinstance(s, Square):
            s = s.id
        return chess.square_rank(s) if stm else 7 - chess.square_rank(s)

    def get_promo_piece(self, move, stm, human):
        """
        Returns promotion piece.

        :param move: python-chess format
        :param stm: side to move
        :param human: if side to move is human this is True
        :return: promoted piece in python-chess and pythonsimplegui formats
        """
        # If this move is from a user, we will show a window with piece images
        if human:
            psg_promo = select_promotion_piece(stm)

            # If user pressed x we set the promo to queen
            if psg_promo is None:
                print('User did not select a promotion piece, defaulted to queen.')
                psg_promo = QUEENW if stm else QUEENB

            pyc_promo = promote_psg_to_pyc[psg_promo]
        # Else if move is from computer
        else:
            pyc_promo = move.promotion  # This is from python-chess
            if stm:
                if pyc_promo == chess.QUEEN:
                    psg_promo = QUEENW
                elif pyc_promo == chess.ROOK:
                    psg_promo = ROOKW
                elif pyc_promo == chess.BISHOP:
                    psg_promo = BISHOPW
                elif pyc_promo == chess.KNIGHT:
                    psg_promo = KNIGHTW
            else:
                if pyc_promo == chess.QUEEN:
                    psg_promo = QUEENB
                elif pyc_promo == chess.ROOK:
                    psg_promo = ROOKB
                elif pyc_promo == chess.BISHOP:
                    psg_promo = BISHOPB
                elif pyc_promo == chess.KNIGHT:
                    psg_promo = KNIGHTB

        return pyc_promo, psg_promo
    
    def get_human_move(self, window_read_result):
        button, value = window_read_result

        if type(button) is tuple:
            if self.move_state == 1:
                move_to = Square(rank_id = button[0], file_id = button[1])
                to_row, to_col = move_to.tuple
                moved_piece = self.board.piece_type_at(self.move_from.internal_square)
                button_square = self.window.find_element(key=self.move_from.tuple)

                # Create a move in python-chess format based from user input
                user_move = None

                # Get the fr_sq and to_sq of the move from user, based from this info
                # we will create a move based from python-chess format.
                # Note chess.square() and chess.Move() are from python-chess module

                # If user move is a promote
                if self.relative_row(s=move_to, stm=self.board.turn) == RANK_8 and moved_piece == chess.PAWN:
                    pyc_promo, psg_promo = self.get_promo_piece(move=user_move, stm=self.board.turn, human=True)
                    user_move = chess.Move(self.move_from.internal_square, move_to.internal_square, promotion=pyc_promo)
                else:
                    user_move = chess.Move(self.move_from.internal_square, move_to.internal_square)
                
        return window_read_result

    def build_main_layout(self):
        """
        Creates all elements for the GUI, icluding the board layout.

        :return: GUI layout
        """

        # Define board
        board_layout = self.create_board()

        board_tab = [[sg.Column(board_layout)]]

        # Named elements that might need to be updated on the fly
        self.text_output_board_date_seen = sg.Text()
        self.text_output_board_eval_stockfish = sg.Text()
        self.text_output_board_eval_leela = sg.Text()
        self.text_output_board_eval = sg.Text()
        self.text_output_puzzle_latest_real_attempt_evaluation = sg.Text()
        self.text_output_puzzle_latest_real_attempt_evaluation_loss = sg.Text()
        self.text_output_puzzle_priority = sg.Text()
        self.text_output_puzzle_times_seen_in_real_games = sg.Text()
        self.text_output_puzzle_last_practiced_date = sg.Text()
        self.text_output_puzzle_latest_attempt_move = sg.Text()
        self.text_output_puzzle_latest_attempt_evaluation = sg.Text()
        self.text_output_puzzle_latest_evaluation_loss = sg.Text()
        self.text_output_puzzle_real_time_control = sg.Text()
        self.text_output_puzzle_latest_time_taken = sg.Text()
        self.progress_output_today_study = sg.ProgressBar(max_value=1, expand_x=True, size=(1, 3))
        self.progress_output_puzzles_study = sg.ProgressBar(max_value=1, expand_x=True, size=(1, 3))
        self.text_output_today_games = sg.Text()
        self.text_output_today_puzzles = sg.Text()
        self.text_output_alltime_games = sg.Text()
        self.text_output_alltime_puzzles = sg.Text()
        self.text_io_review_comment = sg.Multiline(default_text=self.review_comment, size=(None,20), auto_refresh=True, key="review_comment_key", expand_x=True, expand_y=True)
        self.text_io_review_evaluation = sg.Input(default_text=self.review_evaluation, key="review_manual_evaluation_key")
        self.text_io_review_name = sg.Input(default_text=self.position_name, key="position_name_key")

        # Settings tab
        self.radio_after_success_next_game_position = sg.Radio("Next position from game", group_id="ON_SUCCESS")
        self.radio_after_success_played_move = sg.Radio("Played move", group_id="ON_SUCCESS")
        self.radio_after_success_played_stockfish = sg.Radio("Stockfish response", group_id="ON_SUCCESS")
        self.radio_after_success_played_next_puzzle = sg.Radio("Next Puzzle", group_id="ON_SUCCESS")

        self.radio_after_fail_no_change = sg.Radio("Keep current position", group_id="ON_FAIL")
        self.radio_after_fail_find_refutation = sg.Radio("Find refutation", group_id="ON_FAIL")

        moves_table = self.moves_table
        self.table_output_moves = sg.Table(values=moves_table.values.tolist(), headings=moves_table.columns.tolist())

        self.console_output = sg.Multiline(echo_stdout_stderr=True, reroute_stdout=True, reroute_cprint=True, reroute_stderr=True, expand_x=True, expand_y=True, autoscroll=True)

        main_layout = [[sg.Frame("Position Info", [[sg.Text(text="Position Name:"), self.text_io_review_name],
                                                   [self.text_output_board_date_seen],
                                                   [self.text_output_board_eval_stockfish],
                                                   [self.text_output_board_eval_leela]])]]
        puzzle_layout = [[sg.Frame("Puzzle Info", [
                                                   [self.progress_output_puzzles_study],
                                                   [self.text_output_puzzle_priority],
                                                   [self.text_output_puzzle_times_seen_in_real_games],
                                                   [self.text_output_puzzle_last_practiced_date],
                                                   [self.text_output_puzzle_real_time_control],
                                                   [self.text_output_puzzle_latest_time_taken],
                                                   [self.text_output_puzzle_latest_real_attempt_evaluation],
                                                   [self.text_output_puzzle_latest_real_attempt_evaluation_loss],
                                                   [self.text_output_puzzle_latest_attempt_move],
                                                   [self.text_output_puzzle_latest_attempt_evaluation],
                                                   [self.text_output_puzzle_latest_evaluation_loss]])],
                         [RoundedButton("Next Puzzle", corner_radius=1, border_width=0)]]
        today_layout = [[sg.Frame(title="Games", layout=[[self.text_output_today_games]])],
                        [sg.Frame(title="Puzzles", layout=[[self.progress_output_today_study],
                                                           [self.text_output_today_puzzles]])],
                        [RoundedButton("Refresh", corner_radius=1, border_width=0, key="refresh_stats_tab")]]
        alltime_layout = [[sg.Frame(title="Games", layout=[[self.text_output_alltime_games]])],
                          [sg.Frame(title="Puzzles", layout=[[self.text_output_alltime_puzzles]])]]
        review_layout = [[sg.Text("Manual Evaluation:"), self.text_io_review_evaluation],
                         [sg.Frame(title="Comment", layout=[[self.text_io_review_comment]])]]
        moves_layout = [[sg.Frame(title="Moves", layout=[[self.table_output_moves]])]]
        settings_layout = [[sg.Frame(title="Interaction", layout=[[]])]]
        console_layout = [[self.console_output]]

        # l1 is the layout for tab1
        # l2 is the layout for tab2
        tab_main=sg.Tab("Play", main_layout, key="main_tab")
        tab_puzzles=sg.Tab("Puzzles", puzzle_layout, key="puzzles_tab")
        tab_today=sg.Tab("Today", today_layout, key="today_tab")
        tab_alltime=sg.Tab("All-Time", alltime_layout, key="alltime_tab")
        tab_review=sg.Tab("Review", review_layout, key="review_tab")
        tab_moves=sg.Tab("Moves", moves_layout, key="moves_tab")
        tab_console=sg.Tab("Console", console_layout, key="console_tab")
        self.tab_container = sg.TabGroup([[tab_puzzles, tab_main, tab_today, tab_alltime, tab_review, tab_moves, tab_console]])
        # This titlegroup object may be further used
        # in the row of the main layout.

        layout = [
                [sg.Column(board_tab), 
                 sg.VSeparator(), 
                            [self.tab_container],
                            [RoundedButton("Engine Move", corner_radius=1, border_width=0)],
                            [RoundedButton("<-", corner_radius=1, border_width=0), RoundedButton("->", corner_radius=1, border_width=0)]]
        ]

        return layout

    def main_loop(self):
        """
        Build GUI, read user and engine config files and take user inputs.

        :return:
        """

        if value["review_comment_key"] != self.review_comment:
            self.database.set_position_comment(position=self.position, comment=value["review_comment_key"])

        if value["review_manual_evaluation_key"] != "":
            new_manual_eval = float(value["review_manual_evaluation_key"])
        else:
            new_manual_eval = None

        if new_manual_eval != self.review_evaluation:
            self.database.set_position_manual_evaluation(position=self.position, manual_evaluation=new_manual_eval)

        if value["position_name_key"] != "":
            new_position_name = value["position_name_key"]
        else:
            new_position_name = ""

        if new_position_name != self.position_name:
            self.database.set_position_name(position=self.position, name=new_position_name)

        window_read_result = self.get_human_move(window_read_result=window_read_result)

        if type(window_read_result) == chess.Move:
            # Apply the move logic
            if self.current_puzzle is not None:
                if self.position == self.current_puzzle.position:
                    self.puzzle_attempt += 1
                    if self.puzzle_attempt == 1:
                        # Log the first attempt in the database
                        self.database.log_human_move(board=self.board, 
                                                        timestamp=datetime.datetime.now(), 
                                                        player=username, 
                                                        move=window_read_result, 
                                                        is_real=False,
                                                        time_taken_seconds=(datetime.datetime.now() - self.current_puzzle_start_time).total_seconds())
                        
                        def puzzle_fail() -> None:
                            self.play_sound(sound="sounds//error-when-entering-the-game-menu-132111.mp3")
                            self.popup_display_text(popup_title="Puzzle Result", text=f"""Not Quite!\n"""
                                                                                        f"""Best Move Eval: {self.current_puzzle.evaluation}\n"""
                                                                                        f"""Goal Eval: {goal_eval}\n"""
                                                                                        f"""Your Original Eval: {self.current_puzzle.latest_real_eval}\n"""
                                                                                        f"""Your Last Try: {self.current_puzzle.latest_practice_eval}\n"""
                                                                                        f"""This Try: {new_eval}""")
                            print(f"FAIL:: Target Eval ({goal_eval}) - Your Eval ({new_eval})")
                            self.highlight_moves(square_colour_tuple=((window_read_result, red),))
                        def puzzle_success() -> None:
                            self.play_sound("sounds//success-1-6297.mp3")
                            print(f"SUCCESS:: Target Eval ({goal_eval}) - Your Eval ({new_eval})")
                            self.highlight_moves(square_colour_tuple=((self.current_puzzle.latest_attempt_move_object, red),
                                                                        (window_read_result, green)))

                        self.play_move(move=window_read_result)

                        engine_move: chess.Move = self.database.engine_move(board=self.board, engine=self.combined_engines.stockfish(), depth_value=23, multipv=1)
                        if engine_move == window_read_result:
                            puzzle_success()

                        new_eval: float = self.combined_engines.stable_evaluation(min_depth=20, min_nodes=10_000, max_depth=30, max_instability=0.009)

                        # Want to move at least 5% towards the best move to consider myself 'improving' (otherwise 'success' can mean going from 99.9% loss to 99.8% when there's a way out)
                        if self.current_puzzle.whose_turn == chess.WHITE:
                            # At least 10% improvement on last try if not the best move
                            goal_eval = max(self.current_puzzle.latest_practice_eval, self.current_puzzle.latest_real_eval) * 0.9 + self.current_puzzle.evaluation * 0.1
                            # At most 20% evaluation loss against best move
                            goal_eval = max(goal_eval, self.current_puzzle.evaluation - 0.2)
                            # Always success if within 1% evaluation of best move (at least while engine evaluations aren't so reliable cos I want them fast)
                            goal_eval = min(goal_eval, self.current_puzzle.evaluation - 0.01)
                            if (new_eval >= goal_eval):
                                puzzle_success()
                            else:
                                puzzle_fail()
                        else:
                            goal_eval = min(self.current_puzzle.latest_practice_eval, self.current_puzzle.latest_real_eval) * 0.9 + self.current_puzzle.evaluation * 0.1
                            goal_eval = min(goal_eval, self.current_puzzle.evaluation + 0.2)
                            goal_eval = max(goal_eval, self.current_puzzle.evaluation + 0.01)
                            if (new_eval <= goal_eval):
                                puzzle_success()
                            else:
                                puzzle_fail()
                    else:
                        self.play_move(move=window_read_result)
                else:
                    self.puzzle_attempt += 1
                    self.play_move(move=window_read_result)
            elif self.game_review_mode:
                # Similar to doing a puzzle, BUT
                # - Success = Playing a move that is good when compared with the best move and the move that was originally played in that game (not our last attempt)
                # - On success, the board will progress to the next board state from that game, not necessarily from the move we just played
                # - There are unlimited attempts to solve
                # Log the first attempt in the database
                if self.review_attempt == 0:
                    self.database.log_human_move(board=self.board, 
                                                    timestamp=datetime.datetime.now(), 
                                                    player=username, 
                                                    move=window_read_result, 
                                                    is_real=False,
                                                    time_taken_seconds=(datetime.datetime.now() - self._current_game_review_position_start_time).total_seconds())
                self.review_attempt += 1
                
                original_next_position = self.game_node.next()
                this_attempt_next_position = self.game_node.board().copy()
                this_attempt_next_position.push(window_read_result)
                
                def game_review_fail() -> None:
                    self.play_sound("sounds//error-when-entering-the-game-menu-132111.mp3")
                    print(f"FAIL:: Target Eval ({goal_eval}) - Your Eval ({new_eval})")
                    # Let's try to find a refutation to understand properly why it's not a good move
                    if original_next_position is not None:
                        if original_next_position.move != window_read_result:
                            # If it was the actual next move, we'll find the refutation later!
                            self.play_move(move=window_read_result)
                            self.review_attempt = 0

                    self.highlight_moves(move_colour_tuple=((window_read_result, red),))

                def game_review_success() -> None:
                    self.play_sound("sounds//success-1-6297.mp3")
                    print(f"SUCCESS:: Target Eval ({goal_eval}) - Your Eval ({new_eval})")

                    if self.game_node.is_mainline():
                        self.review_attempt = 0
                        if original_next_position is not None:
                            # Proceed to the next actual position from the game
                            self.play_move(move=original_next_position.move)
                            original_move = original_next_position.move
                            original_game_eval: float = self.combined_engines.stable_evaluation(min_depth=23, min_nodes=5000, max_depth=30, max_instability=0.009, board=original_next_position.board())
                            if self.turn != chess.WHITE:
                                if new_eval > original_game_eval:
                                    self.highlight_moves(((original_move, red),
                                                            (window_read_result, green)))
                            else:
                                if new_eval < original_game_eval:
                                    self.highlight_moves(((original_move, red),
                                                            (window_read_result, green)))
                        else:
                            self.play_move(move=window_read_result)
                    else:
                        # Ok, we have found the "refutation" for the current board state which we got ourselves into by making a bad move
                        # Now we go back up a step, hopefully until we get back to the actual mainline of the game!
                        self.game_node = self.game_node.parent
                        self.review_attempt = 999

                engine_move: chess.Move = self.database.engine_move(board=self.board, engine=self.combined_engines.stockfish(), depth_value=23, multipv=1)
                engine_move_position = self.game_node.board().copy()
                engine_move_position.push(engine_move)

                current_eval: float = self.combined_engines.stable_evaluation(min_depth=23, min_nodes=5000, max_depth=30, max_instability=0.009)
                current_eval_2: float = self.combined_engines.stable_evaluation(min_depth=23, min_nodes=5000, max_depth=30, max_instability=0.009, board=engine_move_position)
                new_eval: float = self.combined_engines.stable_evaluation(min_depth=23, min_nodes=5000, max_depth=30, max_instability=0.009, board=this_attempt_next_position)

                if engine_move == window_read_result:
                    goal_eval = current_eval
                    game_review_success()

                if original_next_position is not None:
                    # There is a next move in the game already (either a mainline move or an already explored sub-variation)
                    original_move = original_next_position.move
                    original_game_eval: float = self.combined_engines.stable_evaluation(min_depth=23, min_nodes=5000, max_depth=30, max_instability=0.009, board=original_next_position.board())

                    # Want to move at least 5% towards the best move to consider myself 'improving' (otherwise 'success' can mean going from 99.9% loss to 99.8% when there's a way out)
                    if self.turn == chess.WHITE:
                        current_eval = min(current_eval, current_eval_2)  # Engine evaluations get unstable in sharp positions, this helps
                        # At least 10% improvement on last try if not the best move
                        # At most 5% evaluation loss against best move
                        goal_eval = max(original_game_eval, current_eval - 0.03)  # If the move played in the game was worse than ~20cp loss, we want to find an even better one!
                        goal_eval = min(goal_eval, current_eval - 0.01)  # If we play a move as good as carlsen manages on average, it should still count as a success even if the move in the original game is better!
                        if (new_eval >= goal_eval):
                            game_review_success()
                        else:
                            game_review_fail()
                    else:
                        current_eval = max(current_eval, current_eval_2)  # Engine evaluations get unstable in sharp positions, this helps
                        goal_eval = min(original_game_eval, current_eval + 0.03)
                        goal_eval = max(goal_eval, current_eval + 0.01)
                        if (new_eval <= goal_eval):
                            game_review_success()
                        else:
                            game_review_fail()
                else:
                    # There is not a next move already (either the game is over or we are going down a new sub-variation)
                    # Want to move at least 5% towards the best move to consider myself 'improving' (otherwise 'success' can mean going from 99.9% loss to 99.8% when there's a way out)
                    if self.turn == chess.WHITE:
                        # At least 10% improvement on last try if not the best move
                        current_eval = min(current_eval, current_eval_2)  # Engine evaluations get unstable in sharp positions, this helps
                        goal_eval = current_eval - 0.04
                        if (new_eval >= goal_eval):
                            game_review_success()
                        else:
                            game_review_fail()
                    else:
                        current_eval = max(current_eval, current_eval_2)  # Engine evaluations get unstable in sharp positions, this helps
                        goal_eval = current_eval + 0.04
                        if (new_eval <= goal_eval):
                            game_review_success()
                        else:
                            game_review_fail()
            else:
                self.play_move(move=window_read_result)

        if button == "Engine Move":
            self.puzzle_attempt += 1
            self.play_move(self.database.engine_move(board=self.board, engine=self.combined_engines.stockfish(), depth_value=20, multipv=1))

        if button == "Open .pgn":
            with open(self.file_picker(prompt=".pgn file:")[1]["Browse"], "r") as f:
                self.game = chess.pgn.read_game(f)
                self.game_review_mode = True

        if button == "Download all lichess .pgn's":
            self.database.download_latest_games()

        if button == "Time Controls":
            time_control_table = pd.DataFrame(self.database.con.execute("SELECT time_control, total_games, average_n_moves, average_total_time_seconds, average_seconds_per_move, bank_seconds, increment_seconds FROM time_controls_summary").fetchall(),
                                        columns=["time_control", "total_games", "average_n_moves", "average_total_time_seconds", "average_seconds_per_move", "bank_seconds", "increment_seconds"]).sort_values("total_games", ascending=False)
            time_control_percentiles = pd.DataFrame(self.database.con.execute("SELECT time_control, length/2 AS half_moves FROM games").fetchall(),
                                                    columns=["time_control", "95%_n_moves"]).groupby("time_control")["95%_n_moves"].quantile(.95)
            time_control_table = pd.merge(time_control_table, time_control_percentiles, how="left", on="time_control")
            time_control_table["95%_total_time_seconds"] = time_control_table["bank_seconds"].replace("", "0").astype(int) + time_control_table["increment_seconds"].replace("-", "0").astype(int) * time_control_table["95%_n_moves"]
            time_control_table["95%_seconds_per_move"] = time_control_table["95%_total_time_seconds"] / time_control_table["95%_n_moves"]
            time_control_table[["average_n_moves", "average_total_time_seconds", "average_seconds_per_move", "95%_n_moves", "95%_total_time_seconds", "95%_seconds_per_move"]] = time_control_table[["average_n_moves", "average_total_time_seconds", "average_seconds_per_move", "95%_n_moves", "95%_total_time_seconds", "95%_seconds_per_move"]].round(2)
            self.popup_display_table(popup_title="Time Control Data",
                                        data=time_control_table)

        if button == "Games":
            game_table = pd.DataFrame(data=self.database.con.execute("SELECT white, black, timestamp, link, result, time_control, variant, length, pgn, unique_positions, positions_reviewed, proportion_reviewed, avg_eval_loss, avg_times_practiced, min_times_practiced, avg_time_since_practice, training_priority FROM game_stats").fetchall(),
                                        columns=["white", "black", "timestamp", "link", "result", "time_control", "variant", "length", "pgn", "unique_positions", "positions_reviewed", "proportion_reviewed", "avg_eval_loss", "avg_times_practiced", "min_times_practiced", "avg_time_since_practice", "priority"]).sort_values(by="timestamp", ascending=False)
            game_table["avg_eval_loss"] = game_table["avg_eval_loss"].apply(lambda x: f"{x*100:.1f}%")
            game_table["priority"] = game_table["priority"].apply(lambda x: f"{x:.2f}")
            game_table["avg_times_practiced"] = game_table["avg_times_practiced"].apply(lambda x: f"{x:.2f}")
            game_table["min_times_practiced"] = game_table["min_times_practiced"].apply(lambda x: f"{x:.0f}")
            game_table["avg_time_since_practice"] = game_table["avg_time_since_practice"].apply(lambda x: f"{x:.1f}")
            game_table["proportion_reviewed"] = game_table["proportion_reviewed"].apply(lambda x: f"{x*100:.1f}%")
            popup_result = self.popup_display_table(popup_title="Games",
                                                    data=game_table.drop(columns=["pgn"]))
            if popup_result[1][0] is not None:
                self.game = chess.pgn.read_game(StringIO(game_table.iloc[popup_result[1][0][0], :]["pgn"]))
                self.game_review_mode = True

        if button == "Prioritised Games":
            game_table = pd.DataFrame(data=self.database.con.execute("SELECT white, black, timestamp, link, result, time_control, variant, length, pgn, unique_positions, positions_reviewed, proportion_reviewed, avg_eval_loss, avg_times_practiced, min_times_practiced, avg_time_since_practice, training_priority FROM game_stats").fetchall(),
                                        columns=["white", "black", "timestamp", "link", "result", "time_control", "variant", "length", "pgn", "unique_positions", "positions_reviewed", "proportion_reviewed", "avg_eval_loss", "avg_times_practiced", "min_times_practiced", "avg_time_since_practice", "priority"])
            game_table["due"] = (game_table["avg_time_since_practice"] > (game_table["min_times_practiced"] ** 2)).astype(int) * 2
            game_table.loc[game_table["min_times_practiced"] == 0, "due"] = 1
            game_table.loc[(game_table["min_times_practiced"] == 0) & (game_table["white"] != username) & (game_table["black"] != username), "due"] = 2
            game_table["priority"] = game_table["priority"] * game_table["avg_times_practiced"] / game_table["avg_time_since_practice"]
            game_table = game_table.sort_values(by=["due", "priority"], ascending=[False, False])
            game_table["avg_eval_loss"] = game_table["avg_eval_loss"].apply(lambda x: f"{x*100:.1f}%")
            game_table["priority"] = game_table["priority"].apply(lambda x: f"{x:.2f}")
            game_table["avg_times_practiced"] = game_table["avg_times_practiced"].apply(lambda x: f"{x:.2f}")
            game_table["min_times_practiced"] = game_table["min_times_practiced"].apply(lambda x: f"{x:.0f}")
            game_table["avg_time_since_practice"] = game_table["avg_time_since_practice"].apply(lambda x: f"{x:.1f}")
            game_table["proportion_reviewed"] = game_table["proportion_reviewed"].apply(lambda x: f"{x*100:.1f}%")
            popup_result = self.popup_display_table(popup_title="Prioritised Games",
                                                    data=game_table.drop(columns=["pgn"]))
            if popup_result[1][0] is not None:
                self.game = chess.pgn.read_game(StringIO(game_table.iloc[popup_result[1][0][0], :]["pgn"]))
                self.game_review_mode = True

        if button == "Showcase Games":
            game_table = pd.DataFrame(data=self.database.con.execute("SELECT white, black, timestamp, link, result, time_control, variant, length, pgn, unique_positions, positions_reviewed, proportion_reviewed, avg_eval_loss, avg_times_practiced, min_times_practiced, avg_time_since_practice, training_priority FROM game_stats").fetchall(),
                                        columns=["white", "black", "timestamp", "link", "result", "time_control", "variant", "length", "pgn", "unique_positions", "positions_reviewed", "proportion_reviewed", "avg_eval_loss", "avg_times_practiced", "min_times_practiced", "avg_time_since_practice", "priority"])
            game_table["quality"] = game_table["avg_eval_loss"] / game_table["length"]
            game_table = game_table.sort_values(by=["quality"], ascending=True)
            game_table["avg_eval_loss"] = game_table["avg_eval_loss"].apply(lambda x: f"{x*100:.1f}%")
            game_table["priority"] = game_table["priority"].apply(lambda x: f"{x:.2f}")
            game_table["avg_times_practiced"] = game_table["avg_times_practiced"].apply(lambda x: f"{x:.2f}")
            game_table["min_times_practiced"] = game_table["min_times_practiced"].apply(lambda x: f"{x:.0f}")
            game_table["avg_time_since_practice"] = game_table["avg_time_since_practice"].apply(lambda x: f"{x:.1f}")
            game_table["proportion_reviewed"] = game_table["proportion_reviewed"].apply(lambda x: f"{x*100:.1f}%")
            popup_result = self.popup_display_table(popup_title="Showcase Games",
                                                    data=game_table.drop(columns=["pgn"]))
            if popup_result[1][0] is not None:
                self.game = chess.pgn.read_game(StringIO(game_table.iloc[popup_result[1][0][0], :]["pgn"]))
                self.game_review_mode = True

        if button == "Puzzles":
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
            popup_result = self.popup_display_table(popup_title="Puzzles",
                                                    data=puzzle_table)
            #if popup_result[1][0] is not None:
            #    self.game_node = chess.pgn.read_game(StringIO(game_table.iloc[popup_result[1][0][0], :]["pgn"]))

        if button == "Stats":
            self.popup_display_table(popup_title="Stats",
                                        data=pd.DataFrame(dict(self.database.con.execute("SELECT * FROM move_stats").fetchall()[0]), index=["Values"]).transpose().reset_index())

        if button == "Download this positions lichess stats":
            self.database._populate_lichess_stats(fen=self.fen)
            

        if (button == "->") or (button == "right_arrow_key"):
            next_node = self.game_node.next()
            if next_node is not None:
                self.game_node = next_node
            else:
                print("End of game")

        if (button == "<-") or (button == "left_arrow_key"):
            if not isinstance(self.game_node, chess.pgn.ChildNode):
                print("Can't get parent node of non-ChildNode game_node")
            
            prev_node = self.game_node.parent
            if prev_node is not None:
                self.game_node = prev_node

        if button == 'Flip':
            self.flip_board()

        if button == "Mirror":
            self.mirrored = (self.mirrored + 1) % 2

        if button == "refresh_stats_tab":
            self.refresh_stats_tab()
    
    
