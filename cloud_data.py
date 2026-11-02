"""Cloud database selector for NBA Decision Intelligence.

Optional bring-your-own DuckDB file in a Streamlit session, or authorized private
Hugging Face snapshot. Never publish a local research database automatically.
"""
from pathlib import Path
import os
import tempfile
import uuid

import duckdb
import streamlit as st

ROOT = Path(__file__).resolve().parent
LOCAL_DB = ROOT / 'deployment' / 'nba_demo.duckdb'
# Only place a snapshot here if third-party cloud storage and public display are authorized.
AUTO_PORTFOLIO_DB = ROOT / 'deployment' / 'portfolio_public.duckdb'
REQUIRED_TABLES = {'player_games', 'team_games', 'shot_events'}


@st.cache_resource(show_spinner='Connecting to private research data...')
def _download_private_database(repo_id: str, token: str) -> str:
    from huggingface_hub import HfApi, hf_hub_download
    api = HfApi(token=token)
    info = api.repo_info(repo_id=repo_id, repo_type='dataset', token=token)
    if not info.private:
        raise RuntimeError('The dataset repository must be private.')
    return hf_hub_download(
        repo_id=repo_id, filename='nba_demo.duckdb',
        repo_type='dataset', token=token,
    )


def _validate_database(path: str) -> None:
    with duckdb.connect(path, read_only=True) as con:
        rows = con.execute(
            'SELECT table_name FROM information_schema.tables '
            "WHERE table_schema = 'main'"
        ).fetchall()
    present = {row[0] for row in rows}
    missing = REQUIRED_TABLES - present
    if missing:
        raise ValueError('Missing expected tables: ' + ', '.join(sorted(missing)))


def _session_upload() -> str | None:
    st.sidebar.markdown('### Online research data')
    st.sidebar.caption('Optional: open your own DuckDB snapshot in this browser session. The file is transferred to Streamlit hosting, not added to GitHub or Hugging Face.')
    upload = st.sidebar.file_uploader('Choose DuckDB snapshot', type=['duckdb'], key='research_db_upload')
    if upload is None:
        # Preserve the temporary file during normal Streamlit widget reruns.
        existing = st.session_state.get('_research_db_path')
        return existing if existing and Path(existing).is_file() else None

    identity = (upload.name, upload.size, upload.file_id)
    if (identity == st.session_state.get('_research_db_identity')
            and Path(st.session_state.get('_research_db_path', '')).is_file()):
        return st.session_state['_research_db_path']

    path = os.path.join(tempfile.gettempdir(), 'nba_research_' + uuid.uuid4().hex + '.duckdb')
    try:
        with open(path, 'wb') as output:
            while chunk := upload.read(1024 * 1024):
                output.write(chunk)
        _validate_database(path)
    except Exception as exc:
        try:
            os.remove(path)
        except OSError:
            pass
        st.sidebar.error(f'Invalid or incompatible DuckDB snapshot: {type(exc).__name__}: {exc}')
        st.stop()

    previous = st.session_state.get('_research_db_path')
    st.session_state['_research_db_path'] = path
    st.session_state['_research_db_identity'] = identity
    if previous and previous != path:
        try:
            os.remove(previous)
        except OSError:
            pass
    return path


def resolve_cloud_db() -> str:
    # Public portfolio: load a separately authorized snapshot automatically.
    # Never bundle the original local research database by default.
    if AUTO_PORTFOLIO_DB.is_file():
        try:
            _validate_database(str(AUTO_PORTFOLIO_DB))
        except Exception as exc:
            st.error(f'Bundled portfolio database is invalid: {type(exc).__name__}: {exc}')
            st.stop()
        return str(AUTO_PORTFOLIO_DB)
    uploaded = _session_upload()
    if uploaded:
        st.sidebar.success('Research snapshot loaded for this session.')
        return uploaded

    try:
        repo_id = st.secrets.get('HF_DATASET_REPO', '')
        token = st.secrets.get('HF_TOKEN', '')
    except (FileNotFoundError, KeyError):
        repo_id, token = '', ''

    if repo_id and token:
        try:
            path = _download_private_database(str(repo_id), str(token))
            _validate_database(path)
            return path
        except Exception as exc:
            st.warning('The private research snapshot is not available yet. Use the upload control in the sidebar to open your own permitted dataset.')
            st.caption(f'Private database status: {type(exc).__name__}')
    elif repo_id or token:
        st.warning('Private research database configuration is incomplete. You can use the upload control instead.')

    if LOCAL_DB.is_file():
        try:
            _validate_database(str(LOCAL_DB))
            return str(LOCAL_DB)
        except (duckdb.Error, ValueError) as exc:
            st.error(f'Bundled database is incompatible: {exc}')
            st.stop()

    # SHOOTING_PORTFOLIO_GALLERY_V1 — static screenshots, not live event feeds.
    st.divider()
    st.subheader('Shooting Showcase — Research Screenshots')
    st.caption('Examples produced in the local research environment. These are static images, not interactive live shooting data. Published display is subject to underlying NBA data and image rights.')
    col1, col2 = st.columns(2)
    with col1:
        chart = ROOT / 'assets' / 'shooting-shot-chart.png'
        if chart.is_file():
            st.image(str(chart), caption='Example shot chart (local research dashboard)', use_container_width=True)
        else:
            st.info('Shot-chart image not included in this deployment.')
    with col2:
        heatmap = ROOT / 'assets' / 'shooting-heatmap.png'
        if heatmap.is_file():
            st.image(str(heatmap), caption='Example shot-density heatmap: brighter indicates greater attempt density, not accuracy', use_container_width=True)
        else:
            st.info('Heatmap image not included in this deployment.')
    st.caption('For the interactive shot-chart, heatmap, and zone-efficiency tools, a compatible authorized snapshot containing shot_events is required.')

    st.info('To open the full NBA Decision Intelligence dashboard, upload a compatible .duckdb snapshot using the sidebar. The original application and its analytics have not been changed.')
    st.caption('Only upload data you are authorized to transfer to a third-party cloud server. This session-upload option does not provide a permanent public data source.')
    st.stop()
