"""Historical matchup engine: observed rankings, never false predictive win probabilities."""
from pathlib import Path
import csv
import duckdb

ROOT = Path(__file__).parent
REQUIRED = {'stint_id','game_id','season','season_type','team_abbr','opponent_abbr',
            'period','start_sec','end_sec','points_for','points_against',
            'possessions_for','possessions_against','team_player_ids',
            'opponent_player_ids','source'}

def initialize(con):
    con.execute((ROOT/'schema.sql').read_text())
    con.execute((ROOT/'lineup_schema.sql').read_text())

def canonical_ids(raw):
    ids = [int(v.strip()) for v in str(raw).split('|')]
    if len(ids) != 5 or len(set(ids)) != 5 or any(v <= 0 for v in ids):
        raise ValueError('Every side must contain 5 distinct positive player IDs')
    return sorted(ids)

def import_stints(con, csv_path):
    """Atomic import of externally reconstructed, source-attributed 5v5 stints.
    Reject duplicate IDs, invalid clock boundaries, missing box-score players,
    or scores not reconcilable with supplied stint events. The source pipeline must
    separately validate substitution continuity and point attribution.
    """
    initialize(con)
    with open(csv_path, newline='', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        if not REQUIRED.issubset(set(reader.fieldnames or [])):
            raise ValueError('Missing CSV columns: '+str(REQUIRED-set(reader.fieldnames or [])))
        rows = list(reader)
    if not rows: raise ValueError('Empty input: no stints to import')
    normalized=[]
    seen=set()
    for r in rows:
        stint_id=r['stint_id'].strip()
        if not stint_id or stint_id in seen: raise ValueError('Duplicate/blank stint ID in CSV')
        seen.add(stint_id)
        tm=canonical_ids(r['team_player_ids']); opp=canonical_ids(r['opponent_player_ids'])
        if set(tm)&set(opp): raise ValueError('Same player on both sides')
        start,end=float(r['start_sec']),float(r['end_sec'])
        period=int(r['period'])
        if period<1 or not (0 <= start < end <= (720 if period<=4 else 300)):
            raise ValueError('Invalid period-clock interval')
        pf,pa=int(r['points_for']),int(r['points_against'])
        if pf<0 or pa<0: raise ValueError('Negative score')
        pfposs=float(r['possessions_for']) if r['possessions_for'].strip() else None
        paposs=float(r['possessions_against']) if r['possessions_against'].strip() else None
        if (pfposs is not None and pfposs<=0) or (paposs is not None and paposs<=0):
            raise ValueError('Invalid possession denominator')
        season=r['season'].strip()
        if not season or r['season_type'] not in ('Regular Season','Playoffs'):
            raise ValueError('Invalid season')
        if not r['source'].strip(): raise ValueError('Source required')
        # Ensures imported stints refer to a previously collected game and verified participants.
        game=con.execute('SELECT COUNT(*) FROM team_games WHERE game_id=? AND team_abbr IN (?,?)',
                         [r['game_id'],r['team_abbr'],r['opponent_abbr']]).fetchone()[0]
        if game != 2: raise ValueError('Game/team mismatch or game not collected: '+r['game_id'])
        for pid in tm+opp:
            exists=con.execute('SELECT COUNT(*) FROM player_games WHERE game_id=? AND player_id=?',
                               [r['game_id'],pid]).fetchone()[0]
            if exists!=1: raise ValueError(f'Player {pid} absent from game {r["game_id"]} box')
        normalized.append((r,stint_id,tm,opp,start,end,period,pf,pa,pfposs,paposs,season))
    con.execute('BEGIN TRANSACTION')
    try:
        for r,sid,tm,opp,start,end,period,pf,pa,pfposs,paposs,season in normalized:
            con.execute('DELETE FROM lineup_stint_players WHERE stint_id=?',[sid])
            con.execute('DELETE FROM lineup_stints WHERE stint_id=?',[sid])
            con.execute("""INSERT INTO lineup_stints (
                stint_id,game_id,season,season_type,team_abbr,opponent_abbr,period,
                start_sec,end_sec,duration_sec,points_for,points_against,
                possessions_for,possessions_against,lineup_key,opponent_lineup_key,
                source,validation_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [sid,r['game_id'],season,r['season_type'],r['team_abbr'],r['opponent_abbr'],period,
                 start,end,end-start,pf,pa,pfposs,paposs,'|'.join(map(str,tm)),
                 '|'.join(map(str,opp)),r['source'],'verified'])
            for side,ids in [('team',tm),('opponent',opp)]:
                for pid in ids:
                    con.execute('INSERT INTO lineup_stint_players VALUES (?,?,?)',[sid,side,pid])
        con.execute('COMMIT')
    except Exception:
        con.execute('ROLLBACK');raise
    return len(normalized)

def matchup_rankings(con, team='LAL', opponent='BOS', seasons=None,
                     season_types=('Regular Season','Playoffs'), min_minutes=100):
    """Observed LAL vs BOS matchups only. Filter minimum minutes after aggregation.
    Zero or unavailable possessions => null ratings; never guessed.
    """
    seasons=seasons or ['2022-23','2023-24','2024-25','2025-26']
    if not seasons or not season_types: raise ValueError('Seasons and types required')
    ps=','.join(['?']*len(seasons)); pt=','.join(['?']*len(season_types))
    query=f"""WITH valid AS (
        SELECT * FROM lineup_stints
        WHERE team_abbr=? AND opponent_abbr=?
          AND season IN ({ps}) AND season_type IN ({pt})
          AND validation_status='verified'
    ), agg AS (
        SELECT lineup_key, COUNT(DISTINCT game_id) AS games,
          ROUND(SUM(duration_sec)/60.0,2) AS minutes,
          SUM(points_for) AS points_for, SUM(points_against) AS points_against,
          SUM(possessions_for) AS possessions_for,
          SUM(possessions_against) AS possessions_against,
          COUNT(*) AS stints
        FROM valid GROUP BY lineup_key
    ) SELECT *,
        ROUND(100.0*points_for/NULLIF(possessions_for,0),2) AS offensive_rating,
        ROUND(100.0*points_against/NULLIF(possessions_against,0),2) AS defensive_rating,
        ROUND(100.0*points_for/NULLIF(possessions_for,0)-
              100.0*points_against/NULLIF(possessions_against,0),2) AS net_rating,
        ROUND(60.0*(points_for-points_against)/NULLIF(minutes,0),2) AS plus_minus_per_60_minutes
    FROM agg WHERE minutes >= ? ORDER BY net_rating DESC NULLS LAST,minutes DESC"""
    return con.execute(query,[team,opponent,*seasons,*season_types,float(min_minutes)]).df()

def lineup_players(con, lineup_key):
    """Attach individual full-season player profiles; NOT stats within a lineup."""
    from analysis import player_summary
    ids=canonical_ids(lineup_key)
    return ids

def data_quality(con, team='LAL', opponent='BOS'):
    return con.execute("""SELECT season,season_type, COUNT(DISTINCT game_id) AS games,
      COUNT(*) AS stints, ROUND(SUM(duration_sec)/60,1) AS minutes,
      SUM(CASE WHEN possessions_for IS NULL OR possessions_against IS NULL THEN 1 ELSE 0 END) AS missing_possession_stints
      FROM lineup_stints WHERE team_abbr=? AND opponent_abbr=? AND validation_status='verified'
      GROUP BY 1,2 ORDER BY 1,2""",[team,opponent]).df()
