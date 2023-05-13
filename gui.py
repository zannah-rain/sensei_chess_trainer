#!/usr/bin/env python3
""" 
python_easy_chess_gui.py

Requirements:
    Python 3.7.3 and up

PySimpleGUI Square Mapping
board = [
    56, 57, ... 63
    ...
    8, 9, ...
    0, 1, 2, ...
]

row = [
    0, 0, ...
    1, 1, ...
    ...
    7, 7 ...
]

col = [
    0, 1, 2, ... 7
    0, 1, 2, ...
    ...
    0, 1, 2, ... 7
]


Python-Chess Square Mapping
board is the same as in PySimpleGUI
row is reversed
col is the same as in PySimpleGUI

"""

import PySimpleGUI as sg
import os
import sys
import queue
import copy
import chess
import chess.pgn
import chess.engine
import chess.polyglot
import logging
import platform as sys_plat
from utils.constants import *
from zPosition import zPosition
from pathlib import Path
from typing import Dict
from utils.database import Database

logging.basicConfig(level=logging.INFO)

platform = sys.platform
sys_os = sys_plat.system()

APP_NAME = 'Sensei'
APP_VERSION = 'v1.0.0'
BOX_TITLE = '{} {}'.format(APP_NAME, APP_VERSION)

MIN_DEPTH = 1
MAX_DEPTH = 1000


# (1) Mode: Neutral
menu_def_neutral = [
        ["File", ["Open .pgn"]],
        ['&Mode', ['Play']],
        ['Boar&d', ['Flip', 'Color', ['Brown::board_color_k',
                                      'Blue::board_color_k',
                                      'Green::board_color_k',
                                      'Gray::board_color_k'],
                    'Theme', GUI_THEME
                   ]
        ],
        ['&Time', ['User::tc_k', 'Engine::tc_k']],
        ['&Settings', ['Game::settings_game_k']],
        ['&Help', ['About']],
]

class EasyChessGui:
    queue = queue.Queue()
    is_user_white = True  # White is at the bottom in board layout

    def __init__(self, theme, fen = chess.STARTING_FEN):
        self.database = Database()

        self.theme = theme
        self.gui_theme = 'Reddit'
        
        self.menu_elem = None
        self.username = 'Acolyte Zoe'

        self.human_side = chess.WHITE

        # Default board color is brown
        self.sq_light_color = '#F0D9B5'
        self.sq_dark_color = '#B58863'

        # Move highlight, for brown board
        self.move_sq_light_color = '#E8E18E'
        self.move_sq_dark_color = '#B8AF4E'

        layout = self.build_main_layout(True)
        self.window = sg.Window('{} {}'.format(APP_NAME, APP_VERSION),
                                layout, default_button_element_size=(12, 1),
                                auto_size_buttons=False,
                                icon=ico_path[platform]['pecg']).finalize()
        
        self.game = chess.pgn.Game()
        self.game_node = self.game

        # Tracking any short term variables in between window reads
        self.move_state = 0
        self.move_from = None

    @property
    def game(self) -> chess.pgn.Game:
        return self._game
    
    @game.setter
    def game(self, value: chess.pgn.Game):
        self._game = value
        self.game_node = self.game

    @property
    def game_node(self) -> chess.pgn.GameNode:
        return self._game_node
    
    @game_node.setter
    def game_node(self, value: chess.pgn.GameNode):

        self.redraw_board(self.window)
        self._game_node = value
        self._psg_board = self.fen_to_psg_board()
        self.redraw_board(self.window)

        if isinstance(self._game_node, chess.pgn.ChildNode):
            # Has a parent node and 'move' that we can highlight
            move = self._game_node.move
            if move is not None:
                self.change_square_color(self.window, 7 - chess.square_rank(move.from_square), chess.square_file(move.from_square))
                self.change_square_color(self.window, 7 - chess.square_rank(move.to_square), chess.square_file(move.to_square))
    
    @property
    def board(self) -> chess.Board:
        # Accessor as changes to this board should prompt re-drawing and stuff like that
        # Don't want in general to directly modify it
        return self._game_node.board().copy()
    
    @property
    def zpos(self) -> zPosition:
        return zPosition(fen=self.fen)

    @property
    def psg_board(self):
        return self._psg_board

    @property
    def fen(self) -> str:
        return self.board.fen()

    def create_new_window(self, window: sg.Window, flip=False) -> sg.Window:
        """ Close the window param just before turning the new window """

        loc = window.CurrentLocation()
        window.Hide()
        if flip:
            self.is_user_white = not self.is_user_white

        layout = self.build_main_layout(self.is_user_white)

        w = sg.Window('{} {}'.format(APP_NAME, APP_VERSION),
            layout,
            default_button_element_size=(12, 1),
            auto_size_buttons=False,
            location=(loc[0], loc[1]),
            icon=ico_path[platform]['pecg']).finalize()

        window.Close()
        return w
    
    def file_picker(self, prompt) -> Path:
        event, values = sg.Window('Login Window',
                  [[sg.T(prompt), sg.FileBrowse()],
                  [sg.B('OK')]]).read(close=True)
        return event, values

    def fen_to_psg_board(self):
        """ Update psg_board based on FEN """
        psgboard = []

        # Get piece locations only to build psg board
        pc_locations = self.fen.split()[0]

        board = chess.BaseBoard(pc_locations)
        old_r = None

        for s in chess.SQUARES:
            r = chess.square_rank(s)

            if old_r is None:
                piece_r = []
            elif old_r != r:
                psgboard.append(piece_r)
                piece_r = []
            elif s == 63:
                psgboard.append(piece_r)

            try:
                pc = board.piece_at(s^56)
            except Exception:
                pc = None
                logging.exception('Failed to get piece.')

            if pc is not None:
                pt = pc.piece_type
                c = pc.color
                if c:
                    if pt == chess.PAWN:
                        piece_r.append(PAWNW)
                    elif pt == chess.KNIGHT:
                        piece_r.append(KNIGHTW)
                    elif pt == chess.BISHOP:
                        piece_r.append(BISHOPW)
                    elif pt == chess.ROOK:
                        piece_r.append(ROOKW)
                    elif pt == chess.QUEEN:
                        piece_r.append(QUEENW)
                    elif pt == chess.KING:
                        piece_r.append(KINGW)
                else:
                    if pt == chess.PAWN:
                        piece_r.append(PAWNB)
                    elif pt == chess.KNIGHT:
                        piece_r.append(KNIGHTB)
                    elif pt == chess.BISHOP:
                        piece_r.append(BISHOPB)
                    elif pt == chess.ROOK:
                        piece_r.append(ROOKB)
                    elif pt == chess.QUEEN:
                        piece_r.append(QUEENB)
                    elif pt == chess.KING:
                        piece_r.append(KINGB)

            # Else if pc is None or square is empty
            else:
                piece_r.append(BLANK)

            old_r = r

        return psgboard

    def change_square_color(self, window: sg.Window, row, col):
        """ 
        Change the color of a square based on square row and col.
        """
        btn_sq = window.find_element(key=(row, col))
        is_dark_square = True if (row + col) % 2 else False
        bd_sq_color = self.move_sq_dark_color if is_dark_square else \
                      self.move_sq_light_color
        btn_sq.Update(button_color=('white', bd_sq_color))

    def relative_row(self, s, stm):
        """
        The board can be viewed, as white at the bottom and black at the
        top. If stm is white the row 0 is at the bottom. If stm is black
        row 0 is at the top.
        :param s: square
        :param stm: side to move
        :return: relative row
        """
        return 7 - self.get_row(s) if stm else self.get_row(s)

    def get_row(self, s):
        """
        This row is based on PySimpleGUI square mapping that is 0 at the
        top and 7 at the bottom.
        In contrast Python-chess square mapping is 0 at the bottom and 7
        at the top. chess.square_rank() is a method from Python-chess that
        returns row given square s.

        :param s: square
        :return: row
        """
        return 7 - chess.square_rank(s)

    def get_col(self, s):
        """ Returns col given square s """
        return chess.square_file(s)

    def redraw_board(self, window: sg.Window):
        """
        Redraw board at start and afte a move.

        :param window:
        :return:
        """
        for i in range(8):
            for j in range(8):
                color = self.sq_dark_color if (i + j) % 2 else \
                        self.sq_light_color
                piece_image = images[self.psg_board[i][j]]
                elem = window.find_element(key=(i, j))
                elem.Update(button_color=('white', color),
                            image_filename=piece_image, )

    def render_square(self, image, key, location):
        """ Returns an RButton (Read Button) with image image """
        if (location[0] + location[1]) % 2:
            color = self.sq_dark_color  # Dark square
        else:
            color = self.sq_light_color
        return sg.RButton('', image_filename=image, size=(1, 1),
                          border_width=0, button_color=('white', color),
                          pad=(0, 0), key=key)

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
            psg_promo = self.select_promotion_piece(stm)

            # If user pressed x we set the promo to queen
            if psg_promo is None:
                logging.info('User did not select a promotion piece, '
                             'set this to queen.')
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

        # Mode: Play, stm: User, user starts moving
        if type(button) is tuple:
            # If fr_sq button is pressed
            if self.move_state == 0:
                self.move_from = button
                fr_row, fr_col = self.move_from
                piece = self.psg_board[fr_row][fr_col]  # get the move-from piece

                # Change the color of the "fr" board square
                self.change_square_color(self.window, fr_row, fr_col)

                self.move_state = 1
                moved_piece = self.board.piece_type_at(chess.square(fr_col, 7-fr_row))  # Pawn=1

                return None

            # Else if to_sq button is pressed
            elif self.move_state == 1:
                move_to = button
                fr_row, fr_col = self.move_from
                to_row, to_col = move_to
                moved_piece = self.board.piece_type_at(chess.square(fr_col, 7-fr_row))
                button_square = self.window.find_element(key=(fr_row, fr_col))

                # If move is cancelled, pressing same button twice
                if move_to == self.move_from:
                    # Restore the color of the pressed board square
                    color = self.sq_dark_color if (to_row + to_col) % 2 else self.sq_light_color

                    # Restore the color of the fr square
                    button_square.Update(button_color=('white', color))
                    self.move_state = 0
                    return None

                # Create a move in python-chess format based from user input
                user_move = None

                # Get the fr_sq and to_sq of the move from user, based from this info
                # we will create a move based from python-chess format.
                # Note chess.square() and chess.Move() are from python-chess module
                fr_row, fr_col = self.move_from
                fr_sq = chess.square(fr_col, 7-fr_row)
                to_sq = chess.square(to_col, 7-to_row)

                # If user move is a promote
                if self.relative_row(to_sq, self.board.turn) == RANK_8 and moved_piece == chess.PAWN:
                    pyc_promo, psg_promo = self.get_promo_piece(user_move, self.board.turn, True)
                    user_move = chess.Move(fr_sq, to_sq, promotion=pyc_promo)
                else:
                    user_move = chess.Move(fr_sq, to_sq)

                # Check if user move is legal
                if user_move in list(self.board.legal_moves):
                    self.play_move(move=user_move)

                    self.move_from = None
                    self.move_state = 0

                    return user_move

                # Else if move is illegal
                else:
                    self.move_state = 0
                    color = self.sq_dark_color \
                        if (self.move_from[0] + self.move_from[1]) % 2 else self.sq_light_color

                    # Restore the color of the fr square
                    button_square.Update(button_color=('white', color))
                    return None
                
        return window_read_result
    
    @property
    def moves(self) -> Dict[chess.Move, chess.pgn.ChildNode]:
        """Return a dict of all sub-variations from this position, keyed by the move that results in them."""
        return {i.move: i for i in self.game_node.variations}
                
    def play_move(self, move: chess.Move):
        """Update the current board state with the given move, highlighting what's changed."""
        if move in self.moves.keys():
            self.game_node = self.moves[move]
            return None
        self.game_node = self.game_node.add_variation(move=move)
        return None

    def create_board(self, is_user_white=True):
        """
        Returns board layout based on color of user. If user is white,
        the white pieces will be at the bottom, otherwise at the top.

        :param is_user_white: user has handling the white pieces
        :return: board layout
        """
        file_char_name = 'abcdefgh'
        self._psg_board = copy.deepcopy(initial_board)

        board_layout = []

        if is_user_white:
            # Save the board with black at the top        
            start = 0
            end = 8
            step = 1
        else:
            start = 7
            end = -1
            step = -1
            file_char_name = file_char_name[::-1]

        # Loop through the board and create buttons with images
        for i in range(start, end, step):
            # Row numbers at left of board is blank
            row = []
            for j in range(start, end, step):
                piece_image = images[self.psg_board[i][j]]
                row.append(self.render_square(piece_image, key=(i, j), location=(i, j)))
            board_layout.append(row)

        return board_layout

    def build_main_layout(self, is_user_white=True):
        """
        Creates all elements for the GUI, icluding the board layout.

        :param is_user_white: if user is white, the white pieces are
        oriented such that the white pieces are at the bottom.
        :return: GUI layout
        """
        sg.ChangeLookAndFeel(self.gui_theme)
        sg.SetOptions(margins=(0, 3), border_width=1)

        # Define board
        board_layout = self.create_board(is_user_white)

        board_tab = [[sg.Column(board_layout)]]

        self.menu_elem = sg.Menu(menu_def_neutral, tearoff=False)

        # White board layout, mode: Neutral
        layout = [
                [self.menu_elem],
                [sg.Column(board_tab), 
                 sg.VSeparator(), 
                 sg.Column([[sg.Button("Engine Move")], 
                            [sg.Button("<-"), sg.Button("->")]])]
        ]

        return layout

    def main_loop(self, engines):
        """
        Build GUI, read user and engine config files and take user inputs.

        :return:
        """
        
        pc_locations = self.fen.split()[0]

        board = chess.Board(fen=self.fen)

        # Mode: Neutral, main loop starts here
        while True:
            window_read_result = self.window.Read(timeout=50)
            button, value = window_read_result

            # Mode: Neutral
            if button is None:
                logging.info('Quit app from main loop, X is pressed.')
                break

            window_read_result = self.get_human_move(window_read_result=window_read_result)
            if window_read_result is None:
                continue
            if type(window_read_result) == chess.Move:
                # Apply the move logic
                continue

            if button == "Engine Move":
                self.play_move(self.zpos.best_engine_move(engine=engines["stockfish"], depth=20))
                continue

            if button == "Open .pgn":
                with open(self.file_picker(prompt=".pgn file:")[1]["Browse"], "r") as f:
                    self.game = chess.pgn.read_game(f)
                continue

            if button == "->":
                next_node = self.game_node.next()
                if next_node is not None:
                    self.game_node = next_node
                else:
                    logging.info("End of game")
                continue

            if button == "<-":
                if not isinstance(self.game_node, chess.pgn.ChildNode):
                    logging.warning("Can't get parent node of non-ChildNode game_node")
                    continue
                
                prev_node = self.game_node.parent
                if prev_node is not None:
                    self.game_node = prev_node
                continue


            # Mode: Neutral
            if button == 'Flip':
                window = self.create_new_window(window, True)
                continue


def main():
    theme = 'Reddit'

    import psutil
    engines = {
        "stockfish": chess.engine.SimpleEngine.popen_uci(r"E:\\chess\\stockfish_15_win_x64_popcnt\\stockfish_15_x64_popcnt.exe"),
        "leela": chess.engine.SimpleEngine.popen_uci(r"C:\\Users\\LZoe\\Desktop\\Leela\\lc0.exe")
    }
    threads: int = int(psutil.cpu_count(logical=True) - 3)  # almost all logical CPU cores
    hash: int = int(psutil.virtual_memory().available / 1024 / 1024 * 0.3)  # 75% of available RAM
    engines["stockfish"].configure({"Hash": hash})
    engines["stockfish"].configure({"Threads": threads})

    pecg = EasyChessGui(theme)

    pecg.main_loop(engines=engines)


if __name__ == "__main__":
    main()
