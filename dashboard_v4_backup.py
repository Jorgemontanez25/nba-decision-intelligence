"""NBA Decision Intelligence V5 dashboard patch: all-opponents, coverage, logos."""
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analysis import player_summary
from lineup_engine import initialize, matchup_rankings, data_quality
from team_branding import TEAMS, render_team_brand
from collect_shots import DDL as SHOT_DDL


# ==========================================
# NBA Shot Chart & Heatmap Configuration
# ==========================================

SHOT_CHART_HEIGHT = 720
HEATMAP_HEIGHT = 760
SHOT_MARKER_SIZE = 7

# NBA shot coordinates (LOC_X, LOC_Y)
COURT_X_RANGE = [-300, 300]
COURT_Y_RANGE = [-50, 350]


def choose_heatmap_bins(n_shots: int):
    if n_shots < 150:
        return 28, 24
    elif n_shots < 400:
        return 40, 32
    else:
        return 55, 42


st.set_page_config(page_title='NBA Decision Intelligence', layout='wide')
st.title('NBA Decision Intelligence — Player & Lineup Analysis')
db = st.sidebar.text_input('DuckDB file', 'nba_current.duckdb')
seasons = st.sidebar.multiselect(
    'Seasons', ['2022-23', '2023-24', '2024-25', '2025-26', '2026-27'],
    default=['2025-26'])
season_types = st.sidebar.multiselect(
    'Game types', ['Regular Season', 'Playoffs'], default=['Regular Season'])
team = st.sidebar.selectbox('Team', list(TEAMS), index=list(TEAMS).index('LAL'),
                            format_func=lambda t: TEAMS[t][0])
opp_options = ['ALL'] + [t for t in TEAMS if t != team]
opponent = st.sidebar.selectbox(
    'Opponent', opp_options, index=0,
    format_func=lambda t: 'All opponents' if t == 'ALL' else TEAMS[t][0])
min_minutes = st.sidebar.number_input('Minimum lineup minutes', min_value=0.0,
                                      value=100.0, step=25.0)

left, right = st.columns(2)
with left:
    render_team_brand(team)
with right:
    if opponent == 'ALL':
        st.subheader('All opponents')
    else:
        render_team_brand(opponent)

if not Path(db).exists():
    st.error('Database file not found. Run the collector first and verify its path.')
    st.stop()
if not seasons or not season_types:
    st.info('Choose at least one season and one game type.')
    st.stop()

# Open read/write only because lineup_engine.initialize() may create missing schema tables.
with duckdb.connect(db) as con:
    initialize(con)
    con.execute(SHOT_DDL)
    tab_players, tab_shots, tab_lineups, tab_coverage = st.tabs(
        ['Player profiles', 'Historical shooting', 'Historical 5v5 lineups', 'Data coverage'])
    selected_opponent = None if opponent == 'ALL' else opponent

    with tab_players:
        st.caption('Observed box-score statistics from imported games, NOT projected lineup values.')
        frames = []
        for typ in season_types:
            df = player_summary(con, seasons, team=team,
                                opponent=selected_opponent, season_type=typ)
            st.subheader(typ)
            if df.empty:
                st.info('No imported player games match these filters. Try All opponents or check Data coverage.')
            else:
                st.dataframe(df, width='stretch', hide_index=True)
                frames.append((typ, df))
        if frames:
            # Join each player's game data using the very same game filters as the profile tables.
            choices = {}
            for _, frame in frames:
                for row in frame.itertuples(index=False):
                    choices[f'{row.player_name} ({int(row.player_id)})'] = int(row.player_id)
            st.subheader('Individual player trends')
            label = st.selectbox('Select player', sorted(choices))
            player_id = choices[label]
            in_seasons = ','.join('?' for _ in seasons)
            in_types = ','.join('?' for _ in season_types)
            extra = '''AND EXISTS (
              SELECT 1 FROM team_games x WHERE x.game_id=p.game_id AND x.team_abbr=?)''' if selected_opponent else ''
            params = [player_id, team, *seasons, *season_types]
            if selected_opponent:
                params.append(selected_opponent)
            trend = con.execute(f'''
                SELECT p.game_date, p.game_id, p.season, p.season_type,
                       p.points, p.rebounds, p.assists, p.minutes
                FROM player_games p
                WHERE p.player_id=? AND p.team_abbr=?
                AND p.season IN ({in_seasons})
                AND p.season_type IN ({in_types})
                AND p.minutes > 0 {extra}
                ORDER BY p.game_date, p.game_id
            ''', params).df()
            if not trend.empty:
                st.caption(f'{len(trend)} observed games for {label}.')
                plot_data = trend[['game_date', 'game_id', 'points', 'rebounds', 'assists']].copy()
                plot_data['game_label'] = plot_data['game_date'].dt.strftime('%Y-%m-%d') if pd.api.types.is_datetime64_any_dtype(plot_data['game_date']) else plot_data['game_date'].astype(str).str[:10]
                plot_data['game_label'] = plot_data['game_label'] + ' (' + plot_data['game_id'].astype(str) + ')'
                long_data = plot_data.melt(id_vars=['game_label'], value_vars=['points','rebounds','assists'], var_name='Metric', value_name='Value')
                chart = px.line(long_data, x='game_label', y='Value', color='Metric', markers=True,
                                title=f'Per-game production — {label}', category_orders={'game_label': plot_data['game_label'].tolist()})
                chart.update_traces(marker={'size': 11})
                chart.update_layout(xaxis_title='Game', yaxis_title='Count', hovermode='x unified')
                st.plotly_chart(chart, width='stretch')
                if len(trend) == 1:
                    st.info('Only one game is imported for this player. Dots show that game; trends require multiple games.')
                st.dataframe(trend, width='stretch', hide_index=True)
                st.subheader('Shooting & box-score detail (imported games)')
                full = con.execute(f'''SELECT game_date, game_id, points, rebounds, assists,
                            steals, blocks, turnovers, minutes, fgm, fga, fg3m, fg3a,
                            ftm, fta, plus_minus, starter
                            FROM player_games p
                            WHERE p.player_id=? AND p.team_abbr=?
                            AND p.season IN ({in_seasons})
                            AND p.season_type IN ({in_types}) {extra}
                            ORDER BY p.game_date, p.game_id''', params).df()
                if not full.empty:
                    st.dataframe(full, width='stretch', hide_index=True)
                    totals = full[['fgm','fga','fg3m','fg3a','ftm','fta']].sum()
                    a,b,c=st.columns(3)
                    a.metric('FG%', f"{100*totals.fgm/totals.fga:.1f}%" if totals.fga else 'N/A')
                    b.metric('3PT%', f"{100*totals.fg3m/totals.fg3a:.1f}%" if totals.fg3a else 'N/A')
                    c.metric('FT%', f"{100*totals.ftm/totals.fta:.1f}%" if totals.fta else 'N/A')


    with tab_shots:
        st.subheader('Individual shot charts & shooting heatmaps')
        st.caption('Event-level shot attempts, not inferred from box scores. Location axes use the NBA provider coordinate system.')
        players = con.execute('SELECT DISTINCT player_id, player_name FROM player_games WHERE team_abbr=? ORDER BY player_name',[team]).df()
        if players.empty:
            st.info('Import player box scores first to populate player selection.')
        else:
            options = {f'{r.player_name} ({int(r.player_id)})':int(r.player_id) for r in players.itertuples(index=False)}
            pick = st.selectbox('Player for shot-location analysis',list(options),key='shot_player')
            pid = options[pick]
            placeholders=','.join(['?']*len(seasons))
            tplaceholders=','.join(['?']*len(season_types))
            shots=con.execute(f'''SELECT season, season_type, game_id, loc_x, loc_y,
                                  shot_distance, shot_made, shot_type, action_type
                                  FROM shot_events WHERE player_id=? AND team_id=? AND season IN ({placeholders})
                                  AND season_type IN ({tplaceholders})''',
                                  [pid,TEAMS[team][1],*seasons,*season_types]).df()
            if shots.empty:
                st.info(f'No shot events loaded for {pick} in the selected seasons. Run collect_shots.py with --player-id {pid} and the desired season.')
            # Only build charts when the selected player has shot events.
            else:
                shots = shots.copy()
                shots["loc_x"] = pd.to_numeric(shots["loc_x"], errors="coerce")
                shots["loc_y"] = pd.to_numeric(shots["loc_y"], errors="coerce")
                shots["shot_distance"] = pd.to_numeric(shots["shot_distance"], errors="coerce")
                shots["shot_made"] = pd.to_numeric(shots["shot_made"], errors="coerce")
                shots = shots.dropna(subset=["loc_x", "loc_y", "shot_made"])
                if shots.empty:
                    st.warning("Shot events were found, but their coordinates or results were invalid.")
                else:
                    shots["Result"] = shots["shot_made"].astype(int).map({1: "Made", 0: "Missed"})
                    shown = shots.loc[
                        shots["loc_x"].between(*COURT_X_RANGE) &
                        shots["loc_y"].between(*COURT_Y_RANGE)
                    ].copy()
                    counts = len(shots)
                    a, b, c = st.columns(3)
                    a.metric("Recorded attempts", f"{counts:,}")
                    b.metric("FG% (recorded)", f"{shots['shot_made'].mean() * 100:.1f}%")
                    c.metric("Within displayed court", f"{len(shown):,}")
                    if len(shown) < counts:
                        st.warning(f"{counts - len(shown)} shot(s) outside the chosen court bounds are not plotted; check raw provider coordinates.")
                    chart_tab, heat_tab, distance_tab = st.tabs(
                        ["Shot Chart", "Shooting Heatmap", "Shooting by Distance"]
                    )
                    with chart_tab:
                        if shown.empty:
                            st.info("No valid shots within the selected coordinate bounds.")
                        else:
                            fig = px.scatter(
                                shown, x="loc_x", y="loc_y", color="Result", symbol="Result",
                                category_orders={"Result": ["Made", "Missed"]},
                                hover_data=["season", "game_id", "shot_distance", "shot_type", "action_type"],
                                title=f"Shot locations — {pick}", opacity=0.75,
                            )
                            fig.update_traces(marker=dict(size=SHOT_MARKER_SIZE))
                            fig.update_layout(
                                height=SHOT_CHART_HEIGHT, margin=dict(l=30, r=30, t=65, b=30),
                                legend_title_text="Shot result",
                            )
                            fig.update_xaxes(range=COURT_X_RANGE, title="NBA LOC_X")
                            fig.update_yaxes(range=COURT_Y_RANGE, title="NBA LOC_Y", scaleanchor="x", scaleratio=1)
                            st.plotly_chart(fig, width="stretch")
                    with heat_tab:
                        if shown.empty:
                            st.info("No valid shots within the selected coordinate bounds.")
                        else:
                            bins_x, bins_y = choose_heatmap_bins(len(shown))
                            heat = go.Figure(go.Histogram2d(
                                x=shown["loc_x"], y=shown["loc_y"],
                                xbins=dict(start=COURT_X_RANGE[0], end=COURT_X_RANGE[1],
                                           size=(COURT_X_RANGE[1] - COURT_X_RANGE[0]) / bins_x),
                                ybins=dict(start=COURT_Y_RANGE[0], end=COURT_Y_RANGE[1],
                                           size=(COURT_Y_RANGE[1] - COURT_Y_RANGE[0]) / bins_y),
                                colorscale="Viridis", colorbar=dict(title="Attempts"),
                            ))
                            heat.update_layout(
                                title=f"Shot attempt density — {pick}",
                                height=HEATMAP_HEIGHT, margin=dict(l=30, r=30, t=65, b=30),
                            )
                            heat.update_xaxes(range=COURT_X_RANGE, title="NBA LOC_X")
                            heat.update_yaxes(range=COURT_Y_RANGE, title="NBA LOC_Y", scaleanchor="x", scaleratio=1)
                            st.plotly_chart(heat, width="stretch")
                            st.caption("Density represents attempt volume, not shot-making efficiency.")
                    with distance_tab:
                        dist = shots.dropna(subset=["shot_distance"]).copy()
                        dist["distance_band"] = pd.cut(
                            dist["shot_distance"], bins=[0, 5, 10, 15, 20, 25, float("inf")],
                            labels=["0-4", "5-9", "10-14", "15-19", "20-24", "25+"], right=False,
                        )
                        summary = dist.groupby("distance_band", observed=True).agg(
                            attempts=("shot_made", "count"), makes=("shot_made", "sum")
                        ).reset_index()
                        if summary.empty:
                            st.info("No shot distance information is available.")
                        else:
                            summary["fg_pct"] = 100 * summary["makes"] / summary["attempts"]
                            chart = px.bar(
                                summary, x="distance_band", y="fg_pct", text="attempts",
                                title="FG% by shot distance",
                                labels={"distance_band": "Distance (feet)", "fg_pct": "FG%"},
                            )
                            chart.update_layout(height=550, yaxis_range=[0, 100])
                            st.plotly_chart(chart, width="stretch")
                            st.dataframe(summary, width="stretch", hide_index=True)
                            st.caption("Numbers above bars indicate attempts. Small samples can be misleading.")


    with tab_lineups:
        if opponent == 'ALL':
            st.info('Choose a specific opponent to view historical 5v5 matchups. '
                    'This section requires validated play-by-play stints.')
        else:
            rankings = matchup_rankings(con, team, opponent, seasons,
                                       season_types, min_minutes)
            if rankings.empty:
                st.warning('No verified historical 5v5 combinations match the filters and minimum minutes. '
                           'This is not a starting-five recommendation.')
            else:
                st.dataframe(rankings, width='stretch', hide_index=True)
            st.caption('Observed historical lineup results only; live availability and predictive optimization are not implemented.')

    with tab_coverage:
        st.subheader('Imported games by season and matchup')
        available = con.execute('''
            SELECT a.season, a.season_type, a.team_abbr AS team,
                   b.team_abbr AS opponent, COUNT(DISTINCT a.game_id) AS games
            FROM team_games a
            JOIN team_games b ON b.game_id=a.game_id AND b.team_abbr <> a.team_abbr
            GROUP BY 1,2,3,4 ORDER BY 1,2,3,4
        ''').df()
        if available.empty:
            st.info('No game metadata has been imported yet.')
        else:
            st.dataframe(available, width='stretch', hide_index=True)
            st.caption('Coverage represents imported games, not complete league-season availability.')
        if opponent != 'ALL':
            st.subheader('Validated matchup-stint coverage')
            st.dataframe(data_quality(con, team, opponent), width='stretch', hide_index=True)
        st.caption('Missing games are not downloaded automatically by this dashboard. Run the collector to expand coverage.')