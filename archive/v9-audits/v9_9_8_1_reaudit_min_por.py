#!/usr/bin/env python3
"""V9.9.8.1: run revised identity solver + existing V9.9.6.1 read-only re-audit on MIN-POR.
Does not modify original V9.9.4, V9.9.7 or database. Reuses existing evidence.
"""
import argparse, json, re, subprocess, sys, csv
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--game-id',default='0022500089')
    p.add_argument('--batch-dir',type=Path,default=Path('v9_9_7_batch_review'))
    p.add_argument('--out',type=Path,default=Path('v9_9_8_min_por_reaudit'))
    a=p.parse_args()
    if not re.fullmatch(r'\d{10}',a.game_id):p.error('game-id must be 10 digits')
    root=Path(__file__).resolve().parent
    pilot=a.batch_dir/a.game_id/'pilot'
    evidence=pilot/'evidence'
    if not (evidence/'playbyplayv3_dataset_0.csv').is_file() or not (evidence/'boxscoretraditionalv3_dataset_0.csv').is_file():
        p.error('Missing official evidence in '+str(evidence))
    if a.out.resolve()==(a.batch_dir/a.game_id/'reaudit').resolve():p.error('Choose a NEW output directory')
    required=['v9_9_8_opening_solver.py','v9_9_6_1_reaudit.py','v9_9_8_1_general_reconstruction.py','v9_9_5_integrated_reconstruction.py']
    for name in required:
        if not (root/name).is_file():p.error('Missing '+name+' in '+str(root))
    a.out.mkdir(parents=True,exist_ok=True)
    # First, emit a transparent mapping of each in-game substitution to the team roster.
    sys.path.insert(0,str(root))
    from v9_9_8_opening_solver import load,resolve
    from collections import defaultdict
    box=load(evidence/'boxscoretraditionalv3_dataset_0.csv')
    roster=defaultdict(dict)
    for r in box:
        t=(r.get('teamTricode') or '').strip();pid=(r.get('personId') or '').strip()
        if t and pid:roster[t][pid]=' '.join(filter(None,[r.get('firstName'),r.get('familyName')])).strip()
    trace=[]
    for e in load(evidence/'playbyplayv3_dataset_0.csv'):
        if e.get('actionType')!='Substitution':continue
        team=e.get('teamTricode','');people=roster.get(team,{})
        incoming,error=resolve(e.get('description',''),people)
        outgoing=e.get('personId','')
        trace.append({'period':e.get('period',''),'action':e.get('actionNumber',''),'team':team,'clock':e.get('clock',''),'description':e.get('description',''),'outgoing_id':outgoing,'outgoing_name':people.get(outgoing,''),'incoming_id':incoming or '', 'incoming_name':people.get(incoming,'') if incoming else '', 'resolution_status':error or 'UNIQUE_MATCH'})
    with (a.out/'SUBSTITUTION_IDENTITY_AUDIT.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['period','action','team','clock','description','outgoing_id','outgoing_name','incoming_id','incoming_name','resolution_status']);w.writeheader();w.writerows(trace)
    cmd=[sys.executable,str(root/'v9_9_6_1_reaudit.py'),'--game-id',a.game_id,'--pilot-dir',str(pilot.resolve()),'--solver',str((root/'v9_9_8_opening_solver.py').resolve()),'--reconstructor',str((root/'v9_9_8_1_general_reconstruction.py').resolve()),'--out',str(a.out.resolve())]
    run=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace')
    (a.out/'RE_AUDIT.stdout.txt').write_text(run.stdout,encoding='utf-8')
    (a.out/'RE_AUDIT.stderr.txt').write_text(run.stderr,encoding='utf-8')
    orig=a.out/'SUMMARY.json'
    summary=json.loads(orig.read_text(encoding='utf-8')) if orig.is_file() else {}
    r=summary.get('reconstruction') or {}
    unresolved=[e for e in trace if e['resolution_status']!='UNIQUE_MATCH']
    report={'version':'9.9.8.1','game_id':a.game_id,'re_audit_exit_code':run.returncode,'status':summary.get('status','NO_SUMMARY'),'substitution_identifications':len(trace),'unresolved_incoming_identifications':len(unresolved),'all_substitutions_applied':summary.get('all_substitutions_applied',False),'applied':r.get('substitutions_applied'),'source_substitutions':r.get('substitutions_in_source'),'blocked_groups':r.get('substitution_groups_blocked'),'unresolved_openings':r.get('unresolved_openings'),'max_player_minutes_difference_seconds':summary.get('max_player_minutes_difference_seconds'),'pass_internal_replay':summary.get('pass_internal_replay',False),'passes_1sec_minutes_check':summary.get('max_player_minutes_difference_seconds') is not None and summary['max_player_minutes_difference_seconds']<=1.0,'production_certified':False,'verified_stints':0,'database_modified':False,'disclaimer':'A successful conditional replay is not independent historical lineup verification or boundary-scoring certification.'}
    (a.out/'V9981_RESULT.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    if run.returncode:print('Check RE_AUDIT.stderr.txt and quarter_2/team_opening_summary.csv',file=sys.stderr)
    return 0 if run.returncode==0 and report['pass_internal_replay'] and report['passes_1sec_minutes_check'] and not unresolved else 2
if __name__=='__main__':sys.exit(main())
