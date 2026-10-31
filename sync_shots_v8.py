"""NBA V8: read-only gap analysis and resumable orchestration of collect_shots.py.

The only database writes come from the existing, user-tested collect_shots.py script.
Always back up the database before using --execute.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime
from pathlib import Path
import subprocess
import sys
import time

import duckdb


def quote_ident(s):
    return '"' + s.replace('"', '""') + '"'


def ensure_schema(con):
    required = {
        'player_games': {'game_id','player_id','season','season_type','fga'},
        'shot_events': {'game_id','player_id','season','season_type'},
    }
    tables = {r[0] for r in con.execute('SHOW TABLES').fetchall()}
    for name, req in required.items():
        if name not in tables:
            raise ValueError(f'Required table {name!r} not found. Run your existing collector first.')
        cols = {r[1] for r in con.execute(f'PRAGMA table_info({quote_ident(name)})').fetchall()}
        absent = req - cols
        if absent:
            raise ValueError(f'{name} missing columns: {sorted(absent)}')
    return True


def read_snapshot(db, season, season_type):
    with duckdb.connect(str(db), read_only=True) as con:
        ensure_schema(con)
        # A shot_event is one attempt, and player_games FGA is the source count.
        # Match season and season type to guard against re-used/mis-tagged IDs.
        rows = con.execute('''
            WITH p AS (
                SELECT CAST(player_id AS VARCHAR) player_id,
                       CAST(game_id AS VARCHAR) game_id,
                       MAX(COALESCE(CAST(fga AS BIGINT), 0)) fga
                FROM player_games WHERE season=? AND season_type=?
                GROUP BY 1,2
            ), s AS (
                SELECT CAST(player_id AS VARCHAR) player_id,
                       CAST(game_id AS VARCHAR) game_id, COUNT(*) shot_count
                FROM shot_events WHERE season=? AND season_type=?
                GROUP BY 1,2
            )
            SELECT p.player_id, p.game_id, p.fga, COALESCE(s.shot_count,0) shots
            FROM p LEFT JOIN s USING(player_id,game_id)
            ORDER BY p.player_id, p.game_id
        ''', [season, season_type, season, season_type]).fetchall()
        # Catch events for non-existing player-game pairs and fail closed.
        orphan = con.execute('''
            WITH p AS (
                SELECT DISTINCT CAST(player_id AS VARCHAR) player_id,
                                CAST(game_id AS VARCHAR) game_id
                FROM player_games WHERE season=? AND season_type=?
            ), s AS (
                SELECT CAST(player_id AS VARCHAR) player_id,
                       CAST(game_id AS VARCHAR) game_id, COUNT(*) attempts
                FROM shot_events WHERE season=? AND season_type=?
                GROUP BY 1,2
            )
            SELECT COUNT(*) FROM s LEFT JOIN p USING(player_id,game_id)
            WHERE p.player_id IS NULL
        ''', [season, season_type, season, season_type]).fetchone()[0]
        names = {}
        cols = {r[1] for r in con.execute('PRAGMA table_info("player_games")').fetchall()}
        if 'player_name' in cols:
            for pid, name in con.execute('''
                SELECT CAST(player_id AS VARCHAR), MAX(player_name)
                FROM player_games WHERE season=? AND season_type=? GROUP BY 1
            ''', [season, season_type]).fetchall():
                names[pid] = name or pid
    players = {}
    for pid, gid, fga, shots in rows:
        p = players.setdefault(pid, dict(player_id=pid, player_name=names.get(pid,pid),
                                         games=0, expected_fga=0, captured_shots=0,
                                         missing_games=0, short_games=0, excess_games=0,
                                         missing_attempts=0, excess_attempts=0))
        p['games'] += 1
        p['expected_fga'] += fga
        p['captured_shots'] += shots
        if fga > 0 and shots == 0:
            p['missing_games'] += 1
        elif fga > shots:
            p['short_games'] += 1
        elif shots > fga:
            p['excess_games'] += 1
        p['missing_attempts'] += max(0, fga-shots)
        p['excess_attempts'] += max(0, shots-fga)
    result = list(players.values())
    for p in result:
        p['status'] = ('complete' if p['missing_attempts'] == 0 and p['excess_attempts'] == 0
                       else 'excess_events' if p['excess_attempts'] else 'missing_events')
    return result, int(orphan)


def write_csv(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ['player_id','player_name','games','expected_fga','captured_shots',
              'missing_games','short_games','excess_games','missing_attempts',
              'excess_attempts','status','action','message']
    with path.open('w',encoding='utf-8',newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(records)


def cli():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db', default='nba_current.duckdb')
    ap.add_argument('--season', default='2025-26')
    ap.add_argument('--season-type', default='Regular Season', choices=['Regular Season','Playoffs'])
    ap.add_argument('--collector', default='collect_shots.py', help='Your existing working collector script')
    ap.add_argument('--max-players', type=int, default=5)
    ap.add_argument('--report', default='v8_shot_coverage.csv')
    ap.add_argument('--execute', action='store_true', help='Required to run imports (default is read-only dry run)')
    ap.add_argument('--sleep', type=float, default=2.0)
    ap.add_argument('--retries', type=int, default=1)
    a = ap.parse_args()
    if a.max_players < 0 or a.sleep < 0 or a.retries < 0:
        ap.error('max-players, sleep and retries must be nonnegative')
    db = Path(a.db).resolve()
    if not db.exists():
        ap.error(f'Database not found: {db}')
    rows, orphans = read_snapshot(db, a.season, a.season_type)
    missing = [p for p in rows if p['missing_attempts'] > 0 and p['excess_attempts'] == 0]
    missing.sort(key=lambda p:(-p['missing_attempts'],p['player_id']))
    selected = missing[:a.max_players] if a.max_players else missing
    print(f'Season: {a.season} | {a.season_type}')
    print(f'Players: {len(rows)} | Fully reconciled: {sum(p["status"] == "complete" for p in rows)}')
    print(f'Players with missing shot attempts: {len(missing)} | Selected for this run: {len(selected)}')
    print(f'Players with excess shot events: {sum(p["excess_attempts"]>0 for p in rows)} | Orphan shot player-games: {orphans}')
    print('Selected:', ', '.join(f'{p["player_name"]} ({p["player_id"]}, {p["missing_attempts"]} missing)' for p in selected[:12]) or '(none)')
    if a.season_type != 'Regular Season' and a.execute:
        ap.error('This V8 importer was tested only for regular-season shot collection; playoffs require collector verification.')
    if a.execute and orphans:
        ap.error('Orphan shot-event game keys detected; investigate before writing.')
    actions = {}
    if a.execute:
        collector = Path(a.collector).resolve()
        if not collector.is_file():
            ap.error(f'Collector not found: {collector}')
        for idx,p in enumerate(selected,1):
            pid = p['player_id']
            print(f'[{idx}/{len(selected)}] Importing player {p["player_name"]} ({pid}) ...', flush=True)
            err = ''
            for trial in range(1, a.retries + 2):
                cmd = [sys.executable, str(collector), '--db', str(db), '--player-id', pid, '--season', a.season]
                # The existing collector handles API and DuckDB writes. No direct
                # SQL INSERTs occur here. Do not run in parallel.
                result = subprocess.run(cmd, cwd=str(collector.parent), capture_output=True, text=True)
                if result.stdout:
                    print(result.stdout[-2000:], flush=True)
                if result.returncode == 0:
                    err = ''
                    break
                err = (result.stderr or result.stdout or f'exit {result.returncode}')[-500:]
                print(f'  attempt {trial}: {err}', flush=True)
                if trial <= a.retries:
                    time.sleep(a.sleep * trial)
            actions[pid] = ('ran' if not err else 'failed', err)
            time.sleep(a.sleep)
    else:
        for p in selected:
            actions[p['player_id']] = ('would_import', 'Dry run; database unchanged')
    after, after_orphans = read_snapshot(db, a.season, a.season_type)
    for p in after:
        p['action'], p['message'] = actions.get(p['player_id'], ('not_selected',''))
    write_csv(Path(a.report), after)
    print(f'After run: {sum(p["status"] == "complete" for p in after)}/{len(after)} players reconciled.')
    print(f'Orphan shot player-games after run: {after_orphans}')
    print(f'Report: {Path(a.report).resolve()}')
    print('NOTE: This compares shot attempts to box-score FGA by game; it does not verify makes or shot metadata.')


if __name__ == '__main__':
    cli()
