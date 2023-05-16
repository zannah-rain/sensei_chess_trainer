

class Puzzle:
    """Very basic container for puzzle related stuff to help me remember what's in it."""
    def __init__(self, x):
        # General position info
        self.position = x["position"]
        """The starting position for the puzzle."""
        self.evaluation = x["initial_eval"]
        """The evaluation of the puzzle starting position."""
        self.whose_turn = x["whose_turn"]
        """chess.WHITE or chess.BLACK"""
        self.priority = x["priority"]
        """The priority of studying this puzzle."""

        # Info about when it's been seen in real games
        self.frequency = x["frequency"]
        """How many times this position has been seen in a real game."""
        self.days_since_last_seen = x["days_since_last_seen"]
        """How many days (decimal) since this position has been seen in a real game."""
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
        self.latest_real_eval = x["latest_real_eval"]
        """The evaluation of the latest attempt in a real game."""
        self.latest_real_eval_loss = x["latest_real_eval_loss"]
        """The evaluation loss of the latest attempt in a real game."""

        # Info about practice attempts
        self.latest_practice_eval = x["latest_practice_eval"]
        """The evaluation of the latest practice attempt."""
        self.latest_practice_eval_loss = x["latest_practice_eval_loss"]
        """The evaluation loss of the latest practice attempt."""
        self.days_since_last_practiced = x["days_since_last_practiced"]
        """The days (decimal) since the position has been practiced last."""
        