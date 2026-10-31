#!/usr/bin/env python3
"""V9.8.4 read-only first-divergence tracer. Does not certify reconstructed stints."""
import argparse, csv, json, re, unicodedata
from pathlib import Path
from collections import defaultdict

def load(path):
    with open(path, newline='', encoding='utf-8-sig') as f: return list(csv.DictReader(f))
def save(path, rows, cols):
    with open(path,'w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(rows)
def norm(s):
    s=unicodedata.normalize('NFKD',str(s or ''))
    return re.sub(r'[^a-z0-9]+',' ',''.join(c for c in s if not unicodedata.combining(c)).lower()).strip()
def elapsed(clock,period):
    m=re.fullmatch(r'PT(?:(\d+)M)?(\d+(?:\.\d+)?)S',str(clock or ''))
    if not m: raise ValueError('Unexpected NBA clock: '+repr(clock))
    return (period-1)*720+720-(int(m[1] or 0)*60+float(m[2])) if period<=4 else 2880+(period-5)*300+300-(int(m[1] or 0)*60+float(m[2]))
def roster_index(rows):
    by_team=defaultdict(dict)
    for r in rows:
        team=str(r.get('teamTricode') or '').strip().upper(); pid=str(r.get('personId') or '').strip()
        if not pid or not team: continue
        name=r.get('name') or r.get('playerName') or (str(r.get('firstName') or '')+' '+str(r.get('familyName') or '')).strip()
        if name: by_team[team][pid]=name
    return by_team
def incoming_from_description(description, teamroster):
    m=re.match(r'^\s*SUB:\s*(.+?)\s+FOR\s+(.+?)\s*$',description or '',re.I)
    if not m: return None,'INVALID_DESCRIPTION'
    query=norm(m[1]); matches=[]
    for pid,name in teamroster.items():
        n=norm(name); p=n.split(); alias={n}
        if p: alias.add(p[-1])
        if len(p)>1: alias.add(' '.join(p[1:]))
        if len(p)>2 and p[-1] in {'ii','iii','iv','jr','sr'}: alias.add(' '.join(p[-2:]))
        if query in alias or n.endswith(' '+query): matches.append(pid)
    return (matches[0],'') if len(matches)==1 else (None,'UNRESOLVED_INCOMING:'+query+':'+','.join(matches))
def fmt(players): return '|'.join(sorted(players,key=lambda x:int(x)))

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game-id',required=True);ap.add_argument('--official-dir',type=Path,required=True)
    ap.add_argument('--timeline',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    actions=load(args.official_dir/'playbyplayv3_dataset_0.csv')
    roster=roster_index(load(args.official_dir/'boxscoretraditionalv3_dataset_0.csv'))
    timeline=load(args.timeline)
    timeline_by_period=defaultdict(list)
    for r in timeline: timeline_by_period[int(r['period'])].append(r)
    for rows in timeline_by_period.values(): rows.sort(key=lambda r:float(r['start_seconds']))
    if not timeline_by_period or not roster['LAL'] or not roster['GSW']: raise SystemExit('Missing team roster or reconstructed timeline')
    source={}
    for idx,a in enumerate(actions):
        if a.get('actionType','').strip().lower()!='substitution': continue
        p=int(a['period']); key=(p,a['clock']); source.setdefault(key,[]).append((int(a['actionNumber']),idx,a))
    details=[];groups=[];first=None;bad_groups=0;compared=0;subcount=0
    for period in sorted(timeline_by_period):
        firstrow=timeline_by_period[period][0]
        current={t:set(firstrow[t+'_lineup'].split('|')) for t in ('LAL','GSW')}
        # Separate quarter initializations: Q2-Q4 are CONDITIONAL candidate inputs.
        for (p,clock), acts in sorted(source.items(),key=lambda kv:(kv[0][0],elapsed(kv[0][1],kv[0][0]))):
            if p!=period: continue
            acts.sort(key=lambda x:(x[0],x[1])); sec=elapsed(clock,period)
            before={t:set(current[t]) for t in ('LAL','GSW')}; after={t:set(current[t]) for t in ('LAL','GSW')}
            rowdetail=[];problems=[]
            for action_number,_,a in acts:
                team=str(a.get('teamTricode') or '').strip().upper(); out=str(a.get('personId') or '').strip()
                inc,error=incoming_from_description(a.get('description'),roster.get(team,{}))
                if team not in ('LAL','GSW'): error='UNKNOWN_TEAM'
                row=dict(period=period,clock=clock,elapsed=round(sec,3),action_number=action_number,team=team,
                    description=a.get('description'),outgoing_id=out,outgoing_name=roster.get(team,{}).get(out,''),
                    incoming_id=inc or '',incoming_name=roster.get(team,{}).get(inc,'') if inc else '',parse_error=error)
                details.append(row);rowdetail.append(row);subcount+=1
                if error:problems.append('action '+str(action_number)+': '+error)
            # Atomic replacement by team, with explicit membership checks.
            for t in ('LAL','GSW'):
                these=[r for r in rowdetail if r['team']==t]
                outs=[r['outgoing_id'] for r in these];ins=[r['incoming_id'] for r in these]
                if not these: continue
                if len(outs)!=len(set(outs)) or len(ins)!=len(set(ins)):problems.append(t+': duplicate substitutions')
                for outgoing in outs:
                    if outgoing not in before[t]:problems.append(t+': outgoing missing '+outgoing)
                for incoming in ins:
                    if not incoming or incoming in (before[t]-set(outs)):problems.append(t+': incoming invalid '+incoming)
                after[t]=(before[t]-set(outs))|set(ins)
                if len(after[t])!=5:problems.append(t+': lineup size '+str(len(after[t])))
            if problems:bad_groups+=1
            # A substitution at time sec takes effect for the interval beginning at sec.
            expected=next((r for r in timeline_by_period[period] if float(r['start_seconds'])-0.11<=sec<float(r['end_seconds'])-1e-8),None)
            divergence=[]
            if expected:
                compared+=1
                for t in ('LAL','GSW'):
                    if after[t]!=set(expected[t+'_lineup'].split('|')):divergence.append(t)
            else:divergence.append('NO_TIMELINE_INTERVAL')
            record=dict(period=period,clock=clock,elapsed=round(sec,3),actions='|'.join(str(x[0]) for x in acts),
                LAL_before=fmt(before['LAL']),LAL_replayed_after=fmt(after['LAL']),
                LAL_timeline_after=expected['LAL_lineup'] if expected else '',
                GSW_before=fmt(before['GSW']),GSW_replayed_after=fmt(after['GSW']),
                GSW_timeline_after=expected['GSW_lineup'] if expected else '',
                divergence='|'.join(divergence),issues='; '.join(problems))
            groups.append(record)
            if first is None and (divergence or problems):first=record
            # Stop replaying at first invalid state; still export all evidence gathered.
            if problems: break
            current=after
        if bad_groups:break
    detailcols=['period','clock','elapsed','action_number','team','description','outgoing_id','outgoing_name','incoming_id','incoming_name','parse_error']
    groupcols=['period','clock','elapsed','actions','LAL_before','LAL_replayed_after','LAL_timeline_after','GSW_before','GSW_replayed_after','GSW_timeline_after','divergence','issues']
    save(args.out/'substitution_events_trace.csv',details,detailcols)
    save(args.out/'substitution_groups_trace.csv',groups,groupcols)
    summary={'version':'9.8.4','game_id':args.game_id,'status':'READ_ONLY_DIAGNOSTIC','substitution_records_examined':subcount,'groups_compared':compared,'invalid_groups':bad_groups,'first_divergence':first,'publication_gate':'BLOCKED_UNVERIFIED_STINTS','database_modified':False}
    (args.out/'SUMMARY.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
