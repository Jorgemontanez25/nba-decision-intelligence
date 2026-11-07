#!/usr/bin/env python3
"""Read-only NBA V9.8.3: substitution replay and scoring attribution audit."""
import argparse,csv,json,re,unicodedata
from collections import defaultdict,Counter
from pathlib import Path

def read_csv(path):
    with open(path,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write_csv(path,rows,columns):
    with open(path,'w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore');w.writeheader();w.writerows(rows)
def norm(s):
    s=unicodedata.normalize('NFKD',str(s or ''));s=''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+',' ',s.lower()).strip()
def number(x):
    try:return int(float(x))
    except (ValueError,TypeError):return 0
def seconds(clock,period):
    m=re.fullmatch(r'PT(?:(\d+)M)?(\d+(?:\.\d+)?)S',str(clock or ''))
    if not m:raise ValueError('Invalid clock '+repr(clock))
    remaining=int(m.group(1) or 0)*60+float(m.group(2))
    periodlen=720 if period<=4 else 300
    return (period-1)*720+(periodlen-remaining) if period<=4 else 2880+(period-5)*300+(periodlen-remaining)
def roster_names(box):
    d=defaultdict(dict);names={}
    for r in box:
        team=r.get('teamTricode','').strip().upper(); pid=str(r.get('personId','')).strip()
        if not team or not pid:continue
        display=r.get('name') or r.get('playerName') or (' '.join([r.get('firstName',''),r.get('familyName','')]).strip())
        if display:
            d[team][pid]=display;names[pid]=display
    return d,names
def resolve_incoming(text,team_roster):
    m=re.match(r'^\s*SUB:\s*(.+?)\s+FOR\s+(.+?)\s*$',str(text or ''),re.I)
    if not m:return None,'BAD_DESCRIPTION'
    incoming=norm(m.group(1));candidates=[]
    for pid,name in team_roster.items():
        n=norm(name);parts=n.split(); aliases={n}
        if parts:aliases.add(parts[-1])
        if len(parts)>1:aliases.add(' '.join(parts[1:]))
        # NBA uses Butler III and Payton II in descriptions
        if len(parts)>2 and parts[-1] in ('ii','iii','iv','jr','sr'): aliases.add(' '.join(parts[-2:]))
        if incoming in aliases or n.endswith(' '+incoming):candidates.append(pid)
    if len(candidates)==1:return candidates[0],''
    return None,('AMBIGUOUS_INCOMING' if candidates else 'UNKNOWN_INCOMING')
def load_openings(timeline):
    periods=defaultdict(list)
    for r in timeline:
        periods[number(r.get('period'))].append(r)
    openings={}
    for p,rows in periods.items():
        first=min(rows,key=lambda r:float(r['start_seconds']))
        openings[p]={t:set(filter(None,first[t+'_lineup'].split('|'))) for t in ('LAL','GSW')}
    return openings

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game-id',required=True);ap.add_argument('--official-dir',type=Path,required=True)
    ap.add_argument('--timeline',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    events=read_csv(a.official_dir/'playbyplayv3_dataset_0.csv')
    box=read_csv(a.official_dir/'boxscoretraditionalv3_dataset_0.csv')
    timeline=read_csv(a.timeline)
    roster,names=roster_names(box);openings=load_openings(timeline)
    if not roster['GSW'] or not roster['LAL']:raise SystemExit('ERROR: Boxscore player roster absent; no audit results written.')
    issues=[];audit=[];scoring=[];pm={mode:Counter() for mode in ('recorded','before','after')}
    def issue(kind,period,action,detail):issues.append(dict(type=kind,period=period,action_number=action,detail=detail))
    # Action number may repeat across teams. Source order is authoritative for ties.
    events=sorted(enumerate(events),key=lambda pair:(number(pair[1].get('period')),seconds(pair[1].get('clock'),number(pair[1].get('period'))),number(pair[1].get('actionNumber')),pair[0]))
    groups=defaultdict(list)
    for _,r in events:groups[(number(r['period']),r.get('clock',''))].append(r)
    sorted_groups=sorted(groups,key=lambda k:(k[0],seconds(k[1],k[0])))
    current={};prior_score={'LAL':0,'GSW':0};affected=0;changed=0;applied=0;parsed=0;unassigned=0
    for period,clock in sorted_groups:
        if period not in openings:
            issue('MISSING_QUARTER_OPENING',period,'',f'Period {period} has no opening lineup');continue
        if current.get('_period')!=period:
            current={'_period':period,**{t:set(openings[period][t]) for t in ('LAL','GSW')}}
            for t in ('LAL','GSW'):
                if len(current[t])!=5:issue('INVALID_OPENING',period,'',f'{t}: {len(current[t])} players')
        rows=groups[(period,clock)];before={t:set(current[t]) for t in ('LAL','GSW')}
        substitutions=[]
        for r in rows:
            if norm(r.get('actionType'))!='substitution':continue
            team=str(r.get('teamTricode','')).upper();out=str(r.get('personId','')).strip();act=r.get('actionNumber','')
            if team not in ('LAL','GSW'):
                issue('UNKNOWN_TEAM',period,act,team);continue
            incoming,err=resolve_incoming(r.get('description',''),roster[team]);parsed+=not bool(err)
            if err:issue(err,period,act,r.get('description',''))
            substitutions.append((r,team,out,incoming,err))
        # Apply as one atomic group per team; permits chained and simultaneously swapped players.
        after={t:set(before[t]) for t in ('LAL','GSW')};valid=True
        for t in ('LAL','GSW'):
            team_subs=[x for x in substitutions if x[1]==t]
            outgoing=[x[2] for x in team_subs];incoming=[x[3] for x in team_subs]
            if any(x[4] for x in team_subs):valid=False;continue
            if len(outgoing)!=len(set(outgoing)) or len(incoming)!=len(set(incoming)):
                issue('DUPLICATE_GROUP_PLAYER',period,','.join(x[0].get('actionNumber','') for x in team_subs),t);valid=False;continue
            missing=set(outgoing)-before[t]
            existing=set(incoming)-(set(outgoing)| (set(roster[t])-before[t])) # checked below explicitly
            still_on=set(incoming)&(before[t]-set(outgoing))
            if missing:issue('OUTGOING_ABSENT',period,','.join(x[0].get('actionNumber','') for x in team_subs),f'{t}: {sorted(missing)}');valid=False
            if still_on:issue('INCOMING_ALREADY_ON_COURT',period,','.join(x[0].get('actionNumber','') for x in team_subs),f'{t}: {sorted(still_on)}');valid=False
            candidate=(before[t]-set(outgoing))|set(incoming)
            if len(candidate)!=5:issue('ILLEGAL_LINEUP_SIZE',period,','.join(x[0].get('actionNumber','') for x in team_subs),f'{t}: {len(candidate)}');valid=False
            after[t]=candidate
        if not valid:
            write_csv(a.out/'issues.csv',issues,['type','period','action_number','detail'])
            summary=dict(version='9.8.3',game_id=a.game_id,status='FAILED_SUBSTITUTION_STATE',first_invalid_period=period,first_invalid_clock=clock,issues=len(issues),substitutions_parsed=parsed,substitutions_applied=applied,publication_gate='BLOCKED')
            (a.out/'SUMMARY.json').write_text(json.dumps(summary,indent=2),encoding='utf8');print(json.dumps(summary,indent=2));raise SystemExit(2)
        for r,t,out,inc,err in substitutions:
            audit.append(dict(period=period,clock=clock,action_number=r.get('actionNumber'),team=t,outgoing_id=out,outgoing_name=names.get(out,''),incoming_id=inc,incoming_name=names.get(inc,''),state='VALID'))
        applied+=len(substitutions)
        seen=0
        for r in rows:
            if norm(r.get('actionType'))=='substitution':seen+=1
            hs=r.get('scoreHome','');aws=r.get('scoreAway','')
            if not str(hs).strip() and not str(aws).strip():continue
            home=number(hs) if str(hs).strip() else prior_score['LAL']
            away=number(aws) if str(aws).strip() else prior_score['GSW']
            hd,ad=home-prior_score['LAL'],away-prior_score['GSW']
            if hd<0 or ad<0:issue('SCORE_REGRESSION',period,r.get('actionNumber',''),str((hd,ad)))
            prior_score={'LAL':home,'GSW':away}
            if not(hd>0 or ad>0):continue
            if substitutions:affected+=1
            # Action-order replay state; individual substitutions at same clock applied sequentially.
            rec={t:set(before[t]) for t in ('LAL','GSW')}
            for sr,t,out,inc,err in substitutions:
                if number(sr['actionNumber'])<number(r.get('actionNumber')):
                    rec[t].discard(out);rec[t].add(inc)
            # Prevent partial within-group state from becoming implicit proof; report if invalid.
            if any(len(rec[t])!=5 for t in ('LAL','GSW')):issue('INVALID_RECORDED_EVENT_STATE',period,r.get('actionNumber',''),clock)
            scenarios={'recorded':rec,'before':before,'after':after}
            if substitutions and (rec!=before or rec!=after or before!=after):changed+=1
            scorer=str(r.get('personId','')).strip();scorer_team=str(r.get('teamTricode','')).upper()
            item=dict(period=period,clock=clock,action_number=r.get('actionNumber',''),action_type=r.get('actionType',''),description=r.get('description',''),scorer_id=scorer,scorer_team=scorer_team,LAL_points=hd,GSW_points=ad,same_clock_substitutions=len(substitutions),substitutions_before_action=seen)
            for mode,lineups in scenarios.items():
                for t in ('LAL','GSW'):
                    player_ids=sorted(lineups[t],key=lambda p:number(p));item[mode+'_'+t+'_ids']='|'.join(player_ids)
                    gain=(hd-ad) if t=='LAL' else (ad-hd)
                    for pid in player_ids:pm[mode][pid]+=gain
                if scorer_team in ('LAL','GSW') and scorer not in lineups[scorer_team]:
                    issue('SCORER_ABSENT_'+mode.upper(),period,r.get('actionNumber',''),f'{scorer} absent in {scorer_team}')
            item['before_after_different']=before!=after;item['recorded_before_different']=rec!=before;item['recorded_after_different']=rec!=after
            scoring.append(item)
        current=after
    bplayers=[]
    for r in box:
        pid=str(r.get('personId','')).strip();team=str(r.get('teamTricode','')).upper()
        if team not in ('GSW','LAL') or not pid:continue
        actual=number(r.get('plusMinusPoints',''))
        item=dict(player_id=pid,player_name=names.get(pid,''),team=team,official_pm=actual)
        for mode in pm:
            item[mode+'_pm']=pm[mode][pid];item[mode+'_delta']=pm[mode][pid]-actual
        bplayers.append(item)
    summary=dict(version='9.8.3',game_id=a.game_id,mode='READ_ONLY_INDEPENDENT_REPLAY',scoring_events=len(scoring),boundary_scoring_events=affected,boundary_events_with_scenario_changes=changed,substitutions_parsed=parsed,substitutions_applied=applied,issue_count=len(issues),final_score=prior_score,scenario_results={mode:{'matched_players':sum(x[mode+'_delta']==0 for x in bplayers),'total_players':len(bplayers),'absolute_pm_error':sum(abs(x[mode+'_delta']) for x in bplayers)} for mode in pm},verified_stints=0,publication_gate='BLOCKED_CONDITIONAL_OPENINGS_AND_BOUNDARIES',database_modified=False)
    write_csv(a.out/'substitution_audit.csv',audit,['period','clock','action_number','team','outgoing_id','outgoing_name','incoming_id','incoming_name','state'])
    cols=['period','clock','action_number','action_type','description','scorer_id','scorer_team','LAL_points','GSW_points','same_clock_substitutions','substitutions_before_action']+[f'{mode}_{t}_ids' for mode in pm for t in ('LAL','GSW')]+['before_after_different','recorded_before_different','recorded_after_different']
    write_csv(a.out/'event_player_assignments.csv',scoring,cols)
    write_csv(a.out/'boundary_differences.csv',[r for r in scoring if r['same_clock_substitutions']],cols)
    write_csv(a.out/'player_pm_comparison.csv',bplayers,['player_id','player_name','team','official_pm']+[z for mode in pm for z in (mode+'_pm',mode+'_delta')])
    write_csv(a.out/'issues.csv',issues,['type','period','action_number','detail'])
    (a.out/'SUMMARY.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
