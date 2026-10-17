from typing import Tuple, List
import copy
import random
import chess

from utils.square import Square
import gui.square

from utils.constants import *
from gui.popups import PromotionPickerDialog

from PySide6.QtWidgets import QPushButton, QDialog, QGridLayout, QGraphicsRectItem, QVBoxLayout, QFrame, QSizePolicy
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Signal, Slot, QTimer


class SquareGridFrame(QFrame):
    """
    A QFrame that keeps a centered, square-shaped region for its grid layout.

    Without this, resizing the frame to a non-square shape (e.g. a wide, short
    window) would stretch each cell of an 8x8 grid into a non-square rectangle.
    Instead, this pads whichever dimension is larger with margins so the grid
    itself always renders as a square, centered within the frame.
    """

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        layout = self.layout()
        if layout is None:
            return
        side = min(self.width(), self.height())
        horizontal_margin = max(0, (self.width() - side) // 2)
        vertical_margin = max(0, (self.height() - side) // 2)
        layout.setContentsMargins(horizontal_margin, vertical_margin, horizontal_margin, vertical_margin)


class Board(QDialog):
    """
    Class representing the GUI board.
    
    Doesn't handle any changes to its own state (e.g. perspective, mirrored, etc.), only displays the board and emits events.
    """

    move_signal = Signal(chess.Move)
    mirror_changed = Signal()  # fires whenever `mirrored` actually changes, e.g. so a
                                # listener can refresh anything (turn label, eval
                                # display) that depends on it without re-running an
                                # expensive background evaluation for the same position

    def __init__(self, board: chess.Board = chess.Board(), parent=None) -> None:
        super(Board, self).__init__(parent)
        self.setWindowTitle("Simple Board")

        self._mirrored = False
        self.perspective = chess.WHITE
        self._board: chess.Board = board

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.sub_layout = QVBoxLayout(self)

        self.board_frame = SquareGridFrame(self)
        self.board_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.sub_layout.addWidget(self.board_frame, 1)  # stretch=1: board grows first, label/buttons stay their natural size
        self.board_frame.setFrameStyle(QFrame.Panel | QFrame.Raised)

        self.board_layout = QGridLayout()
        self.board_layout.setSpacing(0)
        for i in range(8):
            self.board_layout.setRowStretch(i, 1)
            self.board_layout.setColumnStretch(i, 1)
        self.board_frame.setLayout(self.board_layout)

        self.board_buttons = self.create_board_buttons()
        self.update_board_pieces_and_colours()

        self.extra_buttons_bar = QGridLayout()
        self.sub_layout.addLayout(self.extra_buttons_bar)

        # Add a button to flip the board
        self.flip_button = QPushButton("Flip")
        self.flip_button.clicked.connect(self.flip)
        self.extra_buttons_bar.addWidget(self.flip_button, 0, 0)

        # Add a button to mirror the board
        self.mirror_button = QPushButton("Mirror")
        self.mirror_button.clicked.connect(self.mirror)
        self.extra_buttons_bar.addWidget(self.mirror_button, 0, 1)

        self.current_selected_square: Square = None

        self._pending_flash_timer = None
        self._pending_move = None

    def start_pending_highlight(self, move: chess.Move) -> None:
        """Flashes the move's squares to show its evaluation is in progress."""
        self._pending_move = move
        if self._pending_flash_timer is None:
            self._pending_flash_timer = QTimer(self)
            self._pending_flash_timer.timeout.connect(self._toggle_pending_flash)
        self._pending_flash_on = False
        self._toggle_pending_flash()  # show immediately, don't wait for the first interval
        self._pending_flash_timer.start(350)

    def _toggle_pending_flash(self) -> None:
        self._pending_flash_on = not self._pending_flash_on
        strength = 0.65 if self._pending_flash_on else 0.2
        self.highlight_moves(((self._pending_move, pending),), highlight_strength=strength)

    def stop_pending_highlight(self) -> None:
        """Stops the flash. Does not restore any other highlight - the caller is
        expected to apply whatever highlight (success/fail/last-move) comes next."""
        if self._pending_flash_timer is not None:
            self._pending_flash_timer.stop()
        self._pending_move = None

    def create_board_buttons(self) -> List[List[QGraphicsRectItem]]:
        """
        Creates the board buttons.
        
        In the resulting list of lists:
        - The first index is the file (x) (0-7)
        - The second index is the rank (y) (0-7)

        If the board is not mirrored or flipped:
        0, 0 is a1
        7, 7 is h8
        0, 1 is a2

        Within the board_layout, y is 7 - rank because the grid layout displays top to bottom.
        """
        board = list()
        for x in range(8):
            x_buttons = list()
            board.append(x_buttons)
            for y in range(8):
                elem = self.create_square_button(x=x, y=y)
                elem.square_clicked.connect(self.button_clicked)
                
                x_buttons.append(elem)
                self.board_layout.addWidget(elem, 7 - y, x) # 7 - y because grid layout displays top to bottom
        return board
    
    @Slot()
    def button_clicked(self, x: int, y: int) -> None:
        """Handles the button click event."""

        square = self.xy_to_square(x, y)
        print(f"Translates to square {square}.")

        if self.current_selected_square is None:
            self.current_selected_square = square
            self.board_buttons[x][y].select()
        else:
            from_square = self.current_selected_square

            old_board_x, old_board_y = self.square_to_xy(from_square)
            self.board_buttons[old_board_x][old_board_y].deselect()

            self.current_selected_square = None

            moved_piece = self.board.piece_type_at(from_square.internal_square)
            reaches_back_rank = chess.square_rank(square.internal_square) in (0, 7)

            if moved_piece == chess.PAWN and reaches_back_rank:
                promotion_piece = PromotionPickerDialog.get_promotion_piece(stm=self.board.turn, parent=self)
                move = chess.Move(from_square.internal_square, square.internal_square, promotion=promotion_piece)
            else:
                move = from_square.move_to(square)

            if move in self.board.legal_moves:
                self.move_signal.emit(move)
                print(f"Move {move} emitted.")
    
    def square_color(self, square: Square) -> Tuple[int, int, int]:
        """Returns the colour of the square."""
        if (square.rank_id + square.file_id) % 2 == 0:
            return dark_gray
        else:
            return light_gray
    
    @property
    def board(self) -> chess.Board:
        return self._board
    
    @board.setter
    def board(self, value: chess.Board) -> None:
        self._board = value
        self.update_board_pieces_and_colours()

        # Highlight most recent move
        self.clear_highlights()
        if self.board.move_stack:
            move = self.board.peek()
            self.highlight_moves(move_colour_tuple=[(move, yellow)], highlight_strength=0.5)

    def create_square_button(self, x: int, y: int) -> QGraphicsRectItem:
        """ Returns a QGraphicRectItem representing a square on the board. """
        button = gui.square.Square(x=x, y=y, parent=self)
        return button
    
    def highlight_squares(self, square_colour_tuple: Tuple[Tuple[Square, tuple]], highlight_strength: float = 0.5) -> None:
        """
        Change the color of a square based on row & col. Adds the given colour to the base colour of that square.
        """
        for square, colour in square_colour_tuple:
            if isinstance(square, int):
                square = Square(square)
            x, y = self.square_to_xy(square)
            self.board_buttons[x][y].highlight = (*colour, highlight_strength)

    def clear_highlights(self) -> None:
        """Resets all squares back to their unhighlighted base colour."""
        for x in range(8):
            for y in range(8):
                self.board_buttons[x][y].highlight = (0, 0, 0, 0)

    def highlight_moves(self, move_colour_tuple: tuple, highlight_strength: float = 0.5) -> None:
        """
        Change the color of squares relevant to the given moves. Adds the given colour to the base colour of that square.
        """
        square_colour_tuple = tuple([(move.from_square, colour) for move, colour in move_colour_tuple]) + tuple([(move.to_square, colour) for move, colour in move_colour_tuple])
        self.highlight_squares(square_colour_tuple=square_colour_tuple, highlight_strength=highlight_strength)

    def flip(self) -> None:
        """Flips the perspective (NOT THE COLOURS!)"""
        self.perspective = not self.perspective
        self.update_board_pieces_and_colours()

    def mirror(self) -> None:
        """Mirrors the board."""
        self.mirrored = not self.mirrored

    def randomise_perspective_and_mirroring(self) -> None:
        self.perspective = random.choice([chess.WHITE, chess.BLACK])
        self.mirrored = random.choice([True, False])

    @property
    def mirrored(self) -> bool:
        """Whether the colours have been swapped in displays without changing them in the back end stuff."""
        return self._mirrored

    @mirrored.setter
    def mirrored(self, value) -> None:
        if value != self.mirrored:
            self._mirrored = value
            self.update_board_pieces_and_colours()
            self.mirror_changed.emit()

    def translate_coordinates(self, rank: int, file: int) -> Tuple[int, int]:
        """
        Translates the coordinates based on the perspective and mirroring.
        
        Can't be handled by the Square class as it doesn't know about the board's perspective or mirroring.

        Is always its own inverse.
        """
        rank = rank
        file = file
        if self.mirrored:
            file = 7 - file
        if self.perspective == chess.BLACK:
            rank = 7 - rank
            file = 7 - file
        return rank, file

    def xy_to_square(self, x: int, y: int) -> Square:
        """Converts a set of x & y coordinates (which don't account for flipping / mirroring) to a real square (eg e4)."""
        rank_id, file_id = self.translate_coordinates(rank=y, file=x)
        return Square(rank_id=rank_id, file_id=file_id)
    
    def square_to_xy(self, square: Square) -> Tuple[int, int]:
        """Converts a square to a button x & y coordinates, accounting for current flipping & mirroring."""
        y, x = self.translate_coordinates(square.rank_id, square.file_id)
        return x, y

    def update_board_pieces_and_colours(self) -> None:
        """Updates the board pieces."""

        for real_rank in range(8):
            for real_file in range(8):
                real_square = Square(rank_id=real_rank, file_id=real_file)
                board_x, board_y = self.square_to_xy(real_square)

                piece_image = QPixmap(images[self.psg_board()[real_rank][real_file]])
                self.board_buttons[board_x][board_y].setIcon(piece_image)

                color = self.square_color(real_square)
                self.board_buttons[board_x][board_y].color = color
    
    def psg_board(self) -> List[List[int]]:
        """ 
        Extract piece positions as a list of lists of ints corresponding to the piece images. 
        
        0, 0 is a1
        7, 7 is h8

        The first index is the rank, the second is the file!
        """
        psgboard = []

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
                pc = self.board.piece_at(s^56)
            except Exception:
                pc = None
                print('Failed to get piece.')

            if pc is not None:
                pt = pc.piece_type
                # Mirroring is meant to swap which colour each piece is *displayed*
                # as (so a puzzle doesn't always visually look like "a White
                # puzzle"), without changing the real side to move - MainWindow's
                # mirror_aware_turn and its eval-flipping already assume this swap
                # happens; it has to happen here for them to be showing the truth.
                displayed_color = (not pc.color) if self.mirrored else pc.color
                c = displayed_color % 2
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

        return list(reversed(psgboard))
    

if __name__ == '__main__':
    import sys
    from PySide6.QtWidgets import QApplication

    # Create the Qt Application
    app = QApplication(sys.argv)
    # Create and show the form
    form = Board()
    form.show()
    # Run the main Qt loop
    sys.exit(app.exec())