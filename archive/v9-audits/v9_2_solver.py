"""V9.2 constraint-based NBA 5v5 reconstruction; read-only diagnostic.

Uses action CSV produced by V9 pilot plus DuckDB player_games to map player IDs
and OR-Tools CP-SAT to reconstruct each period independently.
No result is marked verified solely because a feasible solution exists.
"""
import argparse, csv, json, re, unicodedata
from collections import defaultdict, Counter
from pathlib import Path


def norm(s):
    s = unicodedata.normalize('NFKD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def read_csv(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def save_csv(path, rows, columns):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore'); w.writeheader(); w.writerows(rows)


def number(v, default=0):
    try: return int(float(v))
    except (TypeError, ValueError): return default


def db_rosters(path, game):
    import duckdb
    conn = duckdb.connect(str(path), read_only=True)
    try:
        cols = {r[0] for r in conn.execute('DESCRIBE player_games').fetchall()}
        required = {'game_id','player_id','team_abbr'}
        if not required <= cols: raise ValueError('player_games missing '+str(required-cols))
        name_col = 'player_name' if 'player_name' in cols else None
        if not name_col: raise ValueError('player_games has no player_name column')
        rows = conn.execute('SELECT DISTINCT player_id, player_name, team_abbr FROM player_games WHERE game_id = ?', [game]).fetchall()
        if not rows: raise ValueError('No player_games records for game '+game)
        return [(int(pid),name,team) for pid,name,team in rows]
    finally: conn.close()


def resolve_incoming(desc, team, roster):
    m = re.search(r'\bSUB\s*:\s*(.*?)\s+FOR\s+', desc or '', flags=re.I)
    if not m: return None, 'unparsed_description'
    target=norm(m.group(1))
    choices=[]
    for pid, name, abbr in roster:
        if abbr != team: continue
        tokens=norm(name).split()
        aliases={norm(name), ' '.join(tokens[-2:]), tokens[-1]}
        # Surnames with suffixes, including "Butler III" and "Payton II".
        suffixes={'ii','iii','iv','jr','sr'}
        if len(tokens)>=2 and tokens[-1] in suffixes:
            aliases.add(' '.join(tokens[-2:])); aliases.add(tokens[-2])
        if len(tokens)>=2: aliases.add(' '.join(tokens[1:]))
        if target in aliases: choices.append(pid)
    if len(set(choices)) == 1: return choices[0], ''
    return None, 'unresolved_name:'+target+':'+','.join(map(str,sorted(set(choices))))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--db', required=True)
    ap.add_argument('--game-dir', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--time-limit',type=int,default=60)
    args=ap.parse_args()
    try: from ortools.sat.python import cp_model
    except ImportError: raise SystemExit('Missing OR-Tools. Install: .\\.venv\\Scripts\\python.exe -m pip install ortools')
    indir=Path(args.game_dir); out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    game=indir.name; raw=read_csv(indir/'actions_preview.csv')
    roster=db_rosters(args.db,game)
    team_ids={1610612747:'LAL',1610612744:'GSW'}
    # Generalize team mapping from the action stream via known abbreviations only for this pilot.
    if set(team for _,_,team in roster) != {'LAL','GSW'}:
        raise ValueError('This pilot is only intended for LAL vs GSW; game roster teams: '+str(set(x[2] for x in roster)))
    ids_by_team={abbr:sorted({p for p,_,a in roster if a==abbr}) for abbr in ('LAL','GSW')}
    id_to_team={p:a for p,_,a in roster}
    issues=[]; events=[]
    for i,r in enumerate(raw):
        try: period=int(r['period']); t=float(r['elapsed'])
        except (ValueError,TypeError,KeyError): continue
        e=dict(r); e['_idx']=i; e['_period']=period; e['_time']=t
        e['_team']=team_ids.get(number(r.get('team_id')))
        e['_pid']=number(r.get('person_id'))
        events.append(e)
    events.sort(key=lambda e:(e['_period'],e['_time'],e['_idx']))
    groups=defaultdict(list)
    for e in events:
        if str(e.get('type','')).strip().lower()=='substitution':
            groups[(e['_period'], e['_time'])].append(e)
    swaps=defaultdict(list)
    for (period,t), evs in sorted(groups.items()):
        for e in evs:
            team=e['_team']; outgoing=e['_pid']
            if team not in ids_by_team or outgoing not in ids_by_team[team]:
                issues.append(dict(period=period,elapsed=t,action=e.get('action_number'),problem='outgoing_id_not_in_game_roster',detail=e.get('description',''))); continue
            incoming,problem=resolve_incoming(e.get('description',''),team,roster)
            if problem:
                issues.append(dict(period=period,elapsed=t,action=e.get('action_number'),problem=problem,detail=e.get('description',''))); continue
            swaps[(period,t,team)].append((outgoing,incoming,e.get('action_number')))
    all_results=[]; minutes=defaultdict(float); statuses=[]
    # CP-SAT reconstructs each quarter; unobserved lineup membership is not assumed.
    for period in sorted({e['_period'] for e in events}):
        evs=[e for e in events if e['_period']==period]
        period_length=720 if period<=4 else 300
        period_start=720*(period-1) if period<=4 else 2880+300*(period-5)
        # elapsed absolute from NBA V3, clocks used to guard coordinate convention.
        times=sorted({period_start, period_start+period_length}|{e['_time'] for e in evs if period_start<=e['_time']<=period_start+period_length})
        if len(times)<2: continue
        model=cp_model.CpModel(); vars={}
        for team,players in ids_by_team.items():
            for k in range(len(times)):
                for p in players: vars[(team,p,k)]=model.NewBoolVar(f'{period}_{team}_{p}_{k}')
                model.Add(sum(vars[(team,p,k)] for p in players)==5)
            for k in range(len(times)-1):
                t=times[k+1]
                pair=swaps.get((period,t,team),[])
                ins={b for a,b,_ in pair}; outs={a for a,b,_ in pair}
                if len(ins)!=len(pair) or len(outs)!=len(pair) or ins & outs:
                    issues.append(dict(period=period,elapsed=t,action='',problem='duplicate_or_chained_sub_group',detail=str(pair)))
                # Every substitution in the group must be valid; if unresolved, model may be inconsistent.
                for a,b,_ in pair:
                    model.Add(vars[(team,a,k)]==1)
                    model.Add(vars[(team,b,k)]==0)
                    model.Add(vars[(team,a,k+1)]==0)
                    model.Add(vars[(team,b,k+1)]==1)
                for p in players:
                    if p not in ins and p not in outs:
                        model.Add(vars[(team,p,k)]==vars[(team,p,k+1)])
        # Require actors in clearly on-court events; sideline-only technicals excluded.
        evidence_types={'made shot','missed shot','rebound','turnover','foul','free throw','jump ball','block','steal'}
        evidence=0
        for e in evs:
            if str(e.get('type','')).lower() not in evidence_types: continue
            team=e['_team']; p=e['_pid']; t=e['_time']
            if team not in ids_by_team or p not in ids_by_team[team] or t not in times: continue
            k=times.index(t)
            # At the exact substitution clock the event's placement is ambiguous.
            if (period,t) in groups: continue
            model.Add(vars[(team,p,k)]==1); evidence+=1
        solver=cp_model.CpSolver(); solver.parameters.max_time_in_seconds=args.time_limit; solver.parameters.num_search_workers=4
        status=solver.Solve(model); label=solver.StatusName(status)
        statuses.append(dict(period=period,status=label,evidence_events=evidence,clock_points=len(times)))
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            issues.append(dict(period=period,elapsed='',action='',problem='period_no_feasible_solution',detail=label))
            continue
        # Critical: check uniqueness. A feasible but nonunique solution is never verified.
        chosen={(team,p,k):solver.Value(v) for (team,p,k),v in vars.items()}
        n_vars=len(vars)
        model.Add(sum(v if chosen[key]==0 else (1-v) for key,v in vars.items())>=1)
        second=cp_model.CpSolver(); second.parameters.max_time_in_seconds=args.time_limit
        second_status=second.Solve(model)
        unique = (second_status==cp_model.INFEASIBLE)
        if not unique:
            issues.append(dict(period=period,elapsed='',action='',problem='multiple_feasible_lineup_histories',detail=second.StatusName(second_status)))
        for k in range(len(times)-1):
            start,end=times[k:k+2]
            selected={team:[p for p in players if chosen[(team,p,k)]==1] for team,players in ids_by_team.items()}
            for team,players in selected.items():
                for p in players: minutes[p]+=(end-start)/60
            all_results.append(dict(game_id=game,period=period,start_seconds=start,end_seconds=end,duration_seconds=round(end-start,3),lal_lineup='|'.join(map(str,selected['LAL'])),gsw_lineup='|'.join(map(str,selected['GSW'])),status='UNVERIFIED_NONUNIQUE_OR_NOT_RECONCILED' if not unique else 'PROVISIONAL_UNRECONCILED'))
    save_csv(out/'reconstruction_stints_PROVISIONAL.csv',all_results,['game_id','period','start_seconds','end_seconds','duration_seconds','lal_lineup','gsw_lineup','status'])
    save_csv(out/'review_flags.csv',issues,['period','elapsed','action','problem','detail'])
    names={p:n for p,n,_ in roster}
    min_rows=[dict(player_id=p,player_name=names[p],team=id_to_team[p],reconstructed_minutes=round(v,3)) for p,v in sorted(minutes.items())]
    save_csv(out/'reconstructed_minutes_UNVERIFIED.csv',min_rows,['player_id','player_name','team','reconstructed_minutes'])
    summary=dict(game=game,source_rows=len(raw),substitution_timestamps=len(groups),unresolved_identity_flags=sum('name' in i['problem'] for i in issues),review_flags=len(issues),periods=statuses,provisional_stints=len(all_results),verified_stints=0,notes='No official minute/score comparison; NEVER use provisional output as verified matchup statistics.')
    (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))
    print('Reports:',out.resolve())

if __name__=='__main__':main()
