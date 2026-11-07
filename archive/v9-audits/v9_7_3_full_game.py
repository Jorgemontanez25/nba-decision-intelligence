#!/usr/bin/env python3
"""V9.7.3 read-only, conditional NBA full-game lineup reconstruction.
No database writes. Known Q2-Q4 opening candidates for game 0022500002 are
supplied from independently inspected play-by-play; NOT certified official lineups.
"""
import argparse,csv,json,re,collections,pathlib,sys

Q_OPEN={
1:{'GSW':[201939,202710,203110,1630228,1641764],'LAL':[1629028,1629029,1629060,1629216,1630559]},
2:{'GSW':[202710,203110,1641764,1642366,1627741],'LAL':[1629216,1630559,1631222,1629020,1629637]},
3:{'GSW':[201939,202710,203110,1630228,1641764],'LAL':[1629028,1629029,1629060,1629216,1630559]},
4:{'GSW':[202710,203110,1627741,1641764,1642366],'LAL':[203935,1629020,1629029,1629637,1631222]},
}
CLOCK=re.compile(r'^PT(?:(\d+)M)?([\d.]+)S$',re.I)
SUB=re.compile(r'^\s*SUB:\s*(.*?)\s+FOR\s+(.*?)\s*$',re.I)
def rows(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write_csv(path,items,fields):
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(items)
def clock_remaining(value):
    m=CLOCK.match(str(value).strip());return int(m[1] or 0)*60+float(m[2]) if m else None
def norm(s):return re.sub('[^a-z0-9]','',str(s).casefold().replace('č','c').replace('ć','c').replace('ć','c'))
def choose_name(r):
    return (r.get('name') or r.get('nameI') or (r.get('firstName','')+' '+r.get('familyName','')).strip() or '').strip()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--game-id',required=True);ap.add_argument('--official-dir',required=True);ap.add_argument('--stints');ap.add_argument('--out',required=True);a=ap.parse_args()
    src=pathlib.Path(a.official_dir);out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=True)
    acts=rows(src/'playbyplayv3_dataset_0.csv');roster=rows(src/'boxscoretraditionalv3_dataset_0.csv')
    players={};teamids=collections.defaultdict(set)
    for r in roster:
        pid=str(r.get('personId','')).strip();team=str(r.get('teamTricode','')).strip().upper()
        if pid and team in ('LAL','GSW'):
            players[pid]=choose_name(r);teamids[team].add(pid)
    issues=[];audit=[];intervals=[];boundaries=[];states={}
    def issue(p,t,kind,detail,actions=''):
        issues.append(dict(period=p,team=t,issue=kind,detail=detail,action_numbers=actions))
    for p in range(1,5):
        if not all(str(x) in teamids[t] for t in ('GSW','LAL') for x in Q_OPEN[p][t]):issue(p,'BOTH','OPENING_ROSTER_MISMATCH','Opening candidate includes ID absent from box score')
        states={t:set(map(str,Q_OPEN[p][t])) for t in ('GSW','LAL')}
        for t in states:
            if len(states[t])!=5:issue(p,t,'INVALID_OPENING_SIZE',str(states[t]))
        entries=[]
        for i,r in enumerate(acts):
            if str(r.get('period','')).strip()!=str(p):continue
            rem=clock_remaining(r.get('clock',''))
            if rem is None:continue
            action=int(r.get('actionNumber') or 0)
            entries.append((720-rem,action,i,r))
        entries.sort(key=lambda z:(z[0],z[1],z[2]))
        subs_by_time=collections.defaultdict(list)
        for elapsed,action,i,r in entries:
            if str(r.get('actionType','')).strip().lower()=='substitution':subs_by_time[round(elapsed,4)].append((action,r))
        times=sorted(set([0.0,720.0]+[k for k in subs_by_time if 0<=k<=720]))
        for left,right in zip(times,times[1:]):
            if right>left:
                intervals.append(dict(period=p,start_seconds=round((p-1)*720+left,3),end_seconds=round((p-1)*720+right,3),duration_seconds=round(right-left,3),LAL_lineup='|'.join(sorted(states['LAL'],key=int)),GSW_lineup='|'.join(sorted(states['GSW'],key=int)),status='CONDITIONAL_UNVERIFIED',provenance=('OFFICIAL_Q1_STARTERS' if p==1 else 'Q_OPENING_PARTICIPATION_CANDIDATE')))
            batch=subs_by_time.get(round(right,4),[])
            for team in ('GSW','LAL'):
                group=sorted([(n,r) for n,r in batch if str(r.get('teamTricode','')).upper()==team],key=lambda x:x[0])
                if not group:continue
                before=set(states[team]);outgoing=[];incoming=[]
                for action,r in group:
                    match=SUB.match(str(r.get('description','')))
                    pid=str(r.get('personId','')).strip()
                    incoming_name=match.group(1).strip() if match else ''
                    outgoing_name=match.group(2).strip() if match else ''
                    candidates=[x for x in teamids[team] if norm(incoming_name)==norm(players.get(x,'')) or (incoming_name and norm(incoming_name)==norm(players.get(x,'').replace(' III','').replace(' II','')))]
                    if len(candidates)!=1:
                        # Description often abbreviates the first name; safe unique surname and optional suffix match.
                        candidates=[x for x in teamids[team] if incoming_name and (norm(incoming_name)==norm(' '.join(players.get(x,'').split()[1:])) or norm(incoming_name)==norm(players.get(x,'').split()[-1]))]
                    if len(candidates)!=1:issue(p,team,'INCOMING_RESOLUTION',f'{incoming_name}: {len(candidates)} matching roster IDs',action)
                    new=candidates[0] if len(candidates)==1 else ''
                    if pid not in before:issue(p,team,'OUTGOING_NOT_ON_COURT',f'{pid} {players.get(pid,"")} not in pre-group lineup',action)
                    if outgoing_name and pid in players:
                        last=players[pid].split()[-1]
                        if norm(last) not in norm(outgoing_name):issue(p,team,'OUTGOING_NAME_MISMATCH',f'{players[pid]} vs {outgoing_name}',action)
                    outgoing.append(pid)
                    if new:incoming.append(new)
                    audit.append(dict(period=p,elapsed_seconds=round((p-1)*720+right,3),action_number=action,team=team,outgoing_id=pid,outgoing_name=players.get(pid,''),incoming_id=new,incoming_name=players.get(new,''),recorded_description=r.get('description',''),parse_status='RESOLVED' if new else 'UNRESOLVED'))
                if len(set(outgoing))!=len(outgoing):issue(p,team,'DUPLICATE_OUTGOING',str(outgoing),','.join(str(n) for n,_ in group))
                if len(set(incoming))!=len(incoming):issue(p,team,'DUPLICATE_INCOMING',str(incoming),','.join(str(n) for n,_ in group))
                if set(incoming)&(before-set(outgoing)):issue(p,team,'INCOMING_ALREADY_PRESENT',str(set(incoming)&(before-set(outgoing))))
                after=(before-set(outgoing))|set(incoming)
                if len(after)!=5:issue(p,team,'INVALID_POST_GROUP_SIZE',f'{len(after)}: {sorted(after)}')
                boundaries.append(dict(period=p,elapsed_seconds=round((p-1)*720+right,3),team=team,actions='|'.join(str(n) for n,_ in group),pre_lineup='|'.join(sorted(before,key=int)),post_lineup='|'.join(sorted(after,key=int)),status='CONDITIONAL_UNVERIFIED'))
                states[team]=after
        # no automatic inference at quarter break
    # player minute checks provide diagnostics, never a way to pick lineups.
    minute_rows=[]
    official={}
    for r in roster:
        pid=str(r.get('personId','')).strip()
        if pid not in players:continue
        raw=str(r.get('minutes','')).strip();m=re.match(r'^(\d+):(\d+(?:\.\d+)?)$',raw)
        if m:official[pid]=int(m[1])*60+float(m[2])
    for pid,name in players.items():
        computed=sum(float(z['duration_seconds']) for z in intervals if pid in z['LAL_lineup'].split('|') or pid in z['GSW_lineup'].split('|'))
        target=official.get(pid)
        minute_rows.append(dict(player_id=pid,player_name=name,official_seconds=target if target is not None else '',conditional_seconds=round(computed,2),difference_seconds=round(computed-target,2) if target is not None else '',status='CONDITIONAL_ONLY'))
    compare=[]
    if a.stints and pathlib.Path(a.stints).exists():
        for r in rows(pathlib.Path(a.stints)):
            try:s=float(r['start_seconds']);e=float(r['end_seconds']);p=int(r['period'])
            except (ValueError,KeyError):continue
            matches=[x for x in intervals if x['period']==p and float(x['start_seconds'])<e-1e-6 and float(x['end_seconds'])>s+1e-6]
            for x in matches:
                overlap=min(e,float(x['end_seconds']))-max(s,float(x['start_seconds']))
                # Compare sets, not string ordering.
                same=all(set(str(r.get(f'{t.lower()}_lineup','')).split('|'))==set(x[f'{t}_lineup'].split('|')) for t in ('LAL','GSW'))
                compare.append(dict(period=p,provisional_start=s,provisional_end=e,reconstructed_start=x['start_seconds'],reconstructed_end=x['end_seconds'],overlap_seconds=round(overlap,3),result='MATCH_CONDITIONAL' if same else 'CONFLICT_REVIEW',confidence='UNVERIFIED'))
    write_csv(out/'substitution_audit.csv',audit,['period','elapsed_seconds','action_number','team','outgoing_id','outgoing_name','incoming_id','incoming_name','recorded_description','parse_status'])
    write_csv(out/'lineup_timeline_CONDITIONAL_UNVERIFIED.csv',intervals,['period','start_seconds','end_seconds','duration_seconds','LAL_lineup','GSW_lineup','status','provenance'])
    write_csv(out/'substitution_group_boundaries.csv',boundaries,['period','elapsed_seconds','team','actions','pre_lineup','post_lineup','status'])
    write_csv(out/'player_minutes_diagnostic.csv',minute_rows,['player_id','player_name','official_seconds','conditional_seconds','difference_seconds','status'])
    write_csv(out/'provisional_comparison.csv',compare,['period','provisional_start','provisional_end','reconstructed_start','reconstructed_end','overlap_seconds','result','confidence'])
    write_csv(out/'issues.csv',issues,['period','team','issue','detail','action_numbers'])
    summary=dict(version='9.7.3',game_id=a.game_id,mode='READ_ONLY_FULL_GAME_CONDITIONAL_RECONSTRUCTION',source_actions=len(acts),substitution_events=sum(str(r.get('actionType','')).strip().lower()=='substitution' for r in acts),substitutions_resolved=sum(x['parse_status']=='RESOLVED' for x in audit),substitutions_applied=len(audit),opening_lineup_status={'1':'OFFICIAL_Q1_STARTERS','2':'PARTICIPATION_DERIVED_CANDIDATES','3':'PARTICIPATION_DERIVED_CANDIDATES','4':'PARTICIPATION_DERIVED_CANDIDATES'},conditional_intervals=len(intervals),issue_count=len(issues),issue_types=dict(collections.Counter(x['issue'] for x in issues)),comparison_counts=dict(collections.Counter(x['result'] for x in compare)),verified_stints=0,publication_gate='BLOCKED_CONDITIONAL_OPENINGS_AND_SCORING_BOUNDARIES',database_modified=False,limitations=['Q2-Q4 opening candidates inferred from selected game evidence, not certified starting fives','Same-clock scoring attribution remains unresolved and is not fitted to plus/minus','Potential unrecorded substitutions are not ruled out','Report does not certify stints for production'])
    (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
