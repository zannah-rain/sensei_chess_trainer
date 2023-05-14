

class Puzzle:
    """Very basic container for puzzle related stuff to help me remember what's in it."""
    def __init__(self, x):
        self.position = x["position"]
        """The starting position for the puzzle."""
        self.evaluation = x["initial_eval"]
        """The evaluation of the puzzle starting position."""
        self.whose_turn = x["whose_turn"]
        """chess.WHITE or chess.BLACK"""
        self.frequency = x["frequency"]
        """How many times this position has been seen in a real game."""
        self.days_since_last_seen = x["days_since_last_seen"]
        """How many days (decimal) since this position has been seen in a real game."""
        self.priority = x["priority"]
        """The priority of studying this puzzle."""

        # Info about previous attempts
        self.latest_resulting_position = x["resulting_position"]
        """The resulting position from the latest attempt."""
        self.latest_timestamp = x["timestamp"]
        """When the latest attempt took place."""
        self.latest_player = x["player"]
        """The player who made the latest attempt."""
        self.latest_attempt_move = x["move"]
        """The move made on the latest attempt."""
        self.latest_attempt_real_or_practice = x["real_or_practice"]
        """Whether the latest attempt was in a real game (1) or practice session (0)."""
        self.latest_time_control = x["time_control"]
        """The time control the latest attempt was made in."""
        self.latest_resulting_evaluation = x["resulting_eval"]
        """The evaluation of the latest attempt."""
        self.latest_evaluation_loss = x["evaluation_loss"]
        """The evaluation loss of the latest attempt."""
        