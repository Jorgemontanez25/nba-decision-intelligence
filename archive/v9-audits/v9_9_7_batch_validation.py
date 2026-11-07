#!/usr/bin/env python3
"""V9.9.7: read-only multi-game conditional reconstruction / minutes cross-check.
No plus-minus fitting, no database writes, no publication certification.
"""
import argparse,csv,json,re,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone

def load_csv(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def save_json(path,data):path.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
def run(label,args,folder):
    proc=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',errors='replace')
    (folder/(label+'.stdout.txt')).write_text(proc.stdout,encoding='utf-8')
    (folder/(label+'.stderr.txt')).write_text(proc.stderr,encoding='utf-8')
    return proc.returncode

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--games',type=Path,default=Path('v9_9_7_games.csv'))
    ap.add_argument('--out',type=Path,default=Path('v9_9_7_batch_review'))
    ap.add_argument('--max-games',type=int,default=3)
    ap.add_argument('--minutes-tolerance',type=float,default=1.0)
    ap.add_argument('--reuse-evidence',action='store_true',default=True,help='Reuse existing complete PBP+box CSVs (default).')
    ap.add_argument('--force-collect',action='store_true',help='Re-download evidence even when CSV files exist.')
    a=ap.parse_args()
    if not a.games.is_file():ap.error('Missing games manifest: '+str(a.games))
    if a.max_games<1 or a.minutes_tolerance<0:ap.error('Require max-games>=1 and minutes-tolerance>=0')
    games=load_csv(a.games)
    if not games:ap.error('Manifest is empty')
    for row in games[:a.max_games]:
        if not re.fullmatch(r'\d{10}',str(row.get('game_id',''))):ap.error('Invalid game_id: '+str(row))
    selected=games[:a.max_games]
    if len({r['game_id'] for r in selected})!=len(selected):ap.error('Duplicate game IDs')
    a.out.mkdir(parents=True,exist_ok=True)
    root=Path(__file__).resolve().parent
    prerequisites=['v9_4e_collect_official.py','v9_9_6_1_reaudit.py','v9_9_3_general_reconstruction.py','v9_9_4_opening_solver.py']
    for name in prerequisites:
        if not (root/name).is_file():ap.error('Missing script beside batch runner: '+name)
    results=[]
    for i,row in enumerate(selected,1):
        game=row['game_id'];folder=a.out/game;folder.mkdir(parents=True,exist_ok=True)
        pilot=folder/'pilot';evidence=pilot/'evidence';evidence.mkdir(parents=True,exist_ok=True)
        print(f'[{i}/{len(selected)}] game {game} ({row.get("label", "")})',flush=True)
        required=[evidence/'playbyplayv3_dataset_0.csv',evidence/'boxscoretraditionalv3_dataset_0.csv']
        result={'game_id':game,'label':row.get('label',''),'status':'NOT_RUN','evidence_reused':False,'publication_certified':False,'database_modified':False}
        if all(x.is_file() and x.stat().st_size>50 for x in required) and not a.force_collect:
            result['evidence_reused']=True
        else:
            rc=run('collection',[sys.executable,str((root/'v9_4e_collect_official.py').resolve()),'--game-id',game,'--out',str(evidence.resolve()),'--skip-rotation','--retries','1'],folder)
            result['collection_exit_code']=rc
        if not all(x.is_file() and x.stat().st_size>50 for x in required):
            result.update(status='COLLECTION_BLOCKED',reason='Missing official core CSV evidence; inspect collection logs')
        else:
            # The re-audit script solves Q2+ when the pilot/quarter_* outputs are absent.
            reaudit=folder/'reaudit'
            rc=run('reaudit',[sys.executable,str((root/'v9_9_6_1_reaudit.py').resolve()),'--game-id',game,'--pilot-dir',str(pilot.resolve()),'--reconstructor',str((root/'v9_9_3_general_reconstruction.py').resolve()),'--solver',str((root/'v9_9_4_opening_solver.py').resolve()),'--out',str(reaudit.resolve())],folder)
            summary_file=reaudit/'SUMMARY.json'
            result['reaudit_exit_code']=rc
            if not summary_file.is_file():result.update(status='ENGINE_ERROR',reason='No reaudit SUMMARY.json; inspect reaudit logs')
            else:
                summary=json.loads(summary_file.read_text(encoding='utf-8'))
                r=summary.get('reconstruction') or {}
                result.update(teams='|'.join(summary.get('teams',[])),openings_integrated=summary.get('openings_integrated'),expected_openings=summary.get('expected_openings'),substitutions_in_source=r.get('substitutions_in_source'),substitutions_applied=r.get('substitutions_applied'),groups_blocked=r.get('substitution_groups_blocked'),unresolved_openings=r.get('unresolved_openings'),intervals_total=r.get('intervals_total'),intervals_complete=r.get('intervals_with_both_lineups'),issue_count=r.get('issue_count'),minutes_players=summary.get('minutes_players_with_official'),max_minutes_diff_seconds=summary.get('max_player_minutes_difference_seconds'))
                if summary.get('status','').startswith('BLOCKED'):
                    result.update(status='OPENINGS_BLOCKED',reason='Ambiguous or missing opening candidates; see reaudit/quarter_opening_audit.csv')
                elif rc or summary.get('status')!='AUDIT_COMPLETED_UNVERIFIED':
                    result.update(status='ENGINE_ERROR',reason=summary.get('status','Re-audit subprocess failed'))
                elif not summary.get('pass_internal_replay') or not summary.get('all_intervals_complete'):
                    result.update(status='REPLAY_FAILED',reason='One or more substitution groups or intervals invalid')
                elif summary.get('max_player_minutes_difference_seconds') is None:
                    result.update(status='MINUTES_NOT_COMPARABLE',reason='No official minutes available')
                elif float(summary['max_player_minutes_difference_seconds'])>a.minutes_tolerance:
                    result.update(status='MINUTES_FAILED',reason='Max minutes difference exceeds configured tolerance')
                else:
                    result.update(status='PASS_INTERNAL_UNVERIFIED',reason='Internal replay and minutes tolerances passed; not certified')
        results.append(result)
        save_json(folder/'BATCH_RESULT.json',result)
        print(f'  {result["status"]} | applied={result.get("substitutions_applied","?")}/{result.get("substitutions_in_source","?")} | max_min_diff={result.get("max_minutes_diff_seconds","?")}',flush=True)
        write_results(a.out,results,a.minutes_tolerance,len(selected),partial=True)
    write_results(a.out,results,a.minutes_tolerance,len(selected),partial=False)
    print(json.dumps(json.loads((a.out/'SUMMARY.json').read_text(encoding='utf-8')),indent=2))
    return 0 if all(r['status']=='PASS_INTERNAL_UNVERIFIED' for r in results) else 2

def write_results(out,results,tolerance,requested,partial):
    cols=['game_id','label','status','teams','evidence_reused','openings_integrated','expected_openings','substitutions_in_source','substitutions_applied','groups_blocked','unresolved_openings','intervals_total','intervals_complete','issue_count','minutes_players','max_minutes_diff_seconds','reason']
    with (out/'GAME_RESULTS.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');writer.writeheader();writer.writerows(results)
    summary={'version':'9.9.7','mode':'READ_ONLY_MULTIGAME_CONDITIONAL_VALIDATION','created_utc':datetime.now(timezone.utc).isoformat(),'requested':requested,'processed':len(results),'partial':partial,'internal_passes':sum(r['status']=='PASS_INTERNAL_UNVERIFIED' for r in results),'not_passing':sum(r['status']!='PASS_INTERNAL_UNVERIFIED' for r in results),'minutes_tolerance_seconds':tolerance,'production_certified':False,'verified_stints':0,'database_modified':False,'reference_games_not_counted':'0022500002 and 0022500018 were previously tested outside this batch','results_file':'GAME_RESULTS.csv','caveat':'A passing internal replay is not independent lineup certification and does not resolve scoring boundary attribution.'}
    save_json(out/'SUMMARY.json',summary)

if __name__=='__main__':sys.exit(main())
