import sqlite3
from utils.lichess_api import client as lichess_client
from io import StringIO
import chess.pgn
import datetime
import logging
from globals import username
from zPosition import zPosition

# Tables:

# Games:
# - white player
# - black player
# - timestamp
# - chess.pgn.Game object

# Positions:

logging.basicConfig(level=logging.INFO)


def fen_to_position(fen: str):
    """
    Strips out bits of the FEN that aren't usually relevant for analysis.
    
    - IE no full / halfmove count
    """
    return " ".join(fen.split(" ")[:-2])


class Database:
    """Wrapper for stuff I want to keep track of that's gotten too complicated to just save in loads of .json files."""
    def __init__(self, file="chess_database.db", rated_only: bool = True):
        self.con = sqlite3.connect(database=file)
        self.initialise_database_schema()

    def initialise_database_schema(self):
        # All games of interest which could be used to generate lessons / statistics
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

        # Position table.
        # Position refers to piece placement + who's turn + castling avaibs + en passant
        # Does NOT include halfmove or fullmove clocks as these generally aren't relevant for evaluation and practice
        self.con.execute("""CREATE TABLE IF NOT EXISTS positions (
            position TEXT NOT NULL,
            comment TEXT,
            PRIMARY KEY (position)
        )""")

        # Tracking attempts to combine multiple forms of evaluation into a best view
        self.con.execute("""CREATE TABLE IF NOT EXISTS combined_evaluations (
            position TEXT NOT NULL,
            eval REAL NOT NULL,
            best_move TEXT NOT NULL,
            difficulty REAL NOT NULL,
            timestamp TIMESTAMP NOT NULL DEFAULT NOW,
            PRIMARY KEY (position, timestamp)
        )""")

        # Tracking potentially multiple depth stockfish evaluations by position
        self.con.execute("""CREATE TABLE IF NOT EXISTS stockfish_evaluations (
            position TEXT NOT NULL,
            depth INTEGER NOT NULL,
            evaluation REAL NOT NULL,
            PRIMARY KEY (position, depth)
        )""")

        # Tracking potentially multiple depth leela evaluations by position
        self.con.execute("""CREATE TABLE IF NOT EXISTS leela_evaluations (
            position TEXT NOT NULL,
            nodes INTEGER NOT NULL,
            evaluation REAL NOT NULL,
            PRIMARY KEY (position, nodes)
        )""")

        # Tracking which positions have been seen when, and who was playing each side
        self.con.execute("""CREATE TABLE IF NOT EXISTS positions_seen_in_games (
            position TEXT NOT NULL,
            whose_turn INTEGER NOT NULL,
            white TEXT NOT NULL,
            black TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL
        )""")

        # One to many table tracking which moves have been played in each position
        # Either in an actual game (real_or_practice = "REAL") or not "PRACTICE"
        self.con.execute("""CREATE TABLE IF NOT EXISTS move_attempts (
            position TEXT NOT NULL,
            resulting_position TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            player TEXT NOT NULL,
            move TEXT NOT NULL,
            real_or_practice TEXT NOT NULL,
            time_control TEXT NOT NULL
        )""")

        # Tracking FEN level data
        # Mostly for a one to many table tracking which FEN's have led to any given position
        # FEN level stats can then be summarised up to position level
        self.con.execute("""CREATE TABLE IF NOT EXISTS fens (
            position TEXT NOT NULL,
            fen TEXT NOT NULL,
            times_seen INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (fen)
        )""")

        # For storing human statistics for positions
        # Subsetted by rating band / master vs amateur etc
        self.con.execute("""CREATE TABLE IF NOT EXISTS fen_stats (
            fen TEXT NOT NULL,
            source TEXT NOT NULL,
            band TEXT NOT NULL,
            white_wins INTEGER NOT NULL,
            draws INTEGER NOT NULL,
            black_wins INTEGER NOT NULL,
            query_timestamp TIMESTAMP NOT NULL DEFAULT NOW,
            PRIMARY KEY (fen, source, band)
        )""")

    @property
    def latest_game_timestamp(self):
        if self.latest_game_time is None:
            return None
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
            criteria.append(f"white = '{white}'")
        if black is not None:
            criteria.append(f"black = '{black}'")
        if event is not None:
            criteria.append(f"event = '{event}'")
        if link is not None:
            criteria.append(f"link = '{link}'")
        if timestamp is not None:
            criteria.append(f"timestamp = '{timestamp}'")
        if result is not None:
            criteria.append(f"result = '{result}'")
        if time_control is not None:
            criteria.append(f"time_control = '{time_control}'")
        if variant is not None:
            criteria.append(f"variant = '{variant}'")
        if len(criteria) > 0:
            query += " WHERE " + " AND ".join(criteria)

        return self.con.execute(query).fetchall()
    
    def log_played_position(self, board: chess.Board, white: str, black: str, timestamp: datetime.datetime):
        """Should be called ONCE for each observed position in a real game."""
        assert (white == username) or (black == username)

        position = fen_to_position(board.fen())

        self.con.execute(f"""INSERT INTO positions_seen_in_games (position, white, black, timestamp, whose_turn) VALUES(?,?,?,?,?)""",
                         (
                            position,
                            white,
                            black,
                            timestamp,
                            int(board.turn)
                         ))

    def log_human_move(self, board: chess.Board, timestamp: datetime.datetime, player: str, move: chess.Move, is_real: bool, time_control: str):
        """Should be called ONCE for each attempted human move for each position, real or practice game, user or opponent."""

        position = fen_to_position(board.fen())
        move_string = board.san(move)

        resulting_position = board.copy()
        resulting_position.push(move)
        resulting_position = fen_to_position(resulting_position.fen())

        self.con.execute("""INSERT INTO move_attempts (position, timestamp, player, move, resulting_position, real_or_practice, time_control) VALUES(?,?,?,?,?,?,?)""",
                          (
                            position,
                            timestamp,
                            player,
                            move_string,
                            resulting_position,
                            is_real,
                            time_control
                          ))
        
    def log_human_fen(self, board: chess.Board):
        """Should be called ONCE for each FEN seen in a real game."""

        fen = board.fen()

        if self.con.execute(f"SELECT EXISTS(SELECT 1 FROM fens WHERE fen='{fen}');").fetchone():
            self.con.execute(f"""UPDATE fens
                                 SET times_seen = times_seen + 1
                                 WHERE fen = '{fen}'""")
        else:
            self.con.execute(f"INSERT INTO fens (position, fen, times_seen) VALUES(?,?,?)",
                             (
                                fen_to_position(fen),
                                fen,
                                1
                             ))
    
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
        except sqlite3.IntegrityError:
            return False
        
        current_game_node = game
        next_game_node = game.next()
        while not current_game_node.is_end():
            if current_game_node.turn == chess.WHITE:
                this_player = game.headers["White"]
            else:
                this_player = game.headers["Black"]

            self.log_played_position(board=current_game_node.board(), white=game.headers["White"], black=game.headers["Black"], timestamp=timestamp)
            self.log_human_move(board=current_game_node.board(), timestamp=timestamp, player=this_player, move=next_game_node.move, is_real=True, time_control=game.headers["TimeControl"])
            self.log_human_fen(board=current_game_node.board())

            current_game_node = current_game_node.next()
            next_game_node = current_game_node.next()
        
        logging.info(f"Added game to db: {game.headers['White']} vs {game.headers['Black']} ({game.headers['UTCDate']})")

        return True
    
    def download_latest_games(self):
        new_pgns = lichess_client.games.export_by_player(username=username,
                                                         as_pgn=True,
                                                         since=self.latest_game_timestamp,
                                                         rated=True,
                                                         finished=True)
        
        games_added = 0
        for i in new_pgns:
            this_new_game = chess.pgn.read_game(StringIO(i))
            success = self.add_game(this_new_game)
            if success:
                games_added += 1
            else:
                break

        if games_added > 0:
            self.con.commit()
            logging.info(f"Added {games_added} games to the database.")
        else:
            logging.info(f"No new games found.")

        self.log_db_stats()

    def log_db_stats(self):
        def print_info(table):
            logging.info(f"{self.con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()} rows in {table}")
        
        for i in ["games", "positions", "combined_evaluations", "stockfish_evaluations", "leela_evaluations", "positions_seen_in_games", "move_attempts", "fens", "fen_stats"]:
            print_info(i)
