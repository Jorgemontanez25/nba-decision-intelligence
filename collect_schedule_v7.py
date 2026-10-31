"""Schedule-aware NBA backfill for the existing NBA V5/V6 DuckDB schema.

Needs collector.py (your working, minutes-fixed version), schema.sql, nba_api,
duckdb, pandas. Does not change your existing dashboard.
"""
import argparse
import csv
import datetime as dt
import time
from pathlib import Path

import duckdb
import pandas as pd

from collector import api_team_logs, api_box, fetch_and_store


def schedule_games(season):
    from nba_api.stats.endpoints import scheduleleaguev2
    return scheduleleaguev2.ScheduleLeagueV2(season=season, timeout=60).season_games.get_data_frame()


def normalize_schedule(frame, season_type):
    required = {'gameId', 'gameStatus', 'homeTeam_teamTricode', 'awayTeam_teamTricode'}
    if not required.issubset(frame.columns):
        raise ValueError(f'Schedule schema missing columns: {sorted(required-set(frame.columns))}')
    out = frame.copy()
    out['game_id'] = out['gameId'].astype(str).str.strip().str.zfill(10)
    out['home'] = out['homeTeam_teamTricode'].astype(str).str.upper()
    out['away'] = out['awayTeam_teamTricode'].astype(str).str.upper()
    out['status'] = pd.to_numeric(out['gameStatus'], errors='coerce')
    # NBA IDs: 002=regular season, 004=playoffs. Other classes excluded.
    prefix = '002' if season_type == 'Regular Season' else '004'
    out = out.loc[out['game_id'].str.startswith(prefix)].copy()
    return out.drop_duplicates('game_id')


def select_games(schedule, game_logs, existing, team=None, opponent=None, limit=None):
    """Return final games missing a complete local import, with 2 valid log rows."""
    if team:
        schedule = schedule[(schedule.home == team) | (schedule.away == team)]
    if opponent:
        schedule = schedule[(schedule.home == opponent) | (schedule.away == opponent)]
    final = schedule.loc[schedule.status == 3].copy()
    log_groups = {gid: g for gid, g in game_logs.groupby('GAME_ID', sort=False)}
    candidates, missing_logs = [], []
    for r in final.itertuples(index=False):
        gid = r.game_id
        if gid in existing:
            continue
        group = log_groups.get(gid)
        if group is None or len(group) != 2 or group['TEAM_ID'].nunique() != 2:
            missing_logs.append(gid)
            continue
        candidates.append((gid, group, str(group.iloc[0]['GAME_DATE'])[:10]))
    return candidates[:limit] if limit is not None else candidates, missing_logs, len(final)


def local_completeness(con, season, season_type):
    """Both team rows, ≥1 player per team and successful log are required."""
    rows = con.execute('''
        SELECT g.game_id,
               COUNT(DISTINCT g.team_id) AS team_count,
               COUNT(DISTINCT CASE WHEN p.player_id IS NOT NULL THEN p.team_id END) AS box_teams,
               COUNT(DISTINCT p.player_id) AS players,
               MAX(CASE WHEN r.status = 'complete' THEN 1 ELSE 0 END) AS logged_complete
        FROM team_games g
        LEFT JOIN player_games p ON p.game_id=g.game_id
        LEFT JOIN collection_runs r ON r.game_id=g.game_id
        WHERE g.season=? AND g.season_type=?
        GROUP BY g.game_id
    ''', [season, season_type]).fetchall()
    return {str(gid) for gid, nteams, nbox, nplayers, completed in rows
            if nteams == 2 and nbox == 2 and nplayers >= 2 and completed == 1}


def save_report(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        wr = csv.DictWriter(f, fieldnames=['game_id','home','away','status','local_status','detail'])
        wr.writeheader()
        wr.writerows(rows)


def main(args):
    if not Path(args.db).exists():
        raise SystemExit('Database not found; provide the existing nba_current.duckdb path.')
    if args.opponent and not args.team:
        raise SystemExit('--opponent requires --team.')
    if args.team and args.opponent and args.team == args.opponent:
        raise SystemExit('Team and opponent must differ.')
    print(f'Loading NBA schedule for {args.season} ...')
    sch = normalize_schedule(schedule_games(args.season), args.season_type)
    if sch.empty:
        raise SystemExit('No schedule entries of the selected game type were returned. No import attempted.')
    with duckdb.connect(args.db) as con:
        existing = local_completeness(con, args.season, args.season_type)
    # Get completed game team logs for both teams and dates / scores.
    print('Loading completed NBA team game logs ...')
    logs = api_team_logs(args.season, args.season_type).copy()
    if logs.empty:
        print('Team game-log endpoint returned no games; will report without importing.')
        logs = pd.DataFrame(columns=['GAME_ID','TEAM_ID','GAME_DATE'])
    logs['GAME_ID'] = logs['GAME_ID'].astype(str).str.strip().str.zfill(10)
    if 'TEAM_ID' in logs:
        logs['TEAM_ID'] = pd.to_numeric(logs['TEAM_ID'], errors='coerce')
    to_import, log_missing, final_count = select_games(sch, logs, existing, args.team, args.opponent, args.max_games)
    selected_sch = sch.copy()
    if args.team:
        selected_sch = selected_sch[(selected_sch.home == args.team) | (selected_sch.away == args.team)]
    if args.opponent:
        selected_sch = selected_sch[(selected_sch.home == args.opponent) | (selected_sch.away == args.opponent)]
    print(f'Final games in selected schedule: {final_count}; already imported (season-wide): {len(existing)}; '
          f'eligible missing imports this run: {len(to_import)}; final games missing team logs: {len(log_missing)}')
    attempted, success, failures = set(), set(), {}
    if not args.dry_run:
        with duckdb.connect(args.db) as con:
            for gid, group, game_date in to_import:
                attempted.add(gid)
                for attempt in range(1, args.retries + 2):
                    try:
                        box = api_box(gid)
                        fetch_and_store(con, gid, args.season, args.season_type, game_date, group, box)
                        success.add(gid)
                        print(f'Imported {gid}: {len(box)} player rows')
                        break
                    except Exception as exc:
                        failures[gid] = str(exc)[:300]
                        print(f'FAILED {gid} attempt {attempt}: {exc}')
                        if attempt <= args.retries:
                            time.sleep(args.sleep * attempt)
                time.sleep(args.sleep)
    with duckdb.connect(args.db, read_only=True) as con:
        after = local_completeness(con, args.season, args.season_type)
    all_report = []
    missing_log_set = set(log_missing)
    for r in selected_sch.itertuples(index=False):
        if r.status != 3:
            state, detail = 'not_final', f'gameStatus={r.status}'
        elif r.game_id in after:
            state, detail = 'complete', ''
        elif r.game_id in failures:
            state, detail = 'failed', failures[r.game_id]
        elif r.game_id in missing_log_set:
            state, detail = 'missing_team_logs', 'Final on schedule but missing/invalid team log'
        elif args.dry_run:
            state, detail = 'missing', 'Dry run; no downloads attempted'
        else:
            state, detail = 'missing', 'Not yet imported (possibly --max-games limit)'
        all_report.append({'game_id': r.game_id, 'home': r.home, 'away': r.away,
                           'status': int(r.status) if pd.notna(r.status) else 'unknown',
                           'local_status': state, 'detail': detail})
    report_path = Path(args.report)
    save_report(all_report, report_path)
    completed_local = sum(r['local_status'] == 'complete' for r in all_report if r['status'] == 3)
    print(f'Coverage: {completed_local}/{final_count} final scheduled games for the selected filters.')
    print(f'New imports: {len(success)}; failed attempts: {len(failures)-len(success)}; report: {report_path}')
    print('Only games with status=3 count as completed. Not-final games are never treated as missing.')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description='V7 schedule-aware NBA collection and coverage report')
    p.add_argument('--db', default='nba_current.duckdb')
    p.add_argument('--season', default='2025-26')
    p.add_argument('--season-type', choices=['Regular Season', 'Playoffs'], default='Regular Season')
    p.add_argument('--team', help='Three-letter team abbreviation, e.g. LAL')
    p.add_argument('--opponent', help='Requires --team; e.g. CLE')
    p.add_argument('--max-games', type=int, default=None)
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--retries', type=int, default=2)
    p.add_argument('--sleep', type=float, default=1.5)
    p.add_argument('--report', default='coverage_v7.csv')
    main(p.parse_args())
