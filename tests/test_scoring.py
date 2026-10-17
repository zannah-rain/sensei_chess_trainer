import chess
import pytest

from utils.scoring import puzzle_goal_eval, review_goal_eval


def test_puzzle_goal_eval_floors_to_within_one_percent_of_best_move_for_white():
    # Given a puzzle where the player's last two tries already matched the best
    # move's own evaluation
    goal = puzzle_goal_eval(whose_turn=chess.WHITE, latest_practice_eval=0.80,
                            latest_real_eval=0.80, puzzle_evaluation=0.80)

    # When computing the success threshold
    # Then the goal never demands closer than 1% of the best move's eval
    assert goal == pytest.approx(0.79)


def test_puzzle_goal_eval_floors_to_within_one_percent_of_best_move_for_black():
    # Given the same scenario mirrored for Black (lower eval = better for Black)
    goal = puzzle_goal_eval(whose_turn=chess.BLACK, latest_practice_eval=0.20,
                            latest_real_eval=0.20, puzzle_evaluation=0.20)

    # Then the goal never demands closer than 1% of the best move's eval, in the
    # opposite direction from White's case
    assert goal == pytest.approx(0.21)


def test_puzzle_goal_eval_caps_at_20_percent_loss_for_white():
    # Given a puzzle where the player's practice history is far worse than the best
    # move (so blending with history alone would demand far more improvement)
    goal = puzzle_goal_eval(whose_turn=chess.WHITE, latest_practice_eval=0.0,
                            latest_real_eval=0.0, puzzle_evaluation=0.90)

    # When computing the success threshold
    # Then the goal never demands more than a 20% loss against the best move
    assert goal == pytest.approx(0.70)


def test_puzzle_goal_eval_caps_at_20_percent_loss_for_black():
    # Given the same scenario mirrored for Black
    goal = puzzle_goal_eval(whose_turn=chess.BLACK, latest_practice_eval=1.0,
                            latest_real_eval=1.0, puzzle_evaluation=0.10)

    # Then the goal never demands more than a 20% loss against the best move
    assert goal == pytest.approx(0.30)


def test_puzzle_goal_eval_rewards_improving_on_the_better_of_the_last_two_tries():
    # Given a practice attempt that was better than the real-game attempt
    goal_using_better_practice = puzzle_goal_eval(whose_turn=chess.WHITE, latest_practice_eval=0.70,
                                                  latest_real_eval=0.50, puzzle_evaluation=0.90)
    # And the reverse: a real-game attempt that was better than the practice attempt
    goal_using_better_real = puzzle_goal_eval(whose_turn=chess.WHITE, latest_practice_eval=0.50,
                                              latest_real_eval=0.70, puzzle_evaluation=0.90)

    # When computing the success threshold in both cases
    # Then the better of the two historical attempts is what the blend is based on,
    # so both scenarios demand the same threshold
    assert goal_using_better_practice == pytest.approx(goal_using_better_real)


def test_review_goal_eval_uses_the_real_games_move_when_within_the_instability_band_for_white():
    # Given the real game's move landed strictly between the 1%-and-3%-worse-than-
    # current-eval band (where the goal is allowed to track it directly)
    goal = review_goal_eval(turn=chess.WHITE, current_eval=0.50, current_eval_2=0.50,
                            original_game_eval=0.485)

    # When computing the success threshold
    # Then the goal matches the real game's move exactly
    assert goal == pytest.approx(0.485)


def test_review_goal_eval_floors_at_3_percent_worse_than_current_eval_for_white():
    # Given the real game's own move was bad (evaluated far worse than White's
    # current position)
    goal = review_goal_eval(turn=chess.WHITE, current_eval=0.50, current_eval_2=0.50,
                            original_game_eval=0.0)

    # When computing the success threshold
    # Then the goal never drops more than 3% below the current position's eval,
    # regardless of how bad the real game's move was
    assert goal == pytest.approx(0.47)


def test_review_goal_eval_damps_instability_by_taking_the_worse_of_two_current_evals_for_white():
    # Given two noisy readings of "how good is the current position for White" that
    # disagree (engine evaluations get unstable in sharp positions)
    goal_high_first = review_goal_eval(turn=chess.WHITE, current_eval=0.90, current_eval_2=0.40)
    goal_low_first = review_goal_eval(turn=chess.WHITE, current_eval=0.40, current_eval_2=0.90)

    # When there's no real-game move to compare against (falls back to current eval alone)
    # Then the goal is based on the worse (lower) of the two readings in both orderings,
    # not whichever one happened to come first
    assert goal_high_first == pytest.approx(goal_low_first)
    assert goal_high_first == pytest.approx(0.40 - 0.04)


def test_review_goal_eval_damps_instability_by_taking_the_worse_of_two_current_evals_for_black():
    # Given two noisy readings of "how good is the current position for Black" (lower
    # eval = better for Black, so "worse" here means the higher reading)
    goal = review_goal_eval(turn=chess.BLACK, current_eval=0.40, current_eval_2=0.90)

    # Then the goal is based on the worse (higher) of the two readings
    assert goal == pytest.approx(0.90 + 0.04)
