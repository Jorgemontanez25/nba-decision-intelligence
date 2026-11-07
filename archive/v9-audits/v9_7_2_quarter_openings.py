#!/usr/bin/env python3
"""V9.7.2: read-only, evidence-constrained quarter opening lineup candidates.

Never infers a missing fifth player from plus/minus, official minutes, or prior provisional stints.
A complete opening five is a conditional candidate based on play-by-play before first team
substitution and the first substitution's outgoing players; not a certified lineup.
"""
import argparse, csv, json, re, unicodedata
from collections import defaultdict
from pathlib import Path

def read_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def write_csv(path, rows, columns):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w=csv.DictWriter(f, fieldnames=columns, extrasaction='ignore');w.writeheader();w.writerows(rows)

def normalize(s):
    s=unicodedata.normalize('NFKD',str(s or ''))
    return re.sub(r'[^a-z0-9]+',' ',''.join(c for c in s if not unicodedata.combining(c)).lower()).strip()

def seconds(period,clock):
    m=re.fullmatch(r'PT(\d+)M(\d+(?:\.\d+)?)S',str(clock or ''),re.I)
    if not m or period<1 or period>4:return None
    return round((period-1)*720+720-int(m[1])*60-float(m[2]),3)

def name_matches(label, roster, team):
    n=normalize(label); hits=[]
    for pid, r in roster.items():
        if r['team']!=team:continue
        full=normalize(r['name']); toks=full.split()
        candidates={full,normalize(r['first']+' '+r['last']),normalize(r['last']),normalize(r['last']+' '+r['suffix'])}
        if len(toks)>=2:candidates.add(' '.join(toks[1:]))
        if n and n in candidates:hits.append(pid)
    return sorted(set(hits))

def encode(ids):return '|'.join(sorted(ids,key=lambda x:int(x)))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--game-id',default='0022500002')
    ap.add_argument('--official-dir',default='./v9_4e_official_evidence')
    ap.add_argument('--stints',default='./v9_2c_lakers_review/reconstruction_stints_PROVISIONAL.csv')
    ap.add_argument('--out',default='./v9_7_2_openings_review')
    args=ap.parse_args();out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    source=Path(args.official_dir)
    actions=read_csv(source/'playbyplayv3_dataset_0.csv')
    box=read_csv(source/'boxscoretraditionalv3_dataset_0.csv')
    stints=read_csv(args.stints) if Path(args.stints).exists() else []
    roster={}; starters=defaultdict(set)
    for r in box:
        pid=str(r.get('personId') or '').strip();team=str(r.get('teamTricode') or '').strip().upper()
        if not pid.isdigit() or not team:continue
        first=str(r.get('firstName') or '').strip();last=str(r.get('familyName') or '').strip()
        name=' '.join(x for x in (first,last) if x) or str(r.get('nameI') or r.get('name') or pid)
        suffix=last.split()[-1] if last.split() and last.split()[-1].lower() in ('ii','iii','iv','jr') else ''
        roster[pid]={'team':team,'name':name,'first':first,'last':last,'suffix':suffix}
        flag=str(r.get('startersBench') or '').strip().lower()
        pos=str(r.get('position') or '').strip()
        if flag in ('starters','starter','start') or (not flag and bool(pos) and pos.lower()!='none'):starters[team].add(pid)
    teams=sorted({v['team'] for v in roster.values()})
    if len(teams)!=2:raise ValueError('Expected exactly 2 teams in player box score')
    if any(len(starters[t])!=5 for t in teams):raise ValueError('Official Q1 starters not exactly five per team')
    indexed=[]
    for idx,a in enumerate(actions):
        try:p=int(a['period']);n=int(a['actionNumber'])
        except (KeyError,ValueError):continue
        if p not in (1,2,3,4):continue
        t=seconds(p,a.get('clock'))
        if t is None:continue
        indexed.append({'row':a,'period':p,'elapsed':t,'action':n,'index':idx})
    indexed.sort(key=lambda x:(x['period'],x['elapsed'],x['action'],x['index']))
    substitutions=defaultdict(list)
    for e in indexed:
        if (e['row'].get('actionType') or '').lower()=='substitution':
            substitutions[(e['period'],e['row'].get('teamTricode','').upper())].append(e)
    openings=[]; evidence=[]; subaudit=[]; intervals=[]; issues=[]; quarter_states={}; counts=defaultdict(int)
    actor_types={'made shot','missed shot','free throw','rebound','turnover','foul','jump ball','violation','block','steal'}
    for p in (1,2,3,4):
        period_state={};team_info={}
        for team in teams:
            subs=substitutions[(p,team)]; first_elapsed=min((e['elapsed'] for e in subs),default=p*720)
            first_batch=[e for e in subs if e['elapsed']==first_elapsed]
            observed=defaultdict(list)
            if p==1:
                for pid in starters[team]:observed[pid].append('OFFICIAL_Q1_STARTER')
            else:
                for e in indexed:
                    if e['period']!=p:continue
                    a=e['row'];t=e['elapsed'];atype=str(a.get('actionType','')).lower(); at=a.get('teamTricode','').upper()
                    if at!=team or t>=first_elapsed:continue
                    pid=str(a.get('personId') or '').strip()
                    if atype in actor_types and pid in roster and roster[pid]['team']==team:
                        observed[pid].append(f'ACTOR_ACTION_{e["action"]}')
                    # Assists in descriptions are evidence of secondary participant before first team substitution.
                    desc=str(a.get('description') or '')
                    if atype=='made shot':
                        m=re.search(r'\(([^()]+?)\s+\d+\s+AST\)',desc,re.I)
                        if m:
                            matching=name_matches(m[1],roster,team)
                            if len(matching)==1:observed[matching[0]].append(f'ASSIST_ACTION_{e["action"]}')
                # A substituted-out player was present immediately prior to this team's first substitution batch.
                for e in first_batch:
                    a=e['row'];oid=str(a.get('personId') or '').strip()
                    if oid in roster and roster[oid]['team']==team:
                        observed[oid].append(f'FIRST_SUB_OUT_{e["action"]}')
            candidate=set(observed)
            status='OFFICIAL_Q1_STARTERS' if p==1 else ('FIVE_IDENTIFIED_CONDITIONAL' if len(candidate)==5 else ('OVERCONSTRAINED' if len(candidate)>5 else 'INCOMPLETE'))
            if p>1 and len(candidate)>5:
                issues.append({'period':p,'team':team,'action_number':'','issue':'OVERCONSTRAINED_OPENING','detail':f'{len(candidate)} distinct observed before first substitution; do not infer five'})
            if p>1 and len(candidate)<5:
                issues.append({'period':p,'team':team,'action_number':'','issue':'INCOMPLETE_OPENING','detail':f'{len(candidate)} of 5 distinct observed'})
            period_state[team]=candidate if len(candidate)==5 else None
            team_info[team]={'first_substitution_elapsed':first_elapsed,'observed':candidate,'status':status}
            openings.append({'period':p,'team':team,'status':status,'identified_players':len(candidate),'missing_player_count':max(0,5-len(candidate)),'first_team_substitution_elapsed':first_elapsed,'first_team_substitution_actions':','.join(str(e['action']) for e in first_batch),'candidate_ids':encode(candidate),'candidate_names':' | '.join(roster[pid]['name'] for pid in sorted(candidate,key=int)),'evidence':' ; '.join(roster[pid]['name']+':'+','.join(observed[pid]) for pid in sorted(candidate,key=int))})
            for pid in sorted(candidate,key=int):
                evidence.append({'period':p,'team':team,'player_id':pid,'player_name':roster[pid]['name'],'signals':';'.join(observed[pid]),'first_substitution_elapsed':first_elapsed})
        quarter_states[p]=team_info
        cursor=(p-1)*720
        grouped=defaultdict(list)
        for team in teams:
            for e in substitutions[(p,team)]:grouped[e['elapsed']].append(e)
        for t in sorted(grouped):
            intervals.append({'period':p,'start_seconds':cursor,'end_seconds':t,'duration_seconds':round(t-cursor,3),**{team.lower()+'_lineup':encode(period_state[team]) if period_state[team] is not None else '' for team in teams},'confidence':'CONDITIONAL_EVENT_EVIDENCE' if all(period_state.values()) else 'INCOMPLETE_EVENT_EVIDENCE'})
            byteam=defaultdict(list)
            for e in grouped[t]:byteam[e['row'].get('teamTricode','').upper()].append(e)
            for team, batch in byteam.items():
                parsed=[]
                for e in sorted(batch,key=lambda x:x['action']):
                    a=e['row'];desc=str(a.get('description') or '')
                    m=re.match(r'^\s*SUB\s*:\s*(.*?)\s+FOR\s+(.*?)\s*$',desc,re.I)
                    oid=str(a.get('personId') or '').strip();incoming=name_matches(m[1],roster,team) if m else []
                    outgoing_desc=name_matches(m[2],roster,team) if m else []
                    valid=bool(m and len(incoming)==1 and oid in outgoing_desc and oid in roster and roster[oid]['team']==team)
                    parsed.append((e,oid,incoming[0] if len(incoming)==1 else '',valid))
                prior=period_state.get(team)
                outs=[x[1] for x in parsed];ins=[x[2] for x in parsed]
                valid=all(x[3] for x in parsed) and len(set(outs))==len(outs) and len(set(ins))==len(ins)
                if prior is not None:
                    valid=valid and set(outs).issubset(prior) and not(set(ins)&(prior-set(outs)))
                    after=(prior-set(outs))|set(ins) if valid else set()
                    valid=valid and len(after)==5
                    if valid:period_state[team]=after;counts['applied']+=len(parsed)
                    else:
                        period_state[team]=None
                        issues.append({'period':p,'team':team,'action_number':','.join(str(x[0]['action']) for x in parsed),'issue':'STATE_CONFLICT','detail':'Invalid substitution against conditional or official state'})
                for e,oid,iid,rowvalid in parsed:
                    subaudit.append({'period':p,'elapsed':t,'action_number':e['action'],'team':team,'outgoing_id':oid,'incoming_id':iid,'parse_valid':rowvalid,'state_known_before':prior is not None,'state_known_after':period_state[team] is not None})
                    if not rowvalid:issues.append({'period':p,'team':team,'action_number':e['action'],'issue':'SUBSTITUTION_PARSE','detail':e['row'].get('description','')})
            cursor=t
        intervals.append({'period':p,'start_seconds':cursor,'end_seconds':p*720,'duration_seconds':round(p*720-cursor,3),**{team.lower()+'_lineup':encode(period_state[team]) if period_state[team] is not None else '' for team in teams},'confidence':'CONDITIONAL_EVENT_EVIDENCE' if all(period_state.values()) else 'INCOMPLETE_EVENT_EVIDENCE'})
    comparisons=[]
    for seg in intervals:
        if seg['duration_seconds']<=0:continue
        for stint in stints:
            try:
                if int(stint['period'])!=seg['period']:continue
                low=max(float(stint['start_seconds']),seg['start_seconds']);high=min(float(stint['end_seconds']),seg['end_seconds'])
            except (ValueError,KeyError):continue
            if low>=high:continue
            for team in teams:
                reconstructed=seg[team.lower()+'_lineup'];reference=stint.get(team.lower()+'_lineup','')
                result='UNDETERMINED' if not reconstructed else ('MATCH' if set(reconstructed.split('|'))==set(reference.split('|')) else 'CONFLICT')
                comparisons.append({'period':seg['period'],'start_seconds':low,'end_seconds':high,'team':team,'comparison':result,'candidate_lineup':reconstructed,'provisional_lineup':reference})
    write_csv(out/'opening_lineup_candidates_UNVERIFIED.csv',openings,['period','team','status','identified_players','missing_player_count','first_team_substitution_elapsed','first_team_substitution_actions','candidate_ids','candidate_names','evidence'])
    write_csv(out/'player_presence_evidence.csv',evidence,['period','team','player_id','player_name','signals','first_substitution_elapsed'])
    write_csv(out/'substitution_audit.csv',subaudit,['period','elapsed','action_number','team','outgoing_id','incoming_id','parse_valid','state_known_before','state_known_after'])
    write_csv(out/'chronological_intervals_UNVERIFIED.csv',intervals,['period','start_seconds','end_seconds','duration_seconds']+[t.lower()+'_lineup' for t in teams]+['confidence'])
    write_csv(out/'provisional_comparison.csv',comparisons,['period','start_seconds','end_seconds','team','comparison','candidate_lineup','provisional_lineup'])
    write_csv(out/'issues.csv',issues,['period','team','action_number','issue','detail'])
    summary={'version':'9.7.2','game_id':args.game_id,'mode':'READ_ONLY_CONDITIONAL_OPENING_INFERENCE','source_actions':len(actions),'substitution_events':len(subaudit),'parsed_substitutions':sum(x['parse_valid'] for x in subaudit),'applied_substitutions_from_known_state':counts['applied'],'opening_candidates':{str(p):{team:{'status':quarter_states[p][team]['status'],'identified_players':len(quarter_states[p][team]['observed'])} for team in teams} for p in (1,2,3,4)},'provisional_comparison':{s:sum(x['comparison']==s for x in comparisons) for s in ('MATCH','CONFLICT','UNDETERMINED')},'issues':len(issues),'verified_stints':0,'publication_gate':'BLOCKED_UNVERIFIED_OPENING_AND_BOUNDARY_EVIDENCE','limitations':['Five identified players produce a conditional opening candidate only, assuming no omitted earlier substitutions.','Actor and assist evidence is restricted to before each team first substitution.','A team rebound is not a player-presence signal.','No plus/minus fitting or provisional stints are used to select opening lineups.','No local database modifications; output is not certified.']}
    (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(summary,indent=2,ensure_ascii=False))
if __name__=='__main__':main()
