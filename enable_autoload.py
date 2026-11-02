"""Enable an authorized, automatic local DuckDB snapshot on Streamlit Cloud.

Run from the repository root. This edits only cloud_data.py; it never uploads
or copies databases, and retains the optional upload/Hugging Face paths.
"""
from pathlib import Path

p = Path('cloud_data.py')
if not p.is_file():
    raise SystemExit('cloud_data.py missing: run from nba_platform_v5 root')
s = p.read_text(encoding='utf-8')
if 'AUTO_PORTFOLIO_DB = ' not in s:
    anchor = "LOCAL_DB = ROOT / 'deployment' / 'nba_demo.duckdb'"
    if anchor not in s:
        raise SystemExit('Unrecognized cloud_data.py; no changes made')
    s = s.replace(anchor, anchor + "\n# Only place a snapshot here if third-party cloud storage and public display are authorized.\nAUTO_PORTFOLIO_DB = ROOT / 'deployment' / 'portfolio_public.duckdb'")
if 'if AUTO_PORTFOLIO_DB.is_file():' not in s:
    anchor = 'def resolve_cloud_db() -> str:\n'
    if anchor not in s:
        raise SystemExit('Cloud database resolver not found; no changes made')
    patch = '''def resolve_cloud_db() -> str:
    # Public portfolio: load a separately authorized snapshot automatically.
    # Never bundle the original local research database by default.
    if AUTO_PORTFOLIO_DB.is_file():
        try:
            _validate_database(str(AUTO_PORTFOLIO_DB))
        except Exception as exc:
            st.error(f'Bundled portfolio database is invalid: {type(exc).__name__}: {exc}')
            st.stop()
        return str(AUTO_PORTFOLIO_DB)
'''
    s = s.replace(anchor, patch, 1)
p.write_text(s, encoding='utf-8')
print('Updated cloud_data.py: authorized deployment/portfolio_public.duckdb will auto-load if present.')
print('No databases were uploaded or changed.')
