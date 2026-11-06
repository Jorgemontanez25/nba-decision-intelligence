#!/usr/bin/env python3
"""Out-of-sample second-game audit for V9.9.5; no database writes or certification."""
import argparse,csv,json,subprocess,sys
from pathlib import Path

def save(path,obj):path.write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding='utf-8')
def rows(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def run(label,cmd,dest):
    p=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace')
    (dest/(label+'.stdout.txt')).write_text(p.stdout,encoding='utf-8')
    (dest/(label+'.stderr.txt')).write_text(p.stderr,encoding='utf-8')
    print(label+': '+('OK' if p.returncode==0 else 'FAILED'),flush=True)
    return p.returncode

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--game-id',default='0022500018')
    p.add_argument('--out',type=Path,default=Path('v9_9_6_bos_nyk_pilot'))
    p.add_argument('--reuse-evidence',action='store_true')
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    root=Path(__file__).resolve().parent
    evidence=a.out/'evidence';evidence.mkdir(exist_ok=True)
    report={'game_id':a.game_id,'teams_expected':['BOS','NYK'] if a.game_id=='0022500018' else None,'collection':'PENDING','quarter_openings':{},'v995_status':'NOT_RUN','production_certified':False,'database_modified':False}
    required=[evidence/'playbyplayv3_dataset_0.csv',evidence/'boxscoretraditionalv3_dataset_0.csv']
    if not (a.reuse_evidence and all(x.exists() for x in required)):
        rc=run('collection',[sys.executable,str(root/'v9_4e_collect_official.py'),'--game-id',a.game_id,'--out',str(evidence.resolve()),'--skip-rotation','--retries','1'],a.out)
    else:rc=0
    if rc or not all(x.exists() for x in required):
        report['collection']='FAILED_OR_INCOMPLETE';report['next_action']='Inspect collection.stdout.txt and collection.stderr.txt';save(a.out/'SUMMARY.json',report);print(json.dumps(report,indent=2));return 1
    report['collection']='CORE_SOURCES_READY';box=rows(required[1]);teams=sorted({r['teamTricode'] for r in box if r.get('teamTricode')});report['teams_found']=teams
    if len(teams)!=2:
        report['v995_status']='BLOCKED_UNEXPECTED_TEAMS';save(a.out/'SUMMARY.json',report);return 1
    q2=None
    for quarter in (2,3,4):
        folder=a.out/('quarter_'+str(quarter));folder.mkdir(exist_ok=True)
        code=run('solver_Q'+str(quarter),[sys.executable,str(root/'v9_9_4_opening_solver.py'),'--game-id',a.game_id,'--official-dir',str(evidence.resolve()),'--period',str(quarter),'--out',str(folder.resolve())],a.out)
        if code or not (folder/'team_opening_summary.csv').exists():
            report['quarter_openings'][str(quarter)]={'status':'SOLVER_FAILED'};continue
        team_rows=rows(folder/'team_opening_summary.csv')
        report['quarter_openings'][str(quarter)]={r['team']:{'status':r['status'],'candidate_count':int(r['candidates_surviving'])} for r in team_rows}
        if quarter==2 and set(r['team'] for r in team_rows)==set(teams) and all(r['status']=='UNIQUE_CONDITIONAL' for r in team_rows):q2=folder/'opening_candidates_CONDITIONAL.csv'
    if q2 is None:
        report['v995_status']='BLOCKED_Q2_NOT_UNIQUE';report['next_action']='Inspect quarter_2/team_opening_summary.csv; do not force a candidate'
        save(a.out/'SUMMARY.json',report);print(json.dumps(report,indent=2));return 0
    result=a.out/'integrated_v995'
    rc=run('v995',[sys.executable,str(root/'v9_9_5_integrated_reconstruction.py'),'--game-id',a.game_id,'--official-dir',str(evidence.resolve()),'--q2-candidates',str(q2.resolve()),'--reconstructor',str(root/'v9_9_3_general_reconstruction.py'),'--out',str(result.resolve())],a.out)
    report['v995_status']='FAILED' if rc else 'EXECUTED_UNVERIFIED'
    summary_path=result/'SUMMARY.json'
    if summary_path.exists():
        report['v995_summary']=json.loads(summary_path.read_text(encoding='utf-8'))
        if 'issues' in report['v995_summary']:pass
    if (result/'player_minutes_comparison.csv').exists():
        diffs=[abs(float(r['difference_seconds'])) for r in rows(result/'player_minutes_comparison.csv') if r.get('difference_seconds') not in ('',None)]
        report['max_player_minutes_difference_seconds']=max(diffs) if diffs else None
    report['next_action']='Review SUMMARY.json and quarter opening candidate counts. Do not promote conditional lineups to verified.'
    save(a.out/'SUMMARY.json',report);print(json.dumps(report,indent=2));return 0 if rc==0 else 1
if __name__=='__main__':sys.exit(main())
