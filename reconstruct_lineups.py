"""Conservative 5-on-5 lineup reconstruction from normalized events + verified period anchors.

No guesses: missing anchors, unknown substitutions, discontinuity or invalid scoring
cause the relevant period to be rejected. Events are sorted by (period, sec, sequence).
A substitution at second t is applied *after* closing the pre-substitution stint.
CSV event schema: period,sec,sequence,event_type,team_abbr,player_out,player_in,
                  home_score,away_score
Score snapshot at an event is AFTER that event; field may be blank on substitutions.
Anchor schema: period,home_player_ids,away_player_ids,source (pipe-separated IDs).
"""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def ids(s):
    out = [int(x) for x in s.split('|') if x.strip()]
    if len(out) != 5 or len(set(out)) != 5 or any(x <= 0 for x in out):
        raise ValueError('Anchor must have five distinct positive player IDs')
    return set(out)


def period_length(period):
    return 720 if period <= 4 else 300


def reconstruct(events, anchors, home, away, game_id, season, season_type, source='normalized_pbp'):
    """Return accepted rows, rejected periods. Point totals from score differences.

    Requires explicit score snapshot at 0 and end of each period, and exactly five
    known IDs per side. Event clocks are elapsed seconds in the *period*.
    """
    by_period = defaultdict(list)
    for e in events:
        by_period[int(e['period'])].append(e)
    accepted=[]; rejected=[]
    anchor_map={int(a['period']):a for a in anchors}
    for period, group in sorted(by_period.items()):
        try:
            if period not in anchor_map:
                raise ValueError('missing verified period-start lineup')
            a=anchor_map[period]
            if not str(a.get('source','')).strip():
                raise ValueError('anchor source missing')
            sets={home:ids(a['home_player_ids']),away:ids(a['away_player_ids'])}
            if sets[home] & sets[away]: raise ValueError('same player on both teams')
            limit=period_length(period)
            group=sorted(group,key=lambda e:(float(e['sec']),int(e['sequence'])))
            if not group or float(group[0]['sec']) != 0 or group[0]['event_type']!='score':
                raise ValueError('missing period opening score snapshot')
            if float(group[-1]['sec']) != limit or group[-1]['event_type']!='score':
                raise ValueError('missing period ending score snapshot')
            hs=int(group[0]['home_score']); aws=int(group[0]['away_score'])
            start=0.0; segment_h=hs;segment_a=aws; segment_index=0; period_rows=[]
            # close stints at substitutions, keeping simultaneous changes grouped
            i=1
            while i<len(group):
                e=group[i]; t=float(e['sec'])
                if t<start or t>limit:raise ValueError('event time outside period')
                typ=e['event_type']
                if typ=='score':
                    h=int(e['home_score']); aw=int(e['away_score'])
                    if h<hs or aw<aws: raise ValueError('score decreased')
                    hs,aws=h,aw
                    i+=1;continue
                if typ!='sub': raise ValueError('unrecognized event_type')
                # consume simultaneous substitutions; scores at same instant must have
                # occurred before substitutions, verified by sequence ordering
                if t>start:
                    period_rows.append(_row(sets,start,t,segment_h,segment_a,hs,aws,
                                            game_id,season,season_type,home,away,period,segment_index,source))
                    segment_index+=1
                batch=[]
                while i<len(group) and group[i]['event_type']=='sub' and float(group[i]['sec'])==t:
                    batch.append(group[i]);i+=1
                # remove all outgoing players before adding incoming (swaps checked)
                proposed={home:set(sets[home]),away:set(sets[away])}
                for sub in batch:
                    team=sub['team_abbr']
                    if team not in proposed:raise ValueError('unknown substitution team')
                    p_out=int(sub['player_out']); p_in=int(sub['player_in'])
                    if p_out not in sets[team] or p_in in sets[team]:
                        raise ValueError('invalid incoming/outgoing player')
                    proposed[team].remove(p_out)
                for sub in batch:
                    team=sub['team_abbr']; p_in=int(sub['player_in'])
                    if p_in in proposed[team]:raise ValueError('duplicate incoming player')
                    proposed[team].add(p_in)
                if any(len(s)!=5 for s in proposed.values()) or (proposed[home]&proposed[away]):
                    raise ValueError('invalid five-player substitution result')
                sets=proposed; start=t;segment_h=hs;segment_a=aws
            if limit>start:
                period_rows.append(_row(sets,start,limit,segment_h,segment_a,hs,aws,
                                        game_id,season,season_type,home,away,period,segment_index,source))
            if sum(r['end_sec']-r['start_sec'] for r in period_rows) != limit:
                raise ValueError('period coverage mismatch')
            accepted.extend(period_rows)
        except (ValueError,TypeError,KeyError) as exc:
            rejected.append({'period':period,'reason':str(exc)})
    return accepted,rejected


def _row(sets,start,end,h0,a0,h1,a1,game_id,season,season_type,home,away,period,index,source):
    return dict(stint_id=f'{game_id}:{period}:{index}',game_id=game_id,season=season,
        season_type=season_type,team_abbr=home,opponent_abbr=away,period=period,
        start_sec=start,end_sec=end,points_for=h1-h0,points_against=a1-a0,
        possessions_for='',possessions_against='',
        team_player_ids='|'.join(map(str,sorted(sets[home]))),
        opponent_player_ids='|'.join(map(str,sorted(sets[away]))),source=source)


def read_csv(path):
    with open(path,newline='',encoding='utf8') as f:return list(csv.DictReader(f))


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--events',required=True);p.add_argument('--anchors',required=True)
    p.add_argument('--game-id',required=True);p.add_argument('--season',required=True)
    p.add_argument('--season-type',choices=['Regular Season','Playoffs'],required=True)
    p.add_argument('--home',required=True);p.add_argument('--away',required=True)
    p.add_argument('--output',default='stints_verified.csv')
    args=p.parse_args()
    rows,errors=reconstruct(read_csv(args.events),read_csv(args.anchors),args.home,args.away,args.game_id,args.season,args.season_type)
    if errors:
        print('REJECTED:',json.dumps(errors,indent=2));raise SystemExit(2)
    if not rows:raise SystemExit('No verified stints generated')
    with open(args.output,'w',newline='',encoding='utf8') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(f'Exported {len(rows)} verified stints to {args.output}. Possession counts intentionally unknown.')

if __name__=='__main__':main()
