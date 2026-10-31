from collector import season_label,minutes_value

def test_season():
    assert season_label(2026)=='2026-27'

def test_minutes():
    assert minutes_value('12:30')==12.5
    assert minutes_value('PT12M30S')==12.5
