"""Fetch event-level NBA shot chart data and store in the existing DuckDB file."""
import argparse
import time
import duckdb
import pandas as pd
from nba_api.stats.endpoints import shotchartdetail

DDL = '''CREATE TABLE IF NOT EXISTS shot_events (
    game_id VARCHAR, player_id BIGINT, season VARCHAR, season_type VARCHAR,
    team_id BIGINT, loc_x DOUBLE, loc_y DOUBLE, shot_distance DOUBLE,
    shot_made BOOLEAN, shot_type VARCHAR, action_type VARCHAR, period INTEGER,
    minutes_remaining INTEGER, seconds_remaining INTEGER, event_id BIGINT,
    updated_at TIMESTAMP DEFAULT now(),
    PRIMARY KEY (game_id, player_id, event_id)
)'''

def collect(db, player_id, season, season_type, delay=1.0):
    with duckdb.connect(db) as con:
        con.execute(DDL)
        response = shotchartdetail.ShotChartDetail(
            team_id=0, player_id=player_id, season_nullable=season,
            season_type_all_star=season_type, context_measure_simple='FGA', timeout=90)
        df = response.shot_chart_detail.get_data_frame()
        if df.empty:
            print('No shot events returned. This may reflect API availability rather than no attempts.')
            return 0
        required = ['GAME_ID','PLAYER_ID','TEAM_ID','LOC_X','LOC_Y','SHOT_DISTANCE',
                    'SHOT_MADE_FLAG','SHOT_TYPE','ACTION_TYPE','PERIOD',
                    'MINUTES_REMAINING','SECONDS_REMAINING','GAME_EVENT_ID']
        missing = set(required) - set(df.columns)
        if missing:
            raise ValueError(f'Provider schema changed; missing fields: {sorted(missing)}')
        df = df[required].copy()
        df.columns = ['game_id','player_id','team_id','loc_x','loc_y','shot_distance',
                      'shot_made','shot_type','action_type','period',
                      'minutes_remaining','seconds_remaining','event_id']
        for col in ['player_id','team_id','loc_x','loc_y','shot_distance','shot_made',
                    'period','minutes_remaining','seconds_remaining','event_id']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df['shot_made'] = df['shot_made'].map({1:True, 0:False})
        df['season'] = season
        df['season_type'] = season_type
        df = df.dropna(subset=['game_id','player_id','event_id','loc_x','loc_y','shot_made'])
        con.register('incoming_shots', df)
        # Re-importing one player/season replaces that partition to prevent duplicates or stale values.
        con.execute('BEGIN TRANSACTION')
        try:
            con.execute('DELETE FROM shot_events WHERE player_id=? AND season=? AND season_type=?',
                        [player_id, season, season_type])
            con.execute('''INSERT INTO shot_events
                (game_id,player_id,team_id,loc_x,loc_y,shot_distance,shot_made,shot_type,
                 action_type,period,minutes_remaining,seconds_remaining,event_id,season,season_type)
                 SELECT game_id,player_id,team_id,loc_x,loc_y,shot_distance,shot_made,shot_type,
                        action_type,period,minutes_remaining,seconds_remaining,event_id,season,season_type
                 FROM incoming_shots''')
            con.execute('COMMIT')
        except Exception:
            con.execute('ROLLBACK')
            raise
        count = con.execute('SELECT COUNT(*) FROM shot_events WHERE player_id=? AND season=? AND season_type=?',
                            [player_id,season,season_type]).fetchone()[0]
        print(f'Imported {count} shot attempts for player {player_id}, {season}, {season_type}')
        time.sleep(delay)
        return count

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--db', default='nba_current.duckdb')
    parser.add_argument('--player-id',type=int,required=True)
    parser.add_argument('--season',required=True)
    parser.add_argument('--season-type',choices=['Regular Season','Playoffs'],default='Regular Season')
    args=parser.parse_args()
    collect(args.db,args.player_id,args.season,args.season_type)
