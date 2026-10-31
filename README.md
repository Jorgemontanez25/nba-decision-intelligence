# NBA Decision Intelligence V4.5

Incremental upgrade to your original Streamlit dashboard, not a new application.

## Files and installation

Copy `app_decision_v45.py`, `decision_center_v45.py`, `v45_visuals.py`, `v45_daily_refresh.py`, and `roster_2026_27.py` into `nba_platform_v5`. The existing `analysis.py`, `team_branding.py`, `lineup_engine.py`, `collect_shots.py`, and `collector.py` remain required. The supplied `collect_schedule_v7.py` is a reference copy; retain your working version if locally modified.

Keep your `nba_current.duckdb` and `roster_snapshots` folder unchanged.

Launch (PowerShell one line):

```powershell
.\.venv\Scripts\python.exe -m streamlit run .\app_decision_v45.py
```

## Updated UI

- ESPN-inspired roster table: portrait, player, position, jersey, games, production and box/shot coverage. It does not connect to an ESPN fantasy account.
- NBA 2K-inspired player snapshot with actual per-36 box-score rates; no fabricated overall or 2K attribute ratings.
- Improved full-court 5v5 headshots embedded inside circular picture markers; names below each player. Ranked lineups and flank charts rerender with selection.
- Current-roster membership is from 2026–27 dated snapshots; career stats are matched by NBA player ID regardless of previous teams. All collected seasons are used automatically. No missing seasons invented.

## Daily data refresh, agent-like

A standalone scheduled job is safer than calling an NBA API on every Streamlit page view. It updates rosters and final regular-season box scores, saves a backup and a status report. It does **not** automatically backfill shots, pull injuries or play-by-play, or certify 5v5 stints.

**Before refreshing**, close Streamlit and other processes writing to DuckDB; the job copies the existing DB to a dated backup but cannot guarantee a consistent backup if another process has it open. The NBA Stats endpoint may fail or throttle; failed jobs are reported and do not erase previous data.

Test without network or changes:

```powershell
.\.venv\Scripts\python.exe .\v45_daily_refresh.py --dry-run
```

Manual refresh:

```powershell
.\.venv\Scripts\python.exe .\v45_daily_refresh.py --season 2026-27 --teams ALL --max-games 30
```

Daily at 06:30 local Windows time, opt in (run in PowerShell while inside the project root; task uses absolute paths):

```powershell
$wd=(Get-Location).Path; $act=New-ScheduledTaskAction -Execute "$wd\.venv\Scripts\python.exe" -Argument 'v45_daily_refresh.py --season 2026-27 --teams ALL --max-games 30' -WorkingDirectory $wd; $tr=New-ScheduledTaskTrigger -Daily -At 6:30AM; Register-ScheduledTask -TaskName 'NBA-Decision-Intelligence-Daily' -Action $act -Trigger $tr -Description 'Refresh NBA rosters and completed box scores each morning' -Force
```

The scheduled task runs on your Windows machine under your account when configured and the machine is available; it is not a background task run by ChatGPT. Avoid simultaneous Streamlit read/write operations during the refresh. `data_refresh_v45/latest.json` appears in the roster tab for monitoring.

## Important: historical backfill

The agent's default job only collects the **current season** incrementally. It cannot conjure 2022–23 to 2024–25 data if absent in DuckDB. Use your existing schedule-aware collector separately, season by season, after backing up the database, or add historical backfill later. Shot events require their own collector.

All rankings remain experimental player-box-score heuristics. Not independent five-player matchup certification or automatic live substitution advice.
