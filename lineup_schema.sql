-- Version 4: verified five-on-five stints, always from a documented event source.
CREATE TABLE IF NOT EXISTS lineup_stints (
 stint_id VARCHAR PRIMARY KEY, game_id VARCHAR NOT NULL, season VARCHAR NOT NULL,
 season_type VARCHAR NOT NULL, team_abbr VARCHAR NOT NULL,
 opponent_abbr VARCHAR NOT NULL, period INTEGER NOT NULL,
 start_sec DOUBLE NOT NULL, end_sec DOUBLE NOT NULL,
 duration_sec DOUBLE NOT NULL, points_for INTEGER NOT NULL,
 points_against INTEGER NOT NULL,
 possessions_for DOUBLE, possessions_against DOUBLE,
 lineup_key VARCHAR NOT NULL, opponent_lineup_key VARCHAR NOT NULL,
 source VARCHAR NOT NULL, validation_status VARCHAR NOT NULL,
 imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 CHECK (duration_sec >= 0), CHECK (points_for >= 0), CHECK (points_against >= 0),
 CHECK (validation_status IN ('verified','rejected'))
);
CREATE TABLE IF NOT EXISTS lineup_stint_players (
 stint_id VARCHAR NOT NULL, side VARCHAR NOT NULL, player_id BIGINT NOT NULL,
 PRIMARY KEY (stint_id, side, player_id),
 CHECK (side IN ('team','opponent'))
);
-- Game-day availability is explicit, time-stamped, not inferred from past starts.
CREATE TABLE IF NOT EXISTS player_availability (
 game_id VARCHAR NOT NULL, player_id BIGINT NOT NULL,
 status VARCHAR NOT NULL, source_url VARCHAR NOT NULL,
 verified_at TIMESTAMP NOT NULL,
 PRIMARY KEY (game_id, player_id),
 CHECK (status IN ('available','out','questionable','doubtful','unknown'))
);
