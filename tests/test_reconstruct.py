import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reconstruct_lineups import reconstruct,read_csv
from team_branding import logo_url

def demo():
    root=Path(__file__).resolve().parents[1]/'examples'
    return read_csv(root/'events_demo.csv'),read_csv(root/'anchors_demo.csv')

def test_demo():
    events,anchors=demo()
    rows,errors=reconstruct(events,anchors,'LAL','BOS','DEMO','2025-26','Regular Season')
    assert not errors
    assert len(rows)==3
    assert sum(r['end_sec']-r['start_sec'] for r in rows)==720
    assert sum(r['points_for'] for r in rows)==27
    assert sum(r['points_against'] for r in rows)==23
    assert '16' in rows[1]['team_player_ids']

def test_missing_anchor_rejected():
    events,_=demo()
    rows,errors=reconstruct(events,[],'LAL','BOS','DEMO','2025-26','Regular Season')
    assert not rows and errors

def test_logos():
    assert '1610612747' in logo_url('LAL')
    assert '1610612738' in logo_url('BOS')
