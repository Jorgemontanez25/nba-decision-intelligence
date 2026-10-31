"""Offline-first NBA 2026-27 roster snapshots (never modify DuckDB).
Run this tool explicitly on Windows when internet/NBA Stats is available.
"""
from pathlib import Path
import argparse, datetime as dt, json, time
import pandas as pd

ROOT=Path(__file__).resolve().parent/'roster_snapshots'
SEASON='2026-27'

def roster_path(team):
    return ROOT/SEASON/(team.upper()+'.csv')

def roster_for_team(team):
    p=roster_path(team)
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p,dtype={'player_id':str,'jersey':str}).fillna('')

def fetch_team(team, team_id, season=SEASON):
    from nba_api.stats.endpoints import commonteamroster
    response=commonteamroster.CommonTeamRoster(team_id=int(team_id),season=season,timeout=60)
    df=response.common_team_roster.get_data_frame()
    required={'PLAYER_ID','PLAYER'}
    if not required.issubset(df.columns) or df.empty:
        raise ValueError(f'Roster missing fields / empty for {team}: {sorted(required-set(df.columns))}')
    out=pd.DataFrame({'player_id':df['PLAYER_ID'].astype(str), 'player_name':df['PLAYER'].astype(str),
                      'team_abbr':team,'position':df['POSITION'] if 'POSITION' in df else '',
                      'jersey':df['NUM'].astype(str) if 'NUM' in df else '',
                      'season':season,'retrieved_utc':dt.datetime.now(dt.timezone.utc).isoformat()})
    p=roster_path(team);p.parent.mkdir(parents=True,exist_ok=True)
    out.to_csv(p,index=False)
    return len(out),p

def main():
    a=argparse.ArgumentParser();a.add_argument('--teams',default='LAL,BOS',help='Comma-separated NBA abbreviations; use ALL for all 30');a.add_argument('--season',default=SEASON);a.add_argument('--delay',type=float,default=1.5);args=a.parse_args()
    from nba_api.stats.static import teams
    allteams={t['abbreviation']:t['id'] for t in teams.get_teams()}
    chosen=sorted(allteams) if args.teams.upper()=='ALL' else [x.strip().upper() for x in args.teams.split(',') if x.strip()]
    failed=[]
    for t in chosen:
        if t not in allteams:
            failed.append((t,'Unknown NBA team abbreviation'));continue
        try:
            count,p=fetch_team(t,allteams[t],args.season);print(f'{t}: {count} players -> {p}')
        except Exception as e:
            failed.append((t,str(e)));print(f'{t}: roster unavailable ({e})')
        time.sleep(args.delay)
    print(json.dumps({'season':args.season,'requested':len(chosen),'failed':failed,'no_database_changes':True},indent=2))

if __name__=='__main__':main()
