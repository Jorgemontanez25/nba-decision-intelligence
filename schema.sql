CREATE TABLE IF NOT EXISTS team_games (
 game_id VARCHAR, team_id BIGINT, team_abbr VARCHAR, season VARCHAR, season_type VARCHAR,
 game_date DATE, matchup VARCHAR, points INTEGER, result VARCHAR,
 updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY (game_id, team_id)
);
CREATE TABLE IF NOT EXISTS player_games (
 game_id VARCHAR, player_id BIGINT, player_name VARCHAR, team_id BIGINT,
 team_abbr VARCHAR, season VARCHAR, season_type VARCHAR, game_date DATE,
 minutes DOUBLE, points INTEGER, rebounds INTEGER, assists INTEGER,
 steals INTEGER, blocks INTEGER, turnovers INTEGER,
 fgm INTEGER, fga INTEGER, fg3m INTEGER, fg3a INTEGER, ftm INTEGER, fta INTEGER,
 plus_minus DOUBLE, starter BOOLEAN,
 updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY (game_id, player_id)
);
CREATE TABLE IF NOT EXISTS collection_runs (
 game_id VARCHAR PRIMARY KEY, status VARCHAR, attempted_at TIMESTAMP,
 error VARCHAR
);
