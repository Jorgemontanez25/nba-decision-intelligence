#!/usr/bin/env python3
"""V9.9.10 read-only general scoring/plus-minus scenario audit. Never certifies timing."""
import argparse,csv,json,re,sys
from pathlib import Path
from collections import defaultdict,Counter

def read(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(p,rs,cols):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(rs)
def number(x):
    try:return int(float(str(x).strip()))
    except (TypeError,ValueError):return None
def elapsed(clock,p):
    m=re.fullmatch(r'PT(?:(\d+)M)?(\d+(?:\.\d+)?)S',str(clock or ''))
    if not m:return None
    return round((720 if p<=4 else 300)-60*int(m[1] or 0)-float(m[2]),3)
def line(s):return set(filter(None,str(s or '').split('|')))
def dump(p,obj):p.write_text(json.dumps(obj,indent=2),encoding='utf-8')
def audit(gid,evidence,recon,out):
    out.mkdir(parents=True,exist_ok=True)
    pbp=read(evidence/'playbyplayv3_dataset_0.csv');box=read(evidence/'boxscoretraditionalv3_dataset_0.csv')
    spans=read(recon/'lineup_timeline_CONDITIONAL_UNVERIFIED.csv')
    trace=read(recon/'substitution_groups_trace.csv')
    teams=sorted({r['teamTricode'] for r in box if r.get('teamTricode') and r.get('personId')})
    if len(teams)!=2:raise ValueError('Box score must contain exactly two teams')
    states=defaultdict(list)
    for r in spans:
        p=number(r['period']);a=float(r['start_seconds']);b=float(r['end_seconds'])
        states[p].append((a,b,{t:line(r.get(t+'_lineup')) for t in teams}))
    for p in states:states[p].sort(key=lambda z:(z[0],z[1]))
    boundaries={}
    for r in trace:
        p=number(r['period']);s=round(float(r['elapsed']),3)
        boundaries[(p,s)]={'before':{t:line(r.get(t+'_before')) for t in teams},'after':{t:line(r.get(t+'_after')) for t in teams},'actions':set(filter(None,str(r.get('actions','')).split('|'))),'status':r.get('status')}
    def state(p,s,mode):
        bd=boundaries.get((p,s))
        if bd:return bd[mode]
        candidates=states.get(p,[])
        for a,b,v in candidates:
            if a<=s<b:return v
        # At the end of a period, use the last valid lineup; at its start, the first
        if candidates and abs(s-candidates[-1][1])<0.001:return candidates[-1][2]
        return None
    ev=[]
    for i,r in enumerate(pbp):
        if r.get('gameId') and r['gameId']!=gid:continue
        p=number(r.get('period'));s=elapsed(r.get('clock'),p) if p is not None else None
        if p is None or s is None:continue
        ev.append((p,s,number(r.get('actionNumber')) or 0,i,r))
    ev.sort(key=lambda z:(z[0],z[1],z[2],z[3]))
    # Infer home/away solely from positive scoreboard changes associated with a team.
    prev=(0,0);votes=Counter();score_events=[];anomalies=[]
    for p,s,an,i,r in ev:
        h=number(r.get('scoreHome'));a=number(r.get('scoreAway'))
        if h is None or a is None:continue
        dh,da=h-prev[0],a-prev[1]
        if dh or da:
            team=r.get('teamTricode','')
            if dh>0 and da==0 and team in teams:votes[(team,'home')]+=1
            if da>0 and dh==0 and team in teams:votes[(team,'away')]+=1
            score_events.append((p,s,an,i,r,dh,da))
            if dh<0 or da<0 or (dh>0 and da>0):anomalies.append({'action':an,'problem':'NEGATIVE_OR_DOUBLE_SIDE_SCORE_DELTA','home_delta':dh,'away_delta':da})
        prev=(h,a)
    options=[(home,away) for home in teams for away in teams if home!=away]
    ranked=sorted(((sum(n for (team,side),n in votes.items() if (side=='home' and team==home) or (side=='away' and team==away)),home,away) for home,away in options),reverse=True)
    if not ranked or ranked[0][0]==0 or (len(ranked)>1 and ranked[0][0]==ranked[1][0]):raise ValueError('Could not unambiguously infer home/away team from positive score deltas')
    _,home,away=ranked[0]
    # Recorded-order model: first substitution action within each atomic group switches the
    # entire team group's lineup; this is a diagnostic convention, not legal event ordering.
    first_sub={}
    for p,s,an,i,r in ev:
        if r.get('actionType')=='Substitution' and (p,s) in boundaries:
            first_sub[(p,s)]=min(an,first_sub.get((p,s),an))
    player_pm={mode:defaultdict(int) for mode in ('recorded','before','after')}
    rows=[];unassigned=0;boundary_count=0
    for p,s,an,i,r,dh,da in score_events:
        key=(p,s);bd=boundaries.get(key)
        boundary=bd is not None;boundary_count+=int(boundary)
        mode_states={}
        for mode in ('recorded','before','after'):
            use='before' if mode=='before' else 'after'
            if mode=='recorded' and boundary:use='before' if an<first_sub.get(key,float('inf')) else 'after'
            mode_states[mode]=state(p,s,use)
        output={'period':p,'elapsed':s,'action_number':an,'team':r.get('teamTricode'),'description':r.get('description'),'score_home':r.get('scoreHome'),'score_away':r.get('scoreAway'),'home_delta':dh,'away_delta':da,'at_substitution_timestamp':boundary,'recorded_convention':'FIRST_SUB_ACTION_APPLIES_ATOMIC_GROUP' if boundary else 'NON_BOUNDARY'}
        for mode,st in mode_states.items():
            good=bool(st) and all(len(st[t])==5 for t in teams)
            output[mode+'_assigned']=good
            if not good:continue
            for pid in st[home]:player_pm[mode][(home,pid)]+=dh-da
            for pid in st[away]:player_pm[mode][(away,pid)]+=da-dh
        if not all(output[mode+'_assigned'] for mode in player_pm):unassigned+=1
        rows.append(output)
    per=[];aggregates={}
    for mode in player_pm:
        matches=0;total=0;compared=0
        for r in box:
            t=r.get('teamTricode');pid=r.get('personId')
            if t not in teams or not pid:continue
            official=number(r.get('plusMinusPoints'));calculated=player_pm[mode].get((t,pid),0)
            diff=calculated-official if official is not None else None
            per.append({'scenario':mode,'team':t,'player_id':pid,'player_name':' '.join(filter(None,[r.get('firstName'),r.get('familyName')])),'official_pm':official if official is not None else '','calculated_pm':calculated,'difference':diff if diff is not None else '','comparable':official is not None})
            if official is not None:compared+=1;matches+=int(diff==0);total+=abs(diff)
        aggregates[mode]={'comparable_players':compared,'matching_players':matches,'sum_absolute_pm_error':total}
    write(out/'SCORING_EVENTS.csv',rows,['period','elapsed','action_number','team','description','score_home','score_away','home_delta','away_delta','at_substitution_timestamp','recorded_convention','recorded_assigned','before_assigned','after_assigned'])
    write(out/'PLAYER_PLUS_MINUS_SCENARIOS.csv',per,['scenario','team','player_id','player_name','official_pm','calculated_pm','difference','comparable'])
    write(out/'SCORE_ANOMALIES.csv',anomalies,['action','problem','home_delta','away_delta'])
    complete=unassigned==0 and not anomalies
    summary={'version':'9.9.10','game_id':gid,'status':'AUDIT_COMPLETED_UNVERIFIED' if complete else 'INCOMPLETE_SCORING_EVIDENCE','teams':{'home':home,'away':away},'score_events':len(rows),'scoring_boundary_events':boundary_count,'unassigned_scoring_events':unassigned,'score_anomalies':len(anomalies),'final_score_from_pbp':{'home':prev[0],'away':prev[1]},'scenarios':aggregates,'score_totals_reconciled_to_pbp':sum(r['home_delta'] for r in rows)==prev[0] and sum(r['away_delta'] for r in rows)==prev[1],'score_totals_independently_verified':False,'scoring_boundary_attribution':'UNRESOLVED','scenario_selected':None,'verified_stints':0,'production_certified':False,'database_modified':False,'warning':'Recorded-order scenario switches each substitution group at its first action. These are diagnostics, not certified effective-time semantics. Official plus/minus never selects or modifies lineups.'}
    dump(out/'SUMMARY.json',summary);return summary

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--games',type=Path,default=Path('v9_9_9_regression_games.csv'))
    ap.add_argument('--regression-dir',type=Path,default=Path('v9_9_9_regression_review'))
    ap.add_argument('--out',type=Path,default=Path('v9_9_10_scoring_review'))
    a=ap.parse_args();games=read(a.games);a.out.mkdir(parents=True,exist_ok=True)
    results=[]
    for r in games:
        gid=r['game_id'];ev=Path(r['evidence_dir']);rec=a.regression_dir/gid/'reaudit'/'reconstruction'
        try:
            if not ev.is_dir() or not rec.is_dir():raise FileNotFoundError(f'Missing evidence {ev} or reconstructed timeline {rec}')
            s=audit(gid,ev,rec,a.out/gid);result={'game_id':gid,'status':s['status'],'score_events':s['score_events'],'boundary_events':s['scoring_boundary_events'],'unassigned_events':s['unassigned_scoring_events'],'home':s['teams']['home'],'away':s['teams']['away'],'recorded_matches':s['scenarios']['recorded']['matching_players'],'before_matches':s['scenarios']['before']['matching_players'],'after_matches':s['scenarios']['after']['matching_players'],'recorded_abs_error':s['scenarios']['recorded']['sum_absolute_pm_error'],'before_abs_error':s['scenarios']['before']['sum_absolute_pm_error'],'after_abs_error':s['scenarios']['after']['sum_absolute_pm_error'],'reason':''}
        except Exception as e:result={'game_id':gid,'status':'ERROR','reason':str(e)}
        results.append(result);print(gid,result['status'],flush=True)
    cols=['game_id','status','score_events','boundary_events','unassigned_events','home','away','recorded_matches','before_matches','after_matches','recorded_abs_error','before_abs_error','after_abs_error','reason']
    write(a.out/'GAME_RESULTS.csv',results,cols)
    summary={'version':'9.9.10','requested':len(games),'processed':len(results),'completed':sum(r['status']=='AUDIT_COMPLETED_UNVERIFIED' for r in results),'results_file':'GAME_RESULTS.csv','scenario_selected':None,'scoring_boundary_attribution':'NOT_CERTIFIED','verified_stints':0,'production_certified':False,'database_modified':False}
    dump(a.out/'SUMMARY.json',summary);print(json.dumps(summary,indent=2));return 0 if summary['completed']==len(games) else 2
if __name__=='__main__':sys.exit(main())
