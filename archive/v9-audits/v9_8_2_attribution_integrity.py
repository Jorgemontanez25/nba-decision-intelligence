#!/usr/bin/env python3
"""V9.8.2: independent, READ-ONLY scoring attribution transparency audit.

Replays explicit substitution actions against V9.7.3's period opening lineups.
Reports player IDs/contributions for before, recorded-order, and after scenarios.
Never chooses a scenario using official plus/minus; never changes DuckDB.
"""
import argparse, collections, csv, json, pathlib, re, sys

TEAMS=('LAL','GSW'); SCENARIOS=('recorded','before','after')

def read_csv(path):
    with open(path,encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))

def write_csv(path,rows,columns):
    with open(path,'w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore');w.writeheader();w.writerows(rows)

def number(x):
    try: return int(float(x))
    except (ValueError,TypeError): return None

def canon(x):
    z=number(x); return str(z) if z is not None and z>0 else ''

def time_seconds(clock):
    m=re.fullmatch(r'PT(\d+)M(\d+(?:\.\d+)?)S',str(clock or ''))
    return 60*int(m.group(1))+float(m.group(2)) if m else None

def ids(s):return set(filter(None,(canon(v) for v in str(s or '').split('|'))))

def fmt(s):return '|'.join(sorted(s,key=int))

def norm(s):
    import unicodedata
    s=''.join(c for c in unicodedata.normalize('NFKD',str(s or '')) if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9 ]','',s.lower()).strip()

def player_aliases(r):
    names=[r.get('name'),r.get('nameI'), ' '.join(filter(None,[r.get('firstName'),r.get('familyName')]))]
    out=set()
    for n in names:
        if n:
            cleaned=norm(n)
            if cleaned:out.add(cleaned);out.add(cleaned.split()[-1])
    return out

def copy_state(state):return {t:set(state[t]) for t in TEAMS}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game-id',required=True)
    ap.add_argument('--official-dir',type=pathlib.Path,required=True)
    ap.add_argument('--timeline',type=pathlib.Path,required=True)
    ap.add_argument('--out',type=pathlib.Path,required=True)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    pb=a.official_dir/'playbyplayv3_dataset_0.csv';bp=a.official_dir/'boxscoretraditionalv3_dataset_0.csv'
    plays=read_csv(pb);box=read_csv(bp);timeline=read_csv(a.timeline)
    errors=[];rows=[];scorer_checks=[];score_event_count=0
    def issue(kind,period,action,detail):errors.append(dict(type=kind,period=period,action_number=action,detail=detail))
    # Strictly use box player entries; protect from non-player team rows.
    roster={}; aliases=collections.defaultdict(set); official={}; team_by_id={}
    for r in box:
        team=str(r.get('teamTricode') or r.get('team_abbr') or '').upper()
        p=canon(r.get('personId') or r.get('player_id'))
        if team not in TEAMS or not p:continue
        roster[p]=r;team_by_id[p]=team
        for al in player_aliases(r):aliases[(team,al)].add(p)
        pm=r.get('plusMinusPoints') if r.get('plusMinusPoints') not in ('',None) else r.get('plus_minus')
        if number(pm) is not None:official[p]=number(pm)
    openings={}
    for r in timeline:
        p=number(r.get('period'));start=float(r.get('start_seconds') or 'nan')
        if p is None:continue
        if abs(start-(p-1)*720)<0.015:
            candidate={t:ids(r[t+'_lineup']) for t in TEAMS}
            if p in openings and openings[p]!=candidate:issue('CONFLICTING_OPENING',p,'','Multiple different period-opening intervals')
            openings[p]=candidate
    # Sort by period, descending remaining clock, and action number.
    ordered=[]
    for i,r in enumerate(plays):
        p=number(r.get('period'));seconds=time_seconds(r.get('clock'));n=number(r.get('actionNumber'))
        if p is None or seconds is None or n is None:
            issue('INVALID_PLAY',p or '',n or '',f'CSV row {i+2}');continue
        ordered.append((p,-seconds,n,i,r))
    ordered.sort()
    by_period=collections.defaultdict(list)
    for p,negsec,n,i,r in ordered:by_period[p].append((negsec,n,i,r))
    totals={sc:collections.Counter() for sc in SCENARIOS}
    change_count=0;boundary_count=0;scenario_difference_count=0;unassigned=0
    for p in sorted(by_period):
        if p not in openings:
            issue('OPENING_MISSING',p,'','No first interval begins at the start of this period');continue
        live=copy_state(openings[p]);
        for team in TEAMS:
            if len(live[team])!=5:issue('OPENING_SIZE',p,'',f'{team}: {len(live[team])} players')
        groupings=collections.defaultdict(list)
        for negsec,n,i,r in by_period[p]:groupings[negsec].append((n,i,r))
        for negsec in sorted(groupings):
            group=sorted(groupings[negsec]); start_state=copy_state(live)
            subs=[(n,i,r) for n,i,r in group if r.get('actionType')=='Substitution']
            numsubs=len(subs)
            # Independently replay all substitution instructions in the action sequence.
            staged=[]
            for n,i,r in group:
                state_before_event=copy_state(live)
                if r.get('actionType')=='Substitution':
                    team=str(r.get('teamTricode') or '').upper();incoming=canon(r.get('personId'))
                    desc=str(r.get('description') or '')
                    m=re.search(r'\bFOR\s+(.+?)\s*$',desc,re.I)
                    outgoing=''
                    if team not in TEAMS or not incoming or not m:
                        issue('SUB_PARSE_FAIL',p,n,desc)
                    else:
                        target=norm(m.group(1)); candidates=aliases.get((team,target),set())
                        if len(candidates)!=1:
                            # Exact aliases from official box, then unique full-name suffix.
                            candidates={pid for pid,rr in roster.items() if team_by_id[pid]==team and any(al==target or al.endswith(' '+target) for al in player_aliases(rr))}
                        if len(candidates)==1:outgoing=next(iter(candidates))
                        else:issue('OUTGOING_AMBIGUOUS',p,n,f'{desc}; candidates={sorted(candidates)}')
                    if outgoing and incoming:
                        if outgoing not in live[team]:issue('OUTGOING_NOT_ON_COURT',p,n,desc)
                        if incoming in live[team]:issue('INCOMING_ALREADY_ON_COURT',p,n,desc)
                        live[team].discard(outgoing);live[team].add(incoming)
                        if len(live[team])!=5:issue('ILLEGAL_LINEUP_SIZE',p,n,f'{team}: {len(live[team])}')
                staged.append((n,i,r,state_before_event,copy_state(live)))
            end_state=copy_state(live)
            if numsubs and (start_state!=end_state):change_count+=1
            for n,i,r,before_action,after_action in staged:
                sh=number(r.get('scoreHome'));sa=number(r.get('scoreAway'))
                # Scoring deltas determined from score changes, not action descriptions.
                # Delta calculations are performed in a second chronological pass below.
    # Second replay with globally ordered score deltas, preserving actual action order.
    previous=(0,0)
    scored_deltas={}
    for p,negsec,n,i,r in ordered:
        h=number(r.get('scoreHome'));aw=number(r.get('scoreAway'))
        if h is None or aw is None:continue
        dh=h-previous[0];da=aw-previous[1]
        if dh<0 or da<0:issue('SCORE_REGRESSION',p,n,f'{previous} -> {(h,aw)}')
        if dh>0 or da>0:scored_deltas[(p,n,i)]=(dh,da)
        previous=(h,aw)
    for p in sorted(by_period):
        if p not in openings:continue
        live=copy_state(openings[p]);groupings=collections.defaultdict(list)
        for negsec,n,i,r in by_period[p]:groupings[negsec].append((n,i,r))
        for negsec in sorted(groupings):
            group=sorted(groupings[negsec]);prior_state=copy_state(live)
            subst=[v for v in group if v[2].get('actionType')=='Substitution']
            staged=[];count_prior=0
            for n,i,r in group:
                if r.get('actionType')=='Substitution':
                    team=str(r.get('teamTricode') or '').upper();incoming=canon(r.get('personId'));m=re.search(r'\bFOR\s+(.+?)\s*$',str(r.get('description') or ''),re.I)
                    if team in TEAMS and incoming and m:
                        candidates=aliases.get((team,norm(m.group(1))),set())
                        if len(candidates)==1:
                            outid=next(iter(candidates));live[team].discard(outid);live[team].add(incoming)
                        else:
                            candidates={pid for pid in roster if team_by_id[pid]==team and any(al==norm(m.group(1)) or al.endswith(' '+norm(m.group(1))) for al in player_aliases(roster[pid]))}
                            if len(candidates)==1:live[team].discard(next(iter(candidates)));live[team].add(incoming)
                    count_prior+=1
                staged.append((n,i,r,copy_state(live),count_prior))
            final_state=copy_state(live)
            for n,i,r,recorded_state,already in staged:
                if (p,n,i) not in scored_deltas:continue
                dh,da=scored_deltas[p,n,i];score_event_count+=1
                states={'before':prior_state,'after':final_state,'recorded':recorded_state}
                boundary=bool(subst)
                if boundary:boundary_count+=1
                different=any(states['before'][t]!=states['after'][t] for t in TEAMS)
                if boundary and different:scenario_difference_count+=1
                result={'period':p,'clock':r.get('clock'),'action_number':n,'description':r.get('description'),'home_delta':dh,'away_delta':da,'at_substitution_timestamp':boundary,'same_clock_substitutions':len(subst),'subs_before_scoring':already,'boundary_lineups_differ':different}
                for scenario in SCENARIOS:
                    state=states[scenario]
                    for team in TEAMS:
                        players=state[team]
                        result[scenario+'_'+team+'_ids']=fmt(players)
                        value=(dh-da) if team=='LAL' else (da-dh)
                        result[scenario+'_'+team+'_pm_delta']=value
                        for player in players:totals[scenario][player]+=value
                    scorer=canon(r.get('personId'));scorer_team=str(r.get('teamTricode') or '').upper()
                    result[scenario+'_scorer_present']=str(scorer in state.get(scorer_team,set())) if scorer and scorer_team in TEAMS else 'UNKNOWN'
                    if scorer and scorer_team in TEAMS and scorer not in state[scorer_team]:
                        issue('SCORER_ABSENT',p,n,f'{scenario}: {scorer} not in {scorer_team} lineup')
                result['before_vs_after_different']=any(result['before_'+t+'_ids']!=result['after_'+t+'_ids'] for t in TEAMS)
                result['recorded_vs_before_different']=any(result['recorded_'+t+'_ids']!=result['before_'+t+'_ids'] for t in TEAMS)
                result['recorded_vs_after_different']=any(result['recorded_'+t+'_ids']!=result['after_'+t+'_ids'] for t in TEAMS)
                if boundary and different and not result['before_vs_after_different']:
                    issue('SCENARIO_COLLAPSE',p,n,'Known before/after lineup changes not reflected')
                rows.append(result)
    comparison=[]
    for player in sorted(set(official)|set().union(*(set(totals[x]) for x in SCENARIOS)),key=lambda x:int(x)):
        r=roster.get(player,{});name=r.get('name') or r.get('nameI') or (' '.join(filter(None,[r.get('firstName'),r.get('familyName')])))
        rec={'player_id':player,'player_name':name,'team':team_by_id.get(player,''),'official_pm':official.get(player,'')}
        for sc in SCENARIOS:
            rec[sc+'_pm']=totals[sc][player]
            rec[sc+'_delta']=totals[sc][player]-official[player] if player in official else ''
        comparison.append(rec)
    # Warn if model outputs identical scenarios in spite of differing assignments.
    identical_totals=all(totals['before'][pid]==totals['after'][pid]==totals['recorded'][pid] for pid in set().union(*[set(v) for v in totals.values()]))
    if scenario_difference_count and identical_totals:
        issue('IDENTICAL_AGGREGATES_WITH_DIFFERENT_ASSIGNMENTS','','','Boundary player assignments differ but net player totals cancel or an implementation defect remains; review event rows')
    columns=['period','clock','action_number','description','home_delta','away_delta','at_substitution_timestamp','same_clock_substitutions','subs_before_scoring','boundary_lineups_differ','before_vs_after_different','recorded_vs_before_different','recorded_vs_after_different']
    for sc in SCENARIOS:
        for team in TEAMS:columns += [sc+'_'+team+'_ids',sc+'_'+team+'_pm_delta']
        columns += [sc+'_scorer_present']
    write_csv(a.out/'event_player_attribution.csv',rows,columns)
    write_csv(a.out/'boundary_differences.csv',[r for r in rows if r['at_substitution_timestamp']],columns)
    col=['player_id','player_name','team','official_pm']
    for sc in SCENARIOS:col += [sc+'_pm',sc+'_delta']
    write_csv(a.out/'player_pm_comparison.csv',comparison,col)
    write_csv(a.out/'issues.csv',errors,['type','period','action_number','detail'])
    summary={'version':'9.8.2','game_id':a.game_id,'mode':'READ_ONLY_INDEPENDENT_REPLAY','source_actions':len(plays),'scoring_events':score_event_count,'scoring_boundary_events':boundary_count,'boundary_events_with_changed_lineups':scenario_difference_count,'scenario_totals_identical':identical_totals,'final_score':{'LAL':previous[0],'GSW':previous[1]},'official_players':len(official),'issues':len(errors),'issues_by_type':dict(collections.Counter(e['type'] for e in errors)),'scenario_results':{},'verified_stints':0,'publication_gate':'BLOCKED_UNVERIFIED_QUARTER_OPENINGS_AND_SUBSTITUTION_EFFECTIVE_TIMES','notes':['All scenarios replay substitution actions and expose the assigned player IDs.','Before/after are sensitivity tests; recorded order is not independent evidence of effective-time rules.','Do not select scenarios to fit official plus/minus.','Never accesses or changes DuckDB.']}
    for sc in SCENARIOS:
        ds=[abs(int(r[sc+'_delta'])) for r in comparison if r[sc+'_delta']!='']
        summary['scenario_results'][sc]={'matched_players':sum(d==0 for d in ds),'mismatched_players':sum(d!=0 for d in ds),'absolute_pm_error':sum(ds)}
    (a.out/'SUMMARY.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(summary,indent=2,ensure_ascii=False))
    print('Reports:',a.out.resolve())
    if errors:print('WARNING: audit reported issues; see issues.csv',file=sys.stderr)

if __name__=='__main__':main()
