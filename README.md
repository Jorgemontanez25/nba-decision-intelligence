# NBA Decision Intelligence — Player & Lineup Analysis

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Streamlit](https://img.shields.io/badge/Streamlit-App-red)
![DuckDB](https://img.shields.io/badge/DuckDB-Analytics-gold)
![Status](https://img.shields.io/badge/Status-Active-success)
![Sports Analytics](https://img.shields.io/badge/Focus-Sports%20Analytics-orange)

A local **NBA analytics platform** built with **Streamlit**, **DuckDB**, and custom data pipelines to support:

- **player career analysis**
- **historical shooting analysis**
- **5v5 decision support**
- **roster exploration**
- **daily/current-season refresh workflows**

The goal of this project is to create an interactive basketball decision-support environment that combines **box score history**, **shot-location analysis**, **roster context**, and **lineup recommendations** into one application.

---

## Project Overview

This application was designed as an evolving **NBA Decision Intelligence** tool focused on both:

1. **Player-level analysis**
2. **Lineup / matchup-level decision support**

It currently includes:

- Unified **Player Analysis** view
- **Historical shooting** and shot-chart support
- **5v5 Decision Center** with recommended formations
- **2026–27 Roster Manager**
- Data coverage / health visibility
- Support for multiple historical seasons stored locally in DuckDB

---

## Main Features

### 1) Unified Player Analysis
Analyze one player across all locally collected seasons.

Includes:
- player portrait
- sourced **NBA 2K27 OVR**
- role tag (e.g. rotation, star, developing)
- career sample overview
- multi-season production
- game logs
- season trend visibility

![Player Analysis](assets/player_analysis.png)

---

### 2) Historical Shooting
Shot-location analysis based on collected shot coordinates.

Includes:
- shot chart
- density/heatmap support
- efficiency context
- season-aware shooting coverage
- warning states when box scores exist but shot events are missing

![Historical Shooting](assets/historical_shooting.png)

---

### 3) 5v5 Decision Center
A decision-support page that compares team context and recommended candidate lineups.

Includes:
- top candidate lineups
- interactive selected-lineup visualization
- offense/defense radar comparisons
- full-court lineup visual
- player portraits on the court

![5v5 Decision Center](assets/decision_center.png)

---

### 4) 2026–27 Roster Manager
An ESPN-style roster exploration page for the selected team.

Includes:
- sortable roster view
- player portraits
- minutes / points / rebounds / assists
- cleaner roster UX for quick review

![Roster Manager](assets/roster_manager.png)

---

## Tech Stack

- **Python**
- **Streamlit**
- **DuckDB**
- **Pandas**
- **NumPy**
- **Plotly**

---

## Data Notes

This app depends on locally collected NBA data.

Current architecture uses:
- **player_games**
- **team_games**
- **shot_events**
- locally stored roster snapshots
- locally sourced **NBA 2K27 OVR** cache

### Important
- Box score data and shot-location data are different layers.
- A season may appear in player history even if full shot coordinates for that season have not yet been collected.
- Current-season data is intended to be refreshed frequently/daily.

---

## Project Structure

```text
.
├── assets/
├── app_decision_v491.py
├── decision_center_v481.py
├── v47_visuals.py
├── analysis.py
├── lineup_engine.py
├── roster_2026_27.py
├── collect_shots.py
├── team_branding.py
├── README.md
└── requirements.txt
