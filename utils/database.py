import sqlite3
from utils.lichess_api import client as lichess_client
from utils.puzzle import Puzzle
from utils.position import *
from utils.engine import Engine
from io import StringIO
import chess.pgn
import datetime
import logging
from globals import username
from zPosition import zPosition
from typing import Tuple
from requests.exceptions import ChunkedEncodingError

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
    def __init__(self, 
                 file="chess_database.db"):
        self.con = sqlite3.connect(database=file)
        self.con.row_factory = sqlite3.Row
        self.initialise_database_schema()

    def initialise_games_table(self):
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
        
    def initialise_stockfish_tables(self):
        # Tracking potentially multiple depth stockfish evaluations by position
        self.con.execute("""CREATE TABLE IF NOT EXISTS stockfish_evaluations (
            position TEXT NOT NULL,
            depth INTEGER NOT NULL,
            evaluation REAL NOT NULL,
            best_move TEXT,  -- Can be NULL if the position is game over
            PRIMARY KEY (position, depth)
        )""")

        # Using TRIGGER instead of views to keep real time processing down, increasing update time but updates won't happen that often
        self.con.execute("""CREATE TABLE IF NOT EXISTS best_stockfish_evaluations (
            position TEXT NOT NULL,
            depth INTEGER NOT NULL,
            evaluation REAL NOT NULL,
            best_move TEXT,  -- Can be NULL if the position is game over
            PRIMARY KEY (position)
        )""")

        self.con.execute("""CREATE TRIGGER IF NOT EXISTS best_stockfish_recorder 
                            AFTER INSERT ON stockfish_evaluations
                            WHEN NEW.depth >= (SELECT MAX(depth) from stockfish_evaluations where position=NEW.position)
                            BEGIN
                                INSERT OR REPLACE INTO best_stockfish_evaluations(position,depth,evaluation,best_move)
                                VALUES(NEW.position,NEW.depth,NEW.evaluation,NEW.best_move);
                            END""")

    def initialise_leela_tables(self):
        # Tracking potentially multiple depth leela evaluations by position
        self.con.execute("""CREATE TABLE IF NOT EXISTS leela_evaluations (
            position TEXT NOT NULL,
            nodes INTEGER NOT NULL,
            evaluation REAL NOT NULL,
            best_move TEXT,  -- NULL if position is game over
            PRIMARY KEY (position, nodes)
        )""")

        # Using TRIGGER instead of views to keep real time processing down, increasing update time but updates won't happen that often
        self.con.execute("""CREATE TABLE IF NOT EXISTS best_leela_evaluations (
            position TEXT NOT NULL,
            nodes INTEGER NOT NULL,
            evaluation REAL NOT NULL,
            best_move TEXT,  -- NULL if position is game over
            PRIMARY KEY (position)
        )""")

        self.con.execute("""CREATE TRIGGER IF NOT EXISTS best_leela_recorder 
                            AFTER INSERT ON leela_evaluations
                            WHEN NEW.nodes >= (SELECT MAX(nodes) from leela_evaluations where position=NEW.position)
                            BEGIN
                                INSERT OR REPLACE INTO best_leela_evaluations(position,nodes,evaluation,best_move)
                                VALUES(NEW.position,NEW.nodes,NEW.evaluation,NEW.best_move);
                            END""")

    def initialise_positions_tables(self):
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
        self.con.execute("""CREATE INDEX IF NOT EXISTS ipositions_seen_position on positions_seen_in_games(position)""")

        self.con.execute("""CREATE TABLE IF NOT EXISTS positions_metadata (
            position TEXT NOT NULL PRIMARY KEY,
            whose_turn INTEGER NOT NULL
        )""")
        self.con.execute("""CREATE TRIGGER IF NOT EXISTS position_metadata_updater
                            AFTER INSERT ON positions_seen_in_games
                            WHEN NOT EXISTS (SELECT 1 FROM positions_metadata WHERE position=NEW.position)
                            BEGIN
                                INSERT INTO positions_metadata
                                (position, whose_turn)
                                VALUES(NEW.position, NEW.whose_turn);
                            END""")

        # Used to be grouped by is_users_turn
        # My thinking is that because we're interested in the COUNT and RECENCY of positions, it shouldn't matter from which perspective
        # Errors in thinking on either side should be fixed, whether we're playing as or against!
        self.con.execute("""CREATE TABLE IF NOT EXISTS summarised_positions_seen_in_games (
            position TEXT NOT NULL,
            times_seen INTEGER NOT NULL,
            latest_timestamp TIMESTAMP NOT NULL,
            PRIMARY KEY (position)
        )""")
        self.con.execute("""CREATE TRIGGER IF NOT EXISTS positions_seen_in_games_counter 
                            AFTER INSERT ON positions_seen_in_games
                            BEGIN
                                INSERT OR REPLACE INTO summarised_positions_seen_in_games
                                (position,times_seen,latest_timestamp)
                                SELECT
                                    NEW.position,
                                    COUNT(*),
                                    MAX(timestamp)
                                FROM positions_seen_in_games
                                WHERE position=NEW.position;
                            END""")
        
        
    def initialise_combined_engine_tables(self):
        self.con.execute("""CREATE TABLE IF NOT EXISTS combined_engine_evaluation (
            position TEXT NOT NULL PRIMARY KEY,
            stockfish_evaluation REAL,
            stockfish_depth INTEGER,
            leela_evaluation REAL,
            leela_nodes INTEGER,
            combined_evaluation REAL NOT NULL
        )""")

        self.con.execute("""CREATE VIEW IF NOT EXISTS combined_engine_evaluation_expensive AS
                            SELECT
                                stockfish.position AS position,
                                stockfish.evaluation,
                                stockfish.depth,
                                leela.evaluation,
                                leela.nodes,
                                ((stockfish.evaluation + leela.evaluation) / 2)
                            FROM best_stockfish_evaluations stockfish
                            INNER JOIN best_leela_evaluations leela
                            ON leela.position=stockfish.position""")

        self.con.execute("""CREATE TRIGGER IF NOT EXISTS combined_engine_updater_stockfish
                            AFTER INSERT ON best_stockfish_evaluations
                            WHEN EXISTS (SELECT 1 FROM best_leela_evaluations WHERE position=NEW.position)
                            BEGIN
                                INSERT OR REPLACE INTO combined_engine_evaluation
                                (position, stockfish_evaluation, stockfish_depth, leela_evaluation, leela_nodes, combined_evaluation)
                                SELECT
                                    *
                                FROM combined_engine_evaluation_expensive
                                WHERE position=NEW.position
                                LIMIT 1;
                            END
                            """)
        
        self.con.execute("""CREATE TRIGGER IF NOT EXISTS combined_engine_updater_leela
                            AFTER INSERT ON best_leela_evaluations
                            WHEN EXISTS (SELECT 1 FROM best_stockfish_evaluations WHERE position=NEW.position)
                            BEGIN
                                INSERT OR REPLACE INTO combined_engine_evaluation
                                (position, stockfish_evaluation, stockfish_depth, leela_evaluation, leela_nodes, combined_evaluation)
                                SELECT
                                    *
                                FROM combined_engine_evaluation_expensive
                                WHERE position=NEW.position
                                LIMIT 1;
                            END
                            """)
        
    def initialise_time_control_tables(self):
        self.con.execute("""CREATE TABLE IF NOT EXISTS time_controls (
            time_control TEXT NOT NULL PRIMARY KEY,
            bank_seconds INTEGER AS (substr(time_control, 0, instr(time_control, '+'))) STORED NOT NULL,
            increment_seconds INTEGER AS (substr(time_control, instr(time_control, '+') + 1)) STORED NOT NULL
        )""")
        self.con.execute(f"""CREATE TRIGGER IF NOT EXISTS time_control_adder
                             BEFORE INSERT ON games
                             WHEN NOT EXISTS (SELECT 1 FROM time_controls WHERE NEW.time_control=time_controls.time_control)
                             BEGIN
                                 INSERT INTO time_controls
                                 (time_control)
                                 VALUES(IFNULL(NEW.time_control, "-"));
                             END
                             """)

        self.con.execute("""CREATE TABLE IF NOT EXISTS time_controls_summary (
            time_control TEXT NOT NULL PRIMARY KEY,
            bank_seconds INTEGER NOT NULL,
            increment_seconds INTEGER NOT NULL,
            total_games INTEGER NOT NULL,
            total_moves REAL NOT NULL,  -- A half move is .5
            average_n_moves REAL AS (IFNULL(total_moves / total_games, 0)) STORED NOT NULL,
            average_total_time_seconds REAL AS (IFNULL(bank_seconds + (increment_seconds * (total_moves / total_games)), 0)) STORED NOT NULL,
            average_seconds_per_move REAL AS (IFNULL(increment_seconds + (bank_seconds * total_moves / total_games), 0)) STORED NOT NULL
        )""")
        self.con.execute("""CREATE TRIGGER IF NOT EXISTS time_control_summary_row_initialiser
                            AFTER INSERT ON time_controls
                            WHEN NOT EXISTS (SELECT 1 FROM time_controls_summary WHERE time_control=NEW.time_control)
                            BEGIN
                                INSERT INTO time_controls_summary
                                (time_control, bank_seconds, increment_seconds, total_games, total_moves)
                                VALUES(NEW.time_control, NEW.bank_seconds, NEW.increment_seconds, 0, 0);
                            END""")
        self.con.execute(f"""CREATE TRIGGER IF NOT EXISTS time_control_summariser
                             AFTER INSERT ON games
                             BEGIN
                                UPDATE OR FAIL time_controls_summary
                                SET total_games = total_games + 1,
                                    total_moves = total_moves + (NEW.length / 2)
                                WHERE time_control = NEW.time_control;
                             END""")
    
    def initialise_move_attempts_tables(self):
        # One to many table tracking which moves have been played in each position
        # Either in an actual game (real_or_practice = 1) or not 0
        # NB that for speed, if the same position is seen more than once in one game the latest move will be recorded once
        # This also avoids it being overweighted where it probably shouldn't be
        self.con.execute("""CREATE TABLE IF NOT EXISTS move_attempts (
            position TEXT NOT NULL,
            resulting_position TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            player TEXT NOT NULL,
            move TEXT NOT NULL,
            real_or_practice INTEGER NOT NULL,
            time_control TEXT,
            time_taken_seconds REAL,
            PRIMARY KEY (position, timestamp, player, real_or_practice)
        )""")

        self.con.execute("""CREATE TABLE IF NOT EXISTS latest_real_move_attempts (
            position TEXT NOT NULL PRIMARY KEY,
            resulting_position TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            move TEXT NOT NULL,
            time_control TEXT NOT NULL,
            time_taken_seconds REAL
        )""")
        self.con.execute(f"""CREATE TRIGGER IF NOT EXISTS latest_real_move_attempts_updater
                             AFTER INSERT ON move_attempts
                             WHEN NEW.player='{username}' AND NEW.real_or_practice=1
                             BEGIN
                                 INSERT OR REPLACE INTO latest_real_move_attempts
                                 (position, resulting_position, timestamp, move, time_control, time_taken_seconds)
                                 SELECT
                                     position,
                                     resulting_position,
                                     timestamp,
                                     move,
                                     time_control,
                                     time_taken_seconds
                                 FROM move_attempts
                                 WHERE position=NEW.position
                                 AND player='{username}'
                                 AND real_or_practice=1
                                 AND timestamp=(SELECT MAX(timestamp) FROM move_attempts WHERE position=NEW.position AND player='{username}' AND real_or_practice=1)
                                 LIMIT 1;
                             END
                             """)

        # Whether it's a practice or real move doesn't really matter when getting the last time a move has been practiced
        self.con.execute("""CREATE TABLE IF NOT EXISTS latest_move_attempts (
            position TEXT NOT NULL PRIMARY KEY,
            resulting_position TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            move TEXT NOT NULL,
            time_taken_seconds REAL
        )""")
        self.con.execute(f"""CREATE TRIGGER IF NOT EXISTS latest_move_attempts_updater
                             AFTER INSERT ON move_attempts
                             WHEN NEW.player='{username}'
                             BEGIN
                                 INSERT OR REPLACE INTO latest_move_attempts
                                 (position, resulting_position, timestamp, move, time_taken_seconds)
                                 SELECT
                                     position,
                                     resulting_position,
                                     timestamp,
                                     move,
                                     time_taken_seconds
                                 FROM move_attempts
                                 WHERE position=NEW.position
                                 AND player='{username}'
                                 AND timestamp=(SELECT MAX(timestamp) FROM move_attempts WHERE position=NEW.position AND player='{username}');
                             END
                             """)

    def initialise_database_schema(self):
        # All games of interest which could be used to generate lessons / statistics
        self.initialise_games_table()

        # Position table.
        # Position refers to piece placement + who's turn + castling avaibs + en passant
        # Does NOT include halfmove or fullmove clocks as these generally aren't relevant for evaluation and practice
        self.con.execute("""CREATE TABLE IF NOT EXISTS positions (
            position TEXT NOT NULL,
            comment TEXT,
            PRIMARY KEY (position)
        )""")

        self.initialise_stockfish_tables()
        self.initialise_leela_tables()

        self.initialise_combined_engine_tables()

        self.initialise_positions_tables()

        self.initialise_move_attempts_tables()

        self.initialise_time_control_tables()

        self.con.execute(f"""CREATE TEMP VIEW move_attempt_analysis_stage_0 AS 
                             SELECT 
                                 latest_real_move_attempts.position AS position,
                                 latest_real_move_attempts.resulting_position AS latest_real_resulting_position,
                                 latest_real_move_attempts.move AS latest_real_played_move,
                                 latest_real_move_attempts.time_control AS latest_real_time_control,
                                 basic_position_data.whose_turn AS whose_turn,
                                 initial_evals.combined_evaluation AS initial_eval,
                                 resulting_evals.combined_evaluation AS latest_real_eval,
                                 IFNULL(practice_evals.combined_evaluation, resulting_evals.combined_evaluation) AS latest_practice_eval,
                                 CASE basic_position_data.whose_turn
                                    WHEN TRUE THEN initial_evals.combined_evaluation - resulting_evals.combined_evaluation  -- WHITE
                                    WHEN FALSE THEN resulting_evals.combined_evaluation - initial_evals.combined_evaluation  -- BLACK
                                 END latest_real_eval_loss,
                                 CASE basic_position_data.whose_turn
                                    WHEN TRUE THEN initial_evals.combined_evaluation - IFNULL(practice_evals.combined_evaluation, resulting_evals.combined_evaluation) -- WHITE
                                    WHEN FALSE THEN IFNULL(practice_evals.combined_evaluation, resulting_evals.combined_evaluation) - initial_evals.combined_evaluation -- BLACK
                                 END latest_practice_eval_loss,
                                 positions.times_seen as times_seen_in_real_games,
                                 positions.latest_timestamp as last_seen_in_real_game,
                                 JULIANDAY("NOW") - JULIANDAY(positions.latest_timestamp) as days_since_last_seen,
                                 IFNULL(last_practice.timestamp, positions.latest_timestamp) as last_practiced_timestamp,
                                 JULIANDAY("NOW") - IFNULL(JULIANDAY(last_practice.timestamp), JULIANDAY(positions.latest_timestamp)) as days_since_last_practiced,
                                 IFNULL(latest_real_move_attempts.time_taken_seconds, IFNULL(time_controls_summary.average_seconds_per_move, 30)) AS latest_real_time_taken_seconds,
                                 IFNULL(last_practice.time_taken_seconds, IFNULL(time_controls_summary.average_seconds_per_move, 30)) AS latest_practice_time_taken_seconds
                             FROM latest_real_move_attempts
                             INNER JOIN combined_engine_evaluation initial_evals ON latest_real_move_attempts.position = initial_evals.position
                             INNER JOIN combined_engine_evaluation resulting_evals ON latest_real_move_attempts.resulting_position = resulting_evals.position
                             INNER JOIN combined_engine_evaluation practice_evals ON last_practice.resulting_position = practice_evals.position
                             INNER JOIN summarised_positions_seen_in_games positions ON latest_real_move_attempts.position = positions.position
                             INNER JOIN positions_metadata basic_position_data ON basic_position_data.position = latest_real_move_attempts.position
                             INNER JOIN latest_move_attempts last_practice ON latest_real_move_attempts.position = last_practice.position
                             LEFT JOIN time_controls_summary ON latest_real_move_attempts.time_control = time_controls_summary.time_control
                             """)
        
        self.con.execute(f"""CREATE TEMP VIEW move_attempt_analysis AS
                             SELECT
                                *,
                                (latest_real_eval_loss + latest_practice_eval_loss) * (latest_real_time_taken_seconds + latest_practice_time_taken_seconds) * times_seen_in_real_games * days_since_last_practiced / days_since_last_seen AS priority
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

        self.con.commit()

    def value_exists(self, table, column, value) -> bool:
        """Check if a single value exists within a column."""
        return bool(self.con.execute(f"""SELECT EXISTS (SELECT 1 
                                                        FROM {table} 
                                                        WHERE {column}=?
                                                        LIMIT 1)""", (value, )).fetchone()[0])

    def position_last_played(self, position: str):
        result = self.con.execute(f"SELECT latest_timestamp FROM summarised_positions_seen_in_games WHERE position = '{position}'").fetchone()
        if result is not None:
            return dict(result)["latest_timestamp"]
        else:
            return None
    
    def highest_priority_puzzle(self) -> Puzzle:
        return Puzzle(x=dict(self.con.execute("SELECT * FROM move_attempt_analysis LIMIT 1").fetchone()))

    def all_positions(self):

        position_saved_places = {
            "positions": ["position"],
            "combined_engine_evaluation": ["position"],
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

    def full_engine_evaluation(self,
                               engine: Engine,
                               depth_value: int):
        """Ensure full coverage in cached engine evaluations for the given engine at the wanted depth"""
        positions_to_evaluate = self.all_positions() - set([i[0] for i in self.con.execute(f"SELECT position FROM {engine.evaluations_table} WHERE {engine.depth_parameter} >= {depth_value}").fetchall()])
        for n, i in enumerate(positions_to_evaluate):
            fen = f"{i} 0 0"
            board = chess.Board(fen=fen)
            self.engine_evaluation(board=board, engine=engine, depth_value=depth_value, commit=False)
            logging.info(f"{engine.name} evaluation done! {n} / {len(positions_to_evaluate)}")
            if n % 100 == 0:
                self.con.commit()
        
        self.con.commit()
    
    def read_combined_engine_evaluation(self,
                                        board: chess.Board) -> float:
        position = board_position(board)

        return dict(self.con.execute(f"""SELECT combined_evaluation FROM combined_engine_evaluation WHERE position='{position}'""").fetchone())["combined_evaluation"]

    def engine_move(self, 
                    board: chess.Board, 
                    engine: Engine, 
                    depth_value: int, 
                    multipv: int = 1, 
                    commit: bool = True,
                    exact_requirements: bool = False) -> float:
        position = board_position(board)

        if exact_requirements:
            comparator = "="
        else:
            comparator = ">="

        if bool(self.con.execute(f"""SELECT EXISTS (SELECT 1 
                                                    FROM {engine.evaluations_table} 
                                                    WHERE position='{position}'
                                                    AND {engine.depth_parameter}{comparator}{depth_value}
                                                    LIMIT 1)""").fetchone()[0]):
            san_move =  self.con.execute(f"""SELECT best_move
                                             FROM {engine.evaluations_table}
                                             WHERE position='{position}'
                                             AND {engine.depth_parameter}{comparator}{depth_value}
                                             ORDER BY {engine.depth_parameter} DESC
                                             LIMIT 1""").fetchone()[0]
            return board.parse_san(san_move)
        
        result = engine.evaluate_board(board=board, depth_value=depth_value)

        if result is None:
            return None
        
        if type(result) == int:
            basic_result = (result, None)
        else:
            basic_result = (result[0]["score"], board.san(result[0]["pv"][0]))  # Simplify to evaluation, best_move

        self.con.execute(f"""INSERT INTO {engine.evaluations_table} (position,{engine.depth_parameter},evaluation,best_move) VALUES(?,?,?,?)""",
                         (
                            board_position(board),
                            depth_value,
                            basic_result[0],
                            basic_result[1]
                         ))
        if commit:
            self.con.commit()

        return result[0]["pv"][0]

    def engine_evaluation(self, 
                          board: chess.Board, 
                          engine: Engine, 
                          depth_value: int, 
                          multipv: int = 1, 
                          commit: bool = True,
                          exact_requirements: bool = False) -> float:
        position = board_position(board)

        if exact_requirements:
            comparator = "="
        else:
            comparator = ">="

        if bool(self.con.execute(f"""SELECT EXISTS (SELECT 1 
                                                    FROM {engine.evaluations_table} 
                                                    WHERE position='{position}'
                                                    AND {engine.depth_parameter}{comparator}{depth_value}
                                                    LIMIT 1)""").fetchone()[0]):
            return self.con.execute(f"""SELECT evaluation
                                        FROM {engine.evaluations_table}
                                        WHERE position='{position}'
                                        AND {engine.depth_parameter}{comparator}{depth_value}
                                        ORDER BY {engine.depth_parameter} DESC
                                        LIMIT 1""").fetchone()[0]
        
        result = engine.evaluate_board(board=board, depth_value=depth_value)

        if result is None:
            return None
        
        if type(result) == float:
            basic_result = (result, None)
        else:
            basic_result = (result[0]["score"], board.san(result[0]["pv"][0]))  # Simplify to evaluation, best_move

        self.con.execute(f"""INSERT INTO {engine.evaluations_table} (position,{engine.depth_parameter},evaluation,best_move) VALUES(?,?,?,?)""",
                         (
                            board_position(board),
                            depth_value,
                            basic_result[0],
                            basic_result[1]
                         ))
        if commit:
            self.con.commit()

        return basic_result[0]

    def log_human_move(self, 
                       board: chess.Board, 
                       timestamp: datetime.datetime, 
                       player: str, 
                       move: chess.Move, 
                       is_real: bool, 
                       time_control: str = None,
                       time_taken_seconds: float = None,
                       commit: bool = True):
        """Should be called ONCE for each attempted human move for each position, real or practice game, user or opponent."""
        assert isinstance(timestamp, datetime.datetime)
        assert (time_control is not None) or (time_taken_seconds is not None)

        position: str = fen_to_position(board.fen())
        move_string: str = board.san(move)

        resulting_position: chess.Board = board.copy()
        resulting_position.push(move)
        resulting_position = fen_to_position(fen=resulting_position.fen())

        self.con.execute("""INSERT INTO move_attempts (position, timestamp, player, move, resulting_position, real_or_practice, time_control, time_taken_seconds) VALUES(?,?,?,?,?,?,?,?)""",
                         (
                             position,
                             timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                             player,
                             move_string,
                             resulting_position,
                             is_real,
                             time_control,
                             time_taken_seconds
                         ))
        
        if commit:
            self.con.commit()
        
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
        game_name: str = f"{game.headers['White']} vs {game.headers['Black']} ({game.headers['UTCDate']})"

        if self.con.execute(f"SELECT 1 FROM games WHERE white=? AND black=? AND timestamp=?", (game.headers["White"], game.headers["Black"], timestamp)).fetchone() is not None:
            logging.info(f"Not adding game as already in database: {game_name}")
            return False

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

            if current_game_node.turn() == chess.WHITE:
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
        
        logging.info(f"Added game to db: {game_name}")

        return True
    
    def download_latest_games(self, max_new_games: int = None):
        new_pgns = lichess_client.games.export_by_player(username=username,
                                                         as_pgn=True,
                                                         since=self.latest_game_timestamp,
                                                         rated=True,
                                                         finished=True,
                                                         sort="dateAsc")
        
        games_added = 0
        try:
            for i in new_pgns:
                this_new_game = chess.pgn.read_game(StringIO(i))
                success = self.add_game(this_new_game)
                if success:
                    games_added += 1
                    if max_new_games is not None:
                        if games_added >= max_new_games:
                            break
                else:
                    continue
        except ChunkedEncodingError:
            logging.info("Connection broken by host (ChunkedEncodingError)")

        if games_added > 0:
            self.con.commit()
            logging.info(f"Added {games_added} games to the database.")
        else:
            logging.info(f"No new games found.")

        self.log_db_stats()

    def log_db_stats(self):
        def print_info(table):
            logging.info(f"{self.con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()} rows in {table}")
        
        for i in ["games", "positions", "combined_engine_evaluation", "stockfish_evaluations", "leela_evaluations", "positions_seen_in_games", "move_attempts", "fens", "fen_stats"]:
            print_info(i)

        print(f"{len(self.all_positions())} total positions.")
