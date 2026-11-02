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

> **Research limitations:** 5v5 recommendations are experimental box-score-based heuristics, **not** validated five-player causal impact estimates or calibrated game-win probabilities. Roster snapshots are not real-time injury feeds. No fabricated shot records are used.

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
