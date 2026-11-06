#!/usr/bin/env python3
"""V9.4b: Read-only, event-ordered scoring / lineup audit for NBA game 0022500002.

Keeps play-by-play source ordering (including duplicate action numbers), resolves
SUB: IN FOR OUT via player_games, and audits both sides of shared timestamps.
Never asserts that provisional lineup assignments are uniquely verified.
"""
import argparse
import csv
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import duckdb


def read(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def save(path, rows, fields):
    with Path(path).open('w', encoding='utf-8', newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore')
        w.writeheader(); w.writerows(rows)


def number(v):
    try:
        if v is None or str(v).strip()=='': return None
        return float(v)
    except (ValueError,TypeError): return None


def canonical(value):
    return tuple(sorted(str(int(x)) for x in str(value).split('|') if x.strip()))


def norm(s):
    s=unicodedata.normalize('NFKD',str(s or ''))
    s=''.join(x for x in s if not unicodedata.combining(x))
    return re.sub('[^a-z0-9]+',' ',s.lower()).strip()


def aliases(name):
    bits=norm(name).split()
    if not bits:return set()
    result={norm(name), bits[-1], ' '.join(bits[1:])}
    if len(bits)>=2:result.add(' '.join(bits[-2:]))
    if len(bits)>=2 and bits[-1] in ('ii','iii','iv','jr','sr'):
        result.add(bits[-2])
    return result


def resolve(name, team, roster):
    text=norm(name)
    hits=[pid for pid,v in roster.items() if v['team']==team and text in aliases(v['name'])]
    return hits[0] if len(hits)==1 else None


def eq_state(a,b):
    return a['LAL']==b['LAL'] and a['GSW']==b['GSW']


def copy_state(x):
    return {k:set(x[k]) for k in ('LAL','GSW')}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',default='nba_current.duckdb')
    p.add_argument('--game-id',default='0022500002')
    p.add_argument('--season',default='2025-26')
    p.add_argument('--season-type',default='Regular Season')
    p.add_argument('--actions-csv',default=r'.\v9_lakers_test\0022500002\actions_preview.csv')
    p.add_argument('--stints-csv',default=r'.\v9_2c_lakers_review\reconstruction_stints_PROVISIONAL.csv')
    p.add_argument('--out',default=r'.\v9_4b_scoring_review')
    p.add_argument('--tolerance',type=float,default=0.002)
    args=p.parse_args()
    if args.tolerance<0 or args.tolerance>0.1:p.error('Tolerance must be between 0 and 0.1 seconds')
    out=Path(args.out)
    for inp in (args.db,args.actions_csv,args.stints_csv):
        if out.resolve()==Path(inp).resolve() or out.resolve()==Path(inp).resolve().parent:
            p.error('Output must not be an input directory or file')
    raw=read(args.actions_csv); src=read(args.stints_csv)
    if not raw or not src:raise SystemExit('Missing/empty source CSV')
    for fields,rows,which in (({'period','elapsed','type','score_home','score_away','team_id','person_id','description'},raw,'actions'),
                              ({'game_id','period','start_seconds','end_seconds','lal_lineup','gsw_lineup'},src,'stints')):
        missing=fields-set(rows[0])
        if missing:raise SystemExit(f'Missing {which} columns: {sorted(missing)}')
    con=duckdb.connect(args.db,read_only=True)
    try:
        recs=con.execute('SELECT CAST(player_id AS VARCHAR),player_name,team_abbr,minutes,plus_minus,starter FROM player_games WHERE game_id=? AND season=? AND season_type=?',
                         [args.game_id,args.season,args.season_type]).fetchall()
        teams=con.execute('SELECT team_abbr,points FROM team_games WHERE game_id=? AND season=? AND season_type=?',
                          [args.game_id,args.season,args.season_type]).fetchall()
    finally:con.close()
    roster={x[0]:dict(name=x[1],team=x[2],minutes=x[3],pm=x[4],starter=x[5]) for x in recs}
    if set(x['team'] for x in roster.values())!={'LAL','GSW'}:
        raise SystemExit('Pilot requires LAL and GSW box-score roster')
    if len({x['game_id'] for x in src})!=1 or src[0]['game_id']!=args.game_id:
        raise SystemExit('Stints game_id mismatch')
    stints=[]
    for i,s in enumerate(src):
        stints.append(dict(period=int(s['period']),start=float(s['start_seconds']),end=float(s['end_seconds']),
                           LAL=set(canonical(s['lal_lineup'])),GSW=set(canonical(s['gsw_lineup'])),row=i+2))
    stints.sort(key=lambda s:(s['period'],s['start'],s['end']))
    for s in stints:
        if len(s['LAL'])!=5 or len(s['GSW'])!=5:
            raise SystemExit(f'Invalid 5v5 interval near source row {s["row"]}')
    grouped_stints=defaultdict(list)
    for s in stints:grouped_stints[s['period']].append(s)
    events=[]
    for i,r in enumerate(raw):
        t=number(r['elapsed']); period=number(r['period'])
        if t is None or period is None:continue
        events.append(dict(r,idx=i,period_num=int(period),time=t))
    events.sort(key=lambda e:(e['period_num'],e['time'],e['idx']))
    by_time=defaultdict(list)
    for e in events:by_time[(e['period_num'],e['time'])].append(e)
    problems=[]; audit=[]; subs=[]
    # Source schema is known to use these IDs; reject unfamiliar teams rather than misassign.
    team_ids={'1610612747':'LAL','1610612744':'GSW'}
    def expected_states(p,t):
        xs=grouped_stints[p]
        before=[s for s in xs if abs(s['end']-t)<=args.tolerance]
        after=[s for s in xs if abs(s['start']-t)<=args.tolerance]
        interior=[s for s in xs if s['start']+args.tolerance<t<s['end']-args.tolerance]
        return before[-1] if before else None, after[0] if after else None, interior[0] if interior else None
    def same(a,b):
        return a is not None and b is not None and a['LAL']==b['LAL'] and a['GSW']==b['GSW']
    last_score=[0,0]
    for (period,t),group in sorted(by_time.items()):
        left,right,middle=expected_states(period,t)
        state=copy_state(left or middle or right) if (left or middle or right) else None
        if state is None:
            problems.append(dict(period=period,elapsed=t,action='',problem='no_lineup_at_timestamp',detail=''))
        group_errors=[]; start_idx=len(audit)
        for e in group:
            event_type=str(e.get('type','')).strip().lower()
            action=e.get('action_number','')
            description=e.get('description','')
            if event_type=='substitution':
                team=team_ids.get(str(e.get('team_id','')).strip())
                outgoing=str(e.get('person_id','')).strip()
                match=re.search(r'\bSUB\s*:\s*(.*?)\s+FOR\s+(.*)$',description,flags=re.I)
                incoming=resolve(match.group(1),team,roster) if match and team else None
                detail=[]
                if not match:detail.append('unparseable_substitution')
                if team is None:detail.append('unknown_team_id')
                if incoming is None:detail.append('ambiguous_incoming_player')
                if state is None:detail.append('missing_state')
                elif team and outgoing not in state[team]:detail.append('outgoing_not_on_court')
                elif team and incoming in state[team]:detail.append('incoming_already_on_court')
                if detail:
                    problem=';'.join(detail)
                    group_errors.append(problem)
                    problems.append(dict(period=period,elapsed=t,action=action,problem='substitution_'+problem,detail=description))
                    applied=False
                else:
                    state[team].remove(outgoing);state[team].add(incoming);applied=True
                subs.append(dict(period=period,elapsed=t,action=action,source_row=e['idx']+2,team=team,
                                 outgoing_id=outgoing,incoming_id=incoming or '',description=description,
                                 applied=applied,issue=';'.join(detail)))
            h=number(e.get('score_home')); aw=number(e.get('score_away'))
            if h is None or aw is None:continue
            dh=int(h)-last_score[0];da=int(aw)-last_score[1]
            if dh<0 or da<0 or dh>4 or da>4 or (dh>0 and da>0):
                problems.append(dict(period=period,elapsed=t,action=action,problem='score_delta_invalid',detail=f'{last_score}->{(h,aw)}'))
                group_errors.append('score_delta_invalid')
            if dh or da:
                audit.append(dict(period=period,elapsed=t,action_number=action,source_row=e['idx']+2,
                    event_type=e.get('type',''),description=description,home_points=dh,away_points=da,
                    lal_lineup='|'.join(sorted(state['LAL'])) if state else '',
                    gsw_lineup='|'.join(sorted(state['GSW'])) if state else '',
                    assignment='PENDING_GROUP_VALIDATION',reason=''))
            last_score=[int(h),int(aw)]
        # Compare sequential substitutions against independent provisional states.
        # The pre/post boundaries may be absent when the CP-SAT lineup didn't change.
        valid_start=left or middle or right
        valid_end=right or middle or left
        if not same(state,valid_end):
            group_errors.append('post_event_lineup_differs_from_solver')
            problems.append(dict(period=period,elapsed=t,action='',problem='post_event_lineup_differs_from_solver',
                                 detail='Cannot certify action replay against interval state'))
        if group_errors:
            for r in audit[start_idx:]:
                r['assignment']='UNRESOLVED_REPLAY_STATE';r['reason']=';'.join(sorted(set(group_errors)))
        else:
            for r in audit[start_idx:]:r['assignment']='ASSIGNED_EVENT_ORDER_PROVISIONAL'
    # A second, stricter gate: a conflict at one time can contaminate events later in the same
    # period. Mark all scoring in that period uncertain until the discrepancy is investigated.
    bad_periods={x['period'] for x in problems if x['problem'].startswith(('substitution_','post_event_lineup','no_lineup'))}
    for a in audit:
        if a['period'] in bad_periods:
            a['assignment']='UNRESOLVED_PERIOD_REPLAY';a['reason']='replay errors elsewhere in period'
    per_player=defaultdict(int)
    for row in audit:
        if row['assignment']!='ASSIGNED_EVENT_ORDER_PROVISIONAL':continue
        for pid in row['lal_lineup'].split('|'):
            per_player[pid]+=row['home_points']-row['away_points']
        for pid in row['gsw_lineup'].split('|'):
            per_player[pid]+=row['away_points']-row['home_points']
    uncertain={pid for row in audit if row['assignment']!='ASSIGNED_EVENT_ORDER_PROVISIONAL' for pid in
               row['lal_lineup'].split('|')+row['gsw_lineup'].split('|') if pid}
    comp=[]
    for pid,d in sorted(roster.items(),key=lambda x:(x[1]['team'],x[1]['name'])):
        pm=number(d['pm']); calculated=per_player[pid]
        status='UNCERTAIN_EVENT_ORDER' if pid in uncertain else ('NO_BOX_PLUS_MINUS' if pm is None else
                'MATCH_PROVISIONAL' if calculated==pm else 'MISMATCH')
        comp.append(dict(team=d['team'],player_id=pid,player_name=d['name'],box_plus_minus=pm if pm is not None else '',
                         attributed_plus_minus=calculated,delta_from_box=calculated-pm if pm is not None else '',status=status))
    out.mkdir(parents=True,exist_ok=True)
    save(out/'scoring_events_event_order.csv',audit,['period','elapsed','action_number','source_row','event_type','description','home_points','away_points','lal_lineup','gsw_lineup','assignment','reason'])
    save(out/'unresolved_scoring_events.csv',[r for r in audit if r['assignment']!='ASSIGNED_EVENT_ORDER_PROVISIONAL'],
         ['period','elapsed','action_number','source_row','event_type','description','home_points','away_points','assignment','reason'])
    save(out/'substitution_replay.csv',subs,['period','elapsed','action','source_row','team','outgoing_id','incoming_id','description','applied','issue'])
    save(out/'replay_issues.csv',problems,['period','elapsed','action','problem','detail'])
    save(out/'player_plus_minus_comparison.csv',comp,['team','player_id','player_name','box_plus_minus','attributed_plus_minus','delta_from_box','status'])
    summary=dict(game_id=args.game_id,scoring_events=len(audit),
       score_from_event_deltas={'LAL':sum(x['home_points'] for x in audit),'GSW':sum(x['away_points'] for x in audit)},
       box_team_scores={x[0]:x[1] for x in teams},
       scoring_events_assigned_provisionally=sum(x['assignment']=='ASSIGNED_EVENT_ORDER_PROVISIONAL' for x in audit),
       unresolved_scoring_events=sum(x['assignment']!='ASSIGNED_EVENT_ORDER_PROVISIONAL' for x in audit),
       substitution_events=len(subs),substitution_events_applied=sum(x['applied'] for x in subs),
       replay_issues=len(problems),bad_periods=sorted(bad_periods),
       plus_minus_matches_provisional=sum(x['status']=='MATCH_PROVISIONAL' for x in comp),
       plus_minus_mismatches=sum(x['status']=='MISMATCH' for x in comp),
       players_with_uncertain_scoring=sum(x['status']=='UNCERTAIN_EVENT_ORDER' for x in comp),
       verified_stints=0,note='Read-only diagnostic. Chronological event assignment alone does not prove the solver lineup is unique or official plus/minus correct.')
    (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2));print('Reports:',out.resolve())

if __name__=='__main__':main()
