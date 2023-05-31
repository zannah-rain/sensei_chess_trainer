import sqlite3
from utils.lichess_api import client as lichess_client
from utils.puzzle import Puzzle
from utils.position import *
from utils.engine import Engine, EngineEvaluationResult
from io import StringIO
import chess.pgn
import datetime
import logging
from globals import username
from zPosition import zPosition
from typing import Tuple, List
from requests.exceptions import ChunkedEncodingError
import requests
import time
import globals

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
        self.con.executescript("""PRAGMA journal_mode = wal;  -- Faster writes
                                  PRAGMA synchronous = normal;  -- Slightly less safety but much faster
                                  PRAGMA temp_store = 2;  -- Keep temp stuff in memory more often
                                  PRAGMA cache_size = -128000;  -- 128mb RAM cache (default is 2 or something :o)""")
        self.initialise_database_schema()

    def close_and_optimise(self):
        self.con.executescript("""PRAGMA analysis_limit=400;
                                  PRAGMA optimize;""")
        self.con.close()

    def _lichess_opening_api_query(self, query_url: str):
        if globals.explorer_limit:
            return None
        
        r = requests.get(query_url)
        time.sleep(1)
        if r.status_code == 429:
            logging.info(f"Hit Lichess stats API rate limit, making no more requests and waiting to avoid restart oopsies")
            time.sleep(60)
            globals.explorer_limit = True
            return None
        else:
            response = r.json()

        return response

    def _populate_lichess_stats(self, fen: str, commit: bool = True):
        def amateur_api(fen: str,
                        speed: str,
                        variant: str = "standard",
                        rating_band: str = 2500,
                        moves: int = 50,
                        recentGames: int = 0,
                        topGames: int = 0,
                        play: str = "") -> str:
            url = "https://explorer.lichess.ovh/lichess?"
            url += f"variant={variant}&"
            url += f"speeds={speed}&"
            url += f"ratings={rating_band}&"
            url += f"recentGames={recentGames}&"
            url += f"topGames={topGames}&"
            url += f"moves={moves}&"
            url += f"play={play}&"
            url += f"fen={fen}"
            return url
        
        for this_speed in ["ultraBullet", "bullet", "blitz", "rapid", "classical", "correspondence"]:
            for this_rating_band in [0, 1000, 1200, 1400, 1600, 1800, 2000, 2200, 2500]:
                x = self._lichess_opening_api_query(query_url=amateur_api(fen=fen, speed=this_speed, variant="standard", rating_band=this_rating_band, moves=0))
                opening_eco = None
                opening_name = None
                white_wins = 0
                draws = 0
                black_wins = 0
                if x is not None:
                    if x["opening"] is not None:
                        opening_eco = x["opening"]["eco"]
                        opening_name = x["opening"]["name"]
                    white_wins = x["white"]
                    draws = x["draws"]
                    black_wins = x["black"]
                self.con.execute("""INSERT INTO lichess_stats
                                    (request_fen,
                                     request_timestamp,
                                     request_variant,
                                     request_speed,
                                     request_rating_band,
                                     request_since,
                                     request_until,
                                     request_n_moves,
                                     request_n_top_games,
                                     request_n_recent_games,
                                     request_history,
                                     opening_eco,
                                     opening_name,
                                     white_wins,
                                     draws,
                                     black_wins
                                     )
                                    VALUES(
                                     ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                                    )""",
                                    (fen,
                                     datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                     "standard",
                                     this_speed,
                                     this_rating_band,
                                     "1952-01",
                                     "3000-12",
                                     0,
                                     0,
                                     0,
                                     0,
                                     opening_eco,
                                     opening_name,
                                     white_wins,
                                     draws,
                                     black_wins))
                logging.info(f"Added lichess amateur stats for fen {fen}, speed {this_speed}, rating band {this_rating_band}")

        def master_api(fen: str,
                       topGames: int = 0,
                       play: str = "",
                       moves: int = 50):
            url = 'https://explorer.lichess.ovh/masters?'
            url += f'topGames={topGames}&'
            url += f'moves={moves}&'
            url += f'play={play}&'
            url += f'fen={fen}'
            return url
        
        x = self._lichess_opening_api_query(query_url=master_api(fen=fen, moves=0))
        opening_eco = None
        opening_name = None
        white_wins = 0
        draws = 0
        black_wins = 0
        if x is not None:
            if x["opening"] is not None:
                opening_eco = x["opening"]["eco"]
                opening_name = x["opening"]["name"]
            white_wins = x["white"]
            draws = x["draws"]
            black_wins = x["black"]
        self.con.execute("""INSERT INTO lichess_master_stats
                            (request_fen,
                             request_timestamp,
                             request_since,
                             request_until,
                             request_n_moves,
                             request_n_top_games,
                             opening_eco,
                             opening_name,
                             white_wins,
                             draws,
                             black_wins
                             )
                            VALUES(
                                ?,?,?,?,?,?,?,?,?,?,?
                            )""",
                            (fen,
                             datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                             "1952",
                             "3000",
                             0,
                             0,
                             opening_eco,
                             opening_name,
                             white_wins,
                             draws,
                             black_wins))
        logging.info(f"Added lichess master stats for fen {fen}")

        if commit:
            self.con.commit()

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
        
    def initialise_lichess_stats_tables(self) -> None:
        # Enum table to help sorting
        self.con.execute("""CREATE TABLE IF NOT EXISTS lichess_speeds_enum (
            speed TEXT NOT NULL,
            speed_ordinal INTEGER NOT NULL,
            PRIMARY KEY (speed)
        );""")
        self.con.executescript("""
        INSERT OR REPLACE INTO lichess_speeds_enum(speed,speed_ordinal) VALUES("ultraBullet", 0);
        INSERT OR REPLACE INTO lichess_speeds_enum(speed,speed_ordinal) VALUES("bullet", 1);
        INSERT OR REPLACE INTO lichess_speeds_enum(speed,speed_ordinal) VALUES("blitz", 2);
        INSERT OR REPLACE INTO lichess_speeds_enum(speed,speed_ordinal) VALUES("rapid", 3);
        INSERT OR REPLACE INTO lichess_speeds_enum(speed,speed_ordinal) VALUES("classical", 4);
        INSERT OR REPLACE INTO lichess_speeds_enum(speed,speed_ordinal) VALUES("correspondence", 5);
        """)

        self.con.executescript("""CREATE TABLE IF NOT EXISTS lichess_ratings_enum (
            rating INTEGER PRIMARY KEY NOT NULL
        );
        INSERT OR REPLACE INTO lichess_ratings_enum(rating) VALUES(0);
        INSERT OR REPLACE INTO lichess_ratings_enum(rating) VALUES(1000);
        INSERT OR REPLACE INTO lichess_ratings_enum(rating) VALUES(1200);
        INSERT OR REPLACE INTO lichess_ratings_enum(rating) VALUES(1400);
        INSERT OR REPLACE INTO lichess_ratings_enum(rating) VALUES(1600);
        INSERT OR REPLACE INTO lichess_ratings_enum(rating) VALUES(1800);
        INSERT OR REPLACE INTO lichess_ratings_enum(rating) VALUES(2000);
        INSERT OR REPLACE INTO lichess_ratings_enum(rating) VALUES(2200);
        INSERT OR REPLACE INTO lichess_ratings_enum(rating) VALUES(2500);
        """)

        self.con.execute("""CREATE TABLE IF NOT EXISTS lichess_stats (
            request_fen TEXT NOT NULL,
            request_timestamp TIMESTAMP NOT NULL,
            request_variant TEXT NOT NULL,
            request_speed TEXT NOT NULL,
            request_rating_band TEXT NOT NULL,
            request_since TEXT NOT NULL,
            request_until TEXT NOT NULL,
            request_n_moves INTEGER NOT NULL,
            request_n_top_games INTEGER NOT NULL,
            request_n_recent_games INTEGER NOT NULL,
            request_history INTEGER NOT NULL,
            opening_eco TEXT,
            opening_name TEXT,
            white_wins INTEGER,
            draws INTEGER,
            black_wins INTEGER,
            total_games INTEGER AS (white_wins + draws + black_wins),
            evaluation REAL AS ((white_wins + draws * 0.5) / (white_wins + draws + black_wins)),
            PRIMARY KEY (request_fen, request_timestamp, request_variant, request_speed, request_rating_band)
        )""")
        self.con.execute("""CREATE TABLE IF NOT EXISTS lichess_master_stats (
            request_fen TEXT NOT NULL,
            request_timestamp TIMESTAMP NOT NULL,
            request_since TEXT NOT NULL,
            request_until TEXT NOT NULL,
            request_n_moves INTEGER NOT NULL,
            request_n_top_games INTEGER NOT NULL,
            opening_eco TEXT,
            opening_name TEXT,
            white_wins INTEGER,
            draws INTEGER,
            black_wins INTEGER,
            total_games INTEGER AS (white_wins + draws + black_wins),
            evaluation REAL AS ((white_wins + draws * 0.5) / (white_wins + draws + black_wins)),
            PRIMARY KEY (request_fen, request_timestamp)
        )""")

        self.con.execute("""CREATE TABLE IF NOT EXISTS openings (
            fen TEXT NOT NULL,
            eco TEXT,
            name TEXT
        )""")

        self.con.execute("""CREATE TABLE IF NOT EXISTS latest_lichess_stats (
            fen TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            variant TEXT NOT NULL,
            speed TEXT NOT NULL,
            speed_index INTEGER NOT NULL,
            rating_band TEXT NOT NULL,
            since TEXT NOT NULL,
            until TEXT NOT NULL,
            white_wins INTEGER,
            draws INTEGER,
            black_wins INTEGER,
            total_games INTEGER AS (white_wins + draws + black_wins) STORED,
            evaluation REAL AS ((white_wins + draws / 2) / (white_wins + draws + black_wins)) STORED,
            PRIMARY KEY (fen, variant, speed, rating_band)
        )""")
        self.con.execute("""CREATE TRIGGER IF NOT EXISTS lichess_stats_summariser_latest
                            AFTER INSERT ON lichess_stats
                            BEGIN
                                INSERT OR REPLACE INTO latest_lichess_stats
                                (fen, timestamp, variant, speed, speed_index, rating_band, since, until, white_wins, draws, black_wins)
                                SELECT
                                    ls.request_fen,
                                    ls.request_timestamp,
                                    ls.request_variant,
                                    ls.request_speed,
                                    lse.speed_ordinal,
                                    ls.request_rating_band,
                                    ls.request_since,
                                    ls.request_until,
                                    ls.white_wins,
                                    ls.draws,
                                    ls.black_wins
                                FROM lichess_stats ls
                                INNER JOIN lichess_speeds_enum lse ON ls.request_speed = lse.speed
                                WHERE request_fen = NEW.request_fen
                                ORDER BY request_timestamp DESC
                                LIMIT 1;
                            END""")
        self.con.execute("""CREATE TABLE IF NOT EXISTS latest_lichess_master_stats (
            fen TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            since TEXT NOT NULL,
            until TEXT NOT NULL,
            white_wins INTEGER,
            draws INTEGER,
            black_wins INTEGER,
            total_games INTEGER AS (white_wins + draws + black_wins) STORED,
            evaluation REAL AS ((white_wins + draws / 2) / (white_wins + draws + black_wins)) STORED,
            PRIMARY KEY (fen)
        )""")
        self.con.execute("""CREATE TRIGGER IF NOT EXISTS lichess_master_stats_summariser_latest
                            AFTER INSERT ON lichess_master_stats
                            BEGIN
                                INSERT OR REPLACE INTO latest_lichess_master_stats
                                (fen, timestamp, since, until, white_wins, draws, black_wins)
                                SELECT
                                    ls.request_fen,
                                    ls.request_timestamp,
                                    ls.request_since,
                                    ls.request_until,
                                    ls.white_wins,
                                    ls.draws,
                                    ls.black_wins
                                FROM lichess_master_stats ls
                                WHERE request_fen = NEW.request_fen
                                ORDER BY request_timestamp DESC
                                LIMIT 1;
                            END""")

        self.con.execute("""CREATE TABLE IF NOT EXISTS latest_lichess_stats_standard (
            fen TEXT NOT NULL,
            minimum_speed TEXT NOT NULL,
            minimum_rating_band TEXT NOT NULL,
            white_wins INTEGER,
            draws INTEGER,
            black_wins INTEGER,
            total_games INTEGER AS (white_wins + draws + black_wins),
            evaluation REAL AS ((white_wins + draws / 2) / (white_wins + draws + black_wins)),
            PRIMARY KEY (fen, minimum_speed, minimum_rating_band)
        )""")
        self.con.execute("""CREATE TRIGGER IF NOT EXISTS lichess_stats_summariser_banding
                            AFTER INSERT ON latest_lichess_stats
                            WHEN NEW.variant = 'standard'
                            BEGIN
                                INSERT OR REPLACE INTO latest_lichess_stats_standard
                                (fen, minimum_speed, minimum_rating_band, white_wins, draws, black_wins)
                                SELECT
                                    stats.fen AS fen,
                                    all_speeds.speed AS minimum_speed,
                                    -- all_speeds.speed_index AS minimum_speed_index,
                                    all_rating_bands.rating AS minimum_rating_band,
                                    SUM(stats.white_wins) AS white_wins,
                                    SUM(stats.draws) AS draws,
                                    SUM(stats.black_wins) AS black_wins
                                FROM lichess_speeds_enum all_speeds
                                CROSS JOIN lichess_ratings_enum all_rating_bands
                                INNER JOIN latest_lichess_stats stats 
                                    ON stats.fen = NEW.fen
                                    AND stats.variant = 'standard'
                                    AND stats.speed_index >= all_speeds.speed_ordinal
                                    AND stats.rating_band >= all_rating_bands.rating
                                GROUP BY stats.fen, all_speeds.speed, all_speeds.speed_ordinal, all_rating_bands.rating;
                            END""")
        
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
        # You can use this to get game info, as games are basically identified by (white, black, timestamp)
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

        self.con.execute(f"""CREATE TEMP VIEW game_stats AS
            SELECT
                g.white AS white,
                g.black AS black,
                g.timestamp AS timestamp,
                g.event AS event,
                g.link AS link,
                g.result AS result,
                g.time_control AS time_control,
                g.variant AS variant,
                g.pgn AS pgn,
                g.length AS length,
                psig.is_users_turn AS is_users_turn,
                COUNT(psig.position) AS unique_positions,
                COUNT(p.comment) AS positions_reviewed,
                CAST(COUNT(p.comment) AS FLOAT) / COUNT(psig.position) AS proportion_reviewed
            FROM games g
            INNER JOIN positions_seen_in_games psig ON g.white=psig.white AND g.black=psig.black AND g.timestamp=psig.timestamp
            LEFT JOIN positions p ON psig.position = p.position
            GROUP BY g.white, g.black, g.timestamp
        """)

        
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
        
    def get_position_comment(self, position: str) -> str:
        comment = self.con.execute(f"SELECT comment FROM positions WHERE position = '{position}'").fetchone()
        if comment is None:
            return ""
        return comment["comment"]

    def set_position_comment(self, position: str, comment: str, commit: bool = True) -> None:
        self.con.execute(f"INSERT OR REPLACE INTO positions (position, comment, manual_evaluation, name) VALUES(?, ?, (SELECT manual_evaluation from positions where position='{position}'), (SELECT name from positions where position='{position}'))", (position, comment))
        if commit:
            self.con.commit()

    def get_position_manual_evaluation(self, position: str) -> str:
        evaluation = self.con.execute(f"SELECT manual_evaluation FROM positions WHERE position = '{position}'").fetchone()
        if evaluation is None:
            return None
        return evaluation["manual_evaluation"]

    def set_position_manual_evaluation(self, position: str, manual_evaluation: float, commit: bool = True) -> None:
        self.con.execute(f"INSERT OR REPLACE INTO positions (position, comment, manual_evaluation, name) VALUES(?, (SELECT comment from positions where position='{position}'), ?, (SELECT name from positions where position='{position}'))", (position, manual_evaluation))
        if commit:
            self.con.commit()

    def get_position_name(self, position: str) -> str:
        name = self.con.execute(f"SELECT name FROM positions WHERE position = '{position}'").fetchone()
        if name is None:
            return None
        return name["name"]

    def set_position_name(self, position: str, name: str, commit: bool = True) -> None:
        self.con.execute(f"INSERT OR REPLACE INTO positions (position, comment, manual_evaluation, name) VALUES(?, (SELECT comment from positions where position='{position}'), (SELECT manual_evaluation from positions where position='{position}'), ?)", (position, name))
        if commit:
            self.con.commit()

    def initialise_database_schema(self):
        # All games of interest which could be used to generate lessons / statistics
        self.initialise_games_table()

        # Position table.
        # Position refers to piece placement + who's turn + castling avaibs + en passant
        # Does NOT include halfmove or fullmove clocks as these generally aren't relevant for evaluation and practice
        self.con.execute("""CREATE TABLE IF NOT EXISTS positions (
            position TEXT NOT NULL,
            comment TEXT,
            manual_evaluation REAL,
            name TEXT,
            PRIMARY KEY (position)
        )""")

        self.initialise_stockfish_tables()
        self.initialise_leela_tables()

        self.initialise_combined_engine_tables()

        self.initialise_positions_tables()

        self.initialise_move_attempts_tables()

        self.initialise_time_control_tables()

        self.initialise_lichess_stats_tables()

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
                                (latest_real_eval_loss + latest_practice_eval_loss) * (MIN(latest_real_time_taken_seconds, 90) + MIN(latest_practice_time_taken_seconds, 90)) * times_seen_in_real_games * days_since_last_practiced / days_since_last_seen AS priority
                             FROM move_attempt_analysis_stage_0
                             ORDER BY priority DESC""")
        
        # Want to know:
        # Stats about practice done today and this week
        # Stats on games done today and this week
        # Overall practice stats
        # Overall game stats

        self.con.execute(f"""
        CREATE TEMP VIEW move_stats AS
            WITH todays_practice_stats AS (
                SELECT 
                    1 AS indxx,
                    COUNT(*) AS positions_practiced,
                    AVG(latest_real_eval_loss) AS average_real_eval_loss,
                    SUM(latest_real_eval_loss) AS sum_real_eval_loss,
                    AVG(latest_practice_eval_loss) AS average_practice_eval_loss,
                    SUM(latest_practice_eval_loss) AS sum_practice_eval_loss,
                    SUM(times_seen_in_real_games) as times_practiced_positions_seen_in_real_games,
                    AVG(latest_real_time_taken_seconds) AS average_time_per_move_real,
                    AVG(latest_practice_time_taken_seconds) AS average_time_per_move_practice,
                    SUM(priority) AS total_re_review_priority
                FROM move_attempt_analysis
                WHERE days_since_last_practiced <= 1
                AND last_practiced_timestamp != last_seen_in_real_game
            ),
            this_month_performance_stats AS (
                SELECT 
                    1 AS indxx,
                    COUNT(*) AS positions_played,
                    AVG(latest_real_eval_loss) AS average_real_eval_loss
                FROM move_attempt_analysis
                WHERE days_since_last_seen <= 30
            ),
            todays_game_stats AS (
                SELECT
                    1 AS indxx,
                    COUNT(*) AS games_played,
                    AVG(length) AS average_half_moves,
                    SUM(length) AS total_half_moves
                FROM games
                WHERE JULIANDAY("NOW") - JULIANDAY(timestamp) <= 1
            ),
            overall_game_stats AS (
                SELECT 
                    1 AS indxx,
                    COUNT(*) AS games_played,
                    AVG(length) as average_half_moves
                FROM games
            ),
            overall_practice_stats AS (
                SELECT 
                    1 AS indxx,
                    COUNT(position) AS positions_practiced,
                    AVG(latest_real_eval_loss) AS average_real_eval_loss,
                    SUM(latest_real_eval_loss) AS sum_real_eval_loss,
                    AVG(latest_practice_eval_loss) AS average_practice_eval_loss,
                    SUM(latest_practice_eval_loss) AS sum_practice_eval_loss,
                    SUM(times_seen_in_real_games) as times_practiced_positions_seen_in_real_games,
                    AVG(latest_real_time_taken_seconds) AS average_time_per_move_real,
                    AVG(latest_practice_time_taken_seconds) AS average_time_per_move_practice,
                    SUM(priority) AS total_re_review_priority
                FROM move_attempt_analysis
                WHERE last_practiced_timestamp != last_seen_in_real_game
            ),
            overall_real_stats AS (
                SELECT 
                    1 AS indxx,
                    COUNT(*) AS positions_played,
                    AVG(latest_real_eval_loss) AS average_real_eval_loss,
                    SUM(latest_real_eval_loss) AS sum_real_eval_loss,
                    SUM(times_seen_in_real_games) as times_real_positions_seen_in_real_games,
                    AVG(latest_real_time_taken_seconds) AS average_time_per_move_real,
                    SUM(priority) AS total_review_priority
                FROM move_attempt_analysis
            )
            SELECT
                IFNULL(todays_practice_stats.positions_practiced, 0) AS positions_practiced_today,
                todays_practice_stats.average_real_eval_loss AS average_real_eval_loss_today,
                IFNULL(todays_practice_stats.sum_real_eval_loss, 0) AS sum_real_eval_loss_today,
                todays_practice_stats.average_practice_eval_loss AS average_practice_eval_loss_today,
                IFNULL(todays_practice_stats.sum_practice_eval_loss, 0) AS sum_practice_eval_loss_today,
                IFNULL(todays_practice_stats.times_practiced_positions_seen_in_real_games, 0) AS times_todays_positions_seen_in_real_games,
                todays_practice_stats.average_time_per_move_real AS average_real_time_per_move_today,
                todays_practice_stats.average_time_per_move_practice AS average_practice_time_per_move_today,
                IFNULL(todays_practice_stats.total_re_review_priority, 0) AS todays_total_re_review_priority,
                IFNULL(todays_game_stats.games_played, 0) AS total_games_played_today,
                todays_game_stats.average_half_moves AS average_half_moves_per_real_game_today,
                IFNULL(todays_game_stats.total_half_moves, 0) AS total_half_moves_from_real_games_today,
                IFNULL(overall_practice_stats.positions_practiced, 0) AS total_positions_practiced_alltime,
                overall_practice_stats.average_real_eval_loss AS average_real_eval_loss_in_practiced_positions,
                IFNULL(overall_practice_stats.sum_real_eval_loss, 0) AS total_real_eval_loss_in_practiced_positions,
                overall_practice_stats.average_practice_eval_loss AS average_practice_eval_loss_alltime,
                IFNULL(overall_practice_stats.sum_practice_eval_loss, 0) AS total_practice_eval_loss_alltime,
                IFNULL(overall_practice_stats.times_practiced_positions_seen_in_real_games, 0) AS times_practiced_positions_seen_in_real_games,
                overall_practice_stats.average_time_per_move_real AS average_real_time_per_move_in_practiced_positions,
                overall_practice_stats.average_time_per_move_practice AS average_practice_time_per_move_in_practiced_positions,
                IFNULL(overall_practice_stats.total_re_review_priority, 0) AS total_alltime_re_review_priority,
                IFNULL(overall_real_stats.positions_played, 0) AS total_unique_real_positions_played_alltime,
                overall_real_stats.average_real_eval_loss AS average_real_eval_loss_alltime,
                IFNULL(overall_real_stats.sum_real_eval_loss, 0) AS total_real_eval_loss_alltime,
                IFNULL(overall_real_stats.times_real_positions_seen_in_real_games, 0) AS total_real_positions_played_alltime,
                overall_real_stats.average_time_per_move_real AS average_real_time_per_move_alltime,
                IFNULL(overall_real_stats.total_review_priority, 0) AS total_review_priority,
                IFNULL(overall_game_stats.games_played, 0) AS total_games_played,
                overall_game_stats.average_half_moves AS average_game_halfmoves_alltime,
                IFNULL(this_month_performance_stats.positions_played, 0) AS this_month_positions_played,
                this_month_performance_stats.average_real_eval_loss AS this_month_average_real_eval_loss
            FROM 
                todays_practice_stats
                INNER JOIN todays_game_stats ON todays_practice_stats.indxx = todays_game_stats.indxx
                INNER JOIN overall_practice_stats ON todays_practice_stats.indxx = overall_practice_stats.indxx
                INNER JOIN overall_real_stats ON todays_practice_stats.indxx = overall_real_stats.indxx
                INNER JOIN overall_game_stats ON todays_practice_stats.indxx = overall_game_stats.indxx
                INNER JOIN this_month_performance_stats ON todays_practice_stats.indxx = this_month_performance_stats.indxx
        """)

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
        assert board.is_valid()

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
            if board.is_valid():
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

        if not bool(self.con.execute(f"""SELECT EXISTS (SELECT 1 
                                                    FROM {engine.evaluations_table} 
                                                    WHERE position='{position}'
                                                    AND {engine.depth_parameter}{comparator}{depth_value}
                                                    LIMIT 1)""").fetchone()[0]):
            self._run_engine_evaluation(board=board, engine=engine, depth_value=depth_value, multipv=multipv, commit=commit)

        san_move =  self.con.execute(f"""SELECT best_move
                                            FROM {engine.evaluations_table}
                                            WHERE position='{position}'
                                            AND {engine.depth_parameter}{comparator}{depth_value}
                                            ORDER BY {engine.depth_parameter} DESC
                                            LIMIT 1""").fetchone()[0]
        return board.parse_san(san_move)
    
    def _run_engine_evaluation(self,
                               board: chess.Board,
                               engine: Engine,
                               depth_value: int,
                               multipv: int = 1,
                               commit: bool = True) -> EngineEvaluationResult:
        result = engine.evaluate_board(board=board, depth_value=depth_value)

        if result is None:
            return None
        
        if result.best_move is None:
            best_move = None
        else:
            best_move = board.san(result.best_move)

        self.con.execute(f"""INSERT OR REPLACE INTO {engine.evaluations_table} (position,{engine.depth_parameter},evaluation,best_move) VALUES(?,?,?,?)""",
                         (
                            board_position(board),
                            depth_value,
                            result.lichess_evaluation,
                            best_move
                         ))
        if commit:
            self.con.commit()

        return result

    def engine_evaluation(self, 
                          board: chess.Board, 
                          engine: Engine, 
                          depth_value: int, 
                          multipv: int = 1, 
                          commit: bool = True,
                          exact_requirements: bool = False) -> EngineEvaluationResult:
        assert board.is_valid()
        position = board_position(board)

        if exact_requirements:
            comparator = "="
        else:
            comparator = ">="

        if not bool(self.con.execute(f"""SELECT EXISTS (SELECT 1 
                                                        FROM {engine.evaluations_table} 
                                                        WHERE position='{position}'
                                                        AND {engine.depth_parameter}{comparator}{depth_value}
                                                        LIMIT 1)""").fetchone()[0]):
            self._run_engine_evaluation(board=board, engine=engine, depth_value=depth_value, multipv=multipv, commit=commit)
        
        return self.con.execute(f"""SELECT evaluation
                                    FROM {engine.evaluations_table}
                                    WHERE position='{position}'
                                    AND {engine.depth_parameter}{comparator}{depth_value}
                                    ORDER BY {engine.depth_parameter} DESC
                                    LIMIT 1""").fetchone()[0]

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
            
    def add_position_features(self, board: chess.Board):
        """Adds raw position related features to the database. Things like how many pieces are on the board, who's turn it is, who has castling rights etc."""
        # This might be quite slow but I want to extract as much stuff as I can as potential future modelling features.
        raise NotImplementedError()
        
        
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

#     @property
#     def lichess_move_frequencies(self):
#         if self.lichess_stats is None:
#             return None
#         return {move["uci"]: (move["white"] + move["black"] + move["draws"]) / self.lichess_game_count
#                 for move in self.lichess_stats["moves"]}
#     
#     @property
#     def lichess_master_move_frequencies(self):
#         if self.lichess_master_stats is None:
#             return None
#         return {move["uci"]: (move["white"] + move["black"] + move["draws"]) / self.lichess_master_game_count
#                 for move in self.lichess_master_stats["moves"]}
#     
#     @property
#     def lichess_master_white_evaluation_historic(self):
#         if self.lichess_master_game_count == 0:
#             return 0.5
#         return (self.lichess_master_stats["white"] + self.lichess_master_stats["draws"] / 2) / self.lichess_master_game_count
#     
#     @property
#     def lichess_master_game_count(self):
#         if self.lichess_master_stats is None:
#             return 0
#         return self.lichess_master_stats["white"] + self.lichess_master_stats["black"] + self.lichess_master_stats["draws"]
# 
#     @property
#     def lichess_white_evaluation_historic(self):
#         if self.lichess_game_count == 0:
#             return 0.5
#         return (self.lichess_stats["white"] + self.lichess_stats["draws"] / 2) / self.lichess_game_count
#     
#     @property
#     def lichess_game_count(self):
#         if self.lichess_stats is None:
#             return 0
#         return (self.lichess_stats["white"] + self.lichess_stats["black"] + self.lichess_stats["draws"])

# 
# # Parts of zPosition that haven't been implemented yet:
# from __future__ import annotations
# from typing import List, Optional, Dict, List, Tuple
# import chess
# import chess.engine
# import chess.pgn
# import json
# import pathlib
# import logging
# import requests
# import time
# from datetime import datetime
# import pandas as pd
# import globals
# from globals import username
# 
# 
# logging.basicConfig(level=logging.INFO)
# 
# 
# class zPosition:
#     def __init__(self, parents=None, children=None, comment=None, fen: str = chess.STARTING_FEN):
#         self.parents = parents
#         self.children = children
# 
#         self._cached_lichess_stats = None
#         self._cached_lichess_master_stats = None
#         self._cached_lichess_engine_evaluation = None
#     
#     @property
#     def lichess_engine_evaluation(self):
#         if self._cached_lichess_engine_evaluation is None:
#             self._cached_lichess_engine_evaluation = self.call_lichess_api_engine()
#             if self._cached_lichess_engine_evaluation is not None:
#                 self.save()
#                 logging.info(f"Cached lichess engine evaluation for FEN: {self.fen}")
#         
#         if self._cached_lichess_engine_evaluation is not None:
#             if "error" in self._cached_lichess_engine_evaluation.keys():
#                 return None
#         
#         return self._cached_lichess_engine_evaluation
# 
#     @property
#     def board(self):
#         if self._board is None:
#             self._board = chess.Board(fen=self.fen)
#         return self._board
#     
#     def engine_multidepth_evaluations(self, engine, depths = [1, 2, 3, 4, 5, 10, 15, 20]) -> Dict[List[str, float]]:
#         """
#         (Intended to help calculate sharpness of the position).
#         In the returned dict, the key is the depth evaluated to and the value is [best_move, evaluation].
#         So: 
#         - You can check if the best move at 2 ply matches that of 20 ply to see how obvious the best move is.
#         - When the moves differ, you can tell how important the distinction is by comparing the evaluations.
#         - You can evaluate the sharpness of both your own positions and the enemy position as potential targets.
#         """
#         if self._cached_engine_multidepth_evaluations is None:
#             self._cached_engine_multidepth_evaluations = dict()
# 
#         for this_depth in depths:
#             if this_depth not in self._cached_engine_multidepth_evaluations.keys():
#                 this_eval = engine.analyse(self.board, chess.engine.Limit(depth=this_depth), multipv=1)
#                 if "pv" in this_eval[0].keys():
#                     this_best_move = this_eval[0]["pv"][0].uci()
#                 else:
#                     this_best_move = "NO_MOVE"
# 
#                 self._cached_engine_multidepth_evaluations[this_depth] = [this_best_move, this_eval[0]["score"].white().wdl(model="lichess").expectation()]
#                 self.save()
#                 logging.info(f"Saved new engine multidepth evaluation of FEN: {self.fen}. Eval: {self._cached_engine_multidepth_evaluations[this_depth]}")
# 
#         return {k: self._cached_engine_multidepth_evaluations[k] for k in depths}
#     
#     def stockfish_evaluation(self, engine: chess.engine.SimpleEngine, depth=35, multipv=1):
# 
#         # Check the game isn't over already cos engines bug out if so
#         if self.board.outcome() is not None:
#             if self.board.outcome().winner is None:
#                 return 0.5  # Draw
#             return self.board.outcome().winner  # 1 for white and 0 for black
# 
#         cloud_eval = self.lichess_engine_evaluation
#         if cloud_eval is not None:
#             if cloud_eval["depth"] >= max(depth, self.engine_evaluation_depth):
#                 if "cp" in cloud_eval["pvs"][0].keys():
#                     return chess.engine.Cp(cloud_eval["pvs"][0]["cp"]).wdl(model="lichess").expectation()
# 
#         if (self.engine_evaluation_depth < depth) or (self._cached_engine_evaluation is None):
#             engine_eval = engine.analyse(self.board, chess.engine.Limit(depth=depth), multipv=multipv)
#             engine_eval[0]["score"] = engine_eval[0]["score"].white().wdl(model="lichess").expectation()  # Converting to json friendly format
#             if "pv" in engine_eval[0].keys():
#                 engine_eval[0]["pv"] = [i.uci() for i in engine_eval[0]["pv"]]  # Converting to json friendly format
#             if "currmove" in engine_eval[0].keys():
#                 engine_eval[0]["currmove"] = engine_eval[0]["currmove"].uci()
#             self._cached_engine_evaluation = engine_eval
#             self.save()
#             stockfish_eval = engine_eval[0]["score"]
#             logging.info(f"Saved new stockfish evaluation of FEN: {self.fen}. Eval: {stockfish_eval}")
#             logging.debug(f"Full evaluation: {self._cached_engine_evaluation}")
# 
#         return self._cached_engine_evaluation[0]["score"]
#     
#     def leela_evaluation(self, engine: chess.engine.SimpleEngine, nodes=10_000, multipv=1):#
# 
#         if self.board.outcome() is not None:
#             if self.board.outcome().winner is None:
#                 return 0.5  # Draw
#             return self.board.outcome().winner  # 1 for white and 0 for black
# 
#         if self.leela_evaluation_nodes < nodes:
#             leela_eval = engine.analyse(self.board, chess.engine.Limit(nodes=nodes), multipv=multipv)
#             leela_eval[0]["score"] = leela_eval[0]["score"].white().wdl(model="lichess").expectation()  # Converting to json friendly format
#             if "pv" in leela_eval[0].keys():
#                 leela_eval[0]["pv"] = [i.uci() for i in leela_eval[0]["pv"]]  # Converting to json friendly format
#             if "currmove" in leela_eval[0].keys():
#                 leela_eval[0]["currmove"] = leela_eval[0]["currmove"].uci()
#             if "nodes" in leela_eval[0].keys():
#                 leela_eval[0]["returned_nodes"] = leela_eval[0]["nodes"]
#                 leela_eval[0]["nodes"] = nodes  # Not sure why leela often seems to do less than requested but no point requesting the same again
#             self._cached_leela_evaluation = leela_eval
#             self.save()
#             leela_eval = leela_eval[0]["score"]
#             logging.info(f"Saved new leela evaluation of FEN: {self.fen}. Eval: {leela_eval}")
#             logging.debug(f"Full evaluation: {self._cached_leela_evaluation}")
#         
#         return self._cached_leela_evaluation[0]["score"]
#     
#     def best_engine_move(self, engine, depth=35) -> chess.Move:
#         """Returns the UCI move recommended by the engine."""
#         if self.board.is_game_over():
#             raise ValueError(f"Can't find best move when is_game_over() True for FEN: {self.fen}")
#         
#         self.stockfish_evaluation(engine=engine, depth=depth)
#         cloud_eval = self.lichess_engine_evaluation
#         if cloud_eval is not None:
#             if cloud_eval["depth"] >= max(depth, self.engine_evaluation_depth):
#                 return chess.Move.from_uci(cloud_eval["pvs"][0]["moves"].split(" ")[0])
#         return chess.Move.from_uci(self._cached_engine_evaluation[0]["pv"][0])
#         
#     def call_lichess_api_engine(self):
#         if globals.engine_rate_limit:
#             return None
#         
#         url = "https://lichess.org/api/cloud-eval?"
#         url += f"fen={self.fen}"
#         logging.debug(f"Downloading lichess engine evaluation for FEN: {self.fen}")
# 
#         r = requests.get(url)
#         time.sleep(0.5)
#         if r.status_code == 429:
#             logging.info(f"Hit Lichess API engine rate limit, not making any more api calls... (And waiting to avoid re-run oopsies)")
#             time.sleep(60)
#             globals.engine_rate_limit = True
#             return None
#         else:
#             response = r.json()
# 
#         return response
# 
#     def create_engine_opening_training(self, engine, side=chess.WHITE, min_depth=35, min_likelihood=0.1):
#         """
#         Pure engine move responses to common moves.
#         :param side: Which side to find the optimum moves for. The resulting repertoire will include all common moves from the other side.
#         :param min_depth: The minimum analysis depth for the given engine move.
#         :param min_likelihood: The minimum likelihood of observing a given variation for it to be included. 0.01 means at least once in 100 games according to lichess stats.
#         :param current_likelihood: The current likelihood of observing the variation up until this position. Do not set this manually.
#         """
# 
#         game = chess.pgn.Game.from_board(self.board)
#         total_progress = 0
#         
#         def iterate_game(game_node: chess.pgn.GameNode, total_progress, current_likelihood=1):
#             this_fen = game_node.board().fen()
#             this_position = zPosition(fen=this_fen)
#             if game_node.turn() == side:
#                 # Use the engine best move
#                 logging.info(f"Appending best engine move after FEN: {this_fen} - {game_node.board().san(this_position.best_engine_move(engine=engine, depth=min_depth))}")
#                 comment=f"Engine move. EE: {this_position.engine_evaluation(engine=engine, depth=min_depth, leela_nodes=leela_nodes)}. D: {this_position.engine_evaluation_depth}. N: {this_position.engine_evaluation_nodes}. F: {current_likelihood}."
#                 next_node = game_node.add_variation(this_position.best_engine_move(engine=engine, depth=min_depth),
#                                                     comment=comment)
#                 total_progress = iterate_game(next_node, total_progress=total_progress, current_likelihood=current_likelihood)
#             else:
#                 has_subvariations = False
#                 for move, frequency in this_position.lichess_move_frequencies.items():
#                     total_frequency = frequency * current_likelihood
#                     if total_frequency >= min_likelihood:
#                         has_subvariations = True
#                         logging.info(f"Appending common enough response ({total_frequency}) after FEN: {this_fen} - {move}")
#                         comment=f"Common response. LE: {this_position.lichess_white_evaluation_historic}. LN: {this_position.lichess_game_count}. F: {total_frequency}."
#                         next_node = game_node.add_variation(chess.Move.from_uci(move))
#                         total_progress = iterate_game(next_node, total_progress=total_progress, current_likelihood=total_frequency)
#                 if not has_subvariations:
#                     total_progress += current_likelihood
#                 else:
#                     logging.info(f"Total progress: {total_progress*100}%")
# 
#             return total_progress
# 
#         iterate_game(game, total_progress=total_progress)
#         return game
#     
#     def probabilistic_engine_evaluation(self, 
#                                         engines, 
#                                         side=chess.WHITE, 
#                                         min_depth=20, 
#                                         min_likelihood=0.01, 
#                                         starting_likelihood=1, 
#                                         min_games=200, 
#                                         leela_nodes=10_000,
#                                         effect_cap=0.01,
#                                         master_only: bool = True):
#         """
#         Expected value of engine evaluation when played against human move probabilities in resulting positions.
#         Any subsequent position at least min_likelihood will be included specifically, less frequent positions will be assumed to have the overall evaluation
#         :param side: Which side to find the optimum moves for. The resulting repertoire will include all common moves from the other side.
#         :param min_depth: The minimum analysis depth for the given engine move.
#         :param min_likelihood: The minimum likelihood of observing a given variation for it to be included. 0.01 means at least once in 100 games according to lichess stats.
#         :param current_likelihood: The current likelihood of observing the variation up until this position. Do not set this manually.
#         """
# 
#         game = chess.pgn.Game.from_board(self.board)
#         
#         def iteratable_evaluation(game_node: chess.pgn.GameNode, current_likelihood=1):
#             this_fen = game_node.board().fen()
#             this_position = zPosition(fen=this_fen)
# 
#             # logging.info(f"Iterable processing fen: {this_fen}")
# 
#             if game_node.turn() == side:
#                 # Use the engine best move
#                 next_node = game_node.add_variation(this_position.best_engine_move(engine=engines["stockfish"], depth=min_depth))
#                 return iteratable_evaluation(next_node, current_likelihood=current_likelihood)
# 
#             base_eval = this_position.engine_evaluation(engines=engines, depth=min_depth, leela_nodes=leela_nodes)
# 
#             if master_only:
#                 this_position_games = this_position.lichess_master_game_count
#                 this_position_frequencies = this_position.lichess_master_move_frequencies
#             else:
#                 this_position_games = this_position.lichess_master_game_count + this_position.lichess_game_count
#                 this_position_frequencies = this_position.lichess_move_frequencies
# 
#             if (this_position_games < min_games) or (this_position_frequencies is None):
#                 return base_eval
# 
#             subvariations_accounted_for = 0  # frequency allocation so infrequent children can just be guessed
#             expected_eval = 0
#             for move, frequency in this_position_frequencies.items():
#                 this_frequency = frequency * current_likelihood
#                 if (this_frequency >= min_likelihood) and (this_position_games * frequency >= min_games):
#                     next_node = game_node.add_variation(chess.Move.from_uci(move))
#                     expected_eval += iteratable_evaluation(next_node, current_likelihood=this_frequency) * frequency
#                     subvariations_accounted_for += frequency
#             
#             expected_eval += (1 - subvariations_accounted_for) * base_eval
# 
#             expected_eval = max(expected_eval, base_eval - effect_cap)
#             expected_eval = min(expected_eval, base_eval + effect_cap)
# 
#             return expected_eval
# 
#         return iteratable_evaluation(game, current_likelihood=starting_likelihood)
# 
#     def children_min_engine_depth(self) -> int:
#         """The minimum engine depth child nodes have already been evaluated to."""
#         # Helpful to do some lazy evaluation sometimes
#         legal_moves = self.legal_moves
#         candidates_positions = {move: self.position_from_move(move.uci()) for move in legal_moves}
#         if len(candidates_positions) == 0:
#             return 0
#         evaluated_depths = [i.engine_evaluation_depth for i in candidates_positions.values()]
#         return min(evaluated_depths)
#             
# 
#     def sharpness(self,
#                   engines=None,
#                   heuristic="null_model_loss",
#                   min_depth=25):
#         """
#         Estimate the sharpness of the position.
# 
#         heuristic=null_model_loss - Sharpness is defined as the average engine evaluation loss when playing a random move rather than the best move.
#         So for example:
#         - A position with one guaranteed winning move while all others are guaranteed losing has a sharpness of ~1 (which then gets inv logit'd)
#         - A position where all moves are exactly the same has a sharpness of 0
# 
#         heuristic=evaluation_depth_analysis - Sharpness is defined as the variability of the engine evaluation as depth increases.
#         So for example:
#         - A position where the max evaluation difference goes from certain loss to certain victory has a sharpness of ~1 (which then gets inv logit'd)
#         - A position where the evaluation at all depths is to do the exact same move has a sharpness of 0
#         (I think this definition is a bit better than null_model_loss, and is also much easier to calculate!)
#         """
#         if heuristic == "null_model_loss":
#             legal_moves = self.legal_moves
#             candidates_positions = {move: self.position_from_move(move.uci()) for move in legal_moves}
#             candidates_evaluations = {move: candidates_positions[move].engine_evaluation(engine=engines["stockfish"], depth=min_depth) for move in legal_moves}
#             if self.turn == chess.BLACK:
#                 # Best move is the lowest evaluated
#                 candidates_evaluations = {move: -evaluation for move, evaluation in candidates_evaluations.items()}
#             best_eval = max(candidates_evaluations.values())
#             average_eval = sum(candidates_evaluations.values()) / len(candidates_evaluations)
#             proportional_sharpness = best_eval - average_eval
#             return proportional_sharpness / (1 - proportional_sharpness)
#         elif heuristic == "evaluation_depth_analysis":
#             depths = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15]
# 
#             evaluations = self.engine_multidepth_evaluations(engine=engines["stockfish"], depths=depths)
# 
#             if self.engine_evaluation_depth > 15:  # Even more accurate 'best' evaluation easily available
#                 best_eval = [self.best_engine_move(engine=engines["stockfish"], depth=self.engine_evaluation_depth), self.stockfish_evaluation(engine=engines["stockfish"], depth=self.engine_evaluation_depth)]
#             else:
#                 best_eval = evaluations[max(depths)]
#                 del evaluations[max(depths)]
# 
#             def one_sharpness(this_evaluation):
#                 if this_evaluation[0] != best_eval[0]:
#                     return abs(this_evaluation[1] - best_eval[1])
#                 return 0
# 
#             sharpnesses = [one_sharpness(i) for k, i in evaluations.items() if k <= 10 and k > 3]
#             return max(sharpnesses) / (1 - max(sharpnesses))
#         else:
#             raise ValueError(f"Unknown heuristic {heuristic}")
#         
#     def recursive_lichess_stats(self, 
#                                 side, 
#                                 move_selection_function, 
#                                 master: bool, 
#                                 current_frequency, 
#                                 min_frequency,
#                                 min_games,
#                                 effect_cap: float):
#         """
#         Helper for applying recursive evaluation functions.
#         """
#         if master:
#             base_eval = self.lichess_master_white_evaluation_historic
#             game_count = self.lichess_master_game_count
#             move_frequencies = self.lichess_master_move_frequencies
#         else:
#             base_eval = self.lichess_white_evaluation_historic
#             game_count = self.lichess_game_count
#             move_frequencies = self.lichess_move_frequencies
# 
#         if self.board.turn == side:
#             # Use the engine best move
#             next_node = self.position_from_move(move_selection_function(self, current_frequency))
#             return next_node.recursive_lichess_stats(side=side, 
#                                                      move_selection_function=move_selection_function, 
#                                                      master=master,
#                                                      current_frequency=current_frequency,
#                                                      min_frequency=min_frequency,
#                                                      min_games=min_games,
#                                                      effect_cap=effect_cap)
# 
#         if (current_frequency < min_frequency) or (game_count < min_games) or (move_frequencies is None):
#             return base_eval
# 
#         subvariations_accounted_for = 0  # frequency allocation so infrequent children can just be guessed
#         expected_eval = 0
#         for move, frequency in move_frequencies.items():
#             this_frequency = frequency * current_frequency
#             if (this_frequency >= min_frequency) and (game_count * frequency >= min_games):
#                 next_node = self.position_from_move(move)
#                 expected_eval += next_node.recursive_lichess_stats(side=side, 
#                                                                    move_selection_function=move_selection_function, 
#                                                                    master=master,
#                                                                    current_frequency=this_frequency,
#                                                                    min_frequency=min_frequency,
#                                                                    min_games=min_games,
#                                                                    effect_cap=effect_cap) * frequency
#                 subvariations_accounted_for += frequency
#         
#         expected_eval += (1 - subvariations_accounted_for) * base_eval
# 
#         expected_eval = max(expected_eval, base_eval - effect_cap)
#         expected_eval = min(expected_eval, base_eval + effect_cap)
# 
#         return expected_eval
#         
#     def holistic_best_move(self,
#                            engines,
#                            min_depth=35,
#                            leela_nodes=10_000,
#                            engine_node_weight=0.01,
#                            lichess_master_game_weight=1,
#                            lichess_game_weight=0,
#                            min_probabilistic_eval_likelihood=0.1,
#                            current_likelihood=1,
#                            min_weight=30,
#                            debug_positions=None,
#                            probabilistic_effect_cap=0.01,
#                            engine_weight_capcollar=((30, (1.0, 1.0)), (100, (0.95, 0.99)), (500, (0.97, 0.99)), (1_000, (0.9, 0.95)), (10_000, (0.8, 0.9)), (100_000, (0.75, 0.8)))) -> Dict:
#         """
#         Combines Stockfish, Leela, Master Stats & Amateur Stats to find an overall best move.
#         """
# 
#         def move_selection_function_for_recursion(y: zPosition, likelihood: float):
#             return y.holistic_best_move(engines=engines,
#                                         min_depth=min_depth,
#                                         leela_nodes=leela_nodes,
#                                         engine_node_weight=engine_node_weight,
#                                         lichess_master_game_weight=lichess_master_game_weight,
#                                         lichess_game_weight=lichess_game_weight,
#                                         min_probabilistic_eval_likelihood=min_probabilistic_eval_likelihood,
#                                         current_likelihood=likelihood,
#                                         min_weight=min_weight,
#                                         debug_positions=debug_positions,
#                                         engine_weight_capcollar=engine_weight_capcollar,
#                                         probabilistic_effect_cap=probabilistic_effect_cap)["move"]
# 
#         side = self.board.turn
# 
#         # Loop through each possible move and evaluate it with engine & lichess stats
#         # Note: pv never really needs to be >1 with this system, just evaluate on each child node instead
#         best_move_so_far = None
#         best_move_evaluation = None
#         
#         ######################if (self.lichess_master_game_count * lichess_master_game_weight) + (self.lichess_game_count * lichess_game_weight) <= 30:
# 
#         # Have to evaluate all positions properly and then adjust each evaluation to a 'loss from best' basis
#         candidates_moves = self.board.legal_moves
#         candidates_moves_uci = {move: move.uci() for move in candidates_moves}
#         candidates_positions = {move: self.position_from_move(candidates_moves_uci[move]) for move in candidates_moves}
#         
#         if engine_node_weight != 0:
#             candidates_engine_evaluations = {move: candidates_positions[move].engine_evaluation(engines=engines, depth=min_depth, leela_nodes=leela_nodes) for move in candidates_moves}  # Could be min_depth -1 but this will probably save processing in long run
#             candidates_probabilistic_evals = {move: candidates_positions[move].probabilistic_engine_evaluation(engines=engines, side=side, min_likelihood=min_probabilistic_eval_likelihood, starting_likelihood=current_likelihood, leela_nodes=leela_nodes, min_depth=min_depth, effect_cap=probabilistic_effect_cap) for move in candidates_moves}
#             candidates_gross_engine_weights = {move: candidates_positions[move].engine_evaluation_nodes * engine_node_weight for move in candidates_moves}
#             
#             # The engine evaluation delta is measured against the top move, the others against the weighted average. This is to try to avoid outliers in the other two. Min depth guards against engine outliers.
#             # engine_evaluation_weighted_average = sum({move: candidates_engine_evaluations[move] * candidates_gross_engine_weights[move] for move in candidates_moves}.values()) / sum(candidates_gross_engine_weights.values())
#             if side == chess.WHITE:
#                 engine_evaluation_best = max(candidates_engine_evaluations.values())
#                 engine_evaluation_best_prob = max(candidates_probabilistic_evals.values())
#             else:
#                 engine_evaluation_best = min(candidates_engine_evaluations.values())
#                 engine_evaluation_best_prob = min(candidates_probabilistic_evals.values())
#             candidates_engine_evaluations_delta = {move: candidates_engine_evaluations[move] - engine_evaluation_best for move in candidates_moves}
#             candidates_engine_evaluations_probabilistic_delta = {move: candidates_probabilistic_evals[move] - engine_evaluation_best_prob for move in candidates_moves}
#             # candidates_engine_evaluations_delta = {move: candidates_engine_evaluations[move] - engine_evaluation_weighted_average for move in candidates_moves}
#         else:
#             candidates_engine_evaluations = {move: 0 for move in candidates_moves}
#             candidates_engine_evaluations_delta = {move: 0 for move in candidates_moves}
#             candidates_engine_evaluations_probabilistic_delta = {move: 0 for move in candidates_moves}
#         
#         if (lichess_game_weight != 0) and (self.lichess_game_count * lichess_game_weight >= min_weight):
#             candidates_lichess_evaluations = {move: candidates_positions[move].lichess_white_evaluation_historic for move in candidates_moves}
#             # candidates_lichess_evaluations_recursive = {move: candidates_positions[move].recursive_lichess_stats(side=side,
#             #                                                                                                      move_selection_function=move_selection_function_for_recursion,
#             #                                                                                                      master=False,
#             #                                                                                                      current_frequency=current_likelihood,
#             #                                                                                                      min_frequency=min_probabilistic_eval_likelihood,
#             #                                                                                                      min_games=min_weight / lichess_game_weight,
#             #                                                                                                      effect_cap=1.5) for move in candidates_moves}
#             candidates_gross_lichess_weights = {move: candidates_positions[move].lichess_game_count * lichess_game_weight for move in candidates_moves}
#             sum_gross_lichess_weight = sum(candidates_gross_lichess_weights.values())
#             if sum_gross_lichess_weight != 0:
#                 lichess_evaluation_weighted_average = sum({move: candidates_lichess_evaluations[move] * candidates_gross_lichess_weights[move] for move in candidates_moves}.values()) / sum_gross_lichess_weight
#                 # lichess_evaluation_weighted_average_rec = sum({move: candidates_lichess_evaluations_recursive[move] * candidates_gross_lichess_weights[move] for move in candidates_moves}.values()) / sum_gross_lichess_weight
#             else:
#                 lichess_evaluation_weighted_average = 0.5
#                 # candidates_lichess_evaluations_recursive = 0.5
#             candidates_lichess_evaluations_deltas = {move: candidates_lichess_evaluations[move] - lichess_evaluation_weighted_average for move in candidates_moves}
#             # candidates_lichess_evaluations_recursive_deltas = {move: candidates_lichess_evaluations_recursive[move] - lichess_evaluation_weighted_average_rec for move in candidates_moves}
#         else:
#             candidates_lichess_evaluations = {move: 0 for move in candidates_moves}
#             candidates_gross_lichess_weights = {move: 0 for move in candidates_moves}
#             candidates_lichess_evaluations_deltas = {move: 0 for move in candidates_moves}
#             # candidates_lichess_evaluations_recursive_deltas = {move: 0 for move in candidates_moves}
#         
#         if (lichess_master_game_weight != 0) and (self.lichess_master_game_count * lichess_master_game_weight >= min_weight):
#             candidates_lichess_master_evaluations = {move: candidates_positions[move].lichess_master_white_evaluation_historic for move in candidates_moves}
#             # candidates_lichess_master_evaluations_recursive = {move: candidates_positions[move].recursive_lichess_stats(side=side,
#             #                                                                                                             move_selection_function=move_selection_function_for_recursion,
#             #                                                                                                             master=True,
#             #                                                                                                             current_frequency=current_likelihood,
#             #                                                                                                             min_frequency=min_probabilistic_eval_likelihood,
#             #                                                                                                             min_games=min_weight / lichess_master_game_weight,
#             #                                                                                                             effect_cap=1.5) for move in candidates_moves}
#             candidates_gross_lichess_master_weights = {move: candidates_positions[move].lichess_master_game_count * lichess_master_game_weight for move in candidates_moves}
#             sum_gross_master_weight = sum(candidates_gross_lichess_master_weights.values())
#             if sum_gross_master_weight != 0:
#                 lichess_master_evaluation_weighted_average = sum({move: candidates_lichess_master_evaluations[move] * candidates_gross_lichess_master_weights[move] for move in candidates_moves}.values()) / sum_gross_master_weight
#                 # lichess_master_evaluation_weighted_average_rec = sum({move: candidates_lichess_master_evaluations_recursive[move] * candidates_gross_lichess_master_weights[move] for move in candidates_moves}.values()) / sum_gross_master_weight
#             else:
#                 lichess_master_evaluation_weighted_average = 0.5
#                 # lichess_master_evaluation_weighted_average_rec = 0.5
#             candidates_lichess_master_evaluations_deltas = {move: candidates_lichess_master_evaluations[move] - lichess_master_evaluation_weighted_average for move in candidates_moves}
#             # candidates_lichess_master_evaluations_recursive_deltas = {move: candidates_lichess_master_evaluations_recursive[move] - lichess_master_evaluation_weighted_average_rec for move in candidates_moves}
#         else:
#             candidates_lichess_master_evaluations = {move: 0 for move in candidates_moves}
#             candidates_gross_lichess_master_weights = {move: 0 for move in candidates_moves}
#             candidates_lichess_master_evaluations_deltas = {move: 0 for move in candidates_moves}
#             # candidates_lichess_master_evaluations_recursive_deltas = {move: 0 for move in candidates_moves}
#         
#         candidates_gross_total_weights = {move: candidates_gross_engine_weights[move] + candidates_gross_lichess_weights[move] + candidates_gross_lichess_master_weights[move] for move in candidates_moves}
#         candidates_gross_all_lichess_weights = {move: candidates_gross_lichess_weights[move] + candidates_gross_lichess_master_weights[move] for move in candidates_moves}
# 
#         candidates_initial_weights = dict()
#         candidates_final_weights = dict()
#         candidates_final_evaluations = dict()
#         for candidate_move in candidates_moves:
#             for lower_weights, upper_weights in zip(engine_weight_capcollar[:-1], engine_weight_capcollar[1:]):
#                 if candidates_gross_all_lichess_weights[candidate_move] < upper_weights[0]:
#                     this_bounded_game_count = max(candidates_gross_all_lichess_weights[candidate_move], lower_weights[0])
#                     game_count_weight_point = (this_bounded_game_count - lower_weights[0]) / (upper_weights[0] - lower_weights[0])
#                     this_cap = upper_weights[1][1] * game_count_weight_point + lower_weights[1][1] * (1 - game_count_weight_point)
#                     this_collar = upper_weights[1][0] * game_count_weight_point + lower_weights[1][0] * (1 - game_count_weight_point)
#                     break
#             else:
#                 # Above the highest band
#                 this_cap = engine_weight_capcollar[-1][1][1]
#                 this_collar = engine_weight_capcollar[-1][1][0]
#             
#             pre_capcol_engine_weight = candidates_gross_engine_weights[candidate_move] / candidates_gross_total_weights[candidate_move]
#             this_engine_weight = min(max(pre_capcol_engine_weight, this_collar), this_cap)
#             if pre_capcol_engine_weight != 1:
#                 non_engine_capcol_multiplier = (1 - this_engine_weight) / (1 - pre_capcol_engine_weight)
#             else:
#                 non_engine_capcol_multiplier = 0
#             
#             this_lichess_weight = candidates_gross_lichess_weights[candidate_move] * non_engine_capcol_multiplier / candidates_gross_total_weights[candidate_move]
#             this_lichess_master_weight = candidates_gross_lichess_master_weights[candidate_move] * non_engine_capcol_multiplier / candidates_gross_total_weights[candidate_move]
# 
#             candidate_weighted_evaluation = (candidates_engine_evaluations_probabilistic_delta[candidate_move] * this_engine_weight) + (candidates_lichess_evaluations_deltas[candidate_move] * this_lichess_weight) + (candidates_lichess_master_evaluations_deltas[candidate_move] * this_lichess_master_weight)
#             candidates_final_evaluations[candidate_move] = candidate_weighted_evaluation
#             candidates_initial_weights[candidate_move] = f"(Engine {pre_capcol_engine_weight:.2f})(Lichess {candidates_gross_lichess_weights[candidate_move] / candidates_gross_total_weights[candidate_move]:.2f})(Master {candidates_gross_lichess_master_weights[candidate_move] / candidates_gross_total_weights[candidate_move]:.2f})"
#             candidates_final_weights[candidate_move] = f"(Engine {this_engine_weight:.2f})(Lichess {this_lichess_weight:.2f})(Master {this_lichess_master_weight:.2f})"
# 
#             if best_move_evaluation is None:
#                 best_move_so_far = candidate_move
#                 best_move_evaluation = candidate_weighted_evaluation
#                 best_engine_weight = this_engine_weight
#                 best_lichess_weight = this_lichess_weight
#                 best_lichess_master_weight = this_lichess_master_weight
#                 continue
#             if side == chess.WHITE:
#                 if best_move_evaluation < candidate_weighted_evaluation:
#                     best_move_so_far = candidate_move
#                     best_move_evaluation = candidate_weighted_evaluation
#                     best_engine_weight = this_engine_weight
#                     best_lichess_weight = this_lichess_weight
#                     best_lichess_master_weight = this_lichess_master_weight
#             else:
#                 if best_move_evaluation > candidate_weighted_evaluation:
#                     best_move_so_far = candidate_move
#                     best_move_evaluation = candidate_weighted_evaluation
#                     best_engine_weight = this_engine_weight
#                     best_lichess_weight = this_lichess_weight
#                     best_lichess_master_weight = this_lichess_master_weight
#         
#         if best_move_so_far is not None:
#             if self.fen in debug_positions.keys():
#                 # Check out:
#                 # candidates_engine_evaluations_delta
#                 # candidates_lichess_evaluations_deltas
#                 # candidates_lichess_master_evaluations_deltas
#                 # candidates_final_evaluations
#                 # candidates_final_weights
#                 eval_frame = pd.concat([pd.Series(candidates_engine_evaluations_delta, name="engine"), 
#                                         pd.Series(candidates_engine_evaluations_probabilistic_delta, name="engine_probabilistic"),
#                                         pd.Series(candidates_lichess_evaluations_deltas, name="lichess"), 
#                                         # pd.Series(candidates_lichess_evaluations_recursive_deltas, name="lichess_recursive"),
#                                         pd.Series(candidates_lichess_master_evaluations_deltas, name="master"), 
#                                         # pd.Series(candidates_lichess_master_evaluations_recursive_deltas, name="master_recursive"),
#                                         pd.Series(candidates_final_evaluations, name="final"), 
#                                         pd.Series(candidates_gross_all_lichess_weights, name="lichess_total_weight"),
#                                         # pd.Series(candidates_initial_weights, name="initial_weights"),
#                                         pd.Series(candidates_final_weights, name="final_weights")], axis=1).sort_values(by="final")
#                 print(f"Debug position: {self.fen} ({debug_positions[self.fen]})")
#                 print(eval_frame)
#                 print("...")
#             
#         return {
#             "move": best_move_so_far,
#             "holistic_evaluation": best_move_evaluation,
#             "engine_evaluation_delta": candidates_engine_evaluations_delta[best_move_so_far],
#             "probabilistic_engine_evaluation_delta": candidates_engine_evaluations_probabilistic_delta[best_move_so_far],
#             "lichess_delta": candidates_lichess_evaluations_deltas[best_move_so_far],
#             # "lichess_recursive_delta": candidates_lichess_evaluations_recursive_deltas[best_move_so_far],
#             "master_delta": candidates_lichess_master_evaluations_deltas[best_move_so_far],
#             # "master_recursive_delta": candidates_lichess_master_evaluations_recursive_deltas[best_move_so_far],
#             "engine_weight": best_engine_weight,
#             "lichess_weight": best_lichess_weight,
#             "master_weight": best_lichess_master_weight
#         }
# 
#     def create_weighted_average_opening_training(self, 
#                                                  engines, 
#                                                  side=chess.WHITE, 
#                                                  min_depth=35, 
#                                                  leela_nodes=10_000,
#                                                  min_likelihood=0.1,
#                                                  min_probabilistic_eval_likelihood=0.1,
#                                                  sharpness_baseline=0.033,
#                                                  sharpness_frequency_override=0.99,
#                                                  min_games=30,
#                                                  engine_node_weight=0.01,
#                                                  lichess_game_weight=0,
#                                                  lichess_master_game_weight=1,
#                                                  debug_positions=dict(),
#                                                  min_illustrative_depth=5,
#                                                  probabilistic_effect_cap=0.01,
#                                                  engine_weight_capcollar=((30, (1.0, 1.0)), (100, (0.95, 0.99)), (500, (0.97, 0.99)), (1_000, (0.9, 0.95)), (10_000, (0.8, 0.9)), (100_000, (0.75, 0.8)))):
#         """
#         Our best move is a weighted average of the engine evaluation and the lichess historic evaluation, depending on how many games & nodes on each side.
#         :param side: Which side to find the optimum moves for. The resulting repertoire will include all common moves from the other side.
#         :param min_depth: The minimum analysis depth for the given engine move.
#         :param min_likelihood: The minimum likelihood of observing a given variation for it to be included. 0.01 means at least once in 100 games according to lichess stats.
#         :param current_likelihood: The current likelihood of observing the variation up until this position. Do not set this manually.
#         :param engine_node_weight: The weight assigned to the engine evaluation for each node scanned
#         :param lichess_game_weight: The weight assigned to the lichess evaluation for each historic lichess game
#         :param lichess_master_game_weight: The weight assigned to the lichess master evaluation for each historic lichess master game
#         :param engine_weight_capcollar: The minimum and maximum weight given to the engine prediction compared to the lichess evaluation at different amounts of lichess game totals. Linear interp between them.
#         :param min_games: The minimum number of games to trust lichess move chance %
#         :param sharpness_baseline: Sharpness is approximately (for null model heuristic) ~0.178 for a closed opening like the English, and ~0.221 for the sicilian defence
#             Sharper positions will be explored more thoroughly, proportional to the overall sharpness of the line.
#         :param sharpness_frequency_override: If a position is at least as sharp as this (ignoring baseline), then it will be explored almost regardless of how frequently the position arises
#         """
# 
#         game = chess.pgn.Game.from_board(self.board)
#         total_progress = 0
#         
#         def iterate_game(game_node: chess.pgn.GameNode, 
#                          total_progress, 
#                          current_likelihood=1, 
#                          min_depth=15, 
#                          current_depth=1,
#                          current_illustrative_depth=0) -> float:
#             """Returns current progress"""
#             initial_progress = total_progress
# 
#             this_fen = game_node.board().fen()
#             this_position = zPosition(fen=this_fen)
# 
#             if this_fen in debug_positions.keys():
#                 print("Debug pos")
#                 test_eval = this_position.engine_evaluation(engines=engines, depth=min_depth, leela_nodes=leela_nodes)
# 
#             if game_node.turn() == side:
#                 # Loop through each possible move and evaluate it with engine & lichess stats
#                 # Note: pv never really needs to be >1 with this system, just evaluate on each child node instead
#                 best_move = this_position.holistic_best_move(
#                     engines=engines,
#                     min_depth=min_depth,
#                     leela_nodes=leela_nodes,
#                     engine_node_weight=engine_node_weight,
#                     lichess_master_game_weight=lichess_master_game_weight,
#                     lichess_game_weight=lichess_game_weight,
#                     min_probabilistic_eval_likelihood=min_probabilistic_eval_likelihood,
#                     current_likelihood=current_likelihood,
#                     min_weight=min_games,
#                     debug_positions=debug_positions,
#                     engine_weight_capcollar=engine_weight_capcollar,
#                     probabilistic_effect_cap=probabilistic_effect_cap)
#                 
#                 logging.info(f"Appending best holistic move after FEN: {this_fen} - {game_node.board().san(best_move['move'])}:")
#                 logging.info(f"- Sharpness {this_position.sharpness(engines=engines, min_depth=min_depth, heuristic='evaluation_depth_analysis'):.3f}")
# 
#                 comment=f"Holistic move:"
#                 comment += f"\nEngine Evaluation: {this_position.engine_evaluation(engines=engines, depth=min_depth, leela_nodes=leela_nodes):.3f}"
#                 comment += f"\nHolistic Evaluation: {best_move['holistic_evaluation']:.1f}"
#                 comment += f"\nDepth: {this_position.engine_evaluation_depth}"
#                 comment += f"\nNodes: {this_position.engine_evaluation_nodes}."
#                 comment += f"\nFrequency: {current_likelihood:.4f}"
#                 comment += f"\nEngine Evaluation Delta: {best_move['engine_evaluation_delta']}"
#                 comment += f"\nProbabilistic Engine Evaluation Delta: {best_move['probabilistic_engine_evaluation_delta']}"
#                 comment += f"\nLichess Delta: {best_move['lichess_delta']}"
#                 # comment += f"\nLichess Recursive Delta: {best_move['lichess_recursive_delta']}"
#                 comment += f"\nMaster Delta: {best_move['master_delta']}"
#                 # comment += f"\nMaster Recursive Delta: {best_move['master_recursive_delta']}"
#                 comment += f"\nEngine Weight: {best_move['engine_weight']}"
#                 comment += f"\nLichess Weight: {best_move['lichess_weight']}"
#                 comment += f"\nMaster Weight: {best_move['master_weight']}"
# 
#                 next_node = game_node.add_variation(best_move["move"],
#                                                     comment=comment)
#                 best_position = this_position.position_from_move(best_move["move"].uci())
#                 
#                 total_progress = iterate_game(next_node, 
#                                               total_progress=total_progress, 
#                                               current_likelihood=current_likelihood, 
#                                               current_depth=current_depth+1,
#                                               current_illustrative_depth=current_illustrative_depth)
#             else:
#                 # Figure out which enemy moves are worth including in training data
#                 # Typically because their frequency * sharpness is high enough
#                 has_subvariations = False
#                 if (this_position.lichess_game_count + this_position.lichess_master_game_count >= min_games) and (current_likelihood != 0) and (this_position.lichess_move_frequencies is not None):
#                     for move, frequency in this_position.lichess_move_frequencies.items():
#                         total_frequency = frequency * current_likelihood
#                         next_position = this_position.position_from_move(move)
#                         next_sharpness = next_position.sharpness(engines=engines, heuristic="evaluation_depth_analysis")
#                         total_priority = frequency * current_likelihood * max(1, next_sharpness / sharpness_baseline)
#                         
#                         frequent_enough = total_priority >= min_likelihood
#                         if frequent_enough:
#                             logging.info(f"Appending common enough response ({total_frequency*100:.2f}%) after FEN: {this_fen} - {game_node.board().san(chess.Move.from_uci(move))} - Sharpness: {next_sharpness} - Priority: {total_priority:.2f}")
#                             comment = "Common response. "
#                         else:
#                             frequent_enough = frequent_enough or (next_sharpness >= sharpness_frequency_override)
#                             if frequent_enough:
#                                 logging.info(f"Appending sharp line response due to override ({next_sharpness:.2f}S) after FEN: {this_fen} - {game_node.board().san(chess.Move.from_uci(move))} - Sharpness: {next_sharpness} - Priority: {total_priority:.2f}")
#                                 comment = "Sharp line. "
# 
#                         if frequent_enough:
#                             has_subvariations = True
#                             comment = comment + f"LE: {next_position.lichess_white_evaluation_historic*100:.1f}. LM: {next_position.lichess_master_white_evaluation_historic*100:.1f}. LN: {next_position.lichess_game_count}. F%: {total_frequency*100:.2f}."
#                             next_node = game_node.add_variation(chess.Move.from_uci(move), comment=comment)
#                             total_progress = iterate_game(next_node, 
#                                                           total_progress=total_progress, 
#                                                           current_likelihood=total_frequency, 
#                                                           current_depth=current_depth+1,
#                                                           current_illustrative_depth=0)
# 
#                 if not has_subvariations:
#                     total_progress += current_likelihood
# 
#                     # Add illustrative moves at the end! At the moment just one in each position
#                     if current_illustrative_depth < min_illustrative_depth:
#                         logging.info(f"Appending illustrative engine move after FEN: {this_fen} - {game_node.board().san(this_position.best_engine_move(engine=engines['stockfish'], depth=min_depth))}")
#                         comment=f"Illustrative engine move. EE: {this_position.engine_evaluation(engines=engines, depth=min_depth, leela_nodes=leela_nodes):.3f}. D: {this_position.engine_evaluation_depth}. N: {this_position.engine_evaluation_nodes}. F: {current_likelihood:.4f}."
#                         next_node = game_node.add_variation(this_position.best_engine_move(engine=engines["stockfish"], depth=min_depth),
#                                                             comment=comment)
#                         total_progress = iterate_game(next_node, 
#                                                       total_progress=total_progress, 
#                                                       current_likelihood=0, 
#                                                       current_depth=current_depth+1,
#                                                       current_illustrative_depth=current_illustrative_depth+1)
#                 else:
#                     total_progress = initial_progress + current_likelihood
#                     logging.info(f"Total progress: {total_progress*100}%")
# 
#             return total_progress
# 
#         iterate_game(game, total_progress=total_progress)
#         game.headers["Event"] = f"create_weighted_average_opening_training"
#         game.headers["Date"] = datetime.now().__str__()
#         if side == chess.WHITE:
#             game.headers["White"] = username
#         else:
#             game.headers["Black"] = username
# 
#         game.headers["min_depth"] = str(min_depth)
#         game.headers["min_likelihood"] = str(min_likelihood)
#         game.headers["min_games"] = str(min_games)
#         game.headers["engine_node_weight"] = str(engine_node_weight)
#         game.headers["lichess_game_weight"] = str(lichess_game_weight)
#         game.headers["lichess_master_game_weight"] = str(lichess_master_game_weight)
#         game.headers["engine_weight_capcollar"] = engine_weight_capcollar
# 
#         return game
# 
# if __name__ == "__main__":
#     import psutil
#     engines = {
#         "stockfish": chess.engine.SimpleEngine.popen_uci(r"C:\\Users\\REDACTED_USER\\PycharmProjects\\chess_analysis\\engines\\stockfish_15.1_win_x64_avx2\\stockfish-windows-2022-x86-64-avx2.exe"),
#         "leela": chess.engine.SimpleEngine.popen_uci(r"C:\\Users\\REDACTED_USER\\PycharmProjects\\chess_analysis\\engines\\lc0-v0.29.0-windows-gpu-nvidia-cuda\\lc0.exe")
#     }
#     threads: int = int(psutil.cpu_count(logical=True) - 3)  # almost all logical CPU cores
#     hash: int = int(psutil.virtual_memory().available / 1024 / 1024 * 0.3)  # 75% of available RAM
#     engines["stockfish"].configure({"Hash": hash})
#     engines["stockfish"].configure({"Threads": threads})
# 
#     a = zPosition()
#  
#     # Depth of 21 can hit lichess rate limit, 22 seems like the best 'quick' number
#     # Big time increase after 40
#     # 35 seems doable for smaller repertoires
#     MIN_DEPTH = 25
#     LEELA_NODES = 10_000
#     MIN_LIKELIHOOD = 0.04
#     MIN_PROBABILISTIC_EVALUATION_LIKELIHOOD = 0.01
#     PROBABILISTIC_EFFECT_CAP = 0.01
#     OUT_POSTFIX = "_repertoire"
#     MIN_ILLUSTRATIVE_DEPTH = 0
# 
#     # For weighted average repertoire
#     STOCKFISH_LEELA_WEIGHT=0.5
#     ENGINE_NODE_WEIGHT=0.000002
#     LICHESS_GAME_WEIGHT=0.001
#     MASTER_GAME_WEIGHT=1
#     DEBUG_POSITIONS = {chess.STARTING_FEN: "Starting position",
#                        "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2": "Sicilian",
#                        "rnbqkbnr/pp1p1ppp/4p3/8/3NP3/8/PPP2PPP/RNBQKB1R b KQkq - 0 4": "French Sicilian",
#                        "rnbqkb1r/pp2pppp/3p1n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R b KQkq - 2 5": "Open Sicilian decision point",  # 
#                        "rnbqkbnr/1p1p1ppp/p3p3/8/3NP3/2N5/PPP2PPP/R1BQKB1R b KQkq - 1 5": "Kan Sicilian",  # 
#     }
#     ENGINE_WEIGHT_CAPCOLLAR=((300, (1.0, 0.99)), (1_000, (0.98, 0.99)), (5_000, (0.95, 0.98)), (10_000, (0.70, 0.80)), (100_000, (0.5, 0.65)), (500_000, (0.4, 0.41)))
# 
#     black_repertoire = a.create_weighted_average_opening_training(engines=engines, 
#                                                                   side=chess.BLACK, 
#                                                                   min_depth=MIN_DEPTH, 
#                                                                   leela_nodes=LEELA_NODES,
#                                                                   min_likelihood=MIN_LIKELIHOOD,
#                                                                   min_probabilistic_eval_likelihood=MIN_PROBABILISTIC_EVALUATION_LIKELIHOOD,
#                                                                   engine_node_weight=ENGINE_NODE_WEIGHT,
#                                                                   lichess_game_weight=LICHESS_GAME_WEIGHT,
#                                                                   lichess_master_game_weight=MASTER_GAME_WEIGHT,
#                                                                   debug_positions=DEBUG_POSITIONS,
#                                                                   engine_weight_capcollar=ENGINE_WEIGHT_CAPCOLLAR,
#                                                                   min_illustrative_depth=MIN_ILLUSTRATIVE_DEPTH,
#                                                                   probabilistic_effect_cap=PROBABILISTIC_EFFECT_CAP)
#     print("Black repertoire:")
#     print(black_repertoire)
#     print(black_repertoire, file=open(f"black{OUT_POSTFIX}.pgn", "w"), end="\n\n")
# 
#     white_repertoire = a.create_weighted_average_opening_training(engines=engines, 
#                                                                   min_depth=MIN_DEPTH, 
#                                                                   leela_nodes=LEELA_NODES,
#                                                                   min_likelihood=MIN_LIKELIHOOD,
#                                                                   min_probabilistic_eval_likelihood=MIN_PROBABILISTIC_EVALUATION_LIKELIHOOD,
#                                                                   engine_node_weight=ENGINE_NODE_WEIGHT,
#                                                                   lichess_game_weight=LICHESS_GAME_WEIGHT,
#                                                                   lichess_master_game_weight=MASTER_GAME_WEIGHT,
#                                                                   debug_positions=DEBUG_POSITIONS,
#                                                                   engine_weight_capcollar=ENGINE_WEIGHT_CAPCOLLAR,
#                                                                   min_illustrative_depth=MIN_ILLUSTRATIVE_DEPTH,
#                                                                   probabilistic_effect_cap=PROBABILISTIC_EFFECT_CAP)
#     print("White repertoire:")
#     print(white_repertoire)
#     print(white_repertoire, file=open(f"white{OUT_POSTFIX}.pgn", "w"), end="\n\n")
# 
#     print("Finished.")
# 