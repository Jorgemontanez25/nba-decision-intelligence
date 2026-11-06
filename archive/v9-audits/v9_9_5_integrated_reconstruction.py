#!/usr/bin/env python3
"""V9.9.5 read-only integration of V9.9.4 Q2 conditional openings and V9.9.3 replay.
Uses official play-by-play/box-score for evidence. Does NOT certify stints or fit plus/minus.
"""
import argparse,csv,json,subprocess,sys,re
from pathlib import Path
from collections import defaultdict


def load(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def save(path,rows,columns):
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore');w.writeheader();w.writerows(rows)

def duration_seconds(v):
    s=str(v or '').strip()
    if not s:return None
    m=re.fullmatch(r'(\d+):(\d+(?:\.\d+)?)',s)
    if m:return 60*int(m[1])+float(m[2])
    m=re.fullmatch(r'PT(?:(\d+)M)?(\d+(?:\.\d+)?)S',s)
    if m:return 60*int(m[1] or 0)+float(m[2])
    try:return 60*float(s)
    except ValueError:return None

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--game-id',required=True)
    p.add_argument('--official-dir',type=Path,required=True)
    p.add_argument('--q2-candidates',type=Path,required=True)
    p.add_argument('--reconstructor',type=Path,default=Path('v9_9_3_general_reconstruction.py'))
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    if not re.fullmatch(r'\d{10}',args.game_id):p.error('Game ID should have 10 digits')
    args.out.mkdir(parents=True,exist_ok=True)
    source=args.official_dir
    for fn in ['playbyplayv3_dataset_0.csv','boxscoretraditionalv3_dataset_0.csv']:
        if not (source/fn).is_file():p.error('Missing '+str(source/fn))
    if not args.reconstructor.is_file():p.error('Missing V9.9.3 script '+str(args.reconstructor))
    rows=load(args.q2_candidates)
    chosen={};issues=[]
    for row in rows:
        if str(row.get('period'))!='2':continue
        team=str(row.get('team','')).strip().upper()
        ids=str(row.get('opening_player_ids','')).split('|')
        if str(row.get('status',''))!='CONDITIONAL_FEASIBLE' or len(ids)!=5 or len(set(ids))!=5 or not all(ids):
            issues.append(dict(type='INVALID_Q2_CANDIDATE',period=2,team=team,action_number='',detail=str(row)));continue
        chosen.setdefault(team,[]).append(ids)
    box=load(source/'boxscoretraditionalv3_dataset_0.csv')
    rosters=defaultdict(set);teams=set();box_minutes={};names={}
    for r in box:
        team=str(r.get('teamTricode','')).upper();pid=str(r.get('personId',''))
        if team and pid:
            rosters[team].add(pid);teams.add(team);box_minutes[(team,pid)]=duration_seconds(r.get('minutes'))
            names[(team,pid)]=' '.join(filter(None,(r.get('firstName'),r.get('familyName')))).strip() or pid
    if len(teams)!=2:p.error('Expected 2 box-score teams')
    if set(chosen)!=teams or any(len(chosen.get(t,[]))!=1 for t in teams):
        p.error('Require exactly ONE conditional Q2 candidate per box-score team: '+repr({k:len(v) for k,v in chosen.items()}))
    if any(set(chosen[t][0])-rosters[t] for t in teams):p.error('Q2 candidates include IDs not in official team roster')
    opening_path=args.out/'q2_openings_CONDITIONAL.csv'
    save(opening_path,[dict(period=2,team=t,player_ids='|'.join(chosen[t][0])) for t in sorted(teams)],['period','team','player_ids'])
    run_dir=args.out/'reconstruction'
    cmd=[sys.executable,str(args.reconstructor.resolve()),'--game-id',args.game_id,'--official-dir',str(source.resolve()),'--openings',str(opening_path.resolve()),'--out',str(run_dir.resolve())]
    r=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace')
    (args.out/'reconstructor.stdout.txt').write_text(r.stdout,encoding='utf-8')
    (args.out/'reconstructor.stderr.txt').write_text(r.stderr,encoding='utf-8')
    if r.returncode!=0:
        s=dict(version='9.9.5',game_id=args.game_id,status='RECONSTRUCTOR_FAILED',exit_code=r.returncode,publication_gate='BLOCKED',database_modified=False)
        (args.out/'SUMMARY.json').write_text(json.dumps(s,indent=2),encoding='utf-8');print(json.dumps(s,indent=2));sys.exit(1)
    base=json.loads((run_dir/'SUMMARY.json').read_text(encoding='utf-8'))
    timeline=load(run_dir/'lineup_timeline_CONDITIONAL_UNVERIFIED.csv')
    events=load(source/'playbyplayv3_dataset_0.csv')
    from importlib.util import spec_from_file_location,module_from_spec
    spec=spec_from_file_location('reconstruction_tools',args.reconstructor.resolve());module=module_from_spec(spec);spec.loader.exec_module(module)
    mins=defaultdict(float);intervals=defaultdict(list)
    for line in timeline:
        period=int(line['period']);start=float(line['start_seconds']);end=float(line['end_seconds'])
        for team in teams:
            ids=set(filter(None,line.get(team+'_lineup','').split('|')))
            if ids:
                for pid in ids:mins[(team,pid)]+=end-start
            intervals[period].append((start,end,team,ids))
    minutes_rows=[]
    for team in sorted(teams):
        for pid in sorted(rosters[team]):
            official=box_minutes[(team,pid)];conditional=round(mins[(team,pid)],3)
            minutes_rows.append(dict(team=team,player_id=pid,player_name=names[(team,pid)],official_seconds='' if official is None else round(official,3),conditional_seconds=conditional,difference_seconds='' if official is None else round(conditional-official,3),status='CONDITIONAL_UNVERIFIED'))
    save(args.out/'player_minutes_comparison.csv',minutes_rows,['team','player_id','player_name','official_seconds','conditional_seconds','difference_seconds','status'])
    # Presence is checked in the state BEFORE actions at that clock, plus the state AFTER;
    # scoring at a substitution clock is intentionally classified as boundary-sensitive.
    sub_keys=set()
    for e in events:
        if e.get('actionType')=='Substitution':
            try:sub_keys.add((int(e['period']),module.clock_secs(e['clock'],int(e['period']))))
            except (ValueError,KeyError):pass
    scoring=[];uncovered=0;missing_nonboundary=0
    for e in events:
        if e.get('actionType') not in ('Made Shot','Free Throw'):continue
        try:
            period=int(e['period']);el=module.clock_secs(e['clock'],period)
        except (ValueError,KeyError):continue
        team=str(e.get('teamTricode','')).upper();pid=str(e.get('personId',''))
        if team not in teams or pid not in rosters[team]:continue
        # Only actual points scored. Missed free throws / non-scoring events excluded.
        if e.get('actionType')=='Made Shot' and str(e.get('shotResult','')).lower()=='missed':continue
        if e.get('actionType')=='Free Throw' and ('MISS' in str(e.get('description','')).upper() or str(e.get('shotResult','')).lower()=='missed'):continue
        before=[ids for st,en,t,ids in intervals[period] if t==team and st<el<=en+1e-8]
        after=[ids for st,en,t,ids in intervals[period] if t==team and st<=el<en]
        before_state=before[-1] if before else set();after_state=after[0] if after else set()
        boundary=(period,el) in sub_keys
        present_before=pid in before_state;present_after=pid in after_state
        if not before_state and not after_state:uncovered+=1
        if not boundary and not (present_before or present_after):missing_nonboundary+=1
        scoring.append(dict(period=period,clock=e.get('clock'),action_number=e.get('actionNumber'),team=team,scorer_id=pid,scorer_name=names.get((team,pid),pid),boundary_substitution=boundary,scorer_in_before=present_before,scorer_in_after=present_after,assessment='BOUNDARY_UNRESOLVED' if boundary else ('PRESENT' if present_before or present_after else 'ABSENT_OR_UNKNOWN')))
    save(args.out/'scorer_presence_diagnostic.csv',scoring,['period','clock','action_number','team','scorer_id','scorer_name','boundary_substitution','scorer_in_before','scorer_in_after','assessment'])
    prior_issues=load(run_dir/'issues.csv');issues.extend(prior_issues)
    save(args.out/'issues.csv',issues,['type','period','team','action_number','detail'])
    s=dict(version='9.9.5',game_id=args.game_id,mode='READ_ONLY_CONDITIONAL_FULL_GAME_INTEGRATION',status='AUDIT_COMPLETED_UNVERIFIED',teams=sorted(teams),q2_candidates_integrated=2,source_actions=base['source_actions'],substitutions_in_source=base['substitutions_in_source'],substitutions_parsed=base['substitutions_parsed'],substitutions_applied=base['substitutions_applied'],substitution_groups_valid=base['substitution_groups_valid'],substitution_groups_blocked=base['substitution_groups_blocked'],unresolved_openings=base['unresolved_openings'],intervals_total=base['intervals_total'],intervals_with_both_lineups=base['intervals_with_both_lineups'],diagnostic_scoring_events=len(scoring),scoring_with_unknown_both_states=uncovered,nonboundary_scorer_absent_or_unknown=missing_nonboundary,boundary_scoring_events=sum(row['boundary_substitution'] for row in scoring),minutes_players_with_official=sum(x['official_seconds']!='' for x in minutes_rows),issue_count=len(issues),verified_stints=0,publication_gate='BLOCKED_CONDITIONAL_OPENINGS_AND_BOUNDARY_ATTRIBUTION',database_modified=False,limitations=['Q2 candidates come from V9.9.4 constraint inference, not independent lineup certification.','Q3/Q4 candidates remain conditional, and scorer presence is not a legal substitution-time proof.','Event-based intervals may contain many rows; those are not independently verified stints.','Official minutes are comparison-only; plus/minus is not used to select lineups.'])
    (args.out/'SUMMARY.json').write_text(json.dumps(s,indent=2),encoding='utf-8');print(json.dumps(s,indent=2))

if __name__=='__main__':main()
