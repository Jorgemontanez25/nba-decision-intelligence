"""Read-only validation for NBA Decision Intelligence DuckDB game and player box scores."""
import argparse
from pathlib import Path
import duckdb
import pandas as pd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='nba_current.duckdb')
    parser.add_argument('--season', default='2025-26')
    parser.add_argument('--season-type', default='Regular Season')
    parser.add_argument('--output', default='validation_2025_26')
    args = parser.parse_args()
    if not Path(args.db).exists():
        parser.error(f'Database file not found: {args.db}')
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    checks = {}
    with duckdb.connect(args.db, read_only=True) as con:
        existing = {r[0] for r in con.execute('SHOW TABLES').fetchall()}
        for table in ('team_games', 'player_games'):
            if table not in existing:
                parser.error(f'Missing expected table: {table}')
        params = [args.season, args.season_type]
        def check(name, query, values=params):
            df = con.execute(query, values).df()
            checks[name] = df
            df.to_csv(out / (name + '.csv'), index=False)
            print(f'{name}: {len(df):,} flagged rows')
            if len(df):
                print(df.head(8).to_string(index=False))
            return df

        all_team = con.execute('''SELECT game_id, team_id, team_abbr, points
                 FROM team_games WHERE season=? AND season_type=?''', params).df()
        all_player = con.execute('''SELECT game_id, player_id, team_abbr, minutes
                 FROM player_games WHERE season=? AND season_type=?''', params).df()
        print(f'Season: {args.season} | {args.season_type}')
        print(f'Unique games: {all_team.game_id.nunique():,}')
        print(f'Team-game rows: {len(all_team):,} | Player-game rows: {len(all_player):,}')
        print('NOTE: These checks do not compare imported game IDs to the official schedule.\n')

        check('team_rows_not_two', '''SELECT game_id, COUNT(*) AS team_rows,
          COUNT(DISTINCT team_abbr) AS distinct_teams
          FROM team_games WHERE season=? AND season_type=?
          GROUP BY game_id HAVING COUNT(*)<>2 OR COUNT(DISTINCT team_abbr)<>2''')
        check('duplicate_team_keys', '''SELECT game_id,team_id, COUNT(*) AS rows
          FROM team_games WHERE season=? AND season_type=?
          GROUP BY game_id,team_id HAVING COUNT(*)>1''')
        check('duplicate_player_keys', '''SELECT game_id,player_id, COUNT(*) AS rows
          FROM player_games WHERE season=? AND season_type=?
          GROUP BY game_id,player_id HAVING COUNT(*)>1''')
        check('missing_player_rows', '''SELECT t.game_id,t.team_abbr,t.points
          FROM team_games t LEFT JOIN player_games p
          ON p.game_id=t.game_id AND p.team_abbr=t.team_abbr
          WHERE t.season=? AND t.season_type=?
          GROUP BY t.game_id,t.team_abbr,t.points HAVING COUNT(p.player_id)=0''')
        check('orphan_player_teams', '''SELECT p.game_id,p.team_abbr, COUNT(*) AS player_rows
          FROM player_games p LEFT JOIN team_games t
          ON p.game_id=t.game_id AND p.team_abbr=t.team_abbr
          WHERE p.season=? AND p.season_type=? AND t.game_id IS NULL
          GROUP BY p.game_id,p.team_abbr''')
        check('team_player_score_mismatch', '''SELECT t.game_id,t.team_abbr,t.points AS team_points,
          COALESCE(SUM(p.points),0) AS player_points,
          t.points - COALESCE(SUM(p.points),0) AS difference,
          COUNT(p.player_id) AS player_rows
          FROM team_games t LEFT JOIN player_games p
          ON t.game_id=p.game_id AND t.team_abbr=p.team_abbr
          WHERE t.season=? AND t.season_type=?
          GROUP BY t.game_id,t.team_abbr,t.points
          HAVING t.points IS NULL OR t.points <> COALESCE(SUM(p.points),0)
          ORDER BY ABS(t.points - COALESCE(SUM(p.points),0)) DESC NULLS LAST''')
        check('invalid_player_stats', '''SELECT game_id,team_abbr,player_id,player_name,
          minutes,points,fgm,fga,fg3m,fg3a,ftm,fta,rebounds,assists,steals,blocks,turnovers
          FROM player_games WHERE season=? AND season_type=? AND
          (COALESCE(minutes,0)<0 OR minutes>65 OR
           COALESCE(points,0)<0 OR COALESCE(fgm,0)<0 OR COALESCE(fga,0)<0 OR
           COALESCE(fg3m,0)<0 OR COALESCE(fg3a,0)<0 OR
           COALESCE(ftm,0)<0 OR COALESCE(fta,0)<0 OR
           fgm>fga OR fg3m>fg3a OR ftm>fta OR fg3m>fgm OR fg3a>fga OR
           points <> 2*fgm+fg3m+ftm OR
           COALESCE(rebounds,0)<0 OR COALESCE(assists,0)<0 OR
           COALESCE(steals,0)<0 OR COALESCE(blocks,0)<0 OR COALESCE(turnovers,0)<0)
          ORDER BY game_id,player_id''')
        check('minutes_outliers', '''SELECT game_id, team_abbr,
          ROUND(SUM(COALESCE(minutes,0)),2) AS player_minutes,
          COUNT(*) AS roster_rows
          FROM player_games WHERE season=? AND season_type=?
          GROUP BY game_id,team_abbr
          HAVING SUM(COALESCE(minutes,0))<230 OR SUM(COALESCE(minutes,0))>350
          ORDER BY player_minutes''')
        check('missing_identity', '''SELECT game_id,player_id,player_name,team_abbr
          FROM player_games WHERE season=? AND season_type=?
          AND (player_name IS NULL OR TRIM(player_name)='' OR team_abbr IS NULL OR TRIM(team_abbr)='')''')
        # Scope shot check to games whose player box scores are present. Missing shot data
        # is a separate collection stream; a mismatch does NOT imply a corrupt box score.
        if 'shot_events' in existing:
            shot_cols = {r[1] for r in con.execute("PRAGMA table_info('shot_events')").fetchall()}
            if {'player_id','game_id','season','shot_made'}.issubset(shot_cols):
                check('shot_attempt_coverage', '''SELECT p.player_id,p.player_name,
                  COUNT(DISTINCT p.game_id) AS box_games,
                  COUNT(DISTINCT CASE WHEN s.game_id IS NOT NULL THEN p.game_id END) AS games_with_shots,
                  SUM(COALESCE(p.fga,0)) AS box_fga,
                  COUNT(s.game_id) AS captured_shots
                  FROM player_games p LEFT JOIN shot_events s
                  ON p.game_id=s.game_id AND p.player_id=s.player_id AND s.season=p.season
                  WHERE p.season=? AND p.season_type=?
                  GROUP BY p.player_id,p.player_name
                  HAVING SUM(COALESCE(p.fga,0))<>COUNT(s.game_id)
                  ORDER BY (SUM(COALESCE(p.fga,0))-COUNT(s.game_id)) DESC''')
        rows = [{'check':k,'flagged_rows':len(v)} for k,v in checks.items()]
        pd.DataFrame(rows).to_csv(out/'summary.csv',index=False)
        print(f'\nAudit saved to: {out.resolve()}')
        if sum(len(x) for x in checks.values()):
            print('Review flags in CSV files before treating the database as statistically verified.')
        else:
            print('No issues flagged by the implemented checks; independent official-source reconciliation is still required.')

if __name__ == '__main__':
    main()
