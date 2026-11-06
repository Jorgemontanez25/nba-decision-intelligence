#!/usr/bin/env python3
"""Read-only re-audit: apply unique solver candidates for every completed quarter.
Uses the existing V9.9.3 engine and official evidence. Never fits to box-score minutes or plus/minus.
"""
import argparse,csv,json,re,subprocess,sys
from pathlib import Path

def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(path,rows,cols):
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(rows)
def execute(label,cmd,out):
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace')
    (out/(label+'.stdout.txt')).write_text(p.stdout,encoding='utf-8')
    (out/(label+'.stderr.txt')).write_text(p.stderr,encoding='utf-8')
    print(f'{label}: {"OK" if p.returncode==0 else "FAILED"}',flush=True)
    return p.returncode

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--game-id',default='0022500018')
    p.add_argument('--pilot-dir',type=Path,default=Path('v9_9_6_bos_nyk_pilot'))
    p.add_argument('--out',type=Path,default=Path('v9_9_6_1_bos_nyk_reaudit'))
    p.add_argument('--reconstructor',type=Path,default=Path('v9_9_3_general_reconstruction.py'))
    p.add_argument('--solver',type=Path,default=Path('v9_9_4_opening_solver.py'))
    a=p.parse_args()
    if not re.fullmatch(r'\d{10}',a.game_id):p.error('game-id must be 10 digits')
    a.out.mkdir(parents=True,exist_ok=True)
    if a.pilot_dir.resolve()==a.out.resolve():p.error('Output folder must differ from original pilot')
    evidence=a.pilot_dir/'evidence'
    for fn in ('playbyplayv3_dataset_0.csv','boxscoretraditionalv3_dataset_0.csv'):
        if not (evidence/fn).is_file():p.error('Existing evidence missing: '+str(evidence/fn))
    for path in (a.reconstructor,a.solver):
        if not path.is_file():p.error('Script missing: '+str(path))
    box=read(evidence/'boxscoretraditionalv3_dataset_0.csv')
    teams={r['teamTricode'] for r in box if r.get('teamTricode') and r.get('personId')}
    if len(teams)!=2:p.error('Expected exactly 2 teams in official box score')
    eligible={t:{r['personId'] for r in box if r.get('teamTricode')==t and r.get('personId')} for t in teams}
    pbp=read(evidence/'playbyplayv3_dataset_0.csv')
    periods=sorted({int(r['period']) for r in pbp if str(r.get('period','')).isdigit()})
    openings=[];diagnostics=[];blocked=[]
    for quarter in (q for q in periods if q>1):
        folder=a.pilot_dir/f'quarter_{quarter}'
        candidate_file=folder/'opening_candidates_CONDITIONAL.csv'
        summary_file=folder/'team_opening_summary.csv'
        if not (candidate_file.is_file() and summary_file.is_file()):
            solver_dir=a.out/f'quarter_{quarter}';solver_dir.mkdir(exist_ok=True)
            rc=execute(f'solver_Q{quarter}',[sys.executable,str(a.solver.resolve()),'--game-id',a.game_id,'--official-dir',str(evidence.resolve()),'--period',str(quarter),'--out',str(solver_dir.resolve())],a.out)
            if rc:
                blocked.append(f'Q{quarter} solver failed; see solver_Q{quarter}.stderr.txt');continue
            candidate_file=solver_dir/'opening_candidates_CONDITIONAL.csv';summary_file=solver_dir/'team_opening_summary.csv'
        if not candidate_file.is_file() or not summary_file.is_file():
            blocked.append(f'Q{quarter}: solver output missing');continue
        summary={r['team']:r for r in read(summary_file)}
        candidates={t:[] for t in teams}
        for r in read(candidate_file):
            if str(r.get('period'))!=str(quarter) or r.get('team') not in teams:continue
            ids=r.get('opening_player_ids','').split('|')
            if r.get('status')=='CONDITIONAL_FEASIBLE' and len(ids)==5 and len(set(ids))==5 and set(ids).issubset(eligible[r['team']]):
                candidates[r['team']].append(ids)
        for t in sorted(teams):
            s=summary.get(t,{})
            unique=(s.get('status')=='UNIQUE_CONDITIONAL' and s.get('candidates_surviving')=='1' and len(candidates[t])==1)
            diagnostics.append(dict(period=quarter,team=t,solver_status=s.get('status','MISSING'),candidate_count=s.get('candidates_surviving',''),valid_candidates=len(candidates[t]),accepted=unique,player_ids='|'.join(candidates[t][0]) if unique else ''))
            if unique:openings.append(dict(period=quarter,team=t,player_ids='|'.join(candidates[t][0]),provenance='V9.9.4_CONDITIONAL_SOLVER'))
            else:blocked.append(f'Q{quarter} {t}: unique feasible candidate not established')
    write(a.out/'quarter_opening_audit.csv',diagnostics,['period','team','solver_status','candidate_count','valid_candidates','accepted','player_ids'])
    write(a.out/'all_quarter_openings_CONDITIONAL.csv',openings,['period','team','player_ids','provenance'])
    base={'version':'9.9.6.1','game_id':a.game_id,'teams':sorted(teams),'periods':periods,'openings_integrated':len(openings),'expected_openings':2*len([q for q in periods if q>1]),'blocked_reasons':blocked,'production_certified':False,'verified_stints':0,'database_modified':False,'publication_gate':'BLOCKED_UNVERIFIED_CONDITIONAL_OPENINGS_AND_BOUNDARY_ATTRIBUTION'}
    if blocked:
        base['status']='BLOCKED_AMBIGUOUS_OR_MISSING_OPENINGS'
        (a.out/'SUMMARY.json').write_text(json.dumps(base,indent=2),encoding='utf-8');print(json.dumps(base,indent=2));return 2
    dest=a.out/'reconstruction'
    rc=execute('reconstruction',[sys.executable,str(a.reconstructor.resolve()),'--game-id',a.game_id,'--official-dir',str(evidence.resolve()),'--openings',str((a.out/'all_quarter_openings_CONDITIONAL.csv').resolve()),'--out',str(dest.resolve())],a.out)
    if rc or not (dest/'SUMMARY.json').is_file():
        base['status']='RECONSTRUCTOR_FAILED';base['reconstructor_exit_code']=rc
        (a.out/'SUMMARY.json').write_text(json.dumps(base,indent=2),encoding='utf-8');print(json.dumps(base,indent=2));return 2
    reconstruction=json.loads((dest/'SUMMARY.json').read_text(encoding='utf-8'))
    import importlib.util
    spec=importlib.util.spec_from_file_location('v995_tools',Path(__file__).resolve().parent/'v9_9_5_integrated_reconstruction.py')
    if spec.origin and Path(spec.origin).is_file():
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        duration_seconds=mod.duration_seconds
    else:
        def duration_seconds(v):
            s=str(v or '').strip()
            m=re.fullmatch(r'(\d+):(\d+(?:\.\d+)?)',s)
            if m:return 60*int(m[1])+float(m[2])
            m=re.fullmatch(r'PT(?:(\d+)M)?(\d+(?:\.\d+)?)S',s)
            return 60*int(m[1] or 0)+float(m[2]) if m else None
    timeline=read(dest/'lineup_timeline_CONDITIONAL_UNVERIFIED.csv')
    seconds={(t,r['personId']):0.0 for t in teams for r in box if r.get('teamTricode')==t and r.get('personId')}
    for item in timeline:
        delta=float(item['end_seconds'])-float(item['start_seconds'])
        for t in teams:
            for pid in filter(None,item.get(t+'_lineup','').split('|')):
                seconds[(t,pid)]=seconds.get((t,pid),0)+delta
    minute_rows=[];diffs=[]
    for r in box:
        t=r.get('teamTricode');pid=r.get('personId')
        if (t,pid) not in seconds:continue
        official=duration_seconds(r.get('minutes'));actual=seconds[(t,pid)]
        diff=actual-official if official is not None else None
        if diff is not None:diffs.append(abs(diff))
        minute_rows.append(dict(team=t,player_id=pid,player_name=' '.join(filter(None,(r.get('firstName'),r.get('familyName')))),official_seconds='' if official is None else round(official,3),conditional_seconds=round(actual,3),difference_seconds='' if diff is None else round(diff,3),status='CONDITIONAL_UNVERIFIED'))
    write(a.out/'player_minutes_comparison.csv',minute_rows,['team','player_id','player_name','official_seconds','conditional_seconds','difference_seconds','status'])
    new_issues=read(dest/'issues.csv')
    old_issues=a.pilot_dir/'integrated_v995'/'issues.csv'
    old_count=len(read(old_issues)) if old_issues.is_file() else None
    base.update(status='AUDIT_COMPLETED_UNVERIFIED',reconstruction=reconstruction,previous_issues=old_count,current_issues=len(new_issues),max_player_minutes_difference_seconds=round(max(diffs),3) if diffs else None,minutes_players_with_official=len(diffs),all_substitutions_applied=(reconstruction['substitutions_applied']==reconstruction['substitutions_in_source']),all_intervals_complete=(reconstruction['intervals_with_both_lineups']==reconstruction['intervals_total']),pass_internal_replay=(reconstruction['issue_count']==0 and reconstruction['substitution_groups_blocked']==0 and reconstruction['unresolved_openings']==0 and reconstruction['substitutions_applied']==reconstruction['substitutions_in_source']),notes=['Official minutes are comparison-only; neither minutes nor +/- selected the opening candidates.','Substitution timestamp boundary attribution remains unresolved.','This script does not publish to production or modify any database.'])
    (a.out/'SUMMARY.json').write_text(json.dumps(base,indent=2),encoding='utf-8');print(json.dumps(base,indent=2));return 0
if __name__=='__main__':sys.exit(main())
