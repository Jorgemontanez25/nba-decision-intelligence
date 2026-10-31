"""Import completed NBA game box scores for one team and optional opponent.
Run from the same directory as collector.py. Uses the existing DuckDB schema.
"""
import argparse
import time
from pathlib import Path
import duckdb
import pandas as pd
from collector import SCHEMA, api_team_logs, api_box, fetch_and_store


def collect_matchups(db, season, season_type, team, opponent, limit, sleep):
    logs = api_team_logs(season, season_type)
    if logs.empty:
        print('NBA endpoint returned no games.'); return 0
    logs = logs.copy()
    logs['GAME_ID'] = logs['GAME_ID'].astype(str)
    selected = []
    for gid, grp in logs.groupby('GAME_ID', sort=False):
        if len(grp) != 2:
            continue
        abbr = set(grp['TEAM_ABBREVIATION'].astype(str))
        if team in abbr and (opponent is None or opponent in abbr):
            selected.append((gid, grp))
    print(f'Found {len(selected)} {team} games' + (f' vs {opponent}' if opponent else '') + f' in {season} ({season_type})')
    imported = 0
    with duckdb.connect(db) as con:
        con.execute(SCHEMA.read_text())
        for gid, grp in selected:
            already = con.execute("SELECT status FROM collection_runs WHERE game_id=?", [gid]).fetchone()
            if already and already[0] == 'complete':
                print(f'SKIP already imported: {gid}')
                continue
            date = str(grp.iloc[0]['GAME_DATE'])[:10]
            try:
                box = api_box(gid)
                fetch_and_store(con, gid, season, season_type, date, grp, box)
                imported += 1
                print(f'IMPORTED {gid} ({len(box)} player rows)')
            except Exception as exc:
                print(f'FAILED {gid}: {exc}')
                con.execute("""INSERT INTO collection_runs VALUES (?, 'error', now(), ?)
                    ON CONFLICT(game_id) DO UPDATE SET status='error',attempted_at=now(),error=excluded.error""", [gid, str(exc)[:1000]])
            if limit is not None and imported >= limit:
                break
            time.sleep(sleep)
    print(f'New games imported: {imported}')
    return imported


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--db', default='nba_current.duckdb')
    p.add_argument('--season', default='2025-26')
    p.add_argument('--season-type', choices=['Regular Season', 'Playoffs'], default='Regular Season')
    p.add_argument('--team', default='LAL')
    p.add_argument('--opponent', default=None, help='e.g. BOS; omit for all team games')
    p.add_argument('--max-games', type=int, default=5)
    p.add_argument('--sleep', type=float, default=1.0)
    args = p.parse_args()
    collect_matchups(args.db, args.season, args.season_type, args.team.upper(),
                     args.opponent.upper() if args.opponent else None, args.max_games, args.sleep)
