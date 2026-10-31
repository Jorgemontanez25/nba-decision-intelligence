# START HERE — NBA Decision Intelligence V5 (Windows)

This project is a local prototype. You **do not** need V1, V2, V3 or V4; V5 includes the code needed from those versions.

## What works, and what does not yet work

- **Works when NBA API is available:** import final-game player box scores; browse individual player tables and trends in Streamlit; choose any NBA team and view its logo (internet required).
- **Works without NBA API:** run the synthetic lineup-reconstruction tests and demonstration.
- **Not automated yet:** translate real NBA play-by-play into verified period starters and substitution records; reconstruct and import historical real-world lineup stints end to end. This is why lineup rankings can be empty.
- **Not implemented:** confirmed daily injuries and availability, predictive starting-five recommendations, live coaching decisions.

## Step 1 — Install software

Install **Python 3.11 (64-bit)** from python.org if needed. In installation, check **Add python.exe to PATH**. Open PowerShell and check:

```powershell
py -3.11 --version
```

You may also use VS Code to edit the source files; it is optional.

## Step 2 — Extract ZIP and open PowerShell

Unzip the provided archive. Go into its `nba_platform_v5` folder (the folder containing `requirements.txt`). In File Explorer, click the address bar, type `powershell`, press Enter. Verify that you see `collector.py`, `dashboard_v4.py`, `requirements.txt`.

## Step 3 — Create virtual environment and install packages

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

These commands work even if Windows blocks virtual-environment activation.

## Step 4 — Check the code using synthetic tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

If installed correctly, the synthetic tests should run. They do not confirm real NBA API access.

To reconstruct the included **fake demonstration only**:

```powershell
.\.venv\Scripts\python.exe reconstruct_lineups.py --events examples/events_demo.csv --anchors examples/anchors_demo.csv --game-id DEMO --season 2025-26 --season-type "Regular Season" --home LAL --away BOS --output demo_stints.csv
```

**Do not import `demo_stints.csv` as real basketball data.**

## Step 5 — Collect a tiny real NBA data sample

From the same folder, run:

```powershell
.\.venv\Scripts\python.exe collector.py --db nba_current.duckdb --season 2025-26 --season-type "Regular Season" --max-games 2
```

Look for `Imported <game id>: ... player rows`. If calls are blocked, time out, or the NBA endpoint changes, inspect the printed `FAILED` message. Nothing is guaranteed until the import succeeds on your machine.

Then optionally collect two NBA playoff games:

```powershell
.\.venv\Scripts\python.exe collector.py --db nba_current.duckdb --season 2025-26 --season-type "Playoffs" --max-games 2
```

**Important:** `--max-games 2` means the **first two eligible games returned**, not necessarily Lakers–Celtics. For Lakers–Celtics analysis, you will need the games in your selected seasons, and may need to collect the full seasons.

## Step 6 — Launch the dashboard

```powershell
.\.venv\Scripts\python.exe -m streamlit run dashboard_v4.py
```

Open the local address printed by Streamlit (often http://localhost:8501). In the sidebar:

1. Keep the database path as `nba_current.duckdb`.
2. Select seasons (e.g. `2025-26` to start).
3. Choose `LAL` as team, `BOS` as opponent, and desired game types.
4. Look at **Player profiles** and **Data coverage**.

If there are no Lakers–Celtics games in the database yet, the player table is empty; this is expected with a small unrelated sample. To test player stats sooner, set **Opponent** to the opponent of one of your imported games (you can check `team_games`), or collect more games.

The **Historical 5v5 lineups** tab is empty until verified lineup stints have been imported.

## Step 7 — Expand the historical data (after small test works)

Run the collector for each season separately; for example:

```powershell
.\.venv\Scripts\python.exe collector.py --db nba_current.duckdb --season 2022-23 --season-type "Regular Season" --sleep 1.5
.\.venv\Scripts\python.exe collector.py --db nba_current.duckdb --season 2023-24 --season-type "Regular Season" --sleep 1.5
.\.venv\Scripts\python.exe collector.py --db nba_current.duckdb --season 2024-25 --season-type "Regular Season" --sleep 1.5
.\.venv\Scripts\python.exe collector.py --db nba_current.duckdb --season 2025-26 --season-type "Regular Season" --sleep 1.5
```

For postseason data, repeat with `--season-type "Playoffs"`. These requests may be slow or throttled by the provider; collection does not guarantee success. The collector uses incremental game-level status information, and you can retry after failures.

For **2026-27**, run the collector only when official games appear in the source. You can run it manually after games; scheduling is a future step.

## Step 8 — What lineup reconstruction requires

To fetch raw play-by-play for a known actual `GAME_ID`:

```powershell
.\.venv\Scripts\python.exe fetch_play_by_play.py --game-id REPLACE_WITH_REAL_GAME_ID
```

This is **raw** data, not yet a verified lineup import. A separate normalization pass must establish the five starters at the beginning of each period, substitutions, timestamps, and score changes. Read `README.md` for the normalized CSV schema. Once real, verified stints are available, import them using:

```powershell
.\.venv\Scripts\python.exe import_stints.py stints_verified.csv --db nba_current.duckdb
```

Never substitute the synthetic demo file for real game data.

## Common problems

- **`py` not recognized:** Install Python 3.11 and reopen the terminal, or use the full path to Python.
- **`ModuleNotFoundError`:** Run the pip install command using `.venv\\Scripts\\python.exe` and keep PowerShell in the project folder.
- **NBA request timeout/403:** A source-side issue, not proof the game or player does not exist. Retry later, reduce request frequency, or use a permitted data feed.
- **Dashboard empty:** Verify the `--db` path, that game imports succeeded, and that your selected team/opponent/season combination exists in the imported sample.
- **No 100-minute lineup:** Head-to-head minutes are sparse; try reducing the dashboard threshold for exploration, but do not describe low-sample results as reliable.
- **Logo missing:** NBA CDN may be unreachable; this does not affect statistics.

## Project files

- `collector.py`: final-game team/player box-score ingestion.
- `schema.sql`: player and team data tables.
- `analysis.py`: individual performance and trends.
- `dashboard_v4.py`: main dashboard and logo selectors.
- `team_branding.py`: NBA team names, IDs, and logo URLs.
- `lineup_engine.py`, `lineup_schema.sql`, `import_stints.py`: validated lineup store and rankings.
- `fetch_play_by_play.py`: raw play-by-play download.
- `reconstruct_lineups.py`: reconstruction from normalized verified events and period anchors.
- `examples/` and `tests/`: synthetic reconstruction example and tests.
- `dashboard.py`: earlier player-only dashboard (optional).
- `recommendations.py`: experimental support module, **not** a validated starting-five predictor.

## Project status and next milestone

The most important next development milestone is the **real NBA play-by-play normalizer**, followed by possession reconciliation, current roster/injury ingestion, and a validated opponent-aware predictive model. Until then, the dashboard can describe observed individual performance but not recommend a trusted starting five.


## Collector fix (2026-10-10)
The collector now uses `now()` in DuckDB timestamp expressions instead of `CURRENT_TIMESTAMP` in `ON CONFLICT` statements. If you saw a `BinderException` referencing `CURRENT_TIMESTAMP`, replace `collector.py` with this package version. Existing `nba_current.duckdb` can be reused; no deletion is needed.
