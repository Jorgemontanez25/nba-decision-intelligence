#!/usr/bin/env python3
"""Read-only V9.3 comparison of provisional reconstructed NBA minutes with box scores."""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import duckdb


def number(value):
    if value is None or str(value).strip() == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', default='nba_current.duckdb')
    p.add_argument('--game-id', default='0022500002')
    p.add_argument('--season', default='2025-26')
    p.add_argument('--season-type', default='Regular Season')
    p.add_argument('--minutes-csv', default=r'v9_2c_lakers_review/reconstructed_minutes_UNVERIFIED.csv')
    p.add_argument('--stints-csv', default=r'v9_2c_lakers_review/reconstruction_stints_PROVISIONAL.csv')
    p.add_argument('--out', default='v9_3_minutes_review')
    a = p.parse_args()
    with open(a.minutes_csv, newline='', encoding='utf-8-sig') as f:
        reconstructed = list(csv.DictReader(f))
    if not reconstructed or not {'player_id', 'team', 'reconstructed_minutes'}.issubset(reconstructed[0]):
        raise SystemExit('Reconstruction CSV missing required columns.')
    conn = duckdb.connect(a.db, read_only=True)
    try:
        rows = conn.execute('''SELECT player_id, player_name, team_abbr, minutes, starter, plus_minus
            FROM player_games WHERE game_id=? AND season=? AND season_type=? ORDER BY team_abbr, player_id''',
            [a.game_id, a.season, a.season_type]).fetchall()
    finally:
        conn.close()
    if not rows:
        raise SystemExit('No box-score records found for selected game, season, and type.')
    box = {}
    for pid, name, team, minutes, starter, pm in rows:
        key = (str(pid), str(team).upper())
        if key in box:
            raise SystemExit(f'Duplicate box-score player key: {key}')
        box[key] = {'name': name, 'minutes': number(minutes), 'starter': starter, 'plus_minus': pm}
    recon = {}
    for row in reconstructed:
        key = (str(row['player_id']), str(row['team']).upper())
        if key in recon:
            raise SystemExit(f'Duplicate reconstructed player key: {key}')
        recon[key] = number(row['reconstructed_minutes'])
    output = []
    for key in sorted(set(box) | set(recon), key=lambda k: (k[1], k[0])):
        official = box.get(key, {})
        obs = recon.get(key)
        actual = official.get('minutes')
        difference = round(obs - actual, 3) if obs is not None and actual is not None else None
        output.append({'team': key[1], 'player_id': key[0], 'player_name': official.get('name',''),
            'box_minutes': actual, 'reconstructed_minutes': obs, 'delta_minutes': difference,
            'absolute_delta': round(abs(difference), 3) if difference is not None else None,
            'starter': official.get('starter',''), 'box_plus_minus': official.get('plus_minus',''),
            'status': 'MISSING_BOX' if key not in box else 'MISSING_RECON' if key not in recon else
                      'MISSING_MINUTES' if difference is None else 'MATCH_LE_0.1' if abs(difference) <= .1 else 'DIFFERENCE'})
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    fields = list(output[0])
    with (out / 'player_minutes_comparison.csv').open('w', newline='', encoding='utf-8') as f:
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader(); wr.writerows(sorted(output, key=lambda x: (x['absolute_delta'] is None, -(x['absolute_delta'] or 0))))

    # Read lineup snapshots ONLY to compare the initial snapshot against box score starter flags.
    with open(a.stints_csv, newline='', encoding='utf-8-sig') as f:
        stints = list(csv.DictReader(f))
    starter_comparison = []
    for team in ('LAL', 'GSW'):
        col = team.lower() + '_lineup'
        early = [x for x in stints if str(x.get('period')) == '1' and number(x.get('start_seconds')) == 0]
        start_ids = set(str(early[0][col]).split('|')) if early and col in early[0] else set()
        true_ids = {pid for (pid, tm), d in box.items() if tm == team and d['starter'] is True}
        starter_comparison.append({'team': team, 'initial_lineup_ids': '|'.join(sorted(start_ids)),
            'box_starter_ids': '|'.join(sorted(true_ids)),
            'match': bool(start_ids and len(true_ids) == 5 and start_ids == true_ids),
            'box_starter_count': len(true_ids)})
    with (out / 'starter_comparison.csv').open('w', newline='', encoding='utf-8') as f:
        wr = csv.DictWriter(f, fieldnames=list(starter_comparison[0])); wr.writeheader(); wr.writerows(starter_comparison)
    totals = defaultdict(lambda: {'box':0.0,'reconstructed':0.0})
    for x in output:
        if x['box_minutes'] is not None: totals[x['team']]['box'] += x['box_minutes']
        if x['reconstructed_minutes'] is not None: totals[x['team']]['reconstructed'] += x['reconstructed_minutes']
    summary = {'game_id':a.game_id,'season':a.season,'season_type':a.season_type,
        'box_player_records':len(box),'reconstruction_player_records':len(recon),
        'missing_box_or_reconstruction':sum(x['status'].startswith('MISSING') for x in output),
        'players_with_delta_over_0_1_minutes':sum(x['absolute_delta'] is not None and x['absolute_delta'] > .1 for x in output),
        'largest_absolute_delta_minutes':max((x['absolute_delta'] for x in output if x['absolute_delta'] is not None),default=None),
        'team_minutes_totals':{t:{k:round(v,3) for k,v in d.items()} for t,d in totals.items()},
        'starter_comparison':starter_comparison,
        'verified_stints':0,
        'note':'Comparison only; does not certify reconstructed lineups, plus/minus, unique solution, or scores.'}
    (out/'SUMMARY.json').write_text(json.dumps(summary, indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))
    print('Reports:',out.resolve())

if __name__ == '__main__':
    main()
