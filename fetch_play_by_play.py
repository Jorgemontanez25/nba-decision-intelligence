"""Fetch raw official NBA live play-by-play actions for audit and later normalization.
This intentionally does not guess player_in/player_out on substitution events.
"""
import argparse
import json
from pathlib import Path


def fetch(game_id):
    from nba_api.live.nba.endpoints import playbyplay
    result=playbyplay.PlayByPlay(game_id=game_id)
    return result.nba_response.get_dict()['game']['actions']

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--game-id',required=True);p.add_argument('--out',default=None)
    a=p.parse_args()
    dest=Path(a.out or f'pbp_{a.game_id}.json')
    actions=fetch(a.game_id)
    dest.write_text(json.dumps(actions,indent=2),encoding='utf8')
    print(f'Saved {len(actions)} source actions to {dest}. Normalize substitutions and period anchors before reconstruction.')
