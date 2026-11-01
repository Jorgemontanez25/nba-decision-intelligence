<div align="center">

# 🏀 NBA Decision Intelligence
### Player & Lineup Analysis · Basketball Decision Support

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-Dashboard-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![DuckDB](https://img.shields.io/badge/DuckDB-Analytics-F5C518)](https://duckdb.org/)
![Status](https://img.shields.io/badge/Status-Research%20prototype-56627A)

*A multi-season NBA research dashboard combining player history, shot-location visualization, roster exploration, and experimental 5-on-5 matchup recommendations.*

</div>

<details>
<summary><strong>How the platform works — data architecture</strong></summary>

![Project architecture](assets/architecture.svg)

</details>

## Overview

NBA Decision Intelligence is an independently developed **sports analytics portfolio project** built with Python, Streamlit, and DuckDB. It aims to help analysts explore player production across franchises and seasons, visualize on-court shooting profiles, and compare hypothetical five-player units against opponents.

**Supported analysis window:** **2023–24, 2024–25, 2025–26, and 2026–27**, subject to local data availability. Roster snapshots are not live injury or availability feeds.

> **Research status:** The 5v5 rankings are experimental, based primarily on historical box-score proxies. The lineup-reconstruction audits are internal consistency checks, **not independent certification** of historical stints, matchup impact, or real-time substitution recommendations.

## Explore the dashboard

### Player Analysis

Unified player profiles combine career box scores, performance trends and a **2K27-inspired roster card** with an externally sourced OVR where available. Player records are matched by NBA player ID across franchises.

![NBA Decision Intelligence player analysis](assets/player-analysis.png)

### 5v5 Decision Center

Compare hypothetical five-player units with a full-court portrait visualization. The relative indexes and radar graphics are **experimental box-score heuristics**, not verified matchup predictions.

![5v5 lineup recommendations and full-court formation](assets/decision-center.png)

<details>
<summary><strong>Explore more visuals — shooting, team comparison, and roster</strong></summary>

#### Shot density heatmap

Brighter regions indicate **more shot attempts**, not higher shooting accuracy.

![Historical shooting density heatmap](assets/shooting-heatmap.png)

#### Shot location chart

Makes and misses plotted on the basketball court for available player shot events.

![Historical player shot chart](assets/shooting-shot-chart.png)

#### Team offense and defense comparisons

Descriptive team-level comparisons using box-score production and defensive-activity proxies.

![Offense and defense comparison between teams](assets/team-comparison.png)

#### 2026–27 Roster Manager

Explore roster snapshots and sortable player statistics (minutes, points, rebounds, assists). The roster is not a live availability or injury feed.

![Roster manager](assets/roster-manager.png)

</details>

## Tech stack

| Layer | Technology | Purpose |
|---|---|---|
| Application | Streamlit | Interactive filters, navigation, and dashboard |
| Data and ETL | Python, Pandas, NumPy | Collection, cleaning, and statistical aggregation |
| Analytics storage | DuckDB | Local historical box scores and shot events |
| Visualization | Plotly | Game trends, shooting charts, comparison graphics |
| Reference ratings | Local NBA 2K27 ratings cache | Sourced OVR display; not a predictive feature by default |

## Data model and limitations

The local database currently uses `player_games`, `team_games`, and `shot_events` tables. Player matching uses NBA player IDs, allowing historical records from previous franchises to contribute to player-level analysis.

- The **box-score** window is broader than complete shot-location coverage.
- Current-season refresh is driven by local scripts; a fully managed 24/7 agent is not yet deployed.
- The lineup recommendation engine ranks **hypothetical** units and does not currently provide a certified live NBA feed.
- Player headshots, team logos, and 2K27 ratings are third-party or league assets and are not owned by this project.
- Local DuckDB files, credentials, API keys, and generated research outputs are **not included** in a normal source-code deployment.

## Run locally

> The complete app requires a compatible local DuckDB database and supporting source modules. A fresh clone is **not yet a fully reproducible, populated demo**. Sample/demo data and deployment configuration are on the roadmap.

```powershell
python -m venv .venv
```

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

```powershell
.\.venv\Scripts\python.exe -m streamlit run .\app_decision_v492.py
```

The primary local entry point in the latest tested project iteration is `app_decision_v491.py`. When `requirements.txt` is not yet synchronized with the active environment, export and review dependencies before deployment.

## Project structure (target)

```text
nba-decision-intelligence/
├── assets/                      # Documentation screenshots and diagrams
├── app_decision_v491.py         # Current Streamlit entry point
├── decision_center_v481.py      # Candidate lineup visualizations
├── v47_visuals.py               # Profile and graphics components
├── analysis.py                  # Analytics queries and transformations
├── lineup_engine.py             # Lineup analysis helpers
├── roster_2026_27.py            # Local roster utilities
├── team_branding.py             # Team branding helpers
├── requirements.txt             # App dependencies
├── README.md
└── .gitignore
```

*The public repository may temporarily contain additional legacy modules and validation scripts. This tree describes the intended production-focused organization, not a verified complete inventory.*

## Development roadmap

- [x] Unified player analysis and career trends
- [x] 5v5 recommendation prototype with court visualization
- [x] Current-season roster exploration
- [ ] Backfill missing historical shot events
- [ ] Improve matchup-adjusted lineup evaluation using verified lineup data
- [ ] Automated daily refresh with retries and monitoring
- [ ] Reproducible sample database and deployment guide
- [ ] Hosted Streamlit demo

## Responsible use

This project is **not affiliated with or endorsed by the NBA, NBA teams, 2K Sports, ESPN, or Streamlit**. It is an educational/research portfolio application. Displayed player ratings are sourced when available; matchup recommendations are experimental and should not be treated as verified coaching instructions.

---

<div align="center">

**Developed by Jorge Montañez** · Sports Analytics · Data Science · Decision Intelligence

</div>
