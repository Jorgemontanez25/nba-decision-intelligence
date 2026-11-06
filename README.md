<div align="center">

# 🏀 NBA Decision Intelligence
### Player & Lineup Analysis · Basketball Decision Support

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-Dashboard-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io)
[![DuckDB](https://img.shields.io/badge/DuckDB-Analytics-F5C518)](https://duckdb.org)
![Status](https://img.shields.io/badge/Status-Research%20prototype-56627A)

**[Launch the Streamlit application](https://nba-decision-intelligence.streamlit.app/)**

*Multi-season NBA research dashboard with player analytics, shot charts, rosters, and experimental 5v5 lineup decision support.*
</div>

## Overview

NBA Decision Intelligence is an independent sports analytics portfolio project built with Python, Streamlit, DuckDB and Plotly. It explores player performance, shooting tendencies, historical trends, team comparisons, and experimental lineup selection. Local research records cover portions of 2022–23 through 2026–27; data completeness varies by season and data type.

## What works

- **Player analysis and game logs** — working locally and in the hosted app, with an automatically retrieved game-log dataset.
- **Career trends and team comparisons** — available where source coverage exists.
- **2026–27 Roster Manager** — dated roster snapshots for exploring current teams.
- **5v5 Decision Center** — an experimental, deterministic heuristic ranking that returns the top five candidate lineups for a selected team and opponent, with a 0–100 relative index for that query.
- **Three-player shooting showcase** — locally validated for Stephen Curry, Luka Dončić, and Nikola Jokić: **3,680 matched events**, zero missing coordinate pairs, zero duplicate event keys, and an idempotent merge. Shot charts, density heatmaps, and zone-efficiency maps rendered successfully in the local app.
- **Shot charts, density heatmaps, and zone efficiency** — working with existing research records locally.

See [Limitations & scope](#limitations--scope) for what is experimental, local-only, or still pending permission.

## Explore the dashboard

### Player Analysis

![Player Analysis](assets/player-analysis.png)

### 5v5 Decision Center

![5v5 Decision Center](assets/decision-center.png)

<details>
<summary><strong>More screenshots — shot charts, team comparison, and roster</strong></summary>

#### Shot density heatmap
Brighter areas mean more shot attempts, **not** higher shooting efficiency.

![Shot density](assets/shooting-heatmap.png)

#### Shot chart
![Shot chart](assets/shooting-shot-chart.png)

#### Team comparison
Box-score comparisons are not opponent-adjusted defensive efficiency.

![Team comparison](assets/team-comparison.png)

#### 2026–27 Roster Manager
![Roster Manager](assets/roster-manager.png)
</details>

<details>
<summary><strong>Data architecture</strong></summary>

![Architecture](assets/architecture.svg)
</details>

## How the 5v5 lineup ranking works (v4.9.2)

A deterministic, interpretable **heuristic ranking** of hypothetical five-player combinations. The implementation is in [`decision_center_v492.py`](decision_center_v492.py), principally `roster_profiles`, `player_components`, `lineup_fit`, and `render_decision_center`.

### Inputs and candidate eligibility

- **Game-level box scores** in DuckDB (`player_games`) across available seasons and regular-season/playoff filters. Player performance is aggregated by **player ID**, including prior teams, using only games with positive minutes.
- **Current 2026–27 roster snapshots** identify eligible roster members and approximate position/role labels. Missing roster entries are not filled from historical teams, and players without historical profiles are not assigned invented metrics. The user can exclude unavailable players manually; live injuries and availability are not automatically connected.
- **Selected opponent five** supplies a descriptive scoring-threat adjustment, based on opponent players' individual points per 36 minutes; no verified head-to-head five-man or defensive assignment information is used.
- **Optional externally sourced NBA 2K27 overall rating** from `nba_2k27_ratings.csv` is used only when a uniquely matched rating is available. The model does **not** infer an OVR from box-score statistics.

### Recency-weighted player profiles

For points, assists, rebounds, steals plus blocks, and turnovers, the model computes recency-weighted **per-36-minute** rates by weighting each observation by its season's coefficient and minutes played. The code uses these season weights:

| Season | Weight |
|---|---:|
| 2026–27 | 1.00 |
| 2025–26 | 0.85 |
| 2024–25 | 0.60 |
| 2023–24 | 0.35 |
| Older/other seasons | 0.20 |

True shooting percentage (`TS%`) is computed from weighted totals: `100 * weighted_points / (2 * (weighted_FGA + 0.44 * weighted_FTA))`. Games played also determine a sample-confidence shrinkage factor, `0.65 + 0.35 * min(games / 20, 1)`.

### Player scoring formula

The current coefficients are **manually selected heuristics**, not weights learned from historical outcomes:

```text
Offense = 0.92 * PTS/36 + 1.50 * AST/36 + 0.22 * (TS% - 54) - 1.25 * TOV/36
Defense = 0.48 * REB/36 + 1.65 * (STL + BLK)/36
Base = (w_offense * Offense + w_defense * Defense) * sample_confidence
Optional OVR prior = 0.20 * (sourced_2K_OVR - 75), or 0 when unavailable
Player score = Base + Optional OVR prior
```

The default strategy weights are **53% offense / 47% defense**. In *manual in-game* mode, the score margin and time remaining can shift these weights: trailing late favors offense; leading late favors defense. A selected opponent five with a higher average `PTS/36` increases the defensive weight slightly. These are explicit heuristic adjustments, not a learned matchup effect.

### Searching and ranking complete lineups

1. Generate all five-player combinations from eligible current-roster players with usable historical box-score profiles.
2. Sum five player scores and apply **lineup-fit penalties** for inadequate guards, wings or bigs, excessive bigs, and unknown positions. Approximate roster positions are used, not tracking-derived roles.
3. In manual in-game mode, enforce the selected maximum substitutions and subtract **0.6 points per substituted player** from the combination score.
4. Sort combinations by score (then fewer substitutions and stable player IDs), and return the **top five candidate lineups**.
5. Display a **0–100 relative index within the combinations evaluated for that specific query**. This number is **not** a win probability, percentile across the NBA, expected scoring margin, or a calibrated performance projection.

The accompanying full-court illustration and radar charts compare summed/averaged **individual** statistics. Their player placement is illustrative, not actual player tracking. No possession-validated five-man synergy or opponent-specific lineup impact is included in the ranking. Historical stint-reconstruction QA remains separate until the underlying results can be independently validated.

### Scope of the 5v5 ranking

This is a heuristic ranking, **not** a trained win-probability predictor, a validated causal lineup-impact model, or a simulation of possessions. See [Known limitations and planned validation](#known-limitations-and-planned-validation) below.

### Known limitations and planned validation

- Box-score defensive proxies (rebounds, steals, blocks) are **not defensive ratings**; individual box-score rates do not directly measure how a unit performs together.
- Availability, injuries, fouls, opponent defensive assignments, and substitutions are **not live feeds**; the in-game mode is manually configured.
- Some roster positions, 2K ratings, seasons, and game logs may be incomplete or stale. The algorithm reports coverage rather than silently filling unavailable values.
- Future work: evaluate rankings against *verified* stint-level outcomes, benchmark against simpler baselines, tune coefficients with held-out games, calibrate uncertainty, and validate out-of-sample performance before describing any output as predictive.

## Three-player shooting showcase — locally validated

The local showcase uses recorded NBA.com-derived shot coordinates and makes/misses for **Stephen Curry, Luka Dončić, and Nikola Jokić** across available 2025–26 and early 2026–27 games. The current showcase includes **3,703** source events; **3,680** match player-game records in the separate portfolio dataset, while **23** Luka Dončić events are excluded because corresponding player-game records are unavailable.

| Player | Matched attempts | Matched makes |
|---|---:|---:|
| Stephen Curry | 887 | 416 |
| Nikola Jokić | 1,218 | 685 |
| Luka Dončić | 1,575 | 749 |
| **Total** | **3,680** | **1,850** |

Validation on November 2, 2026 confirmed **zero missing coordinate pairs**, **zero duplicate event keys**, and an **idempotent merge** (the second import retained 3,680 events, adding no duplicates). Shot charts, density heatmaps and zone-efficiency maps rendered successfully in the original local app. These tests validate database compatibility and recorded-coordinate completeness, not independent event location accuracy or full seasonal coverage.

Implementation: `build_shooting_showcase.py` produces a separate local extract; `shooting_overlay.py` supports a conditional import of authorized shot data into the temporary portfolio database. Neither action publishes the research records by itself.

Example local extraction (do not commit the generated database):

```powershell
.\.venv\Scripts\python.exe .\build_shooting_showcase.py --source nba_current.duckdb --out nba_shooting_showcase_LOCAL_ONLY.duckdb --seasons 2025-26 2026-27
```

### Public-display permissions — pending

The shooting records were collected from NBA.com through an API client. **A free or noncommercial portfolio is not automatically exempt from the original provider's restrictions.** The current public build therefore does not distribute the curated shot-event database. Private storage and limiting coverage to three players do not, on their own, establish a right to display the data or derived charts publicly.

We plan to request written clarification/permission from the NBA for a limited noncommercial showcase covering these three players, approximately 3,680 historical events, interactive shot charts, density heatmaps, and zone efficiency. The request should specifically address **third-party cloud storage and public display**. See [NBA Terms of Use](https://www.nba.com/termsofuse). If permission is not granted, the fallback is a free source with explicit rights suitable for the intended display and storage.

**Permission status: not yet confirmed.** No approval, exemption, or license is claimed by this project.

### Work remaining after authorization

1. Obtain and retain written permission, or verify an alternative dataset license covering cloud hosting and interactive display.
2. Provide the permitted three-player `shooting_showcase.duckdb` through controlled storage (never the public Git repository); configure the existing `SHOOTING_SHOWCASE_ENABLED`, `SHOOTING_SHOWCASE_REPO`, and `SHOOTING_SHOWCASE_TOKEN` secrets without exposing credentials.
3. Review the cloud loader's cached database lifecycle to ensure the approved overlay is applied following a configuration change or app restart.
4. Verify Luka, Curry and Jokić on a **fresh hosted session**, including shot chart, heatmap, zone map, player statistics, and seasons; verify other player profiles display an accurate coverage notice.
5. Update this README only after the public interaction has actually been tested, with source attribution, coverage dates, and limitations.

## Application status — November 2, 2026

| Capability | Local research application | Hosted Streamlit app |
|---|---|---|
| Player analysis and game logs | Working | Working with automatically retrieved game-log dataset |
| Career trends and team comparisons | Working where source coverage exists | Available where source coverage exists |
| Experimental 5v5 Decision Center | Working, with documented limits | Available; verified historical stint data not included |
| Shooting charts, density heatmaps, zone efficiency | Working with existing research records | **Not interactive yet** — shot events not in hosted dataset |
| Three-player shooting overlay | **Validated** (3,680 matched events) | Integration code deployed; data connection disabled pending permission |
| Visitor database upload | Optional research workflow | Not required for the auto-loaded player-statistics views |

**Deployment:** [nba-decision-intelligence.streamlit.app](https://nba-decision-intelligence.streamlit.app/)  
**Branch:** `release/streamlit-cloud`  
**Entrypoint:** `app_decision_cloud.py`  
**Automatic player-game data:** `portfolio_bootstrap.py` (source-attributed external game logs; coverage is incomplete and publisher claims do not independently clear underlying NBA rights).

The hosted app builds/loads its game-log snapshot automatically at startup. The raw shooting dataset is **not** bundled in the public repository or automatically loaded online. A private or authorized upload mechanism remains available for controlled testing, subject to applicable terms.

## Technology

| Layer | Technology |
|---|---|
| Dashboard | Streamlit |
| Analytics | Python, Pandas, NumPy |
| Historical data | DuckDB |
| Visualizations | Plotly |
| Rosters | Dated local CSV snapshots |
| Ratings display | Externally sourced NBA 2K27 ratings cache |
| Deployment | Streamlit Community Cloud and GitHub |

## Historical data and reproducibility

An earlier local research snapshot contained **112,708 player-game rows**, **8,586 team-game rows**, and **221,137 shot-event rows**. These are record counts, not unique games or proof of full seasonal coverage. Historical lineup-stint and player-availability tables were empty in that snapshot. More recent local imports may have changed these counts.

**The full historical DuckDB database is not included in this repository.** Local databases, temporary audits and credentials are deliberately excluded from Git. NBA statistical records, images, logos and external ratings may be subject to third-party restrictions.

## Run locally — v4.9.2 release branch

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run .\app_decision_v492.py
```

To test the deployed entrypoint locally:

```powershell
.\.venv\Scripts\python.exe -m streamlit run .\app_decision_cloud.py
```

The cloud entrypoint automatically attempts to load published game logs. Access to additional research records depends on locally supplied, appropriately authorized data.

## Limitations & scope

> **Research limitations:** 5v5 recommendations are experimental box-score-based heuristics, **not** validated five-player causal impact estimates or calibrated game-win probabilities. Roster snapshots are not real-time injury feeds. No fabricated shot records are used.

- The 5v5 Decision Center is an experimental heuristic, not a validated causal model or a win-probability predictor.
- Shot charts and the three-player overlay are validated locally; the hosted app does not yet include interactive shot events, and public display permission for the shooting showcase is not yet confirmed.
- Data completeness varies by season and data type, and some roster positions, ratings, seasons, and game logs may be incomplete or stale.
- Source attribution is not a substitute for permission when permission is required.

## Roadmap

- [x] Player history, game logs, shooting visualizations and roster exploration in local research app
- [x] Experimental 5v5 decision-support interface
- [x] Streamlit Community Cloud deployment with automatic player-game data loading
- [x] Local three-player shooting overlay: validated 3,680 matching events and duplicate-safe import
- [ ] Obtain a public-display and hosting permission basis for interactive NBA shooting showcase
- [ ] Enable and verify interactive Curry / Dončić / Jokić shooting online
- [ ] Improve historic coverage, roster/availability accuracy and validated lineup impact methodology

## Responsible use

Independent research and portfolio project; not endorsed by the NBA, NBA teams, 2K Sports, ESPN or Streamlit. Results are exploratory, not verified coaching instructions. Source attribution is not a substitute for permission when permission is required.

---

<div align="center">
**Developed by Jorge Montañez** · Sports Analytics · Data Science
</div>
