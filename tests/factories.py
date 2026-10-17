"""
DAMP-style test data builders: sensible defaults, override only what a given test
cares about. Keeps test bodies free of irrelevant setup detail (Software
Engineering at Google, ch. 12).
"""

import chess

from utils.puzzle import Puzzle


def new_puzzle(**overrides) -> Puzzle:
    defaults = {
        "position": chess.STARTING_FEN,
        "initial_eval": 0.5,
        "whose_turn": chess.WHITE,
        "priority": 1.0,
        "times_seen_in_real_games": 1,
        "days_since_last_seen": 0.0,
        "latest_real_resulting_position": None,
        "last_seen_in_real_game": None,
        "latest_real_played_move": None,
        "latest_real_time_control": None,
        "latest_real_eval": 0.5,
        "latest_real_eval_loss": 0.0,
        "latest_practice_eval": 0.5,
        "latest_practice_eval_loss": 0.0,
        "days_since_last_practiced": 0.0,
        "last_practiced_timestamp": None,
        "latest_practice_time_taken_seconds": 30.0,
    }
    defaults.update(overrides)
    return Puzzle(defaults)
