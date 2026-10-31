#!/usr/bin/env python3
"""V9.4 Lakers-Warriors read-only score/stint/plus-minus audit.

Never overwrites input CSVs or writes to DuckDB. Results are diagnostics, not certification.
"""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import duckdb

GAME = '0022500002'
TEAMS = ('LAL', 'GSW')


def read_csv(path):
    with Path(path).open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    with Path(path).open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def fl(value, default=None):
    try:
        if value is None or str(value).strip() == '':
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def int_or_none(value):
    n = fl(value)
    return int(n) if n is not None and n.is_integer() else None


def lineup(value):
    ids = [s.strip() for s in str(value or '').split('|') if s.strip()]
    return tuple(sorted(ids))


def period_range(p):
    if 1 <= p <= 4:
        return 720 * (p - 1), 720 * p
    return 2880 + 300 * (p - 5), 2880 + 300 * (p - 4)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db', default='nba_current.duckdb')
    ap.add_argument('--game-id', default=GAME)
    ap.add_argument('--season', default='2025-26')
    ap.add_argument('--season-type', default='Regular Season')
    ap.add_argument('--stints-csv', default=r'v9_2c_lakers_review/reconstruction_stints_PROVISIONAL.csv')
    ap.add_argument('--actions-csv', default=r'v9_lakers_test/0022500002/actions_preview.csv')
    ap.add_argument('--out', default='v9_4_scoring_review')
    ap.add_argument('--boundary-tolerance', type=float, default=0.001)
    a = ap.parse_args()
    if a.boundary_tolerance < 0 or a.boundary_tolerance > 0.1:
        ap.error('Boundary tolerance must be 0..0.1 seconds')
    out = Path(a.out)
    inputs = [Path(a.stints_csv).resolve(), Path(a.actions_csv).resolve(), Path(a.db).resolve()]
    if out.resolve() in inputs or any(out.resolve() == p.parent for p in inputs):
        ap.error('Choose a separate output directory, not an input directory')
    raw = read_csv(a.actions_csv)
    stints_raw = read_csv(a.stints_csv)
    if not raw or not stints_raw:
        raise SystemExit('Input CSV empty; refusing to report success')
    required_actions = {'period','elapsed','action_number','type','score_home','score_away'}
    required_stints = {'game_id','period','start_seconds','end_seconds','lal_lineup','gsw_lineup'}
    if not required_actions <= set(raw[0]):
        raise SystemExit('Missing action fields: '+str(sorted(required_actions - set(raw[0]))))
    if not required_stints <= set(stints_raw[0]):
        raise SystemExit('Missing stint fields: '+str(sorted(required_stints - set(stints_raw[0]))))

    con = duckdb.connect(str(a.db), read_only=True)
    try:
        players = con.execute('''SELECT CAST(player_id AS VARCHAR), player_name, team_abbr,
            minutes, plus_minus, starter, points
            FROM player_games WHERE game_id=? AND season=? AND season_type=?''',
            [a.game_id, a.season, a.season_type]).fetchall()
        team_rows = con.execute('''SELECT team_abbr, points FROM team_games
            WHERE game_id=? AND season=? AND season_type=?''',
            [a.game_id, a.season, a.season_type]).fetchall()
    finally:
        con.close()
    if not players: raise SystemExit('No box-score player records for game')
    roster = {p[0]:dict(name=p[1],team=p[2],minutes=p[3],plus_minus=p[4],starter=p[5],points=p[6]) for p in players}
    box_team_scores = {str(t): int_or_none(pts) for t,pts in team_rows}
    # These IDs are supported by the previously inspected game header and matchup.
    home, away = 'LAL', 'GSW'

    issues = []
    stints = []
    for i,r in enumerate(stints_raw):
        if r['game_id'] != a.game_id:
            raise SystemExit(f'Stint game mismatch on row {i+2}')
        p = int_or_none(r['period']); s = fl(r['start_seconds']); e = fl(r['end_seconds'])
        if p is None or s is None or e is None or e <= s:
            raise SystemExit(f'Invalid stint timing on row {i+2}')
        l, g = lineup(r['lal_lineup']), lineup(r['gsw_lineup'])
        if len(l)!=5 or len(g)!=5 or len(set(l))!=5 or len(set(g))!=5:
            issues.append(dict(category='invalid_lineup',reference=i+2,detail='Not five unique players per team'))
        for tm,players_ids in ((home,l),(away,g)):
            for pid in players_ids:
                if pid not in roster or roster[pid]['team'] != tm:
                    issues.append(dict(category='wrong_team_or_unknown_player',reference=i+2,detail=f'{tm}:{pid}'))
        stints.append(dict(period=p,start=s,end=e,lal=l,gsw=g,source_row=i+2))
    stints.sort(key=lambda r:(r['start'],r['end']))
    tol = 0.00001
    periods = sorted(set(s['period'] for s in stints))
    for p in periods:
        xs = [s for s in stints if s['period']==p]
        lo,hi = period_range(p)
        if abs(xs[0]['start']-lo)>tol or abs(xs[-1]['end']-hi)>tol:
            issues.append(dict(category='period_coverage',reference=p,detail=f'got {xs[0]["start"]}..{xs[-1]["end"]}, expected {lo}..{hi}'))
        for prev,curr in zip(xs,xs[1:]):
            if abs(prev['end']-curr['start'])>tol:
                issues.append(dict(category='overlap_or_gap',reference=p,detail=f'{prev["end"]} vs {curr["start"]}'))
    totals = defaultdict(float)
    for s in stints:
        if len(s['lal'])==5:
            for pid in s['lal']: totals[pid] += (s['end']-s['start'])/60
        if len(s['gsw'])==5:
            for pid in s['gsw']: totals[pid] += (s['end']-s['start'])/60
    minutes_deltas = []
    for pid,d in roster.items():
        expected = fl(d['minutes'],0)
        calc = totals.get(pid,0)
        minutes_deltas.append(dict(player_id=pid,team=d['team'],player_name=d['name'],box_minutes=expected,reconstructed_minutes=round(calc,5),delta_minutes=round(calc-expected,5)))

    # Merge event-separated intervals only within each period and when both lineups agree.
    merged = []
    for s in stints:
        if (merged and merged[-1]['period']==s['period'] and
            abs(merged[-1]['end']-s['start'])<tol and
            merged[-1]['lal']==s['lal'] and merged[-1]['gsw']==s['gsw']):
            merged[-1]['end']=s['end']
        else:
            merged.append(dict(s))

    # Score snapshots sometimes skip blank rows; use consecutive valid scoreboards.
    # Every positive delta gets its own scoring event, even if a shot was misclassified.
    # Do not infer that a free throw or shot must have yielded a fixed number of points.
    events = []
    prev_score = (0,0)
    prev_time = 0.0
    ordered = sorted(enumerate(raw),key=lambda x:(int_or_none(x[1].get('period')) or 0, fl(x[1].get('elapsed'),0),x[0]))
    for idx,r in ordered:
        h=int_or_none(r['score_home']); aw=int_or_none(r['score_away'])
        if h is None or aw is None: continue
        p = int_or_none(r['period']); t = fl(r['elapsed']); action = r.get('action_number','')
        if p is None or t is None: continue
        dh,da=h-prev_score[0],aw-prev_score[1]
        if dh<0 or da<0 or dh>4 or da>4 or (dh>0 and da>0):
            issues.append(dict(category='score_progression',reference=action,detail=f'{prev_score}->{(h,aw)} at {t}'))
        if dh or da:
            events.append(dict(row=idx+2,period=p,elapsed=t,action_number=action,
                event_type=r.get('type',''),description=r.get('description',''),
                home_points=dh,away_points=da,home_score=h,away_score=aw,
                previous_score_time=prev_time))
        prev_score=(h,aw); prev_time=t
    final_score=dict(LAL=prev_score[0],GSW=prev_score[1])
    for team in TEAMS:
        if team in box_team_scores and box_team_scores[team] is not None and final_score[team] != box_team_scores[team]:
            issues.append(dict(category='team_score_discrepancy',reference=team,detail=f'event={final_score[team]} box={box_team_scores[team]}'))

    scoring_rows = []
    certain = defaultdict(lambda:dict(for_pts=0,against_pts=0))
    ambiguity = defaultdict(lambda:dict(for_pts=0,against_pts=0))
    score_ambiguous = []
    for ev in events:
        p,t = ev['period'],ev['elapsed']
        nearby = [s for s in merged if s['period']==p and s['start']-a.boundary_tolerance <= t <= s['end']+a.boundary_tolerance]
        candidates = {(s['lal'],s['gsw']) for s in nearby}
        # Same-clock substitution: even if solver says identical lineup on both sides,
        # mark boundary for independent review, but score can be assigned if identical.
        if len(candidates)==1:
            l,g=next(iter(candidates)); status='ASSIGNED_PROVISIONAL'
            for team,pids,for_points,against in ((home,l,ev['home_points'],ev['away_points']),
                                                   (away,g,ev['away_points'],ev['home_points'])):
                for pid in pids:
                    certain[pid]['for_pts']+=for_points
                    certain[pid]['against_pts']+=against
        else:
            status = 'AMBIGUOUS_BOUNDARY' if candidates else 'NO_STINT_AT_SCORE_TIME'
            score_ambiguous.append(ev)
            # Track pessimistic uncertainty per player among all adjacent lineup candidates.
            for l,g in candidates:
                for team,pids,for_points,against in ((home,l,ev['home_points'],ev['away_points']),
                                                       (away,g,ev['away_points'],ev['home_points'])):
                    for pid in pids:
                        ambiguity[pid]['for_pts']+=for_points
                        ambiguity[pid]['against_pts']+=against
        scoring_rows.append(dict(**ev,assignment=status,
            candidate_lineup_count=len(candidates),
            lal_lineup='|'.join(next(iter(candidates))[0]) if len(candidates)==1 else '',
            gsw_lineup='|'.join(next(iter(candidates))[1]) if len(candidates)==1 else ''))
    # Ignore duplicate candidate-lineup uncertainty as a metric; it is a diagnostic upper envelope.
    plus_rows=[]
    for pid,d in sorted(roster.items(),key=lambda x:(x[1]['team'],x[1]['name'])):
        assigned=certain[pid]; boxpm=fl(d['plus_minus']); pm=assigned['for_pts']-assigned['against_pts']
        has_uncertain=any(pid in set(s['lal'])|set(s['gsw']) for ev in score_ambiguous
                          for s in merged if s['period']==ev['period'] and s['start']-a.boundary_tolerance<=ev['elapsed']<=s['end']+a.boundary_tolerance)
        status=('UNRESOLVED_SCORING_BOUNDARY' if has_uncertain else
                'NO_BOX_PLUS_MINUS' if boxpm is None else 'MATCH' if abs(pm-boxpm)<=0.001 else 'MISMATCH')
        plus_rows.append(dict(team=d['team'],player_id=pid,player_name=d['name'],box_plus_minus=boxpm,
                              attributed_plus_minus=pm,delta_from_box=round(pm-boxpm,3) if boxpm is not None else '',
                              assigned_points_for=assigned['for_pts'],assigned_points_against=assigned['against_pts'],
                              status=status))
    # Aggressive label: all outputs remain provisional until unique lineup solution demonstrated.
    merged_rows=[]
    for i,s in enumerate(merged):
        evs=[r for r in scoring_rows if r['assignment']=='ASSIGNED_PROVISIONAL' and r['period']==s['period'] and
             s['start']-a.boundary_tolerance<=r['elapsed']<=s['end']+a.boundary_tolerance and
             r['lal_lineup']=='|'.join(s['lal']) and r['gsw_lineup']=='|'.join(s['gsw'])]
        merged_rows.append(dict(segment=i+1,period=s['period'],start_seconds=s['start'],end_seconds=s['end'],
            duration_seconds=round(s['end']-s['start'],3),lal_lineup='|'.join(s['lal']),gsw_lineup='|'.join(s['gsw']),
            points_lal=sum(r['home_points'] for r in evs),points_gsw=sum(r['away_points'] for r in evs),
            status='PROVISIONAL_NOT_UNIQUENESS_VERIFIED'))
    out.mkdir(parents=True,exist_ok=True)
    write_csv(out/'scoring_events_audit.csv',scoring_rows,['row','period','elapsed','action_number','event_type','description','home_points','away_points','home_score','away_score','previous_score_time','assignment','candidate_lineup_count','lal_lineup','gsw_lineup'])
    write_csv(out/'unassigned_scoring_events.csv',[r for r in scoring_rows if r['assignment']!='ASSIGNED_PROVISIONAL'],['row','period','elapsed','action_number','event_type','description','home_points','away_points','assignment','candidate_lineup_count'])
    write_csv(out/'player_plus_minus_comparison.csv',plus_rows,['team','player_id','player_name','box_plus_minus','attributed_plus_minus','delta_from_box','assigned_points_for','assigned_points_against','status'])
    write_csv(out/'merged_lineup_intervals_PROVISIONAL.csv',merged_rows,['segment','period','start_seconds','end_seconds','duration_seconds','lal_lineup','gsw_lineup','points_lal','points_gsw','status'])
    write_csv(out/'player_minutes_audit.csv',minutes_deltas,['player_id','team','player_name','box_minutes','reconstructed_minutes','delta_minutes'])
    write_csv(out/'structural_issues.csv',issues,['category','reference','detail'])
    summary=dict(game_id=a.game_id,raw_rows=len(raw),source_stints=len(stints),merged_intervals=len(merged),
        final_score_from_actions=final_score,box_team_scores=box_team_scores,scoring_events=len(events),
        points_from_scoring_deltas={'LAL':sum(e['home_points'] for e in events),'GSW':sum(e['away_points'] for e in events)},
        scoring_events_assigned_provisionally=sum(r['assignment']=='ASSIGNED_PROVISIONAL' for r in scoring_rows),
        ambiguous_or_unassigned_scoring_events=len(score_ambiguous),
        players_with_box_plus_minus_mismatch=sum(r['status']=='MISMATCH' for r in plus_rows),
        players_with_uncertain_scoring=sum(r['status']=='UNRESOLVED_SCORING_BOUNDARY' for r in plus_rows),
        players_with_minutes_difference_over_0_1=sum(abs(r['delta_minutes'])>0.1 for r in minutes_deltas),
        structural_issues=len(issues),verified_stints=0,
        note='Read-only diagnostic; provisional solver history can be nonunique. Score boundary attribution and play-by-play scoreboard snapshots require verification before certification.')
    (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))
    print('Reports:',out.resolve())

if __name__=='__main__':
    main()
