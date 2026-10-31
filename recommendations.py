"""Safe MVP recommendation policy.
Historical rankings != forward projections or confirmed game-day starters.
"""
from lineup_engine import matchup_rankings

def evaluate_lineups(con, target_game_id, team='LAL', opponent='BOS', min_minutes=100):
    """Only evaluate previously observed combinations whose 5 players are confirmed available.
    Never impute absent availability as 'available'.
    """
    if not target_game_id: raise ValueError('target_game_id required')
    results=matchup_rankings(con,team,opponent,min_minutes=min_minutes)
    if results.empty:
        return {'status':'insufficient_lineup_sample','lineups':[]}
    avail=con.execute('SELECT player_id,status FROM player_availability WHERE game_id=?',
                      [target_game_id]).fetchall()
    statuses={int(pid):status for pid,status in avail}
    verified=[]
    for item in results.to_dict('records'):
        pids=[int(x) for x in item['lineup_key'].split('|')]
        if all(statuses.get(pid)=='available' for pid in pids):
            verified.append(item)
    if not verified:
        return {'status':'availability_unverified','lineups':[]}
    return {'status':'historical_candidates_only','lineups':verified}
