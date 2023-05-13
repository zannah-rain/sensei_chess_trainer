import sqlite3
from utils.lichess_api import client as lichess_client
from io import StringIO
import chess.pgn
import datetime
import logging

# Tables:

# Games:
# - white player
# - black player
# - timestamp
# - chess.pgn.Game object

# Positions:

logging.basicConfig(level=logging.INFO)


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
        return int(datetime.datetime.strptime(self.latest_game_time, "%Y.%m.%d %H:%M:%S").timestamp() * 1000)
    
    @property
    def latest_game_time(self):
        return self.con.execute("SELECT MAX(timestamp) FROM games").fetchone()[0]
    
    def game_search(self,
                    white: str = None,
                    black: str = None,
                    event: str = None,
                    link: str = None,
                    timestamp: str = None,
                    result: str = None,
                    time_control: str = None,
                    variant: str = None):
        """Return a list of games which meet those criteria."""

        query = "SELECT * FROM games"


        criteria = list()
        if white is not None:
            criteria.append(f"white = {white}")
        if black is not None:
            criteria.append(f"black = {white}")
        if event is not None:
            criteria.append(f"event = {event}")
        if link is not None:
            criteria.append(f"link = {link}")
        if timestamp is not None:
            criteria.append(f"timestamp = {timestamp}")
        if result is not None:
            criteria.append(f"result = {result}")
        if time_control is not None:
            criteria.append(f"time_control = {time_control}")
        if variant is not None:
            criteria.append(f"variant = {variant}")
        if len(criteria) > 0:
            query += " WHERE " + " AND ".join(criteria)

        return self.con.execute(query).fetchall()
    
    def add_game(self, game: chess.pgn.Game):
        """
        Adds a game to the game table.
        Note: Does not commit to allow for faster batching.
        """
        timestamp = f"{game.headers['UTCDate']} {game.headers['UTCTime']}"

        try:
            self.con.execute("INSERT INTO games (white,black,event,link,timestamp,result,time_control,variant,pgn) VALUES(?,?,?,?,?,?,?,?,?)",
                            (game.headers["White"],
                            game.headers["Black"],
                            game.headers["Event"],
                            game.headers["Site"],
                            timestamp,
                            game.headers["Result"],
                            game.headers["TimeControl"],
                            game.headers["Variant"],
                            game.__str__()))
            return True
        except sqlite3.IntegrityError:
            return False
    
    def download_latest_games(self):
        new_pgns = lichess_client.games.export_by_player(username="ZannahRain",
                                                         as_pgn=True,
                                                         since=self.latest_game_timestamp,
                                                         rated=True,
                                                         finished=True)
        
        new_games = [chess.pgn.read_game(StringIO(i)) for i in new_pgns]

        games_added = 0
        for i in new_games:
            success = self.add_game(i)
            if success:
                games_added += 1
            else:
                break

        if games_added > 0:
            self.con.commit()
            logging.info(f"Added {len(new_games)} to the database.")
        else:
            logging.info(f"No new games found.")
