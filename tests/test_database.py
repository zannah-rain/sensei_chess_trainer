import datetime

import chess
import pytest

from utils.database import Database

POSITION = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"


def new_database(tmp_path) -> Database:
    return Database(file=str(tmp_path / "test.db"))


def test_position_name_round_trips_through_set_and_get(tmp_path):
    # Given a fresh database with no name set for a position
    database = new_database(tmp_path)

    # When naming that position
    database.set_position_name(position=POSITION, name="Open Sicilian")

    # Then reading it back returns the name just set
    assert database.get_position_name(position=POSITION) == "Open Sicilian"


def test_position_with_no_name_returns_none(tmp_path):
    # Given a fresh database where this position has never been named
    database = new_database(tmp_path)

    # When reading its name
    # Then there's nothing to return
    assert database.get_position_name(position=POSITION) is None


def test_position_comment_round_trips_through_set_and_get(tmp_path):
    # Given a fresh database with no comment set for a position
    database = new_database(tmp_path)

    # When commenting on that position
    database.set_position_comment(position=POSITION, comment="Watch out for ...Qh4")

    # Then reading it back returns the comment just set
    assert database.get_position_comment(position=POSITION) == "Watch out for ...Qh4"


def test_setting_one_field_does_not_clobber_another_already_set_on_the_same_position(tmp_path):
    # Given a position that already has a name
    database = new_database(tmp_path)
    database.set_position_name(position=POSITION, name="Open Sicilian")

    # When separately setting a comment on the same position
    database.set_position_comment(position=POSITION, comment="Watch out for ...Qh4")

    # Then the name set earlier is still there
    assert database.get_position_name(position=POSITION) == "Open Sicilian"


def test_position_manual_evaluation_round_trips_through_set_and_get(tmp_path):
    # Given a fresh database with no manual evaluation set for a position
    database = new_database(tmp_path)

    # When manually evaluating that position
    database.set_position_manual_evaluation(position=POSITION, manual_evaluation=0.65)

    # Then reading it back returns the evaluation just set
    assert database.get_position_manual_evaluation(position=POSITION) == pytest.approx(0.65)


def test_position_never_played_in_a_real_game_has_no_last_played_date(tmp_path):
    # Given a fresh database where this position has never appeared in a real game
    database = new_database(tmp_path)

    # When asking when it was last played
    # Then there's nothing to return
    assert database.position_last_played(position=POSITION) is None


def test_logging_a_played_position_makes_it_appear_as_last_played_at_that_time(tmp_path):
    # Given a fresh database and a position observed in a real game at a known time
    database = new_database(tmp_path)
    board = chess.Board(fen=f"{POSITION} 0 1")
    timestamp = datetime.datetime(2026, 1, 15, 12, 30, 0)

    # When logging that the position was played
    database.log_played_position(board=board, white="Alice", black="Bob", timestamp=timestamp)

    # Then it now shows up as last played at that timestamp
    assert database.position_last_played(position=POSITION) == "2026-01-15 12:30:00"
