"""V9 first-pass NBA 5v5 matchup stints. Conservative: never silently accept ambiguities."""
import argparse,csv,json,re,time,sys
from pathlib import Path
from collections import defaultdict
import duckdb

def clock_sec(s):
    m=re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?([\d.]+)S',str(s or ''))
    if not m: raise ValueError('Unknown NBA clock: '+str(s))
    return int(m.group(1) or 0)*3600+int(m.group(2) or 0)*60+float(m.group(3))

def elapsed(a):
    p=int(a['period']); return sum(720 if i<=4 else 300 for i in range(1,p))+(720 if p<=4 else 300)-clock_sec(a['clock'])

def fetch(game_id,timeout):
    from nba_api.stats.endpoints import playbyplayv3,boxscoretraditionalv3
    pb=playbyplayv3.PlayByPlayV3(game_id=game_id,start_period=0,end_period=0,timeout=timeout).get_dict()
    time.sleep(1)
    bx=boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=game_id,timeout=timeout).get_dict()
    return pb,bx

def unpack_actions(blob):
    if 'game' in blob and 'actions' in blob['game']: return blob['game']['actions']
    for x in blob.get('resultSets',[]):
        if str(x.get('name','')).lower()=='playbyplay':
            return [dict(zip(x['headers'],v)) for v in x['rowSet']]
    return []

def unpack_players(blob):
    if 'boxScoreTraditional' in blob:
        box=blob['boxScoreTraditional']; return [(t,p) for t in (box.get('homeTeam',{}),box.get('awayTeam',{})) for p in t.get('players',[])]
    if 'game' in blob and 'homeTeam' in blob['game']:
        return [(t,p) for t in (blob['game']['homeTeam'],blob['game']['awayTeam']) for p in t.get('players',[])]
    for x in blob.get('resultSets',[]):
        if str(x.get('name','')).lower()=='playerstats':return [(None,dict(zip(x['headers'],v))) for v in x['rowSet']]
    return []

def score(v):
    if v is None or str(v).strip()=='':return None
    try:return int(v)
    except (TypeError,ValueError):return None

def starters_from_box(players):
    byteam=defaultdict(set); names=defaultdict(dict); teams={}
    for t,p in players:
        tid=p.get('teamId') or (t or {}).get('teamId'); pid=p.get('personId') or p.get('playerId')
        if not tid or not pid:continue
        tid=int(tid);pid=int(pid)
        pos=str(p.get('position') or p.get('startPosition') or '').strip()
        name=' '.join(x for x in (p.get('firstName'),p.get('familyName')) if x).strip() or p.get('name') or p.get('nameI') or ''
        names[tid][pid]=name
        teams[tid]=p.get('teamTricode') or (t or {}).get('teamTricode') or str(tid)
        if pos and pos not in ('-', '0'): byteam[tid].add(pid)
    return byteam,names,teams

def norm(s):return re.sub(r'[^a-z0-9]','',str(s).lower())

def resolve(raw,roster):
    n=norm(raw)
    if not n:return None
    exact=[pid for pid,name in roster.items() if norm(name)==n]
    if len(exact)==1:return exact[0]
    found=[pid for pid,name in roster.items() if n in norm(name) or norm(name).endswith(n)]
    return found[0] if len(found)==1 else None

def substitution(a,roster):
    desc=str(a.get('description') or '')
    # NBA action descriptions use 'SUB: Incoming FOR Outgoing'. Refuse other patterns.
    m=re.search(r'\bSUB\s*:\s*(.+?)\s+FOR\s+(.+?)(?:\s*\(|$)',desc,re.I)
    if not m:return None
    pin,pout=resolve(m.group(1).strip(),roster),resolve(m.group(2).strip(),roster)
    return (pin,pout) if pin and pout and pin!=pout else None

def write_csv(path,rows,fields):
    with open(path,'w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)

def build(game_id,pbp,box,out):
    actions=unpack_actions(pbp);players=unpack_players(box)
    starts,names,tricodes=starters_from_box(players)
    raw=[]; warnings=[]
    for a in actions:
        try:t=elapsed(a)
        except Exception as exc:
            warnings.append({'action':a.get('actionNumber'),'problem':'unknown_clock','detail':str(exc)});continue
        raw.append({**a,'_elapsed':t})
    raw.sort(key=lambda a:(a['_elapsed'],int(a.get('actionNumber') or a.get('actionId') or 0)))
    tids=list(names)
    if len(tids)!=2 or any(len(starts.get(t,[]))!=5 for t in tids):
        warnings.append({'action':'GAME','problem':'invalid_starters','detail':f'teams={tids}; starter counts={[len(starts.get(t,[])) for t in tids]}'})
    # Determine home/away only from explicit box team IDs, not team order.
    b=box.get('boxScoreTraditional') or box.get('game') or {}
    home=int((b.get('homeTeam') or {}).get('teamId') or 0)
    away=int((b.get('awayTeam') or {}).get('teamId') or 0)
    if set((home,away))!=set(tids):warnings.append({'action':'GAME','problem':'home_away_unknown','detail':f'home={home}, away={away}'})
    write_csv(out/'actions_preview.csv',[{'action_number':a.get('actionNumber'),'period':a.get('period'),'clock':a.get('clock'),'elapsed':a['_elapsed'],'team_id':a.get('teamId'),'person_id':a.get('personId'),'type':a.get('actionType'),'sub_type':a.get('subType'),'description':a.get('description'),'score_home':a.get('scoreHome'),'score_away':a.get('scoreAway')} for a in raw],['action_number','period','clock','elapsed','team_id','person_id','type','sub_type','description','score_home','score_away'])
    if warnings:
        write_csv(out/'review_flags.csv',warnings,['action','problem','detail']);return 0,len(warnings)
    on={t:set(starts[t]) for t in tids};segments=[]
    start=0.0;last_score=[0,0];invalid=False
    def close(at,sh,sa):
        nonlocal start,last_score
        if at>start+1e-6:
            segments.append({'game_id':game_id,'start_seconds':round(start,2),'end_seconds':round(at,2),'duration_seconds':round(at-start,2),'home_team_id':home,'away_team_id':away,'home_lineup_ids':'|'.join(map(str,sorted(on[home]))),'away_lineup_ids':'|'.join(map(str,sorted(on[away]))),'home_points':'UNVERIFIED','away_points':'UNVERIFIED'})
        start=at;last_score=[sh,sa]
    for a in raw:
        t=a['_elapsed'];typ=str(a.get('actionType') or '').lower()
        sh=score(a.get('scoreHome'));sa=score(a.get('scoreAway'))
        # Score fields can be absent: maintain last known values.
        sh=last_score[0] if sh is None else sh;sa=last_score[1] if sa is None else sa
        if 'substitution' in typ or typ=='sub':
            team=int(a.get('teamId') or 0)
            sub=substitution(a,names.get(team,{}))
            if sub is None or team not in on:
                warnings.append({'action':a.get('actionNumber'),'problem':'ambiguous_substitution','detail':str(a.get('description'))});invalid=True;continue
            incoming,outgoing=sub
            if outgoing not in on[team] or incoming in on[team]:
                warnings.append({'action':a.get('actionNumber'),'problem':'impossible_substitution','detail':str(a.get('description'))});invalid=True;continue
            close(t,sh,sa);on[team].remove(outgoing);on[team].add(incoming)
        elif sh!=last_score[0] or sa!=last_score[1]:
            # Don't split on scores; update score in current stint by accumulating in last_score's running totals.
            # Maintain pending points via independent score anchors instead in subsequent patch.
            pass
    # Conservative pilot: do not certify scoring stints until robust score timeline is audited.
    write_csv(out/'review_flags.csv',warnings,[ 'action','problem','detail'])
    write_csv(out/'candidate_stints_UNVERIFIED.csv',segments,['game_id','start_seconds','end_seconds','duration_seconds','home_team_id','away_team_id','home_lineup_ids','away_lineup_ids','home_points','away_points'])
    return len(segments),len(warnings)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--db',default='nba_current.duckdb');ap.add_argument('--season',default='2025-26');ap.add_argument('--team',default='LAL');ap.add_argument('--max-games',type=int,default=1);ap.add_argument('--out',default='v9_lakers_pilot');ap.add_argument('--timeout',type=int,default=45);ap.add_argument('--fetch',action='store_true');args=ap.parse_args()
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    with duckdb.connect(args.db,read_only=True) as c:
        games=c.execute('SELECT DISTINCT game_id FROM team_games WHERE season=? AND season_type=? AND team_abbr=? ORDER BY game_id LIMIT ?', [args.season,'Regular Season',args.team,args.max_games]).fetchall()
    print('Selected games:',[x[0] for x in games]);print('No changes to DuckDB.')
    if not args.fetch:print('DRY RUN. Add --fetch to request game data.');return
    for (gid,) in games:
        folder=out/gid;folder.mkdir(parents=True,exist_ok=True)
        try:
            pb,bx=fetch(gid,args.timeout)
            (folder/'play_by_play_raw.json').write_text(json.dumps(pb,indent=2),encoding='utf-8')
            (folder/'box_score_raw.json').write_text(json.dumps(bx,indent=2),encoding='utf-8')
            n,w=build(gid,pb,bx,folder)
            print(gid,'unverified candidate stints:',n,'review flags:',w)
        except Exception as e:
            (folder/'ERROR.txt').write_text(repr(e),encoding='utf-8');print('ERROR',gid,e)
        time.sleep(1)
    print('Inspect actions_preview.csv and review_flags.csv. DO NOT use candidate stints for predictions.')
if __name__=='__main__':main()
