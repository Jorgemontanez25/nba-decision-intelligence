#!/usr/bin/env python3
"""V9.4d evidence-first, read-only NBA scoring boundary audit.

Source-order checks are NOT an official ruling on effective substitution timing.
Counterfactual rankings are NOT corrections. No database writes.
"""
import argparse,csv,json,re
from pathlib import Path
from collections import defaultdict,Counter


def read_csv(path):
    path=Path(path)
    if not path.is_file(): raise SystemExit(f'Missing required file: {path}')
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def write_csv(path,rows,fields):
    with open(path,'w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)

def num(value,default=0):
    try:return int(float(value))
    except (ValueError,TypeError):return default

def sub_id(r): return num(r['source_row'])

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--game-id',default='0022500002')
    p.add_argument('--actions-csv',default=r'.\v9_lakers_test\0022500002\actions_preview.csv')
    p.add_argument('--v94b-dir',default=r'.\v9_4b_scoring_review')
    p.add_argument('--v94c-dir',default=r'.\v9_4c_diagnostic')
    p.add_argument('--out',default=r'.\v9_4d_evidence_review')
    a=p.parse_args()
    actions=read_csv(a.actions_csv)
    scores=read_csv(Path(a.v94b_dir)/'scoring_events_event_order.csv')
    subs=read_csv(Path(a.v94b_dir)/'substitution_replay.csv')
    candidates=read_csv(Path(a.v94c_dir)/'boundary_counterfactuals.csv')
    pm=read_csv(Path(a.v94c_dir)/'player_pm_residuals.csv')
    if not actions or not scores:raise SystemExit('Empty actions or scoring input')
    required_a={'action_number','period','elapsed','type','description'}
    required_s={'source_row','action_number','period','elapsed','lal_lineup','gsw_lineup','home_points','away_points'}
    if not required_a.issubset(actions[0]) or not required_s.issubset(scores[0]):raise SystemExit('Unexpected CSV schema')
    if len(actions)<max(sub_id(r) for r in scores)-1:raise SystemExit('actions_preview.csv is shorter than V9.4b source row references')
    # Source row refers to the original CSV data line, header is line 1.
    indexed={i+2:r for i,r in enumerate(actions)}
    score_by_source={sub_id(s):s for s in scores}
    sub_by_source={sub_id(s):s for s in subs}
    for n,s in score_by_source.items():
        source=indexed.get(n)
        if not source or source['action_number']!=s['action_number'] or source['period']!=s['period']:
            raise SystemExit(f'V9.4b scoring source row {n} does not match actions CSV; do not interpret results')
    for n,s in sub_by_source.items():
        source=indexed.get(n)
        if not source or source['action_number']!=s['action'] or source['period']!=s['period']:
            raise SystemExit(f'V9.4b substitution source row {n} does not match actions CSV')
    by_time=defaultdict(list)
    for n,r in indexed.items():by_time[(r['period'],r['elapsed'])].append((n,r))
    substitute_times={(s['period'],s['elapsed']) for s in subs}
    evidence=[]
    for n,s in sorted(score_by_source.items()):
        time=(s['period'],s['elapsed'])
        same_subs=[(m,r) for m,r in by_time[time] if m in sub_by_source]
        if not same_subs:continue
        earlier=[m for m,_ in same_subs if m<n]
        later=[m for m,_ in same_subs if m>n]
        source=indexed[n]
        near=' | '.join(f'{m}:{r["type"]}:{r["description"]}' for m,r in by_time[time] if abs(m-n)<=4)[:450]
        is_ft='free throw' in source.get('type','').lower()
        is_technical='technical' in (source.get('sub_type','')+' '+source.get('description','')).lower()
        is_flagrant='flagrant' in (source.get('sub_type','')+' '+source.get('description','')).lower()
        evidence.append(dict(period=s['period'],elapsed=s['elapsed'],action_number=s['action_number'],source_row=n,
            source_event=source.get('description',''),home_points=s['home_points'],away_points=s['away_points'],
            earlier_substitution_rows='|'.join(map(str,earlier)),later_substitution_rows='|'.join(map(str,later)),
            source_order_state=('AFTER_ALL_SUBS' if earlier and not later else 'BEFORE_ALL_SUBS' if later and not earlier else 'BETWEEN_SUBS' if earlier and later else 'SAME_TIME_WITH_SUBS'),
            source_order_evidence='CHRONOLOGY_ONLY_NOT_OFFICIAL_EFFECTIVE_TIME',
            scoring_type=('TECHNICAL_FT' if is_technical else 'FLAGRANT_FT' if is_flagrant else 'FREE_THROW' if is_ft else 'OTHER_SCORE'),
            nearby_actions=near,official_boundary_confirmation='NOT_AVAILABLE',review_status='REQUIRES_INDEPENDENT_CONFIRMATION'))
    evidence_by_row={int(r['source_row']):r for r in evidence}
    scenarios=[]
    for c in candidates:
        n=sub_id(c);e=evidence_by_row.get(n)
        if not e:continue
        mode=c['scenario']
        if mode=='ALL_BEFORE': altered=e['earlier_substitution_rows']
        elif mode=='ALL_AFTER':altered=e['later_substitution_rows']
        else:altered=''
        # Comparing scores against states where already recorded substitutions are reversed/advanced.
        # Not automatically valid: real-time substitution effective order may differ from row order.
        scenarios.append(dict(period=c['period'],elapsed=c['elapsed'],action_number=c['action_number'],source_row=n,
          scenario=mode,points=c.get('points',''),squared_error_improvement=c.get('squared_error_improvement',''),
          affected_players=c.get('affected_players',''),source_order_state=e['source_order_state'],
          recorded_substitution_rows_reordered=altered,source_order_deviation=('YES' if altered else 'NO'),
          official_support='NOT_ESTABLISHED',minutes_preserved='NOT_TESTED',event_state_uniqueness='NOT_TESTED',
          decision='DO_NOT_APPLY_COUNTERFACTUAL'))
    scenarios.sort(key=lambda r:(-float(r['squared_error_improvement'] or 0),r['source_row']))
    review=[]
    for r in pm:
        review.append(dict(team=r['team'],player_name=r['player_name'],box_plus_minus=r['box_plus_minus'],
          replay_plus_minus=r['replay_plus_minus'],delta_from_box=r['delta_from_box'],
          status=r['status'],independent_reconciliation='NOT_COMPLETE' if r['status']=='MISMATCH' else 'PROVISIONAL_MATCH'))
    out=Path(a.out)
    if out.resolve() in (Path(a.v94b_dir).resolve(),Path(a.v94c_dir).resolve(),Path(a.actions_csv).resolve().parent):
        raise SystemExit('Choose a separate output folder')
    out.mkdir(parents=True,exist_ok=True)
    write_csv(out/'boundary_source_order_evidence.csv',evidence,
      ['period','elapsed','action_number','source_row','source_event','home_points','away_points','earlier_substitution_rows','later_substitution_rows','source_order_state','source_order_evidence','scoring_type','nearby_actions','official_boundary_confirmation','review_status'])
    write_csv(out/'counterfactual_evidence_assessment.csv',scenarios,
      ['period','elapsed','action_number','source_row','scenario','points','squared_error_improvement','affected_players','source_order_state','recorded_substitution_rows_reordered','source_order_deviation','official_support','minutes_preserved','event_state_uniqueness','decision'])
    write_csv(out/'player_pm_evidence_status.csv',review,
      ['team','player_name','box_plus_minus','replay_plus_minus','delta_from_box','status','independent_reconciliation'])
    summary={'game_id':a.game_id,'source_actions':len(actions),'scoring_events':len(scores),'substitutions':len(subs),
       'scoring_events_at_substitution_timestamps':len(evidence),'counterfactual_scenarios':len(scenarios),
       'source_row_integrity':'PASS','provisional_pm_mismatches':sum(r['status']=='MISMATCH' for r in review),
       'source_order_deviating_scenarios':sum(r['source_order_deviation']=='YES' for r in scenarios),
       'official_boundary_confirmations':0,'verified_stints':0,
       'conclusion':'Recorded event order established; independent official effective-time evidence is absent. No counterfactual is certified.',
       'notes':['This audit does not claim that NBA scoring chronology establishes legal substitution effective times.',
                'No official independent play-by-play was supplied or fetched.',
                'Statistical improvement is never treated as evidence of an actual lineup.',
                'Inputs and database remain unmodified.']}
    (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2));print('Reports:',out.resolve())

if __name__=='__main__':main()
