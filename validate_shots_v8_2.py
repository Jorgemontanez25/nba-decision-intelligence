"""NBA V8.2: read-only full-season shot-events vs box-score validation.
Requires duckdb. Never writes to the source database.
"""
import argparse
import csv
from pathlib import Path
from collections import Counter

import duckdb

METRICS = ('fga', 'fgm', 'fg3a', 'fg3m')

def export(con, directory, filename, sql, args=()):
    cursor = con.execute(sql, args)
    fields = [d[0] for d in cursor.description]
    path = directory / (filename + '.csv')
    n = 0
    with path.open('w', newline='', encoding='utf-8-sig') as out:
        writer = csv.writer(out)
        writer.writerow(fields)
        while True:
            chunk = cursor.fetchmany(10000)
            if not chunk:
                break
            writer.writerows(chunk)
            n += len(chunk)
    print(f'{filename}: {n:,} flagged rows')
    return n

def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--db', default='nba_current.duckdb')
    cli.add_argument('--season', default='2025-26')
    cli.add_argument('--season-type', default='Regular Season')
    cli.add_argument('--out', default='validation_v8_2_2025_26')
    args = cli.parse_args()
    db = Path(args.db)
    if not db.is_file():
        cli.error(f'Database not found: {db}')
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    results = {}
    with duckdb.connect(str(db), read_only=True) as con:
        tables = {row[0] for row in con.execute('SHOW TABLES').fetchall()}
        requirements = {
          'player_games': {'game_id','player_id','player_name','team_abbr','season','season_type','fga','fgm','fg3a','fg3m'},
          'shot_events': {'game_id','player_id','season','season_type','event_id','shot_made','shot_type','loc_x','loc_y','shot_distance','period'}
        }
        for table, needed in requirements.items():
            if table not in tables:
                cli.error(f'Missing table {table}')
            columns = {r[1] for r in con.execute(f"PRAGMA table_info('{table}')").fetchall()}
            missing = needed - columns
            if missing:
                cli.error(f'Missing {table} fields: {sorted(missing)}')
        scope = [args.season,args.season_type]
        # Aggregate shots BEFORE joining player_games. The previous audit multiplied FGA
        # by number of shots when joining raw events directly (e.g. 1457 -> 34549).
        shot_agg = """SELECT game_id,player_id,COUNT(*) AS shots_fga,
            SUM(CASE WHEN shot_made IS TRUE THEN 1 ELSE 0 END) AS shots_fgm,
            SUM(CASE WHEN UPPER(COALESCE(shot_type,'')) LIKE '%3PT%' OR UPPER(COALESCE(shot_type,'')) LIKE '%3-POINT%' THEN 1 ELSE 0 END) AS shots_fg3a,
            SUM(CASE WHEN shot_made IS TRUE AND (UPPER(COALESCE(shot_type,'')) LIKE '%3PT%' OR UPPER(COALESCE(shot_type,'')) LIKE '%3-POINT%') THEN 1 ELSE 0 END) AS shots_fg3m
            FROM shot_events WHERE season=? AND season_type=? GROUP BY game_id,player_id"""
        # 4-field comparison scoped to the box-score player-game grain.
        compare = f"""WITH shots AS ({shot_agg})
        SELECT p.game_id,p.player_id,p.player_name,p.team_abbr,
            p.fga AS box_fga,COALESCE(s.shots_fga,0) AS event_fga,
            p.fgm AS box_fgm,COALESCE(s.shots_fgm,0) AS event_fgm,
            p.fg3a AS box_3pa,COALESCE(s.shots_fg3a,0) AS event_3pa,
            p.fg3m AS box_3pm,COALESCE(s.shots_fg3m,0) AS event_3pm,
            COALESCE(s.shots_fga,0)-p.fga AS delta_fga,
            COALESCE(s.shots_fgm,0)-p.fgm AS delta_fgm,
            COALESCE(s.shots_fg3a,0)-p.fg3a AS delta_3pa,
            COALESCE(s.shots_fg3m,0)-p.fg3m AS delta_3pm
        FROM player_games p LEFT JOIN shots s USING(game_id,player_id)
        WHERE p.season=? AND p.season_type=? AND
            (p.fga IS DISTINCT FROM COALESCE(s.shots_fga,0) OR
             p.fgm IS DISTINCT FROM COALESCE(s.shots_fgm,0) OR
             p.fg3a IS DISTINCT FROM COALESCE(s.shots_fg3a,0) OR
             p.fg3m IS DISTINCT FROM COALESCE(s.shots_fg3m,0))
        ORDER BY ABS(COALESCE(s.shots_fga,0)-p.fga) DESC,p.game_id,p.player_id"""
        results['player_game_stat_mismatches'] = export(con,out,'player_game_stat_mismatches',compare,scope+scope)
        results['orphan_shot_games'] = export(con,out,'orphan_shot_games',"""SELECT s.game_id,s.player_id,COUNT(*) AS events
          FROM shot_events s LEFT JOIN player_games p ON p.game_id=s.game_id AND p.player_id=s.player_id
          AND p.season=s.season AND p.season_type=s.season_type
          WHERE s.season=? AND s.season_type=? AND p.game_id IS NULL
          GROUP BY 1,2 ORDER BY 3 DESC""",scope)
        results['duplicate_event_ids'] = export(con,out,'duplicate_event_ids',"""SELECT game_id,player_id,event_id,COUNT(*) AS copies
          FROM shot_events WHERE season=? AND season_type=?
          GROUP BY 1,2,3 HAVING COUNT(*)>1 ORDER BY copies DESC""",scope)
        results['invalid_shot_metadata'] = export(con,out,'invalid_shot_metadata',"""SELECT game_id,player_id,event_id,shot_made,shot_type,period,shot_distance,loc_x,loc_y
          FROM shot_events WHERE season=? AND season_type=? AND
          (shot_made IS NULL OR shot_type IS NULL OR TRIM(shot_type)='' OR period IS NULL OR period<1 OR period>20
           OR shot_distance<0 OR shot_distance>100 OR (shot_distance IS NULL)
           OR loc_x IS NULL OR loc_y IS NULL)
          ORDER BY game_id,player_id,event_id""",scope)
        # Broad location bounds only: flag implausible coordinates, do not assume a
        # rigid court normalisation. The NBA source coordinate convention varies.
        results['coordinate_review'] = export(con,out,'coordinate_review',"""SELECT game_id,player_id,event_id,loc_x,loc_y,shot_distance
          FROM shot_events WHERE season=? AND season_type=?
          AND (ABS(loc_x)>300 OR loc_y< -100 OR loc_y>500)
          ORDER BY game_id,player_id,event_id""",scope)
        results['unrecognized_shot_type'] = export(con,out,'unrecognized_shot_type',"""SELECT shot_type,COUNT(*) AS records
          FROM shot_events WHERE season=? AND season_type=?
          AND shot_type IS NOT NULL AND
          NOT (UPPER(shot_type) LIKE '%2PT%' OR UPPER(shot_type) LIKE '%3PT%' OR
               UPPER(shot_type) LIKE '%2-POINT%' OR UPPER(shot_type) LIKE '%3-POINT%')
          GROUP BY 1 ORDER BY records DESC""",scope)
        totals = con.execute('''SELECT COUNT(DISTINCT player_id),COUNT(*) FROM player_games
          WHERE season=? AND season_type=?''',scope).fetchone()
        shot_total = con.execute('''SELECT COUNT(*) FROM shot_events WHERE season=? AND season_type=?''',scope).fetchone()[0]
    with (out/'SUMMARY.txt').open('w',encoding='utf-8') as f:
        f.write(f'V8.2 READ-ONLY NBA SHOT AUDIT\nSeason: {args.season} / {args.season_type}\n')
        f.write(f'Player identities: {totals[0]}\nPlayer-game box score rows: {totals[1]}\nShot event rows: {shot_total}\n\n')
        for k,v in results.items(): f.write(f'{k}: {v} flagged rows\n')
        f.write('\nReview all exceptions before excluding source events. This is not independent verification against NBA play-by-play.\n')
    print(f'Player-game records: {totals[1]:,}; shot event records: {shot_total:,}')
    print(f'Reports: {out.resolve()}')
    print('READ ONLY: No records were changed or deleted. Review CSV exceptions before acting.')

if __name__=='__main__': main()
