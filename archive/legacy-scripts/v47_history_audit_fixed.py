"""Read-only NBA DuckDB history audit; handles different table schemas safely."""
import argparse
from pathlib import Path
import duckdb

p = argparse.ArgumentParser()
p.add_argument('--db', default='nba_current.duckdb')
p.add_argument('--player-id', default='1630559')
a = p.parse_args()
if not Path(a.db).is_file(): p.error('Database not found')
with duckdb.connect(a.db, read_only=True) as db:
    tables = {r[0] for r in db.execute('SHOW TABLES').fetchall()}
    for name in ('player_games', 'shot_events', 'team_games'):
        print('\n' + name.upper())
        if name not in tables:
            print('TABLE MISSING'); continue
        fields = {r[1] for r in db.execute(f'PRAGMA table_info(\'{name}\')').fetchall()}
        print('COLUMNS:', ', '.join(sorted(fields)))
        if {'season', 'game_id'}.issubset(fields):
            print('SEASON | GAMES | ROWS')
            for row in db.execute(f'SELECT season, COUNT(DISTINCT game_id), COUNT(*) FROM {name} GROUP BY season ORDER BY season').fetchall():
                print(' | '.join(map(str, row)))
        if name == 'team_games' or 'player_id' not in fields: continue
        team_col = 'team_abbr' if 'team_abbr' in fields else ('team_id' if 'team_id' in fields else None)
        team_expr = team_col or "'NOT_IN_TABLE'"
        if {'season', 'game_id'}.issubset(fields):
            print(f'PLAYER {a.player_id} | SEASON | TEAM | GAMES | ROWS')
            query = f'''SELECT season, {team_expr} AS team, COUNT(DISTINCT game_id), COUNT(*)
                        FROM {name} WHERE CAST(player_id AS VARCHAR)=?
                        GROUP BY season, {team_expr} ORDER BY season, team'''
            for row in db.execute(query,[a.player_id]).fetchall(): print(' | '.join(map(str,row)))
    print('\nREAD ONLY: no data changed.')
