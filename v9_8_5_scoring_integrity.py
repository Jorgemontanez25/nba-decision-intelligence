#!/usr/bin/env python3
"""V9.8.5: read-only conditional lineup scoring attribution with auditable player assignments.

The quarter openings come from a CONDITIONAL timeline; this tool does not certify stints.
"""
import argparse, csv, json, re, unicodedata
from collections import Counter, defaultdict
from pathlib import Path

SCENARIOS = ('recorded', 'before', 'after')
TEAMS = ('LAL', 'GSW')

def load(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def save(path, rows, cols):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, cols, extrasaction='ignore'); w.writeheader(); w.writerows(rows)

def key(s):
    s = unicodedata.normalize('NFKD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()

def integer(v):
    try: return int(float(v))
    except (TypeError, ValueError): return 0

def elapsed(clock, period):
    m = re.fullmatch(r'PT(?:(\d+)M)?(\d+(?:\.\d+)?)S', str(clock).strip())
    if not m: raise ValueError(f'Invalid clock: {clock}')
    remaining = int(m.group(1) or 0)*60 + float(m.group(2))
    span = 720 if period <= 4 else 300
    return (period-1)*720 + span-remaining if period <= 4 else 2880+(period-5)*300+span-remaining

def roster_map(box):
    roster = defaultdict(dict)
    for r in box:
        team = r.get('teamTricode','').strip().upper(); pid = r.get('personId','').strip()
        if team not in TEAMS or not pid: continue
        name = r.get('name') or r.get('playerName') or (r.get('firstName','')+' '+r.get('familyName','')).strip()
        if name: roster[team][pid] = name
    return roster

def incoming_id(description, team_roster):
    m = re.match(r'^\s*SUB:\s*(.*?)\s+FOR\s+(.*?)\s*$', description or '', re.I)
    if not m: return None, 'BAD_SUB_DESCRIPTION'
    incoming = key(m.group(1)); found = []
    for pid, full in team_roster.items():
        n = key(full); parts = n.split(); aliases = {n}
        if parts: aliases.add(parts[-1])
        if len(parts)>1: aliases.add(' '.join(parts[1:]))
        if len(parts)>2 and parts[-1] in ('ii','iii','iv','jr','sr'):
            aliases.add(' '.join(parts[-2:]))
        if incoming in aliases or n.endswith(' '+incoming): found.append(pid)
    if len(found)==1: return found[0], None
    return None, 'AMBIGUOUS_INCOMING' if found else 'UNKNOWN_INCOMING'

def parse_set(value):
    return set(x.strip() for x in str(value).split('|') if x.strip())

def encode(players):
    return '|'.join(sorted(players, key=lambda x: integer(x)))

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game-id',required=True)
    ap.add_argument('--official-dir', type=Path,required=True)
    ap.add_argument('--timeline', type=Path,required=True)
    ap.add_argument('--out', type=Path,required=True)
    args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    events=load(args.official_dir/'playbyplayv3_dataset_0.csv')
    box=load(args.official_dir/'boxscoretraditionalv3_dataset_0.csv')
    timeline=load(args.timeline)
    roster=roster_map(box)
    openings={}; timeline_groups=defaultdict(list)
    for row in timeline:
        p=integer(row['period']);timeline_groups[p].append(row)
    for p,rows in timeline_groups.items():
        first=min(rows,key=lambda r:float(r['start_seconds']))
        openings[p]={t:parse_set(first[t+'_lineup']) for t in TEAMS}
    errors=[]; traces=[]; assigned=[]; pm={s:Counter() for s in SCENARIOS}
    score={'LAL':0,'GSW':0}; applied=0; parsed=0; boundary=0; boundary_changed=0; scoring_rows=0
    def err(kind,p,action,detail):
        errors.append(dict(type=kind,period=p,action_number=action,detail=detail))
    indexed=sorted(enumerate(events),key=lambda pair:(integer(pair[1].get('period')),elapsed(pair[1].get('clock'),integer(pair[1].get('period'))),integer(pair[1].get('actionNumber')),pair[0]))
    groups=defaultdict(list)
    for idx,r in indexed:
        groups[(integer(r.get('period')),r.get('clock',''))].append((idx,r))
    current={}; prior_period=None; fail=False
    for p,clock in sorted(groups,key=lambda k:(k[0],elapsed(k[1],k[0]))):
        if p != prior_period:
            if p not in openings:
                err('MISSING_OPENING',p,'','No opening in timeline');fail=True;break
            current={t:set(openings[p][t]) for t in TEAMS};prior_period=p
            if any(len(current[t])!=5 for t in TEAMS):
                err('INVALID_OPENING',p,'',str({t:encode(current[t]) for t in TEAMS}));fail=True;break
        rows=groups[(p,clock)]
        before={t:set(current[t]) for t in TEAMS}
        subs=[]
        for _,r in rows:
            if key(r.get('actionType')) != 'substitution':continue
            t=r.get('teamTricode','').strip().upper();out=r.get('personId','').strip();act=r.get('actionNumber','')
            if t not in TEAMS:err('INVALID_SUB_TEAM',p,act,t);fail=True;continue
            inc,why=incoming_id(r.get('description',''),roster[t]);parsed+=1
            if why:err(why,p,act,r.get('description',''));fail=True
            subs.append((r,t,out,inc))
        if fail:break
        # Apply each group's substitutions atomically to avoid transient illegal states.
        after={t:set(before[t]) for t in TEAMS}
        for t in TEAMS:
            ss=[s for s in subs if s[1]==t]
            outs=[s[2] for s in ss]; ins=[s[3] for s in ss]
            if not ss:continue
            missing=set(outs)-before[t]; present=set(ins)&(before[t]-set(outs))
            if len(set(outs))!=len(outs) or len(set(ins))!=len(ins):err('DUPLICATE_PLAYER_IN_GROUP',p,','.join(s[0]['actionNumber'] for s in ss),t);fail=True
            if missing:err('OUTGOING_ABSENT',p,','.join(s[0]['actionNumber'] for s in ss),t+':'+encode(missing));fail=True
            if present:err('INCOMING_ALREADY_ON_COURT',p,','.join(s[0]['actionNumber'] for s in ss),t+':'+encode(present));fail=True
            after[t]=(before[t]-set(outs))|set(ins)
            if len(after[t])!=5:err('ILLEGAL_LINEUP',p,','.join(s[0]['actionNumber'] for s in ss),t+':'+encode(after[t]));fail=True
        trace=dict(period=p,clock=clock,elapsed=round(elapsed(clock,p),3),actions='|'.join(s[0].get('actionNumber','') for s in subs),sub_count=len(subs))
        for t in TEAMS:trace[f'{t}_before']=encode(before[t]);trace[f'{t}_after']=encode(after[t])
        traces.append(trace)
        if fail:break
        # Each scoring event gets a separate valid recorded-order state.
        running={t:set(before[t]) for t in TEAMS}
        for _,r in rows:
            act=r.get('actionNumber','');typ=key(r.get('actionType'))
            if typ=='substitution':
                t=r.get('teamTricode','').strip().upper()
                s=next((s for s in subs if s[0] is r),None)
                if s:
                    running[t].discard(s[2]);running[t].add(s[3])
                continue
            raw_h=str(r.get('scoreHome','')).strip();raw_a=str(r.get('scoreAway','')).strip()
            if not raw_h and not raw_a:continue
            h=integer(raw_h) if raw_h else score['LAL']
            a=integer(raw_a) if raw_a else score['GSW']
            dh=h-score['LAL'];da=a-score['GSW']
            if dh<0 or da<0:err('SCORE_REGRESSION',p,act,f'{dh},{da}');fail=True;break
            score={'LAL':h,'GSW':a}
            if dh==0 and da==0:continue
            scoring_rows+=1
            scenarios={'recorded':running,'before':before,'after':after}
            actual_diff=before!=after
            if subs:boundary+=1
            if subs and actual_diff:boundary_changed+=1
            scorer=r.get('personId','').strip();team=r.get('teamTricode','').strip().upper()
            row=dict(period=p,clock=clock,action_number=act,action_type=r.get('actionType',''),description=r.get('description',''),scorer_id=scorer,scorer_team=team,LAL_points=dh,GSW_points=da,same_clock_subs=len(subs),boundary_changed=actual_diff)
            for scenario,sets in scenarios.items():
                for t in TEAMS:
                    players=sets[t];row[f'{scenario}_{t}_ids']=encode(players)
                    gain=dh-da if t=='LAL' else da-dh
                    for pid in players:pm[scenario][pid]+=gain
                    if len(players)!=5:err('EVENT_LINEUP_INVALID',p,act,f'{scenario}:{t}:{encode(players)}')
                present=team in TEAMS and scorer in sets[team]
                row[f'{scenario}_scorer_present']=present
                if team in TEAMS and not present:
                    err('SCORER_ABSENT_'+scenario.upper(),p,act,scorer)
            row['recorded_vs_before_changed']=any(row[f'recorded_{t}_ids']!=row[f'before_{t}_ids'] for t in TEAMS)
            row['recorded_vs_after_changed']=any(row[f'recorded_{t}_ids']!=row[f'after_{t}_ids'] for t in TEAMS)
            row['before_vs_after_changed']=any(row[f'before_{t}_ids']!=row[f'after_{t}_ids'] for t in TEAMS)
            assigned.append(row)
        if fail:break
        current=after;applied+=len(subs)
    playerrows=[]
    for r in box:
        t=r.get('teamTricode','').strip().upper();pid=r.get('personId','').strip()
        if t not in TEAMS or not pid:continue
        item=dict(player_id=pid,player_name=roster[t].get(pid,''),team=t,official_pm=integer(r.get('plusMinusPoints')))
        for s in SCENARIOS:
            item[f'{s}_pm']=pm[s][pid];item[f'{s}_delta']=pm[s][pid]-item['official_pm']
        playerrows.append(item)
    cols=['period','clock','action_number','action_type','description','scorer_id','scorer_team','LAL_points','GSW_points','same_clock_subs','boundary_changed']+[f'{s}_{t}_ids' for s in SCENARIOS for t in TEAMS]+[f'{s}_scorer_present' for s in SCENARIOS]+['recorded_vs_before_changed','recorded_vs_after_changed','before_vs_after_changed']
    save(args.out/'event_player_assignments.csv',assigned,cols)
    save(args.out/'boundary_differences.csv',[r for r in assigned if r['same_clock_subs']],cols)
    save(args.out/'substitution_groups_trace.csv',traces,['period','clock','elapsed','actions','sub_count','LAL_before','LAL_after','GSW_before','GSW_after'])
    save(args.out/'player_pm_comparison.csv',playerrows,['player_id','player_name','team','official_pm']+[x for s in SCENARIOS for x in (s+'_pm',s+'_delta')])
    save(args.out/'issues.csv',errors,['type','period','action_number','detail'])
    summary=dict(version='9.8.5',game_id=args.game_id,mode='READ_ONLY_CONDITIONAL_SCORING_ATTRIBUTION',status='FAILED_AUDIT' if fail or errors else 'AUDIT_COMPLETED_UNVERIFIED',substitutions_parsed=parsed,substitutions_applied=applied,scoring_events=scoring_rows,boundary_scoring_events=boundary,boundary_events_with_changed_lineups=boundary_changed,events_with_before_after_assignment_difference=sum(r['before_vs_after_changed'] for r in assigned),unassigned_events=sum(any(len(parse_set(r[f'{s}_{t}_ids']))!=5 for s in SCENARIOS for t in TEAMS) for r in assigned),issue_count=len(errors),final_score=score,scenario_results={s:dict(matched_players=sum(p[s+'_delta']==0 for p in playerrows),total_players=len(playerrows),absolute_pm_error=sum(abs(p[s+'_delta']) for p in playerrows)) for s in SCENARIOS},verified_stints=0,publication_gate='BLOCKED_CONDITIONAL_OPENINGS_AND_BOUNDARY_ATTRIBUTION',database_modified=False,notes=['Q2-Q4 opening lineups come from conditional timeline, not independently certified','Official plus/minus is used only for comparison, never scenario selection','Before/after attribution is a sensitivity test; neither establishes legal substitution effective time','All event-level player assignments are exported even on early audit failure'])
    (args.out/'SUMMARY.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))
    if fail or errors:raise SystemExit(2)

if __name__=='__main__':main()
