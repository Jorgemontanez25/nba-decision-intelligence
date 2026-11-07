#!/usr/bin/env python3
"""V9.9.3: conservative, read-only multi-team substitution reconstruction.
Unknown quarter openings remain unknown. Nothing is fit to plus/minus.
"""
import argparse,csv,json,re,unicodedata,hashlib
from pathlib import Path
from collections import defaultdict

def read(path):
    with path.open('r',encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(path,rows,fields):
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
def norm(v):
    v=unicodedata.normalize('NFKD',str(v or ''));v=''.join(c for c in v if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+',' ',v.lower()).strip()
def clock_secs(clock,period):
    m=re.fullmatch(r'PT(?:(\d+)M)?([0-9]+(?:\.[0-9]+)?)S',str(clock))
    if not m:raise ValueError('Invalid clock '+str(clock))
    length=720 if period<=4 else 300
    rem=int(m.group(1) or 0)*60+float(m.group(2))
    if rem<0 or rem>length+0.001:raise ValueError('Clock outside period '+str(clock))
    return round(length-rem,3)
def roster_data(box):
    roster=defaultdict(dict);positions={};names={}
    for row in box:
        team=str(row.get('teamTricode') or '').strip().upper();pid=str(row.get('personId') or '').strip()
        if not team or not pid:continue
        name=' '.join(filter(None,[row.get('firstName'),row.get('familyName')])).strip() or row.get('playerName') or row.get('nameI') or pid
        roster[team][pid]=name;names[pid]=name;positions[pid]=str(row.get('position') or '').strip()
    return roster,names,positions
def aliases(name):
    n=norm(name);parts=n.split();s={n}
    if len(parts)>1:
        s.add(' '.join(parts[1:]));s.add(parts[-1]);s.add(parts[0][0]+' '+parts[-1])
        if parts[-1] in ('ii','iii','iv','jr','sr') and len(parts)>=3:s.add(' '.join(parts[-2:]))
    return s
def incoming_id(description,team_roster):
    m=re.match(r'^\s*SUB:\s*(.+?)\s+FOR\s+(.+?)\s*$',str(description or ''),re.I)
    if not m:return None,'BAD_SUBSTITUTION_DESCRIPTION'
    incoming=norm(m.group(1));hits=[pid for pid,name in team_roster.items() if incoming in aliases(name)]
    if len(hits)!=1:return None,('AMBIGUOUS_INCOMING' if hits else 'UNKNOWN_INCOMING')
    return hits[0],''
def start_candidates(period,team,events,roster):
    """Conservative inference only: actors before first substitution AND first outgoing players.
    Five such players may be an opening candidate but are NEVER independently certified.
    """
    subs=[e for e in events if e['period_n']==period and e.get('actionType')=='Substitution' and e.get('teamTricode')==team]
    first=min((e['elapsed_n'] for e in subs),default=720 if period<=4 else 300)
    observed=set();evidence=[]
    for e in events:
        if e['period_n']!=period or e.get('teamTricode')!=team:continue
        pid=str(e.get('personId') or '').strip()
        if not pid or pid not in roster[team]:continue
        if e['elapsed_n']<first and e.get('actionType') not in ('Substitution','period'):
            observed.add(pid);evidence.append(str(e.get('actionNumber') or ''))
        if e.get('actionType')=='Substitution' and e['elapsed_n']==first:
            observed.add(pid)
    return observed,first,evidence

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game-id',required=True)
    ap.add_argument('--official-dir',required=True,type=Path)
    ap.add_argument('--out',required=True,type=Path)
    ap.add_argument('--openings',type=Path,help='Optional CSV columns: period,team,player_ids (five IDs separated by |). All user-supplied openings remain conditional.')
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    pbp=a.official_dir/'playbyplayv3_dataset_0.csv';boxpath=a.official_dir/'boxscoretraditionalv3_dataset_0.csv'
    if not pbp.is_file() or not boxpath.is_file():ap.error('Official play-by-play and box score CSVs are required')
    rows=read(pbp);box=read(boxpath);roster,names,pos=roster_data(box);teams=sorted(roster)
    if len(teams)!=2:ap.error('Expected exactly two teams in box score; got '+repr(teams))
    issues=[];trace=[];intervals=[];openings=[];minutes=[]
    def issue(code,p,t,detail,action=''):
        issues.append(dict(type=code,period=p,team=t,action_number=action,detail=str(detail)))
    events=[]
    for ix,row in enumerate(rows):
        if str(row.get('gameId') or a.game_id)!=a.game_id:continue
        try:p=int(row['period']);s=clock_secs(row['clock'],p)
        except (ValueError,KeyError) as ex:
            issue('BAD_EVENT_CLOCK','',row.get('teamTricode',''),ex,row.get('actionNumber',''));continue
        events.append(dict(row,period_n=p,elapsed_n=s,source_index=ix))
    events.sort(key=lambda e:(e['period_n'],e['elapsed_n'],int(e.get('actionNumber') or 0),e['source_index']))
    periods=sorted(set(e['period_n'] for e in events))
    user_open=defaultdict(dict)
    if a.openings:
        for r in read(a.openings):
            p=int(r['period']);t=r['team'].strip().upper();ids=set(r['player_ids'].split('|'))
            if t not in roster or len(ids)!=5 or not ids.issubset(roster[t]):ap.error('Invalid opening row '+str(r))
            user_open[p][t]=ids
    states={};opening_status={}
    for p in periods:
        states[p]={};opening_status[p]={}
        for t in teams:
            if p in user_open and t in user_open[p]:
                ids=user_open[p][t];status='USER_SUPPLIED_CONDITIONAL';first=None
            elif p==1:
                ids={pid for pid in roster[t] if norm(pos.get(pid)) in {'f','g','c','f g','g f','f c','c f'}}
                if len(ids)==5:status='BOX_SCORE_Q1_STARTERS';first=None
                else:ids=set();status='Q1_STARTERS_UNRESOLVED';first=None
            else:
                ids,first,_=start_candidates(p,t,events,roster)
                status='PARTICIPATION_DERIVED_CONDITIONAL' if len(ids)==5 else 'UNRESOLVED_OPENING'
                if len(ids)!=5:ids=set()
            states[p][t]=set(ids) if len(ids)==5 else None
            opening_status[p][t]=status
            openings.append(dict(period=p,team=t,status=status,identified_players=len(ids),player_ids='|'.join(sorted(ids)),player_names=' | '.join(names[i] for i in sorted(ids)),first_sub_elapsed=first if first is not None else ''))
            if states[p][t] is None:issue('UNRESOLVED_OPENING',p,t,status)
    grouped=defaultdict(list)
    for e in events:grouped[(e['period_n'],e['elapsed_n'])].append(e)
    applied=0;parsed=0;valid_groups=0;blocked=0
    for p in periods:
        period_length=720 if p<=4 else 300
        current={t:(set(states[p][t]) if states[p][t] is not None else None) for t in teams}
        prior=0.0
        clocks=sorted(set(s for pp,s in grouped if pp==p))
        for seconds in clocks+[float(period_length)]:
            if seconds>prior:
                intervals.append(dict(period=p,start_seconds=prior,end_seconds=seconds,duration_seconds=round(seconds-prior,3),**{t+'_lineup':'|'.join(sorted(current[t])) if current[t] is not None else '' for t in teams},status='CONDITIONAL_UNVERIFIED' if all(current[t] is not None for t in teams) else 'UNRESOLVED_OPENING_OR_STATE',provenance=';'.join(f'{t}:{opening_status[p][t]}' for t in teams)))
            if seconds==period_length:break
            subs=[e for e in grouped[(p,seconds)] if e.get('actionType')=='Substitution']
            candidate={t:(set(current[t]) if current[t] is not None else None) for t in teams}
            allvalid=True
            for t in teams:
                team_subs=[e for e in subs if e.get('teamTricode')==t]
                if not team_subs:continue
                outgoing=[];incoming=[];errs=[]
                for e in team_subs:
                    out=str(e.get('personId') or '').strip();inn,err=incoming_id(e.get('description',''),roster[t]);parsed+=not bool(err)
                    outgoing.append(out);incoming.append(inn)
                    if err:errs.append(err);issue(err,p,t,e.get('description',''),e.get('actionNumber',''))
                if candidate[t] is None:
                    issue('UNKNOWN_PRIOR_LINEUP',p,t,'Cannot apply substitutions without a valid opening',','.join(e.get('actionNumber','') for e in team_subs));allvalid=False;continue
                before=candidate[t];outs=set(outgoing);ins=set(incoming)
                if errs or len(outs)!=len(outgoing) or len(ins)!=len(incoming) or None in ins or not outs.issubset(before) or bool(ins & (before-outs)) or len((before-outs)|ins)!=5:
                    issue('INVALID_SUBSTITUTION_GROUP',p,t,f'before={sorted(before)} outgoing={outgoing} incoming={incoming}',','.join(e.get('actionNumber','') for e in team_subs))
                    candidate[t]=None;allvalid=False
                else:candidate[t]=(before-outs)|ins;applied+=len(team_subs)
            if subs:
                trace.append(dict(period=p,elapsed=seconds,clock=subs[0].get('clock',''),actions='|'.join(e.get('actionNumber','') for e in subs),status='APPLIED' if allvalid else 'BLOCKED',**{t+'_before':'|'.join(sorted(current[t])) if current[t] is not None else '' for t in teams},**{t+'_after':'|'.join(sorted(candidate[t])) if candidate[t] is not None else '' for t in teams}))
                valid_groups+=int(allvalid);blocked+=int(not allvalid)
            current=candidate;prior=seconds
    for t in teams:
        for pid in roster[t]:
            sec=sum((float(r['duration_seconds']) for r in intervals if pid in r[t+'_lineup'].split('|')),0.0)
            minutes.append(dict(team=t,player_id=pid,player_name=names[pid],conditional_seconds=round(sec,3),status='PARTIAL_UNVERIFIED' if any(r['status']!='CONDITIONAL_UNVERIFIED' for r in intervals) else 'CONDITIONAL_UNVERIFIED'))
    write(a.out/'opening_lineup_candidates.csv',openings,['period','team','status','identified_players','player_ids','player_names','first_sub_elapsed'])
    write(a.out/'lineup_timeline_CONDITIONAL_UNVERIFIED.csv',intervals,['period','start_seconds','end_seconds','duration_seconds',teams[0]+'_lineup',teams[1]+'_lineup','status','provenance'])
    write(a.out/'substitution_groups_trace.csv',trace,['period','elapsed','clock','actions','status',teams[0]+'_before',teams[1]+'_before',teams[0]+'_after',teams[1]+'_after'])
    write(a.out/'player_minutes_conditional.csv',minutes,['team','player_id','player_name','conditional_seconds','status'])
    write(a.out/'issues.csv',issues,['type','period','team','action_number','detail'])
    summary=dict(version='9.9.3',game_id=a.game_id,teams=teams,source_actions=len(events),substitutions_in_source=sum(e.get('actionType')=='Substitution' for e in events),substitutions_parsed=parsed,substitutions_applied=applied,substitution_groups_valid=valid_groups,substitution_groups_blocked=blocked,intervals_total=len(intervals),intervals_with_both_lineups=sum(r['status']=='CONDITIONAL_UNVERIFIED' for r in intervals),unresolved_openings=sum(x['status'] in ('UNRESOLVED_OPENING','Q1_STARTERS_UNRESOLVED') for x in openings),issue_count=len(issues),verified_stints=0,publication_gate='BLOCKED_UNVERIFIED_RECONSTRUCTION',database_modified=False,notes=['Q2+ openings are inference candidates, not established facts.','No plus/minus fitting or certification.','Unknown openings remain missing rather than invented.','This output is not production-ready.'])
    (a.out/'SUMMARY.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
