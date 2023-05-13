import sqlite3
from lichess_api import client as lichess_client
import chess.pgn

# Tables:

# Games:
# - white player
# - black player
# - timestamp
# - chess.pgn.Game object

# Positions:




class Database:
    """Wrapper for stuff I want to keep track of that's gotten too complicated to just save in loads of .json files."""
    def __init__(self, file="chess_database.db", rated_only: bool = True):
        self.con = sqlite3.connect(database=file, factory=sqlite3.Row)

    @property
    def latest_game_timestamp(self):
        return self.con.execute("SELECT MAX(TIMESTAMP) FROM GAMES")
    
    def add_game(self, game: chess.pgn.Game):
        """Adds a game to the game table."""
        self.con.execute(f"INSERT INTO GAMES (white,black,timestamp,game) VALUES({game.headers['White']})")
    
    def download_latest_games(self):
        new_pgns = lichess_client.games.export_by_player(username="ZannahRain",
                                                         as_pgn=True,
                                                         since=self.latest_game_timestamp,
                                                         rated=True,
                                                         finished=True)
        


        my_pgns = list(my_pgns)

        import os
        if not os.path.exists("my_pgns"):
            os.mkdir("my_pgns")
        for ind, i in enumerate(my_pgns):
            with open(f"my_pgns/{ind}.pgn", "w") as f:
                f.write(i)