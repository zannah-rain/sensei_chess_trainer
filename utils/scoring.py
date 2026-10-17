"""
Pure arithmetic for judging puzzle and game-review attempts.

Pulled out of gui.main_window's puzzle/review move handlers specifically so this
math is testable without Qt, a database, or a running chess engine.
"""

import chess


def puzzle_goal_eval(whose_turn: bool, latest_practice_eval: float, latest_real_eval: float,
                     puzzle_evaluation: float) -> float:
    """
    The evaluation a puzzle attempt must reach to count as a success, when the move
    played isn't the engine's own top move.

    Blends the best of the player's last two tries with the puzzle's best-move
    evaluation (so improving on your own history counts, not just matching the
    engine), capped so a move at most ~20% worse than the best move can succeed,
    and floored so anything within ~1% of the best move always succeeds (engine
    evaluations at puzzle-solving speed aren't precise enough to demand closer).
    """
    if whose_turn == chess.WHITE:
        goal_eval = max(latest_practice_eval, latest_real_eval) * 0.9 + puzzle_evaluation * 0.1
        goal_eval = max(goal_eval, puzzle_evaluation - 0.2)
        goal_eval = min(goal_eval, puzzle_evaluation - 0.01)
    else:
        goal_eval = min(latest_practice_eval, latest_real_eval) * 0.9 + puzzle_evaluation * 0.1
        goal_eval = min(goal_eval, puzzle_evaluation + 0.2)
        goal_eval = max(goal_eval, puzzle_evaluation + 0.01)
    return goal_eval


def review_goal_eval(turn: bool, current_eval: float, current_eval_2: float,
                     original_game_eval: float = None) -> float:
    """
    The evaluation a game-review attempt must reach to count as a success, when the
    move played isn't the engine's own top move.

    current_eval and current_eval_2 are two evaluations of "how good is the current
    position" (the position itself, and the position after the engine's own
    reply) - engine evaluations get unstable in sharp positions, so taking the
    worse of the two for the side to move damps that noise.

    original_game_eval, when given, is the evaluation of the move actually played
    in the real game - review mode wants an attempt to be at least as good as that
    (within a small margin), not just "good enough on paper".
    """
    if original_game_eval is not None:
        if turn == chess.WHITE:
            best_current = min(current_eval, current_eval_2)
            goal_eval = max(original_game_eval, best_current - 0.03)
            goal_eval = min(goal_eval, best_current - 0.01)
        else:
            best_current = max(current_eval, current_eval_2)
            goal_eval = min(original_game_eval, best_current + 0.03)
            goal_eval = max(goal_eval, best_current + 0.01)
    else:
        if turn == chess.WHITE:
            best_current = min(current_eval, current_eval_2)
            goal_eval = best_current - 0.04
        else:
            best_current = max(current_eval, current_eval_2)
            goal_eval = best_current + 0.04
    return goal_eval
