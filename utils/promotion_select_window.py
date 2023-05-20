import copy
from utils.constants import *
import PySimpleGUI as sg
import logging
import sys

platform = sys.platform

white_init_promote_board = [[QUEENW, ROOKW, BISHOPW, KNIGHTW]]

black_init_promote_board = [[QUEENB, ROOKB, BISHOPB, KNIGHTB]]

sq_light_color = '#F0D9B5'
sq_dark_color = '#B58863'

def render_square(image, key, location):
        """ Returns an RButton (Read Button) with image image """
        if (location[0] + location[1]) % 2:
            color = sq_dark_color  # Dark square
        else:
            color = sq_light_color
        return sg.RButton('', image_filename=image, size=(1, 1),
                          border_width=0, button_color=('white', color),
                          pad=(0, 0), key=key)

def select_promotion_piece(stm):
    """
    Allow user to select a piece type to promote to.

    :param stm: side to move
    :return: promoted piece, i.e QUEENW, QUEENB ...
    """
    piece = None
    board_layout, row = [], []

    psg_promote_board = copy.deepcopy(white_init_promote_board) if stm \
            else copy.deepcopy(black_init_promote_board)

    # Loop through board and create buttons with images        
    for i in range(1):
        for j in range(4):
            piece_image = images[psg_promote_board[i][j]]
            row.append(render_square(piece_image, key=(i, j),
                                            location=(i, j)))

        board_layout.append(row)

    promo_window = sg.Window('Promotion Select',
                                board_layout,
                                default_button_element_size=(12, 1),
                                auto_size_buttons=False,
                                icon=ico_path[platform]['pecg'])

    while True:
        button, value = promo_window.Read(timeout=0)
        if button is None:
            break
        if type(button) is tuple:
            move_from = button
            fr_row, fr_col = move_from
            piece = psg_promote_board[fr_row][fr_col]
            logging.info('promote piece: {}'.format(piece))
            break

    promo_window.Close()

    return piece
