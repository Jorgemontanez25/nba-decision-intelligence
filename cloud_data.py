"""Resolve an authorized private research database for Streamlit Cloud.

No data is shipped inside the public Git repository. This helper uses a private
Hugging Face dataset repository requiring the owner's token, or an existing
local snapshot for development. The app must be kept private until the operator
has confirmed the rights required for its data usage and publication.
"""
from pathlib import Path
import streamlit as st

ROOT = Path(__file__).resolve().parent
LOCAL_DB = ROOT / 'deployment' / 'nba_demo.duckdb'

@st.cache_resource(show_spinner='Connecting to private research data...')
def _download_private_database(repo_id: str, token: str) -> str:
    from huggingface_hub import HfApi, hf_hub_download
    api = HfApi(token=token)
    info = api.repo_info(repo_id=repo_id, repo_type='dataset', token=token)
    if not info.private:
        raise RuntimeError('Refusing to load dataset: Hugging Face repository is PUBLIC. Make it private first.')
    return hf_hub_download(repo_id=repo_id, filename='nba_demo.duckdb', repo_type='dataset', token=token)


def resolve_cloud_db() -> str:
    """Use private cloud data when configured, otherwise the local snapshot.

    The token is never printed. The private repo ID is provided via Streamlit
    Cloud secrets and is not hard-coded. Public visitors must be disabled in
    Streamlit's sharing settings for this research deployment.
    """
    try:
        repo_id = st.secrets.get('HF_DATASET_REPO', '')
        token = st.secrets.get('HF_TOKEN', '')
    except FileNotFoundError:
        repo_id, token = '', ''
    if repo_id or token:
        if not repo_id or not token:
            st.error('Private research data credentials are incomplete in Streamlit secrets.')
            st.stop()
        try:
            path = Path(_download_private_database(str(repo_id), str(token)))
        except Exception as exc:
            st.error('Could not access the private research database. Check repository privacy, access permissions, and Streamlit secrets.')
            st.caption(f'Technical category: {type(exc).__name__}')
            st.stop()
        return str(path)
    if LOCAL_DB.is_file():
        return str(LOCAL_DB)
    st.error('Research database unavailable. Set HF_DATASET_REPO and HF_TOKEN in Streamlit secrets.')
    st.stop()
