import sqlite3
from utils.lichess_api import client as lichess_client
from utils.puzzle import Puzzle
from utils.position import *
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


def stockfish_evaluation(board: chess.Board, engine: chess.engine.SimpleEngine, depth=10, multipv=1):

        # Check the game isn't over already cos engines bug out if so
        if board.outcome() is not None:
            if board.outcome().winner is None:
                return 0.5  # Draw
            return board.outcome().winner  # 1 for white and 0 for black

        engine_eval = engine.analyse(board, chess.engine.Limit(depth=depth), multipv=multipv)
        engine_eval[0]["score"] = engine_eval[0]["score"].white().wdl().expectation()  # Converting to json friendly format
        if "pv" in engine_eval[0].keys():
            # engine_eval[0]["pv"] = [i.uci() for i in engine_eval[0]["pv"]]  # Converting to json friendly format
            engine_eval[0]["pv"][0] = board.san(engine_eval[0]["pv"][0])
        if "currmove" in engine_eval[0].keys():
            engine_eval[0]["currmove"] = engine_eval[0]["currmove"].uci()

        return (engine_eval[0]["score"], engine_eval[0]["pv"][0])


class Database:
    """Wrapper for stuff I want to keep track of that's gotten too complicated to just save in loads of .json files."""
    def __init__(self, file="chess_database.db", rated_only: bool = True):
        self.con = sqlite3.connect(database=file)
        self.con.row_factory = sqlite3.Row
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
            length INTEGER NOT NULL,  -- halfmoves
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
            best_move TEXT NOT NULL,
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
        self.con.execute(f"""CREATE TABLE IF NOT EXISTS positions_seen_in_games (
            position TEXT NOT NULL,
            whose_turn INTEGER NOT NULL,
            white TEXT NOT NULL,
            black TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            player_turn TEXT GENERATED ALWAYS AS (CASE whose_turn WHEN TRUE THEN white WHEN FALSE THEN black END) STORED,
            is_users_turn INTEGER GENERATED ALWAYS AS (player_turn == '{username}') STORED
        )""")

        self.con.execute("""CREATE INDEX IF NOT EXISTS ipositions_turn on positions_seen_in_games(position, is_users_turn)""")

        self.con.execute(f"""CREATE TEMP VIEW summarised_positions AS
                             SELECT
                                position,
                                whose_turn,
                                is_users_turn,
                                COUNT(*) AS frequency
                             FROM positions_seen_in_games
                             GROUP BY position, is_users_turn""")
        
        self.con.execute(f"""CREATE TEMP VIEW latest_time_position_seen_in_game AS 
                             SELECT
                                position,
                                whose_turn,
                                MAX(timestamp) as timestamp
                             FROM positions_seen_in_games
                             WHERE is_users_turn = 1
                             GROUP BY position""")

        # One to many table tracking which moves have been played in each position
        # Either in an actual game (real_or_practice = "REAL") or not "PRACTICE"
        # NB that for speed, if the same position is seen more than once in one game the latest move will be recorded once
        # This also avoids it being overweighted where it probably shouldn't be
        self.con.execute("""CREATE TABLE IF NOT EXISTS move_attempts (
            position TEXT NOT NULL,
            resulting_position TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            player TEXT NOT NULL,
            move TEXT NOT NULL,
            real_or_practice TEXT NOT NULL,
            time_control TEXT,
            PRIMARY KEY (position, timestamp, player)
        )""")

        self.con.execute(f"""CREATE TEMP VIEW latest_move_attempts AS
                             SELECT base.*
                             FROM move_attempts base
                             INNER JOIN (
                                 SELECT position, 
                                        MAX(timestamp) as timestamp
                                 FROM move_attempts
                                 WHERE player = '{username}'
                                 GROUP BY position) latest
                             ON base.position = latest.position
                             AND base.timestamp = latest.timestamp
                             WHERE base.player = '{username}'""")

        self.con.execute(f"""CREATE TEMP VIEW move_attempt_analysis_stage_0 AS 
                             SELECT 
                                 latest_move_attempts.*,
                                 positions.whose_turn AS whose_turn,
                                 initial_evals.evaluation AS initial_eval,
                                 resulting_evals.evaluation AS resulting_eval,
                                 CASE positions.whose_turn
                                    WHEN TRUE THEN initial_evals.evaluation - resulting_evals.evaluation  -- WHITE
                                    WHEN FALSE THEN resulting_evals.evaluation - initial_evals.evaluation  -- BLACK
                                 END evaluation_loss,
                                 positions.frequency as frequency,
                                 last_seen.timestamp as last_seen_in_real_game,
                                 JULIANDAY("NOW") - JULIANDAY(last_seen.timestamp) as days_since_last_seen
                             FROM latest_move_attempts
                             INNER JOIN stockfish_evaluations initial_evals ON latest_move_attempts.position = initial_evals.position
                             INNER JOIN stockfish_evaluations resulting_evals ON latest_move_attempts.resulting_position = resulting_evals.position
                             INNER JOIN summarised_positions positions ON latest_move_attempts.position = positions.position
                             INNER JOIN latest_time_position_seen_in_game last_seen ON latest_move_attempts.position = last_seen.position
                             WHERE positions.is_users_turn = 1
                             """)
        
        self.con.execute(f"""CREATE TEMP VIEW move_attempt_analysis AS
                             SELECT
                                *,
                                evaluation_loss * frequency / days_since_last_seen AS priority
                             FROM move_attempt_analysis_stage_0
                             ORDER BY priority DESC""")

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

    def position_last_played(self, position: str):
        result = self.con.execute(f"SELECT timestamp FROM latest_time_position_seen_in_game WHERE position = '{position}'").fetchone()
        if result is not None:
            return dict(result)["timestamp"]
        else:
            return None
    
    def highest_priority_puzzle(self) -> Puzzle:
        return Puzzle(x=dict(self.con.execute("SELECT * FROM move_attempt_analysis LIMIT 1").fetchone()))

    def all_positions(self):

        position_saved_places = {
            "positions": ["position"],
            "combined_evaluations": ["position"],
            "stockfish_evaluations": ["position"],
            "leela_evaluations": ["position"],
            "positions_seen_in_games": ["position"],
            "move_attempts": ["position", "resulting_position"],
            "fens": ["position"]
        }

        x = set()
        for table, columns in position_saved_places.items():
            for column in columns:
                new = [i[0] for i in self.con.execute(f"SELECT {column} FROM {table}").fetchall()]
                x |= set(new)
        
        return x

    @property
    def latest_game_timestamp(self):
        if self.latest_game_time is None:
            return None
        return int(datetime.datetime.strptime(self.latest_game_time, "%Y-%m-%d %H:%M:%S").timestamp() * 1000)
    
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
        assert isinstance(timestamp, datetime.datetime)

        position = fen_to_position(board.fen())

        self.con.execute(f"""INSERT INTO positions_seen_in_games (position, white, black, timestamp, whose_turn) VALUES(?,?,?,?,?)""",
                         (
                            position,
                            white,
                            black,
                            timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                            int(board.turn)
                         ))
    
    def full_stockfish_evaluation(self, engine, min_depth: int = 10):
        """Ensure full coverage in cached stockfish evaluations at the wanted depth/s"""
        positions_to_evaluate = self.all_positions() - set([i[0] for i in self.con.execute(f"SELECT position FROM stockfish_evaluations WHERE depth >= {min_depth}").fetchall()])
        for n, i in enumerate(positions_to_evaluate):
            fen = f"{i} 0 0"
            board = chess.Board(fen=fen)
            if board.is_game_over() or (not board.is_valid()):
                continue
            eval = stockfish_evaluation(board=board, engine=engine, depth=min_depth)
            logging.info(f"Stockfish evaluation done! {n} / {len(positions_to_evaluate)}")
            self.con.execute(f"""INSERT INTO stockfish_evaluations (position,depth,evaluation,best_move) VALUES(?,?,?,?)""",
                             (
                                i,
                                min_depth,
                                eval[0],
                                eval[1]
                             ))
            if n % 100 == 0:
                self.con.commit()
        
        self.con.commit()


    def log_human_move(self, board: chess.Board, timestamp: datetime.datetime, player: str, move: chess.Move, is_real: bool, time_control: str):
        """Should be called ONCE for each attempted human move for each position, real or practice game, user or opponent."""
        assert isinstance(timestamp, datetime.datetime)

        position = fen_to_position(board.fen())
        move_string = board.san(move)

        resulting_position = board.copy()
        resulting_position.push(move)
        resulting_position = fen_to_position(resulting_position.fen())

        self.con.execute("""INSERT INTO move_attempts (position, timestamp, player, move, resulting_position, real_or_practice, time_control) VALUES(?,?,?,?,?,?,?)""",
                          (
                            position,
                            timestamp.strftime("%Y-%m-%d %H:%M:%S"),
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
        timestamp = f"{game.headers['UTCDate']} {game.headers['UTCTime']}".replace(".", "-")

        try:
            self.con.execute("INSERT INTO games (white,black,event,link,timestamp,result,time_control,variant,pgn,length) VALUES(?,?,?,?,?,?,?,?,?,?)",
                             (game.headers["White"],
                              game.headers["Black"],
                              game.headers["Event"],
                              game.headers["Site"],
                              timestamp,
                              game.headers["Result"],
                              game.headers["TimeControl"],
                              game.headers["Variant"],
                              game.__str__(),
                              len(list(game.mainline_moves()))))
        except sqlite3.IntegrityError:
            return False
        
        positions_saved = set()  # Only save each position at most once as repeated positions don't deserve being overweighted that much
        current_game_node = game
        next_game_node = game.next()
        current_position = gamenode_position(current_game_node)
        while not current_game_node.is_end():
            if current_position in positions_saved:
                current_game_node = current_game_node.next()
                current_position = gamenode_position(current_game_node)
                next_game_node = current_game_node.next()
                continue

            if current_game_node.turn == chess.WHITE:
                this_player = game.headers["White"]
            else:
                this_player = game.headers["Black"]
            timestamp_datetime = datetime.datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            self.log_played_position(board=current_game_node.board(), white=game.headers["White"], black=game.headers["Black"], timestamp=timestamp_datetime)
            self.log_human_move(board=current_game_node.board(), timestamp=timestamp_datetime, player=this_player, move=next_game_node.move, is_real=True, time_control=game.headers["TimeControl"])
            self.log_human_fen(board=current_game_node.board())
            positions_saved |= {current_position}

            current_game_node = current_game_node.next()
            current_position = gamenode_position(current_game_node)
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

        print(f"{len(self.all_positions())} total positions.")
