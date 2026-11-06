"""V9.6 read-only global scoring-boundary feasibility and source-integrity audit.

This is NOT an unconstrained lineup reconstruction. Lineups remain fixed to the
V9.2c provisional stints. No stints are certified or written to DuckDB.
"""
import argparse, csv, json, re, sys
from collections import defaultdict
from pathlib import Path


def load(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def save(path, rows, cols):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w=csv.DictWriter(f, fieldnames=cols, extrasaction='ignore');w.writeheader();w.writerows(rows)


def clock_time(period, clock):
    m=re.fullmatch(r'PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?',str(clock or ''))
    if not m: raise ValueError('Invalid clock: '+str(clock))
    return round((period-1)*720+720-int(m.group(1) or 0)*60-float(m.group(2) or 0),3)


def L(s): return tuple(str(s or '').split('|'))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game-id', default='0022500002')
    ap.add_argument('--official-dir', default='v9_4e_official_evidence')
    ap.add_argument('--stints',default='v9_2c_lakers_review/reconstruction_stints_PROVISIONAL.csv')
    ap.add_argument('--out',default='v9_6_global_review')
    a=ap.parse_args();o=Path(a.out);o.mkdir(parents=True,exist_ok=True)
    summary={'version':'9.6','game_id':a.game_id,'mode':'READ_ONLY_FIXED_STINT_GLOBAL_ATTRIBUTION_AUDIT',
             'verified_stints':0,'database_modified':False,
             'limitations':['V9.2c lineups are fixed, provisional inputs, NOT solved globally.',
              'Boundary choices cannot establish legal NBA substitution effective-times.',
              'Even exact player plus/minus is insufficient to prove unique lineups.',
              'No provisional data is promoted to production.']}
    try:
        import numpy as np
        from scipy.optimize import milp, Bounds, LinearConstraint
        pbp=load(Path(a.official_dir)/'playbyplayv3_dataset_0.csv')
        box=load(Path(a.official_dir)/'boxscoretraditionalv3_dataset_0.csv')
        st=load(Path(a.stints))
        if not pbp or not box or not st: raise ValueError('Empty input file')
        if len({(r['actionNumber'],r.get('description','')) for r in pbp})!=len(pbp):
            summary['source_duplicate_rows_warning']=True
        periods=defaultdict(list)
        for r in st:
            p=int(r['period']);s=float(r['start_seconds']);e=float(r['end_seconds']);
            if e<=s: raise ValueError('Nonpositive stint '+str(r))
            ids={'LAL':L(r['lal_lineup']),'GSW':L(r['gsw_lineup'])}
            for team,li in ids.items():
                if len(li)!=5 or len(set(li))!=5: raise ValueError('Invalid 5-player lineup in period '+str(p))
            periods[p].append({'s':s,'e':e,'ids':ids})
        for p in periods: periods[p].sort(key=lambda r:r['s'])
        discontinuities=[]
        for p,ss in periods.items():
            for left,right in zip(ss,ss[1:]):
                if abs(left['e']-right['s'])>0.01:
                    discontinuities.append({'period':p,'left_end':left['e'],'right_start':right['s']})
        if discontinuities: raise ValueError(f'{len(discontinuities)} gaps/overlaps in stint sequence')
        official={}; names={}; minutes={}
        for r in box:
            pid=str(r.get('personId',''));team=r.get('teamTricode')
            if not pid or team not in ('LAL','GSW'):continue
            if r.get('plusMinusPoints') not in ('',None):
                official[pid]=int(round(float(r['plusMinusPoints'])))
                names[pid]=r.get('nameI') or r.get('name') or r.get('firstName','')+' '+r.get('familyName','')
            minutes[pid]=r.get('minutes','')
        if not official: raise ValueError('No official plus/minus found')
        pbp.sort(key=lambda r:int(r['actionNumber']))
        last={'LAL':0,'GSW':0};events=[]; regressions=[]; substitutions=defaultdict(list)
        for r in pbp:
            p=int(r['period']);t=clock_time(p,r['clock']); typ=r.get('actionType','')
            if typ=='Substitution': substitutions[(p,t)].append(r)
            sh=r.get('scoreHome');sa=r.get('scoreAway')
            if sh in ('',None) or sa in ('',None):continue
            now={'LAL':int(float(sh)),'GSW':int(float(sa))}
            change={x:now[x]-last[x] for x in now}
            if any(v<0 for v in change.values()):regressions.append(r['actionNumber'])
            elif any(v>0 for v in change.values()):
                events.append({'period':p,'elapsed':t,'action_number':r['actionNumber'],
                               'LAL_points':change['LAL'],'GSW_points':change['GSW'],
                               'scorer_id':str(r.get('personId','')),'action_type':typ})
            last=now
        if regressions:raise ValueError('Score decreased at actions '+','.join(regressions))
        players=sorted(official);index={id:i for i,id in enumerate(players)};baseline=np.zeros(len(players),dtype=int)
        changes=[];candidate=[];uncovered=[];scorer_warnings=[]
        def contribution(lineup,event):
            v=np.zeros(len(players),dtype=int)
            for team,li in lineup.items():
                points=event[team+'_points']-event['GSW_points' if team=='LAL' else 'LAL_points']
                for pid in li:
                    if pid in index:v[index[pid]]+=points
            return v
        for ev in events:
            p=ev['period'];t=ev['elapsed'];ss=periods.get(p,[])
            pre=[r for r in ss if abs(r['e']-t)<0.005]
            post=[r for r in ss if abs(r['s']-t)<0.005]
            interior=[r for r in ss if r['s']-0.005<=t<r['e']-0.005]
            boundary=bool(pre and post and pre[-1]['ids']!=post[0]['ids'])
            selected=post[0] if boundary else (interior[0] if len(interior)==1 else None)
            if selected is None:
                uncovered.append(ev);continue
            cv=contribution(selected['ids'],ev);baseline+=cv
            scoring_team='LAL' if ev['LAL_points']>0 else 'GSW'
            scorer=ev['scorer_id']
            if ev['action_type']=='Made Shot' and scorer and scorer not in selected['ids'][scoring_team]:
                scorer_warnings.append({'action_number':ev['action_number'],'scorer_id':scorer,'reason':'Scorer not in default post-boundary lineup'})
            if boundary:
                alt=contribution(pre[-1]['ids'],ev)
                delta=alt-cv
                if ev['action_type']=='Made Shot' and scorer:
                    valid_pre=scorer in pre[-1]['ids'][scoring_team]
                    valid_post=scorer in post[0]['ids'][scoring_team]
                else:valid_pre=valid_post=True
                # Only constrain made-shot actor presence; free-throw attribution may differ from court presence.
                candidate.append(dict(ev,source_assumption='AFTER',alternative='BEFORE',
                                      substitutions_at_timestamp=len(substitutions.get((p,t),[])),
                                      before_scorer_present=valid_pre,after_scorer_present=valid_post,
                                      changed_players=int(np.count_nonzero(delta))))
                changes.append(delta)
        save(o/'boundary_candidates.csv',candidate,['period','elapsed','action_number','action_type','LAL_points','GSW_points','source_assumption','alternative','substitutions_at_timestamp','before_scorer_present','after_scorer_present','changed_players','scorer_id'])
        save(o/'uncovered_events.csv',uncovered,['period','elapsed','action_number','LAL_points','GSW_points','scorer_id','action_type'])
        save(o/'scorer_presence_warnings.csv',scorer_warnings,['action_number','scorer_id','reason'])
        ref=np.array([official[x] for x in players],dtype=int)
        def resid_rows(vector):
            return [dict(player_id=pid,player_name=names.get(pid,''),official_pm=int(ref[j]),reconstructed_pm=int(vector[j]),delta=int(vector[j]-ref[j])) for j,pid in enumerate(players)]
        save(o/'pm_baseline.csv',resid_rows(baseline),['player_id','player_name','official_pm','reconstructed_pm','delta'])
        summary.update({'source_actions':len(pbp),'official_players':len(players),'provisional_stints':len(st),
                        'scoring_events':len(events),'boundary_variables':len(changes),'uncovered_scoring_events':len(uncovered),
                        'scorer_presence_warnings':len(scorer_warnings),'final_score':last,
                        'baseline_pm_mismatches':int(np.count_nonzero(baseline-ref)),
                        'baseline_absolute_pm_error':int(np.sum(abs(baseline-ref)))})
        if uncovered:summary['verdict']='BLOCKED_UNCOVERED_EVENTS'
        elif not changes:summary['verdict']='NO_BOUNDARY_VARIABLES'
        else:
            n=len(changes);D=np.column_stack(changes).astype(float);rhs=(ref-baseline).astype(float)
            lo=np.zeros(n);hi=np.ones(n)
            for j,r in enumerate(candidate):
                if r['action_type']=='Made Shot':
                    if not r['before_scorer_present']:hi[j]=0
                    if not r['after_scorer_present']:lo[j]=1
                    if lo[j]>hi[j]:raise ValueError('Scorer impossible in both boundary lineups')
            exact=milp(np.zeros(n),integrality=np.ones(n),bounds=Bounds(lo,hi),constraints=LinearConstraint(D,rhs,rhs),options={'time_limit':45})
            summary['exact_solver_status']=str(exact.message)
            if exact.x is not None:
                bits=np.rint(exact.x).astype(int);pred=baseline+D@bits
                summary['verdict']='EXACT_PM_FEASIBLE_FIXED_STINTS_UNVERIFIED'
                summary['exact_residual_L1']=int(np.sum(abs(pred-ref)))
                # Distinct second solution check via flipping a candidate one at a time.
                alternate=False;tested=0
                for j in range(n):
                    if lo[j]==hi[j]:continue
                    fixed=np.zeros(n);fixed[j]=1
                    other=milp(np.zeros(n),integrality=np.ones(n),bounds=Bounds(lo,hi),constraints=[LinearConstraint(D,rhs,rhs),LinearConstraint(fixed,1-bits[j],1-bits[j])],options={'time_limit':3})
                    tested+=1
                    if other.x is not None:alternate=True;break
                summary['nonunique_within_model']=alternate
                summary['uniqueness_checks_completed']=tested
            else:
                # Minimize total absolute player PM residual without pretending it is an exact fit.
                # Variables: n binary choices; m nonnegative positive and negative residual slacks.
                m=len(players);A=np.concatenate([D,-np.eye(m),np.eye(m)],axis=1)
                bounds=Bounds(np.concatenate([lo,np.zeros(2*m)]),np.concatenate([hi,np.full(2*m,np.inf)]))
                objective=np.concatenate([np.zeros(n),np.ones(2*m)])
                best=milp(objective,integrality=np.concatenate([np.ones(n),np.zeros(2*m)]),bounds=bounds,
                          constraints=LinearConstraint(A,rhs,rhs),options={'time_limit':45})
                summary['minimum_error_solver_status']=str(best.message)
                if best.x is None:summary['verdict']='UNDETERMINED_SOLVER_TIMEOUT_OR_FAILURE'
                else:
                    bits=np.rint(best.x[:n]).astype(int);pred=np.rint(baseline+D@bits).astype(int)
                    summary['verdict']='NO_EXACT_PM_MATCH_WITH_FIXED_STINTS'
                if best.x is None:bits=None
            if bits is not None:
                save(o/'pm_best_conditional.csv',resid_rows(pred),['player_id','player_name','official_pm','reconstructed_pm','delta'])
                save(o/'boundary_solution_UNVERIFIED.csv',[dict(r,use_before=bool(bits[j])) for j,r in enumerate(candidate)],list(candidate[0])+['use_before'])
                summary['best_pm_mismatches']=int(np.count_nonzero(pred-ref))
                summary['best_absolute_pm_error']=int(np.sum(abs(pred-ref)))
        summary['publication_gate']='BLOCKED_UNVERIFIED_STINTS'
    except Exception as ex:
        summary['verdict']='INPUT_OR_RUNTIME_ERROR';summary['error']=f'{type(ex).__name__}: {ex}'
    (o/'SUMMARY.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(summary,indent=2,ensure_ascii=False))
    return 1 if summary['verdict']=='INPUT_OR_RUNTIME_ERROR' else 0

if __name__=='__main__':sys.exit(main())
