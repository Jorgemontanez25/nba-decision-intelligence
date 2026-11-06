"""Opt-in, local scheduled NBA data refresh.

The NBA endpoint availability varies. Failed jobs are logged, never treated as zero games.
Requires existing collect_schedule_v7.py + collector.py; does not certify 5v5 stints.
"""
from __future__ import annotations
import argparse, datetime as dt, json, shutil, subprocess, sys, time
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def run_job(name,cmd,timeout):
    start=time.time()
    try:
        p=subprocess.run(cmd,cwd=str(ROOT),capture_output=True,text=True,timeout=timeout)
        return {'name':name,'ok':p.returncode==0,'returncode':p.returncode,'duration_seconds':round(time.time()-start,1),'command':cmd,'stdout_tail':p.stdout[-1500:],'stderr_tail':p.stderr[-1500:]}
    except Exception as exc:
        return {'name':name,'ok':False,'returncode':None,'duration_seconds':round(time.time()-start,1),'command':cmd,'error':str(exc)}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--season',default='2026-27')
    ap.add_argument('--db',default='nba_current.duckdb')
    ap.add_argument('--teams',default='ALL',help='Comma-separated abbreviations, or ALL')
    ap.add_argument('--max-games',type=int,default=30,help='Max newly imported final games per run')
    ap.add_argument('--skip-rosters',action='store_true')
    ap.add_argument('--skip-box',action='store_true')
    ap.add_argument('--dry-run',action='store_true',help='Do not run either collection job')
    args=ap.parse_args()
    out=ROOT/'data_refresh_v45';out.mkdir(exist_ok=True)
    now=dt.datetime.now(dt.timezone.utc)
    stamp=now.strftime('%Y%m%dT%H%M%SZ')
    record={'version':'4.5','started_utc':now.isoformat(),'jobs':[],'season':args.season,'dry_run':args.dry_run,'note':'Current-season box score + roster synchronization; no automatic shot backfill, injuries, live play-by-play, or certified stints.'}
    db=ROOT/args.db
    if not args.dry_run and not args.skip_box and db.exists():
        backup=out/f'pre_refresh_{stamp}.duckdb'
        try:
            # A copy is safe only when no other process has the DB open for writes.
            # Do not claim live atomicity. Shut down Streamlit before refresh.
            shutil.copy2(db,backup)
            record['backup']=str(backup)
        except Exception as e:
            record['status']='ABORTED_BACKUP_FAILED';record['error']=str(e)
            (out/'latest.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
            raise SystemExit('Backup failed; no collection attempted: '+str(e))
    elif not db.exists() and not args.skip_box and not args.dry_run:
        record['status']='ABORTED_MISSING_DATABASE';(out/'latest.json').write_text(json.dumps(record,indent=2),encoding='utf-8');raise SystemExit('Existing database is missing; refusing to create empty database.')
    if not args.dry_run:
        if not args.skip_rosters:
            roster_job=run_job('rosters',[sys.executable,str(ROOT/'roster_2026_27.py'),'--teams',args.teams,'--season',args.season],1800)
            # The legacy roster script may exit 0 while reporting per-team failures.
            if '"failed": [' in roster_job.get('stdout_tail','') and '"failed": []' not in roster_job.get('stdout_tail',''):
                roster_job['ok']=False
                roster_job['warning']='One or more team roster fetches failed'
            record['jobs'].append(roster_job)
        if not args.skip_box:
            record['jobs'].append(run_job('completed_game_box_scores',[sys.executable,str(ROOT/'collect_schedule_v7.py'),'--db',args.db,'--season',args.season,'--season-type','Regular Season','--max-games',str(args.max_games),'--report',str(out/f'coverage_{stamp}.csv')],3600))
    statuses=[j['ok'] for j in record['jobs']]
    record['status']='DRY_RUN' if args.dry_run else ('COMPLETE' if statuses and all(statuses) else 'PARTIAL_OR_FAILED')
    record['ended_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
    (out/f'refresh_{stamp}.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    (out/'latest.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps({'status':record['status'],'jobs':[(j['name'],j['ok']) for j in record['jobs']],'report':str(out/'latest.json')},indent=2))
    if record['status']=='PARTIAL_OR_FAILED':raise SystemExit(2)
if __name__=='__main__':main()
