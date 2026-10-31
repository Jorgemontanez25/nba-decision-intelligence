#!/usr/bin/env python3
"""V9.4c: read-only plus/minus event matrix and substitution boundary sensitivity.

Uses V9.4b's replay outputs as PROVISIONAL inputs; does not optimize or repair lineups.
Alternative boundaries are counterfactual diagnostics, NOT legal or proven reconstructions.
"""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import duckdb


def load(path):
    path = Path(path)
    if not path.is_file():
        raise SystemExit(f'Missing input: {path}')
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write(path, rows, fields):
    with Path(path).open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def integer(value, default=0):
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default


def lineup(row, team):
    return set(filter(None, row[f'{team.lower()}_lineup'].split('|')))


def as_string(ids):
    return '|'.join(sorted(ids, key=int))


def contribution(team, home, away):
    return (home-away) if team == 'LAL' else (away-home)


def apply_swap(state, sub, reverse=False):
    team = sub['team']
    incoming, outgoing = sub['incoming_id'], sub['outgoing_id']
    if reverse:
        incoming, outgoing = outgoing, incoming
    if outgoing not in state[team] or incoming in state[team]:
        return False
    state[team].remove(outgoing)
    state[team].add(incoming)
    return True


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', default='nba_current.duckdb')
    p.add_argument('--game-id', default='0022500002')
    p.add_argument('--season', default='2025-26')
    p.add_argument('--season-type', default='Regular Season')
    p.add_argument('--v94b-dir', default=r'.\v9_4b_scoring_review')
    p.add_argument('--out', default=r'.\v9_4c_diagnostic')
    a = p.parse_args()
    src = Path(a.v94b_dir)
    out = Path(a.out)
    if out.resolve() == src.resolve() or out.resolve() == Path(a.db).resolve().parent:
        p.error('Output must be separate from V9.4b inputs and database directory')
    score = load(src/'scoring_events_event_order.csv')
    subs = load(src/'substitution_replay.csv')
    old = load(src/'player_plus_minus_comparison.csv')
    if not score: raise SystemExit('No scoring events in V9.4b export')
    required = {'period','elapsed','source_row','home_points','away_points','lal_lineup','gsw_lineup','assignment'}
    if not required.issubset(score[0]): raise SystemExit('Unexpected V9.4b scoring schema')
    if subs and not {'period','elapsed','source_row','team','outgoing_id','incoming_id','applied'}.issubset(subs[0]):
        raise SystemExit('Unexpected substitution replay schema')
    con = duckdb.connect(a.db, read_only=True)
    try:
        records = con.execute('''SELECT CAST(player_id AS VARCHAR),player_name,team_abbr,minutes,plus_minus
                                 FROM player_games WHERE game_id=? AND season=? AND season_type=?''',
                              [a.game_id,a.season,a.season_type]).fetchall()
    finally:
        con.close()
    roster = {str(pid): {'name': name,'team':team,'minutes':minutes,'box_pm':pm}
              for pid,name,team,minutes,pm in records}
    if not roster: raise SystemExit('No matching box scores found')
    base = defaultdict(int)
    matrix=[]
    unknown=set()
    for e in score:
        h, aw = integer(e['home_points']), integer(e['away_points'])
        states = {'LAL':lineup(e,'LAL'), 'GSW':lineup(e,'GSW')}
        if e['assignment']!='ASSIGNED_EVENT_ORDER_PROVISIONAL':
            unknown.add(e['source_row'])
        for team in ('LAL','GSW'):
            for pid in sorted(states[team],key=int):
                if pid not in roster or roster[pid]['team']!=team:
                    raise SystemExit(f'Unknown/wrong-team player {pid} in scoring row {e["source_row"]}')
                inc = contribution(team,h,aw)
                base[pid] += inc
                matrix.append({'period':e['period'],'elapsed':e['elapsed'],'action_number':e['action_number'],
                               'source_row':e['source_row'],'team':team,'player_id':pid,
                               'player_name':roster[pid]['name'],'plus_minus_contribution':inc,
                               'home_points':h,'away_points':aw,'assignment':e['assignment']})
    checks=[]
    for pid,r in sorted(roster.items(),key=lambda v:(v[1]['team'],v[1]['name'])):
        calc=base.get(pid,0)
        box=r['box_pm']
        delta=calc-box if box is not None else None
        checks.append({'team':r['team'],'player_id':pid,'player_name':r['name'],
                       'box_plus_minus':box,'replay_plus_minus':calc,'delta_from_box':delta,
                       'status':'MATCH_PROVISIONAL' if delta==0 else ('NO_BOX_PM' if box is None else 'MISMATCH')})
    old_pm = {row['player_id']:integer(row['attributed_plus_minus']) for row in old}
    drift={pid:(base[pid],old_pm[pid]) for pid in old_pm if base[pid]!=old_pm[pid]}
    if drift: raise SystemExit(f'V9.4b scoring matrix does not reproduce prior attribution: {drift}')
    by_key=defaultdict(list)
    for s in subs:
        if s['applied'].strip().lower() in ('true','1','yes'):
            by_key[(s['period'],s['elapsed'])].append(s)
    for group in by_key.values():
        group.sort(key=lambda s:integer(s['source_row']))
    residual={pid:base.get(pid,0)-r['box_pm'] for pid,r in roster.items() if r['box_pm'] is not None}
    base_loss=sum(d*d for d in residual.values())
    candidates=[]
    for e in score:
        key=(e['period'],e['elapsed'])
        group=by_key.get(key,[])
        if not group: continue
        event_row=integer(e['source_row'])
        current={'LAL':lineup(e,'LAL'),'GSW':lineup(e,'GSW')}
        h,aw=integer(e['home_points']),integer(e['away_points'])
        for mode in ('ALL_BEFORE','ALL_AFTER'):
            alt={t:set(ids) for t,ids in current.items()}
            changes=([s for s in group if integer(s['source_row'])<event_row][::-1]
                     if mode=='ALL_BEFORE' else
                     [s for s in group if integer(s['source_row'])>event_row])
            applicable=True
            for s in changes:
                if not apply_swap(alt,s,reverse=(mode=='ALL_BEFORE')):
                    applicable=False
                    break
            if not applicable or alt==current or any(len(alt[t])!=5 for t in alt):continue
            delta={}
            for team in ('LAL','GSW'):
                inc=contribution(team,h,aw)
                for pid in current[team]-alt[team]:delta[pid]=delta.get(pid,0)-inc
                for pid in alt[team]-current[team]:delta[pid]=delta.get(pid,0)+inc
            if any(pid not in residual for pid in delta):continue
            loss=base_loss+sum((residual[pid]+amount)**2-residual[pid]**2 for pid,amount in delta.items())
            candidates.append({'period':e['period'],'elapsed':e['elapsed'],
                'action_number':e['action_number'],'source_row':e['source_row'],
                'scenario':mode,'points':h+aw,'changes_count':len(changes),
                'current_lal':as_string(current['LAL']),'current_gsw':as_string(current['GSW']),
                'hypothetical_lal':as_string(alt['LAL']),'hypothetical_gsw':as_string(alt['GSW']),
                'affected_players':'; '.join(f'{roster[pid]["name"]}({delta[pid]:+d})' for pid in sorted(delta,key=int)),
                'baseline_squared_error':base_loss,'hypothetical_squared_error':loss,
                'squared_error_improvement':base_loss-loss,
                'warning':'COUNTERFACTUAL_ONLY_NOT_VALIDATED; would require official substitution/scoring semantics and minutes constraints'})
    candidates.sort(key=lambda r:(-r['squared_error_improvement'],int(r['source_row']),r['scenario']))
    out.mkdir(parents=True,exist_ok=True)
    write(out/'event_player_pm_matrix.csv',matrix,['period','elapsed','action_number','source_row','team','player_id','player_name','plus_minus_contribution','home_points','away_points','assignment'])
    write(out/'player_pm_residuals.csv',checks,['team','player_id','player_name','box_plus_minus','replay_plus_minus','delta_from_box','status'])
    cols=['period','elapsed','action_number','source_row','scenario','points','changes_count','current_lal','current_gsw','hypothetical_lal','hypothetical_gsw','affected_players','baseline_squared_error','hypothetical_squared_error','squared_error_improvement','warning']
    write(out/'boundary_counterfactuals.csv',candidates,cols)
    summary={'game_id':a.game_id,'source_scoring_events':len(score),
             'player_event_matrix_rows':len(matrix),
             'source_substitutions':len(subs),'candidate_boundary_scenarios':len(candidates),
             'box_pm_matches_provisional':sum(r['status']=='MATCH_PROVISIONAL' for r in checks),
             'box_pm_mismatches':sum(r['status']=='MISMATCH' for r in checks),
             'total_squared_pm_error':base_loss,
             'uncertain_input_scoring_events':len(unknown),'verified_stints':0,
             'notes':['Counterfactuals are sensitivity tests, NOT verified player assignments.',
                      'A lower squared error does not establish legal minute totals, unique lineups, or correct NBA attribution.',
                      'No files or tables in the input database are modified.']}
    (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2));print('Reports:',out.resolve())

if __name__=='__main__':main()
