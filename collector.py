"""Collect current-season NBA team games and per-player box scores.

All historical games are final; recent game records are refreshed upon re-run.
Unverified current lineups/injuries are NOT inferred from historical starts.
"""
import argparse
import time
from pathlib import Path
import duckdb
import pandas as pd

SCHEMA = Path(__file__).with_name('schema.sql')


def season_label(start_year):
    return f'{start_year}-{str(start_year + 1)[-2:]}'


def api_team_logs(season, season_type):
    from nba_api.stats.endpoints import leaguegamelog
    response = leaguegamelog.LeagueGameLog(
        season=season, season_type_all_star=season_type,
        player_or_team_abbreviation='T', timeout=60)
    return response.league_game_log.get_data_frame()


def api_box(game_id):
    from nba_api.stats.endpoints import boxscoretraditionalv3
    response = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=game_id, timeout=60)
    return response.player_stats.get_data_frame()


def number(x, default=None):
    if x is None or pd.isna(x) or x == '':
        return default
    return float(x)


def minutes_value(x):
    """Convert NBA minutes (numeric, MM:SS or ISO 8601) to minutes.

    A blank/DNP value has no playing time and is stored as 0.0.
    Unexpected non-empty values raise ValueError so broken data is visible.
    """
    import re
    if x is None or pd.isna(x):
        return 0.0
    s = str(x).strip()
    if not s or s.upper() in {"DNP", "DND", "NWT", "N/A", "NONE", "NULL"}:
        return 0.0
    if s.startswith("PT"):
        m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", s)
        if m:
            return 60 * int(m.group(1) or 0) + int(m.group(2) or 0) + float(m.group(3) or 0) / 60
        raise ValueError(f"Unsupported ISO-8601 minutes value: {s!r}")
    if ":" in s:
        parts = s.split(":")
        if len(parts) == 2:
            return float(parts[0]) + float(parts[1]) / 60
        raise ValueError(f"Unsupported clock minutes value: {s!r}")
    return float(s)


def fetch_and_store(con, game_id, season, season_type, game_date, team_logs, box):
    if len(team_logs) != 2 or set(team_logs['GAME_ID'].astype(str)) != {game_id}:
        raise ValueError(f'Invalid team logs for game {game_id}')
    if box.empty:
        raise ValueError(f'Empty box for game {game_id}')
    game_team_ids = set(team_logs['TEAM_ID'].astype(int))
    if set(box['teamId'].dropna().astype(int)) != game_team_ids:
        raise ValueError(f'Box teams mismatch in game {game_id}')
    required = {'personId','teamId','firstName','familyName','minutes','points',
                'reboundsTotal','assists','fieldGoalsMade','fieldGoalsAttempted'}
    if not required.issubset(box.columns):
        raise ValueError(f'Missing NBA box fields: {required - set(box.columns)}')
    con.execute('BEGIN')
    try:
        for r in team_logs.to_dict('records'):
            con.execute('''INSERT INTO team_games
              (game_id,team_id,team_abbr,season,season_type,game_date,matchup,points,result)
              VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(game_id,team_id) DO UPDATE SET
              team_abbr=excluded.team_abbr,points=excluded.points,result=excluded.result,
              updated_at=now()''',
              [game_id,int(r['TEAM_ID']),r['TEAM_ABBREVIATION'],season,season_type,
               game_date,r['MATCHUP'],int(r['PTS']),r.get('WL')])
        for r in box.to_dict('records'):
            if pd.isna(r.get('personId')):
                continue
            row = [game_id,int(r['personId']),
                   f"{r.get('firstName') or ''} {r.get('familyName') or ''}".strip(),
                   int(r['teamId']),str(r.get('teamTricode') or ''),season,season_type,game_date,
                   minutes_value(r.get('minutes'))]
            for k in ('points','reboundsTotal','assists','steals','blocks','turnovers',
                      'fieldGoalsMade','fieldGoalsAttempted','threePointersMade','threePointersAttempted',
                      'freeThrowsMade','freeThrowsAttempted'):
                row.append(int(number(r.get(k),0)))
            row.extend([number(r.get('plusMinusPoints')), bool(str(r.get('position') or '').strip())])
            con.execute('''INSERT INTO player_games
              (game_id,player_id,player_name,team_id,team_abbr,season,season_type,game_date,
               minutes,points,rebounds,assists,steals,blocks,turnovers,fgm,fga,fg3m,fg3a,ftm,fta,
               plus_minus,starter) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(game_id,player_id) DO UPDATE SET
               player_name=excluded.player_name,team_id=excluded.team_id,
               team_abbr=excluded.team_abbr,minutes=excluded.minutes,points=excluded.points,
               rebounds=excluded.rebounds,assists=excluded.assists,steals=excluded.steals,
               blocks=excluded.blocks,turnovers=excluded.turnovers,fgm=excluded.fgm,
               fga=excluded.fga,fg3m=excluded.fg3m,fg3a=excluded.fg3a,
               ftm=excluded.ftm,fta=excluded.fta,plus_minus=excluded.plus_minus,
               starter=excluded.starter,updated_at=now()''',row)
        con.execute('''INSERT INTO collection_runs VALUES (?, 'complete', now(), NULL)
          ON CONFLICT(game_id) DO UPDATE SET status='complete',attempted_at=now(),error=NULL''',[game_id])
        con.execute('COMMIT')
    except Exception:
        con.execute('ROLLBACK')
        raise


def collect(db='sports.duckdb', season='2026-27', season_type='Regular Season',
            max_games=None, sleep=1.0, refresh_days=2):
    with duckdb.connect(db) as con:
        con.execute(SCHEMA.read_text())
        logs = api_team_logs(season, season_type)
        if logs.empty:
            print('No games available; source returned zero records.')
            return 0
        logs = logs.copy()
        logs['GAME_ID'] = logs['GAME_ID'].astype(str)
        processed = 0
        for game_id, group in logs.groupby('GAME_ID',sort=False):
            if len(group) != 2:
                print(f'Skipping incomplete game {game_id}')
                continue
            game_date = str(group.iloc[0]['GAME_DATE'])[:10]
            existing = con.execute('''SELECT status, attempted_at FROM collection_runs
                                       WHERE game_id=?''',[game_id]).fetchone()
            if existing and existing[0] == 'complete' and (pd.Timestamp.utcnow().tz_localize(None) - pd.Timestamp(existing[1])).days < refresh_days:
                continue
            try:
                box = api_box(game_id)
                fetch_and_store(con,game_id,season,season_type,game_date,group,box)
                processed+=1
                print(f'Imported {game_id}: {len(box)} player rows')
            except Exception as e:
                con.execute('''INSERT INTO collection_runs VALUES (?, 'error', now(), ?)
                  ON CONFLICT(game_id) DO UPDATE SET status='error',attempted_at=now(),error=excluded.error''',
                  [game_id,str(e)[:1000]])
                print(f'FAILED {game_id}: {e}')
            if max_games is not None and processed >= max_games:
                break
            time.sleep(sleep)
        return processed

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--db',default='sports.duckdb')
    parser.add_argument('--season',default='2026-27')
    parser.add_argument('--season-type',choices=['Regular Season','Playoffs'],default='Regular Season')
    parser.add_argument('--max-games',type=int)
    parser.add_argument('--sleep',type=float,default=1)
    args=parser.parse_args()
    print('New/refreshed games:',collect(args.db,args.season,args.season_type,args.max_games,args.sleep))
