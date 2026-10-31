"""Deterministic NBA player summaries. No invented impact or recommendations."""
import duckdb


def player_summary(con, seasons, team=None, opponent=None, season_type=None):
    if not seasons:
        raise ValueError('Choose at least one season')
    placeholders = ','.join('?' for _ in seasons)
    filters = [f'p.season IN ({placeholders})','p.minutes > 0']
    params = list(seasons)
    if team:
        filters.append('p.team_abbr = ?');params.append(team)
    if opponent:
        filters.append('EXISTS (SELECT 1 FROM team_games o WHERE o.game_id=p.game_id AND o.team_abbr=?)')
        params.append(opponent)
    if season_type:
        filters.append('p.season_type=?');params.append(season_type)
    query=f'''
    SELECT player_id, MAX_BY(player_name,game_date) AS player_name,
      team_abbr, COUNT(*) AS games, ROUND(SUM(minutes),1) AS total_minutes,
      ROUND(AVG(points),2) AS ppg, ROUND(AVG(rebounds),2) AS rpg,
      ROUND(AVG(assists),2) AS apg,
      ROUND(AVG(steals),2) AS spg, ROUND(AVG(blocks),2) AS bpg,
      ROUND(AVG(turnovers),2) AS tpg,
      ROUND(100.0*SUM(fgm)/NULLIF(SUM(fga),0),2) AS fg_pct,
      ROUND(100.0*SUM(fg3m)/NULLIF(SUM(fg3a),0),2) AS three_pct,
      ROUND(100.0*SUM(points)/(2*NULLIF(SUM(fga)+0.44*SUM(fta),0)),2) AS ts_pct,
      ROUND(AVG(plus_minus),2) AS avg_box_plus_minus,
      SUM(CASE WHEN starter THEN 1 ELSE 0 END) AS starts
    FROM player_games p
    WHERE {' AND '.join(filters)}
    GROUP BY player_id,team_abbr
    ORDER BY ppg DESC
    '''
    return con.execute(query,params).df()


def player_trend(con, player_id, seasons, team=None):
    if not seasons:
        raise ValueError('Choose at least one season')
    placeholders=','.join('?' for _ in seasons)
    filter_team='AND team_abbr = ?' if team else ''
    params=[int(player_id),*seasons]+([team] if team else [])
    return con.execute(f'''
      SELECT game_date, game_id, season, season_type, team_abbr,
             points, rebounds, assists, minutes, fgm, fga, fg3m, fg3a,
             plus_minus, starter
      FROM player_games
      WHERE player_id=? AND season IN ({placeholders}) AND minutes > 0 {filter_team}
      ORDER BY game_date,game_id''',params).df()


def candidate_starters(con, team, season, min_games=3):
    """Statistical profiles of CURRENT-SEASON players, not lineup recommendations.
    This list is NOT an authoritative roster or availability check.
    """
    return con.execute('''
        SELECT player_id, MAX_BY(player_name,game_date) AS player_name,
               COUNT(*) AS games, SUM(CASE WHEN starter THEN 1 ELSE 0 END) AS starts,
               ROUND(AVG(points),2) AS ppg,ROUND(AVG(rebounds),2) AS rpg,
               ROUND(AVG(assists),2) AS apg,ROUND(AVG(minutes),2) AS mpg
        FROM player_games WHERE team_abbr=? AND season=? AND minutes>0
        GROUP BY player_id HAVING COUNT(*)>=?
        ORDER BY starts DESC, mpg DESC
    ''',[team,season,min_games]).df()
