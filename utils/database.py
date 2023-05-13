import sqlite3
from utils.lichess_api import client as lichess_client
from io import StringIO
import chess.pgn
import datetime

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
        self.con = sqlite3.connect(database=file)
        self.initialise_database_schema()

    def initialise_database_schema(self):
        self.con.execute("""CREATE TABLE IF NOT EXISTS games (
            white TEXT NOT NULL, 
            black TEXT NOT NULL, 
            event TEXT,
            link TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            result TEXT NOT NULL,
            time_control TEXT NOT NULL,
            variant TEXT NOT NULL, 
            pgn TEXT NOT NULL,
            PRIMARY KEY (white, black, timestamp)
            )""")
        
        self.con.execute("""CREATE TABLE IF NOT EXISTS games_processed (
            white TEXT NOT NULL,
            black TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            processed INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (white, black, timestamp)
        )""")

    @property
    def latest_game_timestamp(self):
        return self.con.execute("SELECT MAX(timestamp) FROM games").fetchone()[0]
    
    def add_game(self, game: chess.pgn.Game):
        """
        Adds a game to the game table.
        Note: Does not commit to allow for faster batching.
        """
        timestamp = f"{game.headers['UTCDate']} {game.headers['UTCTime']}"
        self.con.execute(f"""INSERT INTO games (id,white,black,event,link,timestamp,result,time_control,variant,pgn) 
                             VALUES(
                                {game.headers['White']},
                                {game.headers['Black']},
                                {game.headers['Event']},
                                {game.headers['Site']},
                                {timestamp},
                                {game.headers['Result']},
                                {game.headers['Variant']},
                                {game.__str__()})""")
    
    def download_latest_games(self):
        new_pgns = lichess_client.games.export_by_player(username="ZannahRain",
                                                         as_pgn=True,
                                                         since=self.latest_game_timestamp,
                                                         rated=True,
                                                         finished=True)
        
        new_games = [chess.pgn.read_game(StringIO(i)) for i in new_pgns]

        for i in new_games:
            self.add_game(i)
        self.con.commit()
