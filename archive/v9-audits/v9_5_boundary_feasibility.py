"""V9.5A: read-only *conditional* scoring-boundary feasibility audit.
Tests binary before/after scoring attribution against official plus/minus while
HOLDING the provisional lineups fixed. Does not certify an NBA lineup history.
"""
import argparse, csv, json, math
from collections import defaultdict
from pathlib import Path


def readcsv(p):
    with open(p, newline='', encoding='utf-8-sig') as f: return list(csv.DictReader(f))

def val(row, *keys):
    for k in keys:
        if k in row and row[k] not in ('', None): return row[k]
    return None

def num(v, default=None):
    try: return float(v)
    except (TypeError, ValueError): return default

def lineup(s): return tuple(str(s or '').split('|')) if s else ()

def writecsv(p, records, cols):
    with open(p,'w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(records)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--game-id',default='0022500002')
    ap.add_argument('--source-dir',default='v9_4e_official_evidence')
    ap.add_argument('--stints',default='v9_2c_lakers_review/reconstruction_stints_PROVISIONAL.csv')
    ap.add_argument('--out',default='v9_5_feasibility_review')
    a=ap.parse_args(); out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    summary={'game_id':a.game_id,'mode':'READ_ONLY_CONDITIONAL_AUDIT','verified_stints':0,'limitations':[
      'All lineup states are provisional; the optimization does not prove unique or official player presence.',
      'Only same-timestamp scoring-before/after-substitution changes are allowed; other lineup histories are not explored.',
      'Official plus/minus can follow scoring attribution conventions not encoded by this model.',
      'This program NEVER changes the original DuckDB or promotes provisional stints.']}
    try:
        pbp=readcsv(Path(a.source_dir)/'playbyplayv3_dataset_0.csv')
        box=readcsv(Path(a.source_dir)/'boxscoretraditionalv3_dataset_0.csv')
        st=readcsv(Path(a.stints))
        assert pbp and box and st, 'An input dataset is empty'
        required_st={'period','start_seconds','end_seconds','lal_lineup','gsw_lineup'}
        missing=required_st-set(st[0])
        if missing: raise ValueError('Stints columns missing: '+str(sorted(missing)))
        periods=defaultdict(list)
        for r in st:
            row={'p':int(float(r['period'])),'s':float(r['start_seconds']),'e':float(r['end_seconds']),
                 'LAL':lineup(r['lal_lineup']),'GSW':lineup(r['gsw_lineup'])}
            if len(row['LAL'])!=5 or len(row['GSW'])!=5: raise ValueError('Stint with lineup size !=5')
            periods[row['p']].append(row)
        for arr in periods.values(): arr.sort(key=lambda x:(x['s'],x['e']))
        official={}
        for r in box:
            player=val(r,'personId','person_id')
            pm=num(val(r,'plusMinusPoints','plus_minus'))
            if player and pm is not None: official[str(player)]=int(round(pm))
        if not official: raise ValueError('No official plusMinusPoints found in box score')
        # PBP V3 is one action per row, but sort defensively.
        pbp.sort(key=lambda r:int(float(val(r,'actionNumber') or -1)))
        bytime=defaultdict(list)
        for r in pbp:
            p=num(val(r,'period')); t=num(val(r,'elapsed'))
            if t is None and p is not None:
                import re
                clock=val(r,'clock') or ''
                m=re.fullmatch(r'PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?',clock)
                if m: t=(int(p)-1)*720 + 720-(int(m.group(1) or 0)*60+float(m.group(2) or 0))
            if p is not None and t is not None: bytime[(int(p),round(t,3))].append(r)
        # Reconstruct points from scoreboard snapshots, accounting for non-scoring rows.
        prev={'LAL':0,'GSW':0}; events=[]; score_anomalies=[]
        # pbp ordered by source actionNumber (not by absolute clock)
        for r in pbp:
            sh=num(val(r,'scoreHome'));sa=num(val(r,'scoreAway'))
            if sh is None or sa is None: continue
            dh=int(round(sh))-prev['LAL']; da=int(round(sa))-prev['GSW']
            if dh<0 or da<0: score_anomalies.append(str(val(r,'actionNumber')));continue
            if dh or da:
                p=int(float(val(r,'period'))); import re
                m=re.fullmatch(r'PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?', val(r,'clock') or '')
                if not m: raise ValueError('Unparseable scoring clock at action '+str(val(r,'actionNumber')))
                elapsed=round((p-1)*720+720-int(m.group(1) or 0)*60-float(m.group(2) or 0),3)
                events.append({'period':p,'elapsed':elapsed,'action':str(val(r,'actionNumber')),'LAL':dh,'GSW':da})
            prev={'LAL':int(round(sh)),'GSW':int(round(sa))}
        if score_anomalies: raise ValueError('Scoreboard went backwards at actions '+','.join(score_anomalies))
        if prev != {'LAL':109,'GSW':119}:
            summary['warning']='Final score differs from pilot game expected 109-119: '+str(prev)
        players=sorted(official)
        base={i:0 for i in players}; changes=[]; decisions=[]; uncovered=[]
        def contribute(ids,points):
            arr={i:0 for i in players}
            for team in ('LAL','GSW'):
                sign=points[team]-points['GSW' if team=='LAL' else 'LAL']
                for i in ids[team]:
                    if i in arr: arr[i]+=sign
            return arr
        for ev in events:
            arr=periods.get(ev['period'],[])
            t=ev['elapsed']
            at=[s for s in arr if s['s']-0.005<=t<s['e']-0.005]
            before=[s for s in arr if abs(s['e']-t)<0.005]
            after=[s for s in arr if abs(s['s']-t)<0.005]
            # If there are real lineup boundaries, treat current assumption as AFTER.
            eligible=bool(before and after and (before[-1]['LAL'],before[-1]['GSW'])!=(after[0]['LAL'],after[0]['GSW']))
            chosen=after[0] if eligible else (at[0] if len(at)==1 else None)
            if chosen is None: uncovered.append(ev);continue
            standard=contribute(chosen,ev)
            for i,v in standard.items():base[i]+=v
            if eligible:
                alternative=contribute(before[-1],ev)
                delta={i:alternative[i]-standard[i] for i in players}
                changes.append(delta)
                decisions.append({'period':ev['period'],'elapsed':t,'action_number':ev['action'],
                    'LAL_points':ev['LAL'],'GSW_points':ev['GSW'],
                    'source_assumption':'AFTER_BOUNDARY','alternative':'BEFORE_BOUNDARY',
                    'changed_players':sum(v!=0 for v in delta.values())})
        summary.update({'official_players':len(official),'stints_input':len(st),'scoring_events':len(events),
            'boundary_event_variables':len(changes),'scoring_events_uncovered':len(uncovered),
            'baseline_pm_mismatched_players':sum(base[i]!=official[i] for i in players),
            'baseline_abs_pm_error':sum(abs(base[i]-official[i]) for i in players),
            'baseline_score':prev})
        writecsv(out/'boundary_candidates.csv',decisions,['period','elapsed','action_number','LAL_points','GSW_points','source_assumption','alternative','changed_players'])
        writecsv(out/'pm_baseline.csv',[{'player_id':i,'official_pm':official[i],'baseline_pm':base[i],'delta':base[i]-official[i]} for i in players],['player_id','official_pm','baseline_pm','delta'])
        writecsv(out/'uncovered_events.csv',uncovered,['period','elapsed','action','LAL','GSW'])
        if uncovered:
            summary['feasibility']='NOT_TESTED_UNCOVERED_SCORING_EVENTS'
        elif not changes:
            summary['feasibility']='NO_VARIABLE_BOUNDARIES';summary['exact_match']=all(base[i]==official[i] for i in players)
        else:
            try:
                import numpy as np
                from scipy.optimize import milp, LinearConstraint, Bounds
                mat=np.array([[d[i] for d in changes] for i in players],dtype=float)
                rhs=np.array([official[i]-base[i] for i in players],dtype=float)
                n=len(changes)
                # no objective preference; find exact feasibility under fixed stints and this boundary-only model
                result=milp(np.zeros(n),integrality=np.ones(n),bounds=Bounds(np.zeros(n),np.ones(n)),constraints=[LinearConstraint(mat,rhs,rhs)],options={'time_limit':60})
                summary['solver_status']=str(result.message)
                if result.x is None:
                    summary['feasibility']='NO_EXACT_BOUNDARY_ONLY_SOLUTION' if result.status==2 else 'UNDETERMINED'
                else:
                    bits=np.rint(result.x).astype(int)
                    selected=[dict(decisions[j],use_before=bool(bits[j])) for j in range(n)]
                    writecsv(out/'feasible_assignment_UNVERIFIED.csv',selected,list(selected[0]))
                    summary['feasibility']='CONDITIONALLY_FEASIBLE_UNVERIFIED'
                    # Test alternatives to the first solution one variable at a time.
                    # Any feasible flip suffices to demonstrate nonuniqueness within this narrow model.
                    nonunique=[]; undecided=[]
                    for j in range(n):
                        c=np.zeros(n);c[j]=1
                        r=milp(np.zeros(n),integrality=np.ones(n),bounds=Bounds(np.zeros(n),np.ones(n)),constraints=[LinearConstraint(mat,rhs,rhs),LinearConstraint(c,1-bits[j],1-bits[j])],options={'time_limit':10})
                        if r.x is not None: nonunique.append(j)
                        elif r.status!=2: undecided.append(j)
                    summary['alternative_solution_found']=bool(nonunique)
                    summary['uniqueness']='NON_UNIQUE_WITHIN_MODEL' if nonunique else ('UNDETERMINED' if undecided else 'UNIQUE_WITHIN_FIXED_STINT_BOUNDARY_MODEL_ONLY')
                    summary['alternative_boundary_variables']=len(nonunique)
            except ImportError:
                summary['feasibility']='NOT_TESTED_SCIPY_MISSING';summary['instruction']='pip install scipy'
    except Exception as exc:
        summary['feasibility']='INPUT_ERROR';summary['error']=f'{type(exc).__name__}: {exc}'
    (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))
    return 1 if summary['feasibility'] in ('INPUT_ERROR','NOT_TESTED_SCIPY_MISSING') else 0

if __name__=='__main__': raise SystemExit(main())
