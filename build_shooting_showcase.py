"""Create a local-only, source-preserving shooting showcase for NBA Decision Intelligence.

This tool DOES NOT upload, publish, or grant redistribution rights to NBA-derived data.
It exports real, existing shots plus their corresponding box-score records.
"""
import argparse
from pathlib import Path
import duckdb

DEFAULT_IDS = (201939, 1629029, 203999)  # Curry, Doncic, Jokic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='nba_current.duckdb')
    parser.add_argument('--out', default='nba_shooting_showcase_LOCAL_ONLY.duckdb')
    parser.add_argument('--seasons', nargs='+', default=['2025-26', '2026-27'])
    parser.add_argument('--player-ids', nargs='+', type=int, default=list(DEFAULT_IDS))
    args = parser.parse_args()
    src = Path(args.source).resolve()
    dest = Path(args.out).resolve()
    if not src.is_file():
        parser.error(f'Source file not found: {src}')
    if src == dest:
        parser.error('Source and destination must differ')
    if dest.exists():
        parser.error(f'Destination exists; choose a new --out filename: {dest}')

    con = duckdb.connect()
    try:
        con.execute('ATTACH ? AS src (READ_ONLY)', [str(src)])
        con.execute('ATTACH ? AS demo', [str(dest)])
        for table in ['player_games', 'team_games', 'shot_events', 'lineup_stints', 'lineup_stint_players', 'player_availability']:
            has_table = con.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_catalog='src' AND table_name=?", [table]).fetchone()[0]
            if not has_table:
                if table in ('player_games', 'team_games', 'shot_events'):
                    raise RuntimeError('Required source table missing: ' + table)
                continue
            con.execute(f'CREATE TABLE demo.{table} AS SELECT * FROM src.{table} WHERE 1=0')
        con.execute('CREATE TABLE demo.showcase_metadata (created_at TIMESTAMP, source_note VARCHAR, redistribution_status VARCHAR)')
        con.execute("INSERT INTO demo.showcase_metadata VALUES (CURRENT_TIMESTAMP, 'Local research extract of previously collected shot records', 'LOCAL ONLY — third-party public hosting not cleared')")
        ids = ','.join(['?'] * len(args.player_ids))
        seasons = ','.join(['?'] * len(args.seasons))
        params = [*args.player_ids, *args.seasons]
        con.execute(f'''INSERT INTO demo.shot_events SELECT * FROM src.shot_events
                       WHERE player_id IN ({ids}) AND season IN ({seasons})''', params)
        con.execute(f'''INSERT INTO demo.player_games SELECT * FROM src.player_games
                       WHERE player_id IN ({ids}) AND season IN ({seasons})''', params)
        # Do not invent teams, scores or opponent lineups. Preserve the actual teams for selected games.
        con.execute('''INSERT INTO demo.team_games SELECT t.* FROM src.team_games t
                       WHERE EXISTS (SELECT 1 FROM demo.player_games p WHERE p.game_id=t.game_id)''')
        # Include source-corresponding box-score rows for opponents/teammates so the
        # original team's box-score-based comparison panels can remain informative.
        con.execute(f'''INSERT INTO demo.player_games SELECT p.* FROM src.player_games p
                       WHERE EXISTS (SELECT 1 FROM demo.team_games t WHERE t.game_id=p.game_id)
                         AND NOT EXISTS (SELECT 1 FROM demo.player_games d WHERE d.game_id=p.game_id AND d.player_id=p.player_id)''')
        for table in ['player_games', 'team_games', 'shot_events']:
            n = con.execute(f'SELECT COUNT(*) FROM demo.{table}').fetchone()[0]
            print(f'{table}: {n:,}')
        for name, n in con.execute('''SELECT p.player_name,COUNT(*) FROM demo.shot_events s
                   JOIN (SELECT DISTINCT player_id,MAX(player_name) player_name FROM demo.player_games GROUP BY 1) p
                   USING (player_id) GROUP BY 1 ORDER BY 1''').fetchall():
            print(f'Shots for {name}: {n:,}')
        if con.execute('SELECT COUNT(*) FROM demo.shot_events').fetchone()[0] == 0:
            print('WARNING: no shot events matched the requested players and seasons')
        print('Local showcase written:', dest)
        print('Do NOT upload or commit this file until public hosting rights are confirmed.')
    finally:
        con.close()


if __name__ == '__main__':
    main()
