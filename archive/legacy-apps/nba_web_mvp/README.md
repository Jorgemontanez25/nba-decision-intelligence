# NBA Lineup Lab — Streamlit MVP

A read-only web interface for V9.9.9 reconstruction regression and V9.9.10 scoring audits.

## Install (one-line PowerShell commands, from nba_platform_v5)

1. Extract the `nba_web_mvp` folder inside `C:\Users\jmontanez\Documents\nba_platform_v5`.
2. ` .\.venv\Scripts\python.exe -m pip install -r .\nba_web_mvp\requirements.txt `
3. ` .\.venv\Scripts\python.exe -m streamlit run .\nba_web_mvp\app.py `

The app opens in a browser, typically http://localhost:8501. It reads `v9_9_9_regression_review` and `v9_9_10_scoring_review` from the working directory by default. Edit these paths in the sidebar if needed.

Views: overview, game timeline, player plus/minus scenarios, scoring boundary events, and QA status.

No DuckDB, no writes to source data, no lineup optimization or real-time features yet. Historical lineups remain conditional/unverified.
