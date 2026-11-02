<div align="center">

# 🏀 NBA Decision Intelligence
### Player & Lineup Analysis · Basketball Decision Support

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-Dashboard-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io)
[![DuckDB](https://img.shields.io/badge/DuckDB-Analytics-F5C518)](https://duckdb.org)
![Status](https://img.shields.io/badge/Status-Research%20prototype-56627A)

*Multi-season NBA research dashboard with player analytics, shot charts, rosters, and experimental 5v5 lineup recommendations.*
</div>

## Overview

An independent sports analytics portfolio project built with Python, Streamlit, DuckDB and Plotly. Player IDs connect statistics across teams and seasons. Local records cover portions of 2022–23 through 2026–27; completeness varies by season and data type.

> **Research limitations:** The 5v5 rankings use experimental heuristics, not validated five-player impact or calibrated win probabilities. Historical lineup reconstructions are not used as certified training data. Roster snapshots are not real-time injury feeds.

## Explore the dashboard

### Player Analysis

![Player Analysis](assets/player-analysis.png)

### 5v5 Decision Center

![5v5 Decision Center](assets/decision-center.png)

<details>
<summary><strong>More screenshots — shot charts, team comparison, and roster</strong></summary>

#### Shot density heatmap
Brighter areas mean more shot attempts, **not** higher accuracy.

![Shot density](assets/shooting-heatmap.png)

#### Shot chart
![Shot chart](assets/shooting-shot-chart.png)

#### Team comparison
Box-score proxies, not opponent-adjusted defensive efficiency.

![Team comparison](assets/team-comparison.png)

#### 2026–27 Roster Manager
![Roster Manager](assets/roster-manager.png)
</details>

<details>
<summary><strong>Data architecture</strong></summary>

![Architecture](assets/architecture.svg)
</details>

<!-- CLOUD_SHOWCASE_STATUS_START -->
## Hosted portfolio and shooting-data status (November 2026)

**Live app:** https://nba-decision-intelligence.streamlit.app/  
**Deployment branch:** `release/streamlit-cloud`  
**Entrypoint:** `app_decision_cloud.py`

The original Streamlit dashboard has been launched online. With a compatible,
authorized `.duckdb` file supplied through the session uploader, its player-game
analytics and box-score-based decision-support views can be explored. **A freshly
opened session does not automatically have a populated database**: the cloud
loader expects an authorized private snapshot or a compatible file supplied by
an authorized user. The session upload is temporary, not a persistent public
dataset. The public link alone does not guarantee populated data for visitors.

### Shooting showcase

The original research environment includes actual NBA.com-derived shot-event
coordinates, makes/misses and shot distances, used for shot charts, density
heatmaps and zone-efficiency maps. The currently tested cloud-compatible
game-log snapshot has **no `shot_events`**, so these visuals are unavailable
when that snapshot is selected. No shot coordinates are simulated.

`build_shooting_showcase.py` creates a **local-only** extract of selected player
shot events and their corresponding game/box-score records from an existing
local DuckDB database. Example:

```powershell
.\.venv\Scripts\python.exe .\build_shooting_showcase.py --source nba_current.duckdb --out nba_shooting_showcase_LOCAL_ONLY.duckdb --seasons 2025-26 2026-27
```

This file must **not** be committed to a public repository or uploaded to
third-party hosting without confirming the necessary rights. A noncommercial
portfolio purpose, crediting the source, or extracting a small sample does not
alone confer rights to republish NBA-derived event-level records or charts.

### Shooting showcase validation — 2 November 2026

A separate **local-only** integration test merged existing real shot-event
records with the portfolio game-log database. **3,680 of 3,703 shot events**
matched a portfolio player-game record (99.4%); the remaining **23 events**
were excluded because corresponding player-game records were unavailable.
The original dashboard successfully rendered player statistics, shot charts,
shot-density heatmaps and zone-efficiency maps for **Stephen Curry, Luka Dončić,
and Nikola Jokić** using the combined local snapshot. These counts reflect
available records, not proof of complete season coverage or coordinate accuracy.

**This is a technical compatibility validation, not a permission determination.**
The combined research dataset remains local and is not a public download.
Public display or third-party hosting of NBA.com-derived shot records and
visualizations requires a confirmed permission basis or an appropriately
licensed alternative source. No fabricated shot events are used.

The 5v5 Decision Center includes *experimental box-score-based rankings*;
it is not a validated lineup win-probability or certified historical lineup
impact model. Verified stint coverage and the availability of roster snapshots
are separately reported in the app.

**Deployment next steps:** establish authorized persistent hosting for player
and shooting data, verify the cloud dashboard in a fresh browser session, and
keep secrets and raw research datasets out of Git. The current public app URL
alone does not guarantee populated data for new visitors.
<!-- CLOUD_SHOWCASE_STATUS_END -->

## Technology

| Layer | Technology |
|---|---|
| Dashboard | Streamlit |
| Analytics | Python, Pandas, NumPy |
| Historical data | DuckDB |
| Visualizations | Plotly |
| Rosters | Dated local CSV snapshots |
| Ratings display | Externally sourced NBA 2K27 ratings cache |

## Historical data and reproducibility

A verified local snapshot contained **112,708 player-game rows**, **8,586 team-game rows**, and **221,137 shot-event rows**. These are row counts, not unique NBA games. Data collection and shot-location completeness vary across seasons. Historical lineup-stint and player-availability tables were empty in that snapshot.

**The complete historical DuckDB dataset is not included in the repository.** A fresh clone requires an appropriately licensed or authorized data source. Local databases, temporary audits, and credentials are intentionally excluded from Git tracking. NBA game data, photos, logos and third-party ratings may have usage restrictions.

## Run locally — v4.9.2 release branch

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run .\app_decision_v492.py
```

For a read-only deployment-entrypoint test, first provide an authorized snapshot at `deployment/nba_demo.duckdb`, then run:

```powershell
.\.venv\Scripts\python.exe -m streamlit run .\app_decision_cloud.py
```

**Streamlit Community Cloud deployment exists.** The deployed entrypoint is `app_decision_cloud.py`, branch `release/streamlit-cloud`, with dependencies from `requirements.txt`. Deploying the code without an approved dataset source will not populate the dashboard. Do not publicly redistribute NBA-derived records without appropriate rights.

## Roadmap

- [x] Player history, shooting charts, and roster exploration
- [x] Experimental 5v5 decision-support interface
- [x] Local shooting showcase integration test (3,680 matched events)
- [ ] Reproducible, authorized public demonstration dataset
- [x] Hosted Streamlit app deployed (authorized data must be supplied separately)
- [ ] Validated lineup impact model and monitored refreshes

## Responsible use

Independent research/portfolio project, not endorsed by the NBA, NBA teams, 2K Sports, ESPN or Streamlit. Results are not verified coaching instructions.

---

<div align="center">
**Developed by Jorge Montañez** · Sports Analytics · Data Science
</div>
