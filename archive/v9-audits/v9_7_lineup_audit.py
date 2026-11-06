#!/usr/bin/env python3
"""V9.7 read-only NBA substitution-state reconstruction audit.

Does not certify scoring attribution or infer hidden quarter-opening lineups.
"""
import argparse,csv,json,re,unicodedata
from pathlib import Path
from collections import defaultdict

def read_csv(p):
    with open(p,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write_csv(p,rows,cols):
    with open(p,'w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(rows)
def norm(s):
    s=unicodedata.normalize('NFKD',str(s or ''));s=''.join(x for x in s if not unicodedata.combining(x));return re.sub(r'[^a-z0-9]+',' ',s.lower()).strip()
def fnum(s,default=None):
    try:return float(s)
    except (TypeError,ValueError):return default
def clock_elapsed(period,clock):
    m=re.fullmatch(r'PT(\d+)M(\d+(?:\.\d+)?)S',str(clock or ''),flags=re.I)
    if not m:return None
    length=720 if period<=4 else 300
    return round((period-1)*720+(length-(int(m[1])*60+float(m[2]))),3) if period<=4 else None

def resolve(text, roster,team):
    n=norm(text);matches=[]
    for pid,rec in roster.items():
        if rec['team']!=team:continue
        full=norm(rec['name']); toks=full.split()
        if n==full or (toks and n==' '.join(toks[1:])) or (len(toks)>1 and n==toks[-1]):matches.append(pid)
        elif n in ('butler iii','payton ii','jackson davis') and n in full:matches.append(pid)
    return matches

def lineup_str(x):return '|'.join(sorted(x,key=int)) if x is not None else ''
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--game-id',default='0022500002');ap.add_argument('--official-dir',default='./v9_4e_official_evidence');ap.add_argument('--stints',default='./v9_2c_lakers_review/reconstruction_stints_PROVISIONAL.csv');ap.add_argument('--out',default='./v9_7_lineup_review');args=ap.parse_args()
    src=Path(args.official_dir);out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    actions=read_csv(src/'playbyplayv3_dataset_0.csv');players=read_csv(src/'boxscoretraditionalv3_dataset_0.csv');stints=read_csv(Path(args.stints))
    roster={};starter={}
    for r in players:
        pid=str(r.get('personId','')).strip();team=str(r.get('teamTricode','')).strip().upper()
        if not pid or not team:continue
        display_name=(str(r.get('nameI') or '').strip() or (' '.join(filter(None,[str(r.get('firstName') or '').strip(),str(r.get('familyName') or '').strip()]))).strip() or str(r.get('name') or '').strip() or pid)
        roster[pid]={'name':display_name,'team':team,'starter':str(r.get('comment','')).strip().lower()!='dnp' and str(r.get('position','')).strip()!='' and str(r.get('position','')).strip().lower()!='none'}
        # The NBA boxscore uses position populated for starters; some datasets also have startersBench.
        sb=str(r.get('startersBench','')).lower()
        if sb in ('starters','starter','start'):roster[pid]['starter']=True
        elif sb in ('bench',''):roster[pid]['starter']=False if sb=='bench' else roster[pid]['starter']
    teams=sorted({v['team'] for v in roster.values()});
    if len(teams)!=2:raise ValueError(f'Expected two teams, found {teams}; inspect boxscore dataset_0')
    if any(len([r for r in roster.values() if r['team']==t and r['starter']])!=5 for t in teams):
        raise ValueError('Cannot identify five official starters for each team from boxscoretraditionalv3_dataset_0.csv. Inspect position/startersBench columns; no inferred starters will be used.')
    by_period=defaultdict(list)
    for r in actions:
        if str(r.get('actionType','')).lower()!='substitution':continue
        p=int(r['period']);elapsed=clock_elapsed(p,r.get('clock'));by_period[p].append((elapsed,int(r['actionNumber']),r))
    changes=[];issues=[];segments=[];period_states={};counts=defaultdict(int)
    # Non-starting quarters remain unknown unless explicitly supplied; never seed from provisional stints.
    for p in sorted(by_period):
        if p>4:issues.append({'period':p,'elapsed':'','action_numbers':'','team':'','problem':'OVERTIME_NOT_SUPPORTED','detail':'Regulation-only validation'});continue
        states={t:({pid for pid,v in roster.items() if v['team']==t and v['starter']} if p==1 else None) for t in teams}
        certainty={t:('OFFICIAL_Q1_STARTERS' if p==1 else 'UNKNOWN_PERIOD_START') for t in teams}
        cursor=(p-1)*720
        grp=defaultdict(list)
        for elapsed,anum,r in by_period[p]:
            if elapsed is None:issues.append({'period':p,'elapsed':'','action_numbers':anum,'team':r.get('teamTricode',''),'problem':'BAD_CLOCK','detail':r.get('clock','')});continue
            grp[elapsed].append((anum,r))
        for t in sorted(grp):
            if t<cursor:issues.append({'period':p,'elapsed':t,'action_numbers':'','team':'','problem':'NONMONOTONIC_CLOCK','detail':''});continue
            segments.append({'period':p,'start_seconds':cursor,'end_seconds':t,'duration_seconds':round(t-cursor,3),**{team+'_lineup':lineup_str(states[team]) for team in teams},'evidence_status':'OFFICIAL_Q1_STARTERS_TRACKED' if p==1 and all(states.values()) else 'UNCERTAIN_PERIOD_OPENING' if any(s is None for s in states.values()) else 'PARTIALLY_INFERRED'})
            group=sorted(grp[t]);team_changes=defaultdict(list)
            for anum,r in group:
                team=str(r.get('teamTricode','')).upper();oid=str(r.get('personId','')).strip();desc=str(r.get('description',''))
                m=re.match(r'^\s*SUB\s*:\s*(.*?)\s+FOR\s+(.*?)\s*$',desc,flags=re.I)
                issue=[];incoming=[]
                if team not in teams:issue.append('UNKNOWN_TEAM')
                if oid not in roster or roster[oid]['team']!=team:issue.append('OUTGOING_ID_NOT_ON_TEAM')
                if not m:issue.append('DESCRIPTION_PARSE_FAILED')
                else:
                    incoming=resolve(m[1],roster,team)
                    if len(incoming)!=1:issue.append('INCOMING_NOT_UNIQUE')
                    if oid in roster:
                        oname=norm(roster[oid]['name']);outdesc=norm(m[2]);toks=oname.split()
                        if outdesc!=oname and outdesc!=' '.join(toks[1:]) and outdesc!=toks[-1]:issue.append('OUTGOING_DESCRIPTION_MISMATCH')
                iid=incoming[0] if len(incoming)==1 else ''
                if oid==iid:issue.append('IDENTICAL_IN_OUT')
                row={'period':p,'elapsed':t,'action_number':anum,'team':team,'outgoing_id':oid,'outgoing_name':roster.get(oid,{}).get('name',''),'incoming_id':iid,'incoming_name':roster.get(iid,{}).get('name',''),'description':desc,'parse_status':'PASS' if not issue else ';'.join(issue),'state_before_known':states.get(team) is not None}
                changes.append(row);counts['substitutions']+=1
                if issue:
                    for problem in issue:issues.append({'period':p,'elapsed':t,'action_numbers':anum,'team':team,'problem':problem,'detail':desc})
                team_changes[team].append(row)
            for team,rs in team_changes.items():
                state=states[team]
                ids_valid=all(r['parse_status']=='PASS' for r in rs)
                outgoing=[r['outgoing_id'] for r in rs];incoming=[r['incoming_id'] for r in rs]
                if len(set(outgoing))!=len(outgoing) or len(set(incoming))!=len(incoming):
                    issues.append({'period':p,'elapsed':t,'action_numbers':','.join(str(r['action_number']) for r in rs),'team':team,'problem':'DUPLICATE_SAME_CLOCK_CHANGE','detail':''});ids_valid=False
                if state is None:
                    # First substitution batch can imply membership constraints, but not an entire period opening lineup.
                    counts['unknown_state_groups']+=1
                    continue
                if not ids_valid or not set(outgoing).issubset(state) or any(i in state and i not in outgoing for i in incoming):
                    issues.append({'period':p,'elapsed':t,'action_numbers':','.join(str(r['action_number']) for r in rs),'team':team,'problem':'SUBSTITUTION_STATE_CONFLICT','detail':f'current={lineup_str(state)}; outgoing={outgoing}; incoming={incoming}'})
                    states[team]=None;certainty[team]='INVALID_OR_UNKNOWN';continue
                updated=(state-set(outgoing))|set(incoming)
                if len(updated)!=5:
                    issues.append({'period':p,'elapsed':t,'action_numbers':','.join(str(r['action_number']) for r in rs),'team':team,'problem':'NOT_FIVE_PLAYERS','detail':lineup_str(updated)});states[team]=None;continue
                states[team]=updated;counts['applied_substitutions']+=len(rs)
            cursor=t
        segments.append({'period':p,'start_seconds':cursor,'end_seconds':p*720,'duration_seconds':round(p*720-cursor,3),**{team+'_lineup':lineup_str(states[team]) for team in teams},'evidence_status':'OFFICIAL_Q1_STARTERS_TRACKED' if p==1 and all(states.values()) else 'UNCERTAIN_PERIOD_OPENING' if any(s is None for s in states.values()) else 'PARTIALLY_INFERRED'})
        period_states[p]={team:lineup_str(states[team]) for team in teams}
    # Compare only intervals for which team states are actually known; do not call matching intervals verified.
    comparisons=[]
    for seg in segments:
        if seg['duration_seconds']<=0:continue
        overlap=[s for s in stints if int(s['period'])==seg['period'] and fnum(s.get('start_seconds'),999999)<seg['end_seconds'] and fnum(s.get('end_seconds'),-1)>seg['start_seconds']]
        for s in overlap:
            start=max(seg['start_seconds'],fnum(s['start_seconds']));end=min(seg['end_seconds'],fnum(s['end_seconds']))
            if end<=start:continue
            for team in teams:
                reconstructed=seg[team+'_lineup'];provisional=s.get(team.lower()+'_lineup','')
                if reconstructed:
                    status='MATCH' if set(reconstructed.split('|'))==set(provisional.split('|')) else 'CONFLICT'
                else:status='UNDETERMINED'
                comparisons.append({'period':seg['period'],'start_seconds':start,'end_seconds':end,'team':team,'official_event_reconstruction':reconstructed,'provisional_lineup':provisional,'comparison':status})
    write_csv(out/'substitution_audit.csv',changes,['period','elapsed','action_number','team','outgoing_id','outgoing_name','incoming_id','incoming_name','description','parse_status','state_before_known'])
    write_csv(out/'issues.csv',issues,['period','elapsed','action_numbers','team','problem','detail'])
    write_csv(out/'chronological_intervals_UNVERIFIED.csv',segments,['period','start_seconds','end_seconds','duration_seconds']+[t+'_lineup' for t in teams]+['evidence_status'])
    write_csv(out/'provisional_comparison.csv',comparisons,['period','start_seconds','end_seconds','team','official_event_reconstruction','provisional_lineup','comparison'])
    summary={'version':'9.7.1','game_id':args.game_id,'mode':'READ_ONLY_SUBSTITUTION_TIMELINE_AUDIT','source_actions':len(actions),'substitution_events':len(changes),'substitution_parse_pass':sum(c['parse_status']=='PASS' for c in changes),'substitution_parse_fail':sum(c['parse_status']!='PASS' for c in changes),'applied_substitutions_from_known_state':counts['applied_substitutions'],'unknown_period_start_periods':[p for p in sorted(by_period) if p!=1],'official_q1_starters':{t:sorted([pid for pid,v in roster.items() if v['team']==t and v['starter']],key=int) for t in teams},'issue_count':len(issues),'issue_types':dict((k,sum(x['problem']==k for x in issues)) for k in sorted({x['problem'] for x in issues})),'provisional_comparison':{status:sum(x['comparison']==status for x in comparisons) for status in ['MATCH','CONFLICT','UNDETERMINED']},'verified_stints':0,'publication_gate':'BLOCKED_NO_INDEPENDENT_FULL_GAME_LINEUP_EVIDENCE','limitations':['Q2-Q4 opening lineups not independently established by Q1 starters or substitution log alone.','Matching reconstructed and provisional stints does not independently verify scoring boundary timing.','No official plus/minus based lineup selection.','This script does not read or modify DuckDB.']}
    (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
