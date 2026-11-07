#!/usr/bin/env python3
"""V9.9.9 read-only batch conditional reconstruction, evidence reuse, regression checks.
No box-score minutes or plus/minus used to choose lineups; no DB writes.
"""
import argparse,csv,json,re,subprocess,sys,shutil
from pathlib import Path
from datetime import datetime,timezone

CORE=('playbyplayv3_dataset_0.csv','boxscoretraditionalv3_dataset_0.csv')
FIELDS=['game_id','label','status','evidence_origin','teams','openings_integrated','expected_openings','substitutions_in_source','substitutions_applied','groups_blocked','unresolved_openings','intervals_total','intervals_complete','issue_count','minutes_players','max_minutes_diff_seconds','regression_status','reason']
def rows(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def dump(p,obj):p.write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding='utf-8')
def call(name,cmd,folder):
    try:p=subprocess.run(cmd,text=True,capture_output=True,encoding='utf-8',errors='replace')
    except Exception as e:
        (folder/(name+'.stderr.txt')).write_text(str(e),encoding='utf-8');return 99
    (folder/(name+'.stdout.txt')).write_text(p.stdout,encoding='utf-8');(folder/(name+'.stderr.txt')).write_text(p.stderr,encoding='utf-8');return p.returncode
def publish(out,results,requested,tolerance,partial):
    with (out/'GAME_RESULTS.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,extrasaction='ignore');w.writeheader();w.writerows(results)
    summary={'version':'9.9.9','mode':'READ_ONLY_UNIFIED_CONDITIONAL_BATCH','created_utc':datetime.now(timezone.utc).isoformat(),'requested':requested,'processed':len(results),'partial':partial,'internal_passes':sum(x['status']=='PASS_INTERNAL_UNVERIFIED' for x in results),'not_passing':sum(x['status']!='PASS_INTERNAL_UNVERIFIED' for x in results),'minutes_tolerance_seconds':tolerance,'regression_failures':sum(x.get('regression_status')=='REGRESSION_FAILED' for x in results),'scoring_boundary_attribution':'NOT_CERTIFIED_NOT_EVALUATED','verified_stints':0,'production_certified':False,'database_modified':False,'warning':'Internal replay and official minutes consistency do NOT independently certify lineups or scoring boundaries.'}
    dump(out/'SUMMARY.json',summary)
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--games',type=Path,default=Path('v9_9_9_regression_games.csv'))
    p.add_argument('--out',type=Path,default=Path('v9_9_9_review'))
    p.add_argument('--max-games',type=int,default=5)
    p.add_argument('--minutes-tolerance',type=float,default=1.0)
    p.add_argument('--force-collect',action='store_true')
    a=p.parse_args()
    if a.max_games<1 or a.minutes_tolerance<0:p.error('Invalid max-games or minutes-tolerance')
    if not a.games.is_file():p.error('Manifest missing: '+str(a.games))
    games=rows(a.games)[:a.max_games]
    if not games:p.error('Empty manifest')
    if len({r.get('game_id') for r in games})!=len(games):p.error('Duplicate game IDs')
    root=Path(__file__).resolve().parent
    for script in ('v9_4e_collect_official.py','v9_9_8_opening_solver.py','v9_9_8_1_general_reconstruction.py','v9_9_6_1_reaudit.py','v9_9_5_integrated_reconstruction.py'):
        if not (root/script).is_file():p.error('Missing dependency: '+script)
    a.out.mkdir(parents=True,exist_ok=True)
    results=[]
    for i,r in enumerate(games,1):
        gid=(r.get('game_id') or '').strip();label=r.get('label','')
        if not re.fullmatch(r'\d{10}',gid):p.error('Invalid game ID: '+gid)
        folder=a.out/gid;folder.mkdir(parents=True,exist_ok=True)
        evidence=folder/'pilot'/'evidence';evidence.mkdir(parents=True,exist_ok=True)
        res={'game_id':gid,'label':label,'status':'PENDING','evidence_origin':'','regression_status':'NOT_SPECIFIED','reason':''}
        print(f'[{i}/{len(games)}] {gid} {label}',flush=True)
        try:
            existing=(r.get('evidence_dir') or '').strip()
            source=Path(existing).expanduser() if existing else None
            # Relative paths are relative to current working directory (Windows project root).
            if source and not a.force_collect:
                if not all((source/x).is_file() for x in CORE):
                    res.update(status='EVIDENCE_MISSING',reason='Missing source CSVs: '+str(source));raise RuntimeError('evidence missing')
                for x in CORE:
                    dest=evidence/x
                    if dest.resolve()!=(source/x).resolve():shutil.copy2(source/x,dest)
                res['evidence_origin']='COPIED_EXISTING_READ_ONLY'
            elif all((evidence/x).is_file() for x in CORE) and not a.force_collect:
                res['evidence_origin']='REUSED_BATCH_OUTPUT'
            else:
                rc=call('collection',[sys.executable,str(root/'v9_4e_collect_official.py'),'--game-id',gid,'--out',str(evidence.resolve()),'--skip-rotation','--retries','1'],folder)
                res['evidence_origin']='COLLECTED' if rc==0 else 'COLLECTION_RETURNED_NONZERO'
            if not all((evidence/x).is_file() and (evidence/x).stat().st_size>50 for x in CORE):
                res.update(status='COLLECTION_BLOCKED',reason='Core NBA CSV files absent');raise RuntimeError('core absent')
            rc=call('reaudit',[sys.executable,str(root/'v9_9_6_1_reaudit.py'),'--game-id',gid,'--pilot-dir',str((folder/'pilot').resolve()),'--reconstructor',str((root/'v9_9_8_1_general_reconstruction.py').resolve()),'--solver',str((root/'v9_9_8_opening_solver.py').resolve()),'--out',str((folder/'reaudit').resolve())],folder)
            summaryfile=folder/'reaudit'/'SUMMARY.json'
            if not summaryfile.is_file():res.update(status='ENGINE_ERROR',reason='No reaudit summary; inspect logs');raise RuntimeError('engine summary missing')
            s=json.loads(summaryfile.read_text(encoding='utf-8'));rec=s.get('reconstruction') or {}
            res.update(teams='|'.join(s.get('teams',[])),openings_integrated=s.get('openings_integrated'),expected_openings=s.get('expected_openings'),substitutions_in_source=rec.get('substitutions_in_source'),substitutions_applied=rec.get('substitutions_applied'),groups_blocked=rec.get('substitution_groups_blocked'),unresolved_openings=rec.get('unresolved_openings'),intervals_total=rec.get('intervals_total'),intervals_complete=rec.get('intervals_with_both_lineups'),issue_count=rec.get('issue_count'),minutes_players=s.get('minutes_players_with_official'),max_minutes_diff_seconds=s.get('max_player_minutes_difference_seconds'))
            if s.get('blocked_reasons'):res.update(status='OPENINGS_BLOCKED',reason='Quarter openings not unique or unavailable')
            elif rc or s.get('status')!='AUDIT_COMPLETED_UNVERIFIED':res.update(status='ENGINE_ERROR',reason=s.get('status','Reaudit returned error'))
            elif not s.get('pass_internal_replay') or not s.get('all_intervals_complete'):res.update(status='REPLAY_FAILED',reason='Substitution/interval audit failed')
            elif s.get('max_player_minutes_difference_seconds') is None:res.update(status='MINUTES_NOT_COMPARABLE',reason='No comparable official minutes')
            elif float(s['max_player_minutes_difference_seconds'])>a.minutes_tolerance:res.update(status='MINUTES_FAILED',reason='Minutes discrepancy exceeds tolerance')
            else:res.update(status='PASS_INTERNAL_UNVERIFIED',reason='Internal checks only; no independent lineup certification')
            expectation=(r.get('expected_status') or '').strip()
            if expectation:res['regression_status']='REGRESSION_PASSED' if res['status']==expectation else 'REGRESSION_FAILED'
        except RuntimeError:pass
        except Exception as ex:res.update(status='ENGINE_ERROR',reason=f'{type(ex).__name__}: {ex}')
        results.append(res);dump(folder/'BATCH_RESULT.json',res)
        print(f'  {res["status"]} | {res.get("substitutions_applied","?")}/{res.get("substitutions_in_source","?")} | minute_diff={res.get("max_minutes_diff_seconds","?")}',flush=True)
        publish(a.out,results,len(games),a.minutes_tolerance,True)
    publish(a.out,results,len(games),a.minutes_tolerance,False)
    print((a.out/'SUMMARY.json').read_text(encoding='utf-8'))
    return 0 if all(r['status']=='PASS_INTERNAL_UNVERIFIED' and r.get('regression_status')!='REGRESSION_FAILED' for r in results) else 2
if __name__=='__main__':sys.exit(main())
