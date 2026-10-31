#!/usr/bin/env python3
"""V9.9.8: read-only, per-team quarter-opening candidate enumeration.
Constraints are official player actions and exact substitution membership. Does not fit minutes or +/-.
"""
import argparse,csv,json,re,itertools,unicodedata
from pathlib import Path
from collections import defaultdict

def load(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def save(p,rows,cols):
    with p.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(rows)
def norm(s):
    s=unicodedata.normalize('NFKD',str(s or ''))
    return re.sub(r'[^a-z0-9]+',' ',''.join(c for c in s if not unicodedata.combining(c)).lower()).strip()
def secs(s,p):
    m=re.fullmatch(r'PT(?:(\d+)M)?(\d+(?:\.\d+)?)S',str(s or ''))
    if not m:raise ValueError('bad clock: '+str(s))
    n=(720 if p<=4 else 300)-(int(m[1] or 0)*60+float(m[2]))
    if not -.001<=n<= (720 if p<=4 else 300)+.001:raise ValueError('clock out of period')
    return round(n,3)
def resolve(desc,players):
    m=re.match(r'^\s*SUB:\s*(.*?)\s+FOR\s+(.*?)\s*$',str(desc or ''),re.I)
    if not m:return None,'UNPARSEABLE_SUB'
    term=norm(m[1]);hits=[]
    for pid,name in players.items():
        n=norm(name);pieces=n.split();als={n}
        if len(pieces)>1:
            als.update({' '.join(pieces[1:]),pieces[-1],pieces[0],pieces[0][0]+' '+pieces[-1]})
            if pieces[-1] in ('ii','iii','iv','jr','sr') and len(pieces)>2:als.add(' '.join(pieces[-2:]))
        if term in als:hits.append(pid)
    return (hits[0],'') if len(hits)==1 else (None,('AMBIGUOUS_INCOMING' if hits else 'UNKNOWN_INCOMING'))
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game-id',required=True);ap.add_argument('--official-dir',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--period',type=int,default=2);ap.add_argument('--max-candidates',type=int,default=100000)
    args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    pbp=load(args.official_dir/'playbyplayv3_dataset_0.csv');box=load(args.official_dir/'boxscoretraditionalv3_dataset_0.csv')
    rosters=defaultdict(dict)
    for r in box:
        t=(r.get('teamTricode') or '').strip().upper();pid=str(r.get('personId') or '').strip()
        if t and pid:rosters[t][pid]=(' '.join(filter(None,(r.get('firstName'),r.get('familyName')))).strip() or r.get('nameI') or pid)
    events=[];issues=[];evidence=[];candidates=[];teamsummary=[];traces=[]
    for i,r in enumerate(pbp):
        if str(r.get('gameId') or args.game_id)!=args.game_id:continue
        try:p=int(r['period']);el=secs(r['clock'],p)
        except (ValueError,KeyError) as exc:issues.append(dict(team='',period='',type='INVALID_CLOCK',action=r.get('actionNumber',''),detail=str(exc)));continue
        if p==args.period:events.append(dict(r,p=p,elapsed=el,index=i))
    events.sort(key=lambda r:(r['elapsed'],int(r.get('actionNumber') or 0),r['index']))
    if not events:ap.error('No events for requested period')
    for team,players in sorted(rosters.items()):
        team_subs=[e for e in events if e.get('actionType')=='Substitution' and e.get('teamTricode')==team]
        first=min((e['elapsed'] for e in team_subs),default=(720 if args.period<=4 else 300))
        required=set();forbidden=set();byid=defaultdict(list)
        for e in events:
            if e.get('teamTricode')!=team:continue
            pid=str(e.get('personId') or '').strip();action=e.get('actionType','')
            # Only direct player events prior to first substitution are safe presence signals.
            # Team rebounds, period events and blank IDs are not player evidence.
            if e['elapsed']<first and pid in players and action not in ('period','Substitution'):
                required.add(pid);byid[pid].append(('DIRECT_ACTION',e.get('actionNumber',''),e['elapsed']))
        for e in team_subs:
            if e['elapsed']!=first:continue
            outgoing=str(e.get('personId') or '').strip();incoming,err=resolve(e.get('description'),players)
            if outgoing in players:required.add(outgoing);byid[outgoing].append(('FIRST_SUB_OUT',e.get('actionNumber',''),first))
            else:issues.append(dict(team=team,period=args.period,type='OUTGOING_NOT_IN_ROSTER',action=e.get('actionNumber',''),detail=outgoing))
            if err:issues.append(dict(team=team,period=args.period,type=err,action=e.get('actionNumber',''),detail=e.get('description','')))
            elif incoming:forbidden.add(incoming);byid[incoming].append(('FIRST_SUB_IN_EXCLUSION',e.get('actionNumber',''),first))
        for pid in sorted(required|forbidden):
            for typ,act,el in byid[pid]:evidence.append(dict(period=args.period,team=team,player_id=pid,player_name=players[pid],constraint=typ,action_number=act,elapsed=el))
        available=set(players)-forbidden
        if required & forbidden:issues.append(dict(team=team,period=args.period,type='CONTRADICTORY_MEMBERSHIP',action='',detail='|'.join(sorted(required&forbidden))))
        pool=sorted(available-required);need=5-len(required)
        feasible=0;valid=0;rejected=0;first_rejection='';examples=[]
        if 0<=need<=len(pool) and not(required&forbidden):
            feasible=__import__('math').comb(len(pool),need)
            # Enumerate all possible opening combinations, replaying entire period for each.
            if feasible>args.max_candidates:
                issues.append(dict(team=team,period=args.period,type='CANDIDATE_LIMIT',action='',detail=f'{feasible} initial combinations exceed max {args.max_candidates}'))
            else:
                group=defaultdict(list)
                for e in team_subs:group[e['elapsed']].append(e)
                for combo in itertools.combinations(pool,need):
                    state=set(required)|set(combo);good=True;why='';steps=0
                    for t in sorted(group):
                        outs=[];ins=[]
                        for e in group[t]:
                            out=str(e.get('personId') or '').strip();inn,err=resolve(e.get('description'),players)
                            if err:good=False;why=f'{err} action={e.get("actionNumber","")} description={e.get("description","")}';break
                            outs.append(out);ins.append(inn)
                        if not good:break
                        os=set(outs);ii=set(ins)
                        if len(os)!=len(outs) or len(ii)!=len(ins) or not os.issubset(state) or bool(ii & (state-os)) or len((state-os)|ii)!=5:
                            good=False;why=f'INVALID_SUB_GROUP at {t} actions={"|".join(str(x.get("actionNumber","")) for x in group[t])}';break
                        state=(state-os)|ii;steps+=1
                    if good:
                        valid+=1
                        row=dict(period=args.period,team=team,candidate_number=valid,status='CONDITIONAL_FEASIBLE',opening_player_ids='|'.join(sorted(set(required)|set(combo))),opening_player_names=' | '.join(players[x] for x in sorted(set(required)|set(combo))),substitution_groups_replayed=steps)
                        candidates.append(row)
                    else:
                        rejected+=1
                        if not first_rejection:first_rejection=why
        else:issues.append(dict(team=team,period=args.period,type='IMPOSSIBLE_OPENING_CONSTRAINTS',action='',detail=f'required={len(required)} forbidden={len(forbidden)} pool={len(pool)}'))
        status='UNIQUE_CONDITIONAL' if valid==1 else ('MULTIPLE_CONDITIONAL' if valid>1 else ('SEARCH_LIMIT' if feasible>args.max_candidates else 'NO_FEASIBLE_OPENING'))
        teamsummary.append(dict(period=args.period,team=team,first_sub_elapsed=first,required_count=len(required),required_ids='|'.join(sorted(required)),forbidden_count=len(forbidden),forbidden_ids='|'.join(sorted(forbidden)),initial_combinations=feasible,candidates_surviving=valid,candidates_rejected=rejected,status=status,first_rejection=first_rejection))
    save(args.out/'opening_constraints.csv',evidence,['period','team','player_id','player_name','constraint','action_number','elapsed'])
    save(args.out/'opening_candidates_CONDITIONAL.csv',candidates,['period','team','candidate_number','status','opening_player_ids','opening_player_names','substitution_groups_replayed'])
    save(args.out/'team_opening_summary.csv',teamsummary,['period','team','first_sub_elapsed','required_count','required_ids','forbidden_count','forbidden_ids','initial_combinations','candidates_surviving','candidates_rejected','status','first_rejection'])
    save(args.out/'issues.csv',issues,['team','period','type','action','detail'])
    summary=dict(version='9.9.8',game_id=args.game_id,period=args.period,mode='READ_ONLY_OPENING_CONSTRAINT_ENUMERATION',teams=teamsummary,issue_count=len(issues),verified_stints=0,publication_gate='BLOCKED_CONDITIONAL_OPENINGS',database_modified=False,limitations=['Event actor presence before first substitutions is necessary but not always sufficient.','An action timestamp does not independently determine substitution effective-time.','Unique feasible candidate is not independent certification.','No official minutes or plus/minus fitted.','If there are no feasible candidates, input evidence or assumptions need review.'])
    (args.out/'SUMMARY.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
