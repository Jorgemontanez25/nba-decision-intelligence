#!/usr/bin/env python3
"""V9.8 read-only scoring attribution audit. Does not certify stints.

Consumes locally saved NBA playbyplayv3, boxscoretraditionalv3 and v9.7.3 interval CSV.
"""
import argparse,csv,json,re,collections,pathlib
from decimal import Decimal

def read_csv(p):
    with open(p,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write_csv(p,rows,fields):
    with open(p,'w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
def num(x,default=None):
    try:return float(x)
    except (ValueError,TypeError):return default
def intval(x,default=None):
    try:return int(float(x))
    except (ValueError,TypeError):return default
def clocksec(clock):
    m=re.fullmatch(r'PT(\d+)M(\d+(?:\.\d+)?)S',str(clock or ''))
    return float(m.group(1))*60+float(m.group(2)) if m else None
def pid(x):
    s=str(x or '').strip()
    return str(int(float(s))) if s and s not in ('nan','None') else ''
def lineup(s):return frozenset(pid(z) for z in str(s or '').split('|') if pid(z))
def reltime(period,clock):
    rem=clocksec(clock)
    return ((period-1)*720+720-rem) if rem is not None else None
def getfile(folder,prefix):
    p=folder/(prefix+'_dataset_0.csv')
    if not p.is_file():raise FileNotFoundError(str(p))
    return p

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game-id',required=True)
    ap.add_argument('--official-dir',type=pathlib.Path,required=True)
    ap.add_argument('--timeline',type=pathlib.Path,required=True)
    ap.add_argument('--out',type=pathlib.Path,required=True)
    args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    acts=read_csv(getfile(args.official_dir,'playbyplayv3'))
    box=read_csv(getfile(args.official_dir,'boxscoretraditionalv3'))
    intervals=read_csv(args.timeline)
    plays=[];subclocks=set();problems=[]
    for i,a in enumerate(acts):
        p=intval(a.get('period'));n=intval(a.get('actionNumber'));t=reltime(p,a.get('clock')) if p else None
        if p is None or t is None:
            problems.append({'type':'INVALID_EVENT_CLOCK','detail':f'row {i+1}' });continue
        if a.get('actionType')=='Substitution':subclocks.add((p,round(t,4)))
        plays.append((n if n is not None else -1,i,p,t,a))
    plays.sort(key=lambda q:(q[2],q[3],q[0],q[1]))
    segments=[]
    for i,r in enumerate(intervals):
        p=intval(r.get('period'));s=num(r.get('start_seconds'));e=num(r.get('end_seconds'))
        if p is None or s is None or e is None or e<s:
            problems.append({'type':'INVALID_TIMELINE_INTERVAL','detail':f'row {i+1}'});continue
        la=lineup(r.get('LAL_lineup'));gs=lineup(r.get('GSW_lineup'))
        if len(la)!=5 or len(gs)!=5:problems.append({'type':'INVALID_LINEUP_SIZE','detail':f'row {i+1}, LAL={len(la)}, GSW={len(gs)}'})
        segments.append({'period':p,'start':s,'end':e,'LAL':la,'GSW':gs,'raw':r})
    byperiod=collections.defaultdict(list)
    for v in segments:byperiod[v['period']].append(v)
    for p in byperiod:byperiod[p].sort(key=lambda v:(v['start'],v['end']))
    for p,items in byperiod.items():
        for a,b in zip(items,items[1:]):
            if abs(a['end']-b['start'])>0.011:problems.append({'type':'TIMELINE_GAP_OR_OVERLAP','detail':f'period {p}: {a["end"]} vs {b["start"]}'})
    # Translate absolute game elapsed seconds in timeline into period-relative positions.
    # At boundary, use adjacent interval: choose before for pre and after for post.
    def at(period,t,side):
        ss=byperiod.get(period,[])
        if not ss:return None
        eps=0.00011
        for x in ss:
            if side=='before' and x['start']-eps<t<=x['end']+eps:return x
            if side=='after' and x['start']-eps<=t<x['end']+eps:return x
        return None
    # Score differential from official cumulative values, never infer made shots from descriptions.
    prev_home=0;prev_away=0;scoring=[]
    for n,i,p,t,a in plays:
        h=intval(a.get('scoreHome'));aw=intval(a.get('scoreAway'))
        if h is None or aw is None:continue
        dh=h-prev_home;da=aw-prev_away
        if dh<0 or da<0:
            problems.append({'type':'SCORE_REGRESSION','detail':f'period {p}, action {n}, scores {h}-{aw} from {prev_home}-{prev_away}'})
        if dh>0 or da>0:
            scoring.append((n,i,p,t,a,dh,da))
        prev_home,prev_away=h,aw
    # Score recorded in play-by-play is home=LAL, away=GSW for this game, verify box team aggregate.
    teams=collections.defaultdict(list)
    for r in box:
        team=(r.get('teamTricode') or r.get('team_abbr') or '').upper()
        if team in ('LAL','GSW'):teams[team].append(r)
    official={};names={}
    for team,rows in teams.items():
        for r in rows:
            id_=pid(r.get('personId') or r.get('player_id'))
            if not id_:continue
            pm=num(r.get('plusMinusPoints') or r.get('plus_minus'))
            if pm is not None:official[id_]=int(round(pm))
            names[id_]=(r.get('name') or r.get('nameI') or (str(r.get('firstName') or '')+' '+str(r.get('familyName') or '')).strip() or id_,team)
    # Find score-bearing actions sharing clock with a substitution. Three scenarios:
    # recorded order interpreted by comparing action IDs to substitution IDs at same timestamp.
    suborder=collections.defaultdict(list)
    for n,i,p,t,a in plays:
        if a.get('actionType')=='Substitution':suborder[(p,round(t,4))].append((n,i))
    points=collections.defaultdict(lambda:collections.defaultdict(int))
    reports=[];unassigned=0
    for n,i,p,t,a,dh,da in scoring:
        same=suborder.get((p,round(t,4)),[])
        isbound=bool(same)
        # Treat recorded-order as ambiguous if a score falls inside a multi-substitution group.
        count_prior=sum((sn,si)<(n,i) for sn,si in same)
        mixed=bool(isbound and 0<count_prior<len(same))
        decisions={'before':'before','after':'after','recorded':'after' if isbound and count_prior==len(same) else 'before'}
        # Non-boundary events get same interval for all scenarios.
        boundary_absolute=(p-1)*720+720-clocksec(a.get('clock'))
        if isbound and mixed:problems.append({'type':'MIXED_SUBSTITUTION_GROUP','detail':f'period {p}, action {n}, clock {a.get("clock")}'})
        for scenario,side in decisions.items():
            seg=at(p,boundary_absolute,side)
            if seg is None:
                unassigned+=1;problems.append({'type':'SCORING_UNASSIGNED','detail':f'period {p}, action {n}, scenario {scenario}'});continue
            if len(seg['LAL'])!=5 or len(seg['GSW'])!=5:continue
            for player in seg['LAL']:points[scenario][player]+=dh-da
            for player in seg['GSW']:points[scenario][player]+=da-dh
        reports.append({'period':p,'clock':a.get('clock'),'action_number':n,'action_type':a.get('actionType'),'description':a.get('description'),'home_delta':dh,'away_delta':da,'at_substitution_timestamp':isbound,'same_clock_subs':len(same),'subs_before_in_recorded_order':count_prior,'mixed_substitution_group':mixed})
    players=sorted(set(official)|{j for sc in points.values() for j in sc})
    comparison=[]
    for x in players:
        name,team=names.get(x,(x,''));o=official.get(x)
        row={'player_id':x,'player_name':name,'team':team,'official_pm':o if o is not None else ''}
        for sc in ('recorded','before','after'):
            v=points[sc].get(x,0)
            row[sc+'_pm']=v;row[sc+'_delta']=v-o if o is not None else ''
        comparison.append(row)
    summary={'version':'9.8','game_id':args.game_id,'mode':'READ_ONLY_SCORING_ATTRIBUTION_SENSITIVITY','scoring_events_with_points':len(scoring),'scoring_events_same_clock_as_substitution':sum(r['at_substitution_timestamp'] for r in reports),'total_home_score':prev_home,'total_away_score':prev_away,'lineup_intervals':len(segments),'players_with_official_pm':len(official),'scenario_results':{},'unassigned_scenario_events':unassigned,'issue_count':len(problems),'issues_by_type':dict(collections.Counter(v['type'] for v in problems)),'verified_stints':0,'publication_gate':'BLOCKED_UNVERIFIED_OPENINGS_AND_SCORING_BOUNDARY_EVIDENCE','notes':['Neither exact plus/minus nor a best scenario certifies the lineup reconstruction.','Recorded-order scenario is a sensitivity model; action ordering does not independently establish legal effective substitution time.','The before/after scenarios represent all substitutions at a timestamp on one side of scoring.','Requires scoreHome to mean LAL and scoreAway to mean GSW for this specific game.','Database is never opened or modified.']}
    for sc in ('recorded','before','after'):
        deltas=[abs(r[sc+'_delta']) for r in comparison if r[sc+'_delta']!='']
        summary['scenario_results'][sc]={'matched_players':sum(v==0 for v in deltas),'mismatched_players':sum(v!=0 for v in deltas),'absolute_pm_error':sum(deltas)}
    write_csv(args.out/'player_pm_comparison.csv',comparison,['player_id','player_name','team','official_pm','recorded_pm','recorded_delta','before_pm','before_delta','after_pm','after_delta'])
    write_csv(args.out/'scoring_boundary_events.csv',reports,['period','clock','action_number','action_type','description','home_delta','away_delta','at_substitution_timestamp','same_clock_subs','subs_before_in_recorded_order','mixed_substitution_group'])
    write_csv(args.out/'issues.csv',problems,['type','detail'])
    (args.out/'SUMMARY.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(summary,indent=2,ensure_ascii=False))
    print('Reports:',args.out.resolve())
if __name__=='__main__':main()
