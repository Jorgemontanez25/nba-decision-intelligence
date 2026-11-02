"""Optionally add authorized, existing shot events to a transient portfolio database.

No records are downloaded unless an operator has supplied access to a separate,
authorized Hugging Face dataset and explicitly enabled the showcase. Never
package NBA.com research records or tokens in the public Git repository.
"""
from pathlib import Path
import duckdb
import streamlit as st

PLAYERS = (1629029, 201939, 203999)


def merge_authorized_shots(portfolio_path: str) -> int:
    """Idempotently import only shots with matching player-game + season/type."""
    if not st.secrets.get('SHOOTING_SHOWCASE_ENABLED', False):
        return 0
    repo = st.secrets.get('SHOOTING_SHOWCASE_REPO', '')
    token = st.secrets.get('SHOOTING_SHOWCASE_TOKEN', '')
    if not repo or not token:
        raise ValueError('Shooting showcase enabled but repository/token missing.')
    from huggingface_hub import HfApi, hf_hub_download
    info = HfApi(token=token).repo_info(repo_id=repo, repo_type='dataset', token=token)
    if not info.private:
        raise ValueError('Shooting dataset must stay private; public display rights must be cleared separately.')
    source = hf_hub_download(repo_id=repo, repo_type='dataset', filename='shooting_showcase.duckdb', token=token)
    with duckdb.connect(portfolio_path) as con:
        con.execute('ATTACH ? AS shooting_source (READ_ONLY)', [str(Path(source))])
        try:
            con.execute('''INSERT INTO shot_events BY NAME
                SELECT s.* FROM shooting_source.shot_events AS s
                WHERE s.player_id IN (1629029, 201939, 203999)
                  AND EXISTS (
                    SELECT 1 FROM player_games AS p
                    WHERE p.game_id=s.game_id AND p.player_id=s.player_id
                      AND p.season=s.season AND p.season_type=s.season_type
                  )
                ON CONFLICT (game_id, player_id, event_id) DO NOTHING''')
            n = con.execute('SELECT COUNT(*) FROM shot_events').fetchone()[0]
        finally:
            con.execute('DETACH shooting_source')
    return n
