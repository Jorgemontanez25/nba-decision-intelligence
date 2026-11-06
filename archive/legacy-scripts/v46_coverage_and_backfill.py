"""Read-only coverage by default; optional sequential historical collection with backup.

Runs preexisting collect_schedule_v7.py. This does NOT claim to collect missing shot
locations: box-score and shot coverage are separately reported.
"""
from __future__ import annotations
import argparse, datetime as dt, json, shutil, subprocess, sys
from pathlib import Path

SEASONS=['2022-23','2023-24','2024-25','2025-26']

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--db',default='nba_current.duckdb')
    ap.add_argument('--collector',default='collect_schedule_v7.py')
    ap.add_argument('--seasons',default=','.join(SEASONS))
    ap.add_argument('--max-games-per-season',type=int,default=10)
    ap.add_argument('--execute',action='store_true')
    ap.add_argument('--out',default='history_backfill_v46')
    args=ap.parse_args()
    import duckdb
    database=Path(args.db).resolve()
    if not database.exists():sys.exit(f'Database not found: {database}')
    con=duckdb.connect(str(database),read_only=True)
    coverage={}
    for table in ('player_games','shot_events'):
        try:
            coverage[table]=con.execute(f'SELECT season,COUNT(DISTINCT game_id) games, COUNT(*) rows FROM {table} GROUP BY season ORDER BY season').df().to_dict('records')
        except Exception as exc:coverage[table]={'error':str(exc)}
    con.close()
    requested=[x.strip() for x in args.seasons.split(',') if x.strip()]
    if not requested or any(x not in SEASONS for x in requested):sys.exit('Allowed seasons: '+','.join(SEASONS))
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    log={'mode':'EXECUTE' if args.execute else 'PLAN_ONLY','db':str(database),'coverage_before':coverage,'requested':requested,'jobs':[]}
    print('Local database season coverage:')
    print(json.dumps(coverage,indent=2,default=str))
    if args.execute:
        if args.max_games_per_season<1:sys.exit('--max-games-per-season must be >=1')
        collector=Path(args.collector).resolve()
        if not collector.exists():sys.exit(f'Collector not found: {collector}')
        stamp=dt.datetime.now().strftime('%Y%m%d_%H%M%S')
        backup=database.with_name(database.stem+'_pre_backfill_'+stamp+database.suffix)
        shutil.copy2(database,backup)
        log['backup']=str(backup)
        for season in requested:
            cmd=[sys.executable,str(collector),'--db',str(database),'--season',season,'--max-games',str(args.max_games_per_season),'--report',str(out/f'coverage_{season}.csv')]
            result=subprocess.run(cmd,text=True,capture_output=True)
            (out/f'{season}_stdout.log').write_text(result.stdout,encoding='utf-8')
            (out/f'{season}_stderr.log').write_text(result.stderr,encoding='utf-8')
            log['jobs'].append({'season':season,'returncode':result.returncode,'report':str(out/f'coverage_{season}.csv')})
            print(season,'OK' if result.returncode==0 else 'FAILED — inspect logs')
            if result.returncode:break
    else:
        print('PLAN ONLY: No changes made. Use --execute for a capped backfill.')
    (out/'SUMMARY.json').write_text(json.dumps(log,indent=2,default=str),encoding='utf-8')
    print('Report:',out/'SUMMARY.json')

if __name__=='__main__':main()
