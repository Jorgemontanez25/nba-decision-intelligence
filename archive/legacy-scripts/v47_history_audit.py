"""Read-only per-season coverage and profile/shot evidence verification."""
import argparse, json
import duckdb
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--db',default='nba_current.duckdb');p.add_argument('--player-id',default='1630559');args=p.parse_args()
if not Path(args.db).exists():p.error('Database not found')
con=duckdb.connect(args.db,read_only=True)
for table in ['player_games','shot_events','team_games']:
    print('\n'+table.upper())
    if table not in [x[0] for x in con.execute('SHOW TABLES').fetchall()]:
        print('MISSING TABLE');continue
    print('SEASON | GAMES | ROWS')
    for row in con.execute(f'SELECT season, COUNT(DISTINCT game_id), COUNT(*) FROM {table} GROUP BY season ORDER BY season').fetchall():print(' | '.join(map(str,row)))
    if table!='team_games':
        print('PLAYER',args.player_id,'SEASON | TEAM | GAMES | ROWS')
        for row in con.execute(f'SELECT season, team_abbr, COUNT(DISTINCT game_id), COUNT(*) FROM {table} WHERE CAST(player_id AS VARCHAR)=? GROUP BY season,team_abbr ORDER BY season,team_abbr',[args.player_id]).fetchall():print(' | '.join(map(str,row)))
print('\nThis only tests local data. No games were imported; no database tables were changed.')
