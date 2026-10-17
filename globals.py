import os

engine_rate_limit = False
explorer_limit = False
# Your lichess username - used to tag your own moves/games in the database and
# to fetch your games from the lichess API. Override by setting the CHESS_USERNAME
# environment variable.
username = os.environ.get("CHESS_USERNAME", "ZannahRain")
