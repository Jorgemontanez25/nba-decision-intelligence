"""Build a transient DuckDB portfolio snapshot from source-attributed game logs.

Source: https://huggingface.co/datasets/cbratkovics/nba-game-logs
Publisher labels packaging CC0 and describes non-commercial portfolio use;
underlying NBA rights are not independently cleared by this module.
This script creates no fabricated shot locations or lineup stints.
"""
from __future__ import annotations
import os
from pathlib import Path
import tempfile
import duckdb
from huggingface_hub import hf_hub_download

DATASET = 'cbratkovics/nba-game-logs'
SEASONS = ('2025-26', '2026-27')

SCHEMA = '''
CREATE TABLE team_games (
 game_id VARCHAR,team_id BIGINT,team_abbr VARCHAR,season VARCHAR,season_type VARCHAR,
 game_date DATE,matchup VARCHAR,points INTEGER,result VARCHAR,
 updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(game_id,team_id));
CREATE TABLE player_games (
 game_id VARCHAR,player_id BIGINT,player_name VARCHAR,team_id BIGINT,
 team_abbr VARCHAR,season VARCHAR,season_type VARCHAR,game_date DATE,
 minutes DOUBLE,points INTEGER,rebounds INTEGER,assists INTEGER,
 steals INTEGER,blocks INTEGER,turnovers INTEGER,fgm INTEGER,fga INTEGER,
 fg3m INTEGER,fg3a INTEGER,ftm INTEGER,fta INTEGER,plus_minus DOUBLE,
 starter BOOLEAN,updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(game_id,player_id));
CREATE TABLE shot_events (
 game_id VARCHAR, player_id BIGINT,season VARCHAR,season_type VARCHAR,
 team_id BIGINT,loc_x DOUBLE,loc_y DOUBLE,shot_distance DOUBLE,
 shot_made BOOLEAN,shot_type VARCHAR,action_type VARCHAR,period INTEGER,
 minutes_remaining INTEGER,seconds_remaining INTEGER,event_id BIGINT,
 updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(game_id,player_id,event_id));
CREATE TABLE collection_runs (game_id VARCHAR PRIMARY KEY,status VARCHAR,attempted_at TIMESTAMP,error VARCHAR);
CREATE TABLE lineup_stints (
 stint_id VARCHAR PRIMARY KEY, game_id VARCHAR,season VARCHAR,season_type VARCHAR,
 team_abbr VARCHAR,opponent_abbr VARCHAR,period INTEGER,start_sec DOUBLE,end_sec DOUBLE,
 duration_sec DOUBLE,points_for INTEGER,points_against INTEGER,
 possessions_for DOUBLE,possessions_against DOUBLE,lineup_key VARCHAR,
 opponent_lineup_key VARCHAR,source VARCHAR,validation_status VARCHAR);
CREATE TABLE lineup_stint_players (stint_id VARCHAR,side VARCHAR,player_id BIGINT);
'''


def build_portfolio_db(destination: str | Path, seasons=SEASONS) -> str:
    """Download only published player logs; rebuild a new database atomically."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    paths = []
    for season in seasons:
        paths.append(hf_hub_download(repo_id=DATASET,repo_type='dataset',filename=f'game_logs/game_logs_{season}.parquet'))
    fd, temporary = tempfile.mkstemp(prefix='nba_portfolio_', suffix='.duckdb', dir=str(destination.parent))
    os.close(fd)
    os.unlink(temporary)  # DuckDB must create the file itself.
    try:
        with duckdb.connect(temporary) as con:
            con.execute(SCHEMA)
            con.execute('CREATE TEMP TABLE incoming AS SELECT * FROM read_parquet(?)', [paths])
            # Keep games with both participating teams; no invented opponent statistics.
            con.execute('''CREATE TEMP TABLE valid_games AS
                SELECT CAST(game_id AS VARCHAR) game_id
                FROM incoming GROUP BY game_id HAVING COUNT(DISTINCT team)=2''')
            con.execute('''CREATE TEMP TABLE team_ids AS
                SELECT team, ROW_NUMBER() OVER(ORDER BY team) AS team_id
                FROM (SELECT DISTINCT team FROM incoming)''')
            con.execute('''INSERT INTO player_games
              (game_id,player_id,player_name,team_id,team_abbr,season,season_type,
               game_date,minutes,points,rebounds,assists,steals,blocks,turnovers,
               fgm,fga,fg3m,fg3a,ftm,fta,plus_minus,starter)
              SELECT CAST(i.game_id AS VARCHAR),CAST(i.player_id AS BIGINT),
                CAST(i.player_name AS VARCHAR),t.team_id,CAST(i.team AS VARCHAR),
                CAST(i.season AS VARCHAR),'Regular Season',CAST(i.game_date AS DATE),
                TRY_CAST(i.minutes AS DOUBLE),TRY_CAST(i.pts AS INTEGER),
                TRY_CAST(i.reb AS INTEGER),TRY_CAST(i.ast AS INTEGER),
                TRY_CAST(i.stl AS INTEGER),TRY_CAST(i.blk AS INTEGER),
                TRY_CAST(i.tov AS INTEGER),TRY_CAST(i.fgm AS INTEGER),
                TRY_CAST(i.fga AS INTEGER),TRY_CAST(i.fg3m AS INTEGER),
                TRY_CAST(i.fg3a AS INTEGER),TRY_CAST(i.ftm AS INTEGER),
                TRY_CAST(i.fta AS INTEGER),TRY_CAST(i.plus_minus AS DOUBLE),FALSE
              FROM incoming i JOIN valid_games v ON CAST(i.game_id AS VARCHAR)=v.game_id
              JOIN team_ids t ON i.team=t.team
              WHERE i.player_id IS NOT NULL AND i.game_id IS NOT NULL
              QUALIFY ROW_NUMBER() OVER(PARTITION BY i.player_id,i.game_id ORDER BY i.game_date DESC)=1''')
            con.execute('''CREATE TEMP TABLE teams_per_game AS
                 SELECT p.game_id,p.team_id,p.team_abbr,p.season,MAX(p.game_date) game_date,
                        SUM(p.points) points
                 FROM player_games p GROUP BY 1,2,3,4''')
            con.execute('''INSERT INTO team_games
               (game_id,team_id,team_abbr,season,season_type,game_date,matchup,points,result)
               SELECT a.game_id,a.team_id,a.team_abbr,a.season,'Regular Season',a.game_date,
                 a.team_abbr||' vs '||b.team_abbr,a.points,
                 CASE WHEN a.points>b.points THEN 'W' WHEN a.points<b.points THEN 'L' ELSE NULL END
               FROM teams_per_game a JOIN teams_per_game b
                 ON a.game_id=b.game_id AND a.team_abbr<>b.team_abbr''')
            count = con.execute('SELECT COUNT(*) FROM player_games').fetchone()[0]
            teams = con.execute('SELECT COUNT(*) FROM team_games').fetchone()[0]
            if count < 1000 or teams < 100:
                raise RuntimeError(f'Snapshot too small: player_games={count}, team_games={teams}')
            bad = con.execute('''SELECT COUNT(*) FROM
             (SELECT game_id FROM team_games GROUP BY game_id HAVING COUNT(*)<>2)''').fetchone()[0]
            if bad:
                raise RuntimeError(f'{bad} games lack exactly two teams')
            con.execute('CHECKPOINT')
        os.replace(temporary,destination)
        return str(destination)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
