"""Read-only diagnostics for NBA Decision Intelligence V5/V6 DuckDB data.
Usage: python nba_data_audit.py --db nba_current.duckdb --season 2025-26 --team LAL
"""
import argparse
from pathlib import Path
import duckdb


def table_exists(con, table):
    return bool(con.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='main' AND table_name=?", [table]).fetchone()[0])


def cols(con, table):
    return {r[1] for r in con.execute(f"PRAGMA table_info('{table}')").fetchall()}


def section(title):
    print('\n' + '=' * 68 + '\n' + title + '\n' + '=' * 68)


def rows(con, sql, params=(), limit=20):
    result = con.execute(sql, list(params))
    headers = [d[0] for d in result.description]
    data = result.fetchmany(limit + 1)
    if not data:
        print('  (none)')
        return
    print(' | '.join(headers))
    for record in data[:limit]:
        print(' | '.join(str(v) for v in record))
    if len(data) > limit:
        print(f'  ... more rows not shown (limit {limit})')


def audit(db, season, team):
    if not Path(db).is_file():
        raise SystemExit(f'No database found: {db}. Run from your project directory or pass --db with its full path.')
    with duckdb.connect(str(db), read_only=True) as con:
        section('DATABASE TABLES')
        for table in ('team_games', 'player_games', 'shot_events', 'collection_runs'):
            if not table_exists(con, table):
                print(f'{table}: NOT PRESENT')
            else:
                print(f'{table}: {con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]:,} rows')

        if not table_exists(con, 'team_games'):
            return
        tcols = cols(con, 'team_games')
        if {'game_id', 'team_abbr', 'season', 'season_type'} <= tcols:
            section(f'IMPORTED GAMES: {team} / {season}')
            rows(con, '''SELECT season_type, COUNT(DISTINCT game_id) AS games_imported
                         FROM team_games WHERE season=? AND team_abbr=?
                         GROUP BY season_type ORDER BY season_type''', [season, team])
            section('OPPONENT COVERAGE (ONLY IMPORTED MATCHUPS)')
            rows(con, '''SELECT a.season_type, b.team_abbr AS opponent,
                                COUNT(DISTINCT a.game_id) AS games
                         FROM team_games a JOIN team_games b
                           ON a.game_id=b.game_id AND a.team_abbr<>b.team_abbr
                         WHERE a.season=? AND a.team_abbr=?
                         GROUP BY 1,2 ORDER BY 1,2''', [season, team], 40)
            section('MISSING SECOND TEAM RECORDS')
            rows(con, '''SELECT game_id, COUNT(DISTINCT team_abbr) AS teams
                         FROM team_games WHERE season=?
                         GROUP BY game_id HAVING COUNT(DISTINCT team_abbr)<>2
                         ORDER BY game_id''', [season])
            section('DUPLICATE TEAM-GAME KEYS')
            rows(con, '''SELECT game_id, team_abbr, COUNT(*) AS copies
                         FROM team_games GROUP BY 1,2 HAVING COUNT(*)>1 ORDER BY copies DESC''')

        if table_exists(con, 'player_games'):
            pcols = cols(con, 'player_games')
            if {'game_id', 'player_id', 'team_abbr', 'season'} <= pcols:
                section('PLAYER BOX-SCORE COVERAGE BY TEAM / SEASON')
                rows(con, '''SELECT team_abbr, COUNT(DISTINCT game_id) AS games,
                                    COUNT(*) AS player_game_rows,
                                    COUNT(DISTINCT player_id) AS distinct_players
                             FROM player_games WHERE season=? AND team_abbr=?
                             GROUP BY team_abbr''', [season, team])
                section('GAMES IN TEAM_GAMES WITH NO PLAYER BOX-SCORE ROWS')
                rows(con, '''SELECT t.game_id, t.season_type
                             FROM team_games t LEFT JOIN player_games p
                               ON t.game_id=p.game_id AND t.team_abbr=p.team_abbr
                             WHERE t.season=? AND t.team_abbr=?
                             GROUP BY 1,2 HAVING COUNT(p.player_id)=0
                             ORDER BY 1''', [season, team])
                section('DUPLICATE PLAYER-GAME KEYS')
                rows(con, '''SELECT game_id, player_id, team_abbr, COUNT(*) AS copies
                             FROM player_games GROUP BY 1,2,3 HAVING COUNT(*)>1 ORDER BY copies DESC''')

        if table_exists(con, 'shot_events'):
            scols = cols(con, 'shot_events')
            if {'season', 'player_id', 'game_id'} <= scols:
                section(f'SHOT EVENT COVERAGE: {season}')
                if 'team_id' in scols:
                    team_ids = {'LAL': 1610612747, 'BOS': 1610612738, 'GSW': 1610612744}
                    team_id = team_ids.get(team)
                    if team_id:
                        rows(con, '''SELECT player_id, COUNT(*) AS attempts,
                                            COUNT(DISTINCT game_id) AS games_with_shots
                                     FROM shot_events WHERE season=? AND team_id=?
                                     GROUP BY player_id ORDER BY attempts DESC''', [season, team_id], 35)
                    else:
                        rows(con, '''SELECT player_id, COUNT(*) AS attempts,
                                            COUNT(DISTINCT game_id) AS games_with_shots
                                     FROM shot_events WHERE season=?
                                     GROUP BY player_id ORDER BY attempts DESC''', [season], 35)
                else:
                    rows(con, '''SELECT player_id, COUNT(*) AS attempts,
                                        COUNT(DISTINCT game_id) AS games_with_shots
                                 FROM shot_events WHERE season=?
                                 GROUP BY player_id ORDER BY attempts DESC''', [season], 35)

        section('INTERPRETATION')
        print('Imported games are NOT necessarily every game played that season.')
        print('This audit diagnoses local coverage. It cannot prove a complete season')
        print('without comparing imported game IDs with the official league schedule.')
        print('Shot events and game box scores are collected independently.')
        print('Keep regular season and playoffs separate when checking completeness.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default='nba_current.duckdb')
    parser.add_argument('--season', default='2025-26')
    parser.add_argument('--team', default='LAL')
    arguments = parser.parse_args()
    audit(arguments.db, arguments.season, arguments.team.upper())
