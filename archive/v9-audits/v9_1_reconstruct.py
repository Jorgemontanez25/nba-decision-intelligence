"""V9.1 safe reconstruction diagnostic for exported V9 NBA PBP.
Reads CSVs only, never changes DuckDB. Period-one starting lineups seeded from
V9 candidate export, NOT independently verified. No predicted ratings produced.
"""
import argparse,csv,re,unicodedata,collections,json
from pathlib import Path

def read(path):
    with open(path,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(path,rows,headers):
    with open(path,'w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=headers,extrasaction='ignore');w.writeheader();w.writerows(rows)
def norm(s):
    s=unicodedata.normalize('NFKD',str(s or ''))
    s=''.join(c for c in s if not unicodedata.combining(c)).lower()
    s=s.replace('’',"'").replace('ʻ',"'")
    return re.sub(r'[^a-z0-9]','',s)
def aliases(full):
    parts=re.sub(r'[.,]',' ',full or '').split()
    if not parts:return set()
    suffix={'jr','sr','ii','iii','iv','v'}
    base=parts[:-1] if parts[-1].lower() in suffix else parts
    possibilities={' '.join(parts),' '.join(base),parts[-1],base[-1]}
    if len(base)>1:possibilities.add(' '.join(base[1:]))
    return {norm(p) for p in possibilities if p}
def ids(s):return [int(x) for x in str(s or '').split('|') if x.strip()]
def num(s,default=None):
    try:return float(s)
    except (ValueError,TypeError):return default

def main():
    a=argparse.ArgumentParser();a.add_argument('--db',default='nba_current.duckdb');a.add_argument('--game-dir',required=True);a.add_argument('--out',default='v9_1_review');opts=a.parse_args()
    root=Path(opts.game_dir);dst=Path(opts.out);dst.mkdir(parents=True,exist_ok=True)
    actions=read(root/'actions_preview.csv');seed=read(root/'candidate_stints_UNVERIFIED.csv')
    if not actions or not seed:raise SystemExit('Missing actions or first candidate stint.')
    first=seed[0];home=int(first['home_team_id']);away=int(first['away_team_id']);game=first['game_id']
    lineups={home:set(ids(first['home_lineup_ids'])),away:set(ids(first['away_lineup_ids']))}
    if any(len(v)!=5 for v in lineups.values()):raise SystemExit('Invalid five-player seed')
    # Load names from local box scores. Exact schema introspection prevents guessing columns.
    import duckdb
    con=duckdb.connect(opts.db,read_only=True)
    cols={r[1].lower() for r in con.execute('PRAGMA table_info(player_games)').fetchall()}
    needed={'game_id','team_abbr','player_id','player_name'}
    if not needed.issubset(cols):raise SystemExit('player_games must have: '+', '.join(sorted(needed)))
    roster=con.execute('SELECT DISTINCT player_id, player_name, team_abbr FROM player_games WHERE game_id=?',[game]).fetchall();con.close()
    # Team mapping is derived from the *game's* known starters. Avoid assigning cross-team names.
    teamnames={home:{},away:{}}
    abbr_ids={}
    for pid,name,abbr in roster:
        abbr_ids.setdefault(abbr,set()).add(int(pid))
    for tid,starting in lineups.items():
        match=[abr for abr,ps in abbr_ids.items() if len(ps & starting)>=3]
        if len(match)!=1:raise SystemExit('Cannot confidently map team IDs to game roster from starters.')
        abr=match[0]
        for pid,name,team in roster:
            if team==abr:teamnames[tid][int(pid)]=str(name)
    flags=[];records=[];stints=[];periods=[]
    def flag(row,issue,detail):flags.append(dict(action_number=row.get('action_number',''),period=row.get('period',''),elapsed=row.get('elapsed',''),problem=issue,detail=detail))
    actions=list(enumerate(actions))
    actions.sort(key=lambda t:(int(t[1].get('period') or 0),num(t[1].get('elapsed'),0),t[0]))
    # identify names by matching aliases for ONLY roster of the substituting team
    def incoming(tid,desc):
        m=re.match(r'^SUB:\s*(.*?)\s+FOR\s+(.*?)\s*$',desc or '',re.I)
        if not m:return None,'unparsed_description'
        val=norm(m.group(1));hits=[pid for pid,name in teamnames[tid].items() if val in aliases(name)]
        return (hits[0],None) if len(hits)==1 else (None,'ambiguous_incoming_name:'+m.group(1))
    curr_period=None;active=False;start=0.0; score=[0,0];startscore=(0,0)
    def close(end,why):
        nonlocal start,startscore
        if not active or end<=start:return
        stints.append(dict(game_id=game,period=curr_period,start_seconds=start,end_seconds=end,duration_seconds=round(end-start,3),home_team_id=home,away_team_id=away,home_lineup_ids='|'.join(map(str,sorted(lineups[home]))),away_lineup_ids='|'.join(map(str,sorted(lineups[away]))),home_score_change=score[0]-startscore[0],away_score_change=score[1]-startscore[1],status='UNVERIFIED_PERIOD_STARTERS',stop_reason=why))
    i=0
    while i<len(actions):
        idx,r=actions[i];period=int(r['period']);elapsed=num(r['elapsed'],0.)
        if curr_period!=period:
            if curr_period is not None:
                close(720*curr_period if curr_period<=4 else 2880+300*(curr_period-4),'period_boundary')
                # at quarter starts, team lineups MAY change without recorded substitutions.
                flag(r,'period_start_unverified','Starting lineups not independently known for this period. No interval counted as verified.')
            curr_period=period;start=elapsed;startscore=tuple(score);active=(period==1)
            if period!=1:active=False
        # get score at each row; do not equate missing to 0
        for j,k in enumerate(('score_home','score_away')):
            n=num(r.get(k))
            if n is not None:
                if n<score[j]:flag(r,'score_regression',f'{k} {score[j]} -> {n}')
                else:score[j]=int(n)
        if (r.get('type') or '').lower()!='substitution':i+=1;continue
        # Collect all substitution records at same period and clock; apply atomically.
        j=i;group=[]
        while j<len(actions):
            s=actions[j][1]
            if int(s['period'])!=period or num(s['elapsed'])!=elapsed or (s.get('type') or '').lower()!='substitution':break
            group.append(s);j+=1
        if active:close(elapsed,'substitution')
        proposals=collections.defaultdict(list);bad=False
        for s in group:
            tid=int(s.get('team_id') or 0);out=int(s.get('person_id') or 0)
            if tid not in lineups:flag(s,'unknown_team',str(tid));bad=True;continue
            inc,err=incoming(tid,s.get('description'))
            if err:flag(s,err,s.get('description'));bad=True;continue
            if out not in teamnames[tid]:flag(s,'outgoing_not_on_roster',str(out));bad=True;continue
            proposals[tid].append((out,inc,s))
        if not bad:
            updated={tid:set(players) for tid,players in lineups.items()}
            for tid,changes in proposals.items():
                outs=[out for out,_,_ in changes];ins=[inc for _,inc,_ in changes]
                if len(outs)!=len(set(outs)) or len(ins)!=len(set(ins)) or any(o not in updated[tid] for o in outs):
                    bad=True
                    for _,_,s in changes:flag(s,'state_conflict','Outgoing not in current lineup or duplicate swap; group not applied')
                    continue
                candidate=(updated[tid]-set(outs))|set(ins)
                if len(candidate)!=5:
                    bad=True
                    for _,_,s in changes:flag(s,'invalid_five','Substitution group does not produce exactly five')
                else:updated[tid]=candidate
            if not bad:lineups=updated
        if bad:active=False
        start=elapsed;startscore=tuple(score)
        records.append(dict(period=period,elapsed=elapsed,substitutions=len(group),status='UNRESOLVED' if bad else 'APPLIED',home_lineup='|'.join(map(str,sorted(lineups[home]))),away_lineup='|'.join(map(str,sorted(lineups[away])))))
        i=j
    close(num(actions[-1][1].get('elapsed'),start),'last_observed_action')
    write(dst/'substitution_groups.csv',records,['period','elapsed','substitutions','status','home_lineup','away_lineup'])
    write(dst/'review_flags.csv',flags,['action_number','period','elapsed','problem','detail'])
    write(dst/'stints_UNVERIFIED.csv',stints,['game_id','period','start_seconds','end_seconds','duration_seconds','home_team_id','away_team_id','home_lineup_ids','away_lineup_ids','home_score_change','away_score_change','status','stop_reason'])
    summary={'game':game,'source_rows':len(actions),'substitution_groups':len(records),'unresolved_groups':sum(x['status']=='UNRESOLVED' for x in records),'review_flags':len(flags),'provisional_stints':len(stints),'verified_stints':0,'note':'This diagnostic does not validate period starters or official minutes; no performance rankings should use these stints.'}
    (dst/'SUMMARY.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2));print('Reports:',dst.resolve())
if __name__=='__main__':main()
