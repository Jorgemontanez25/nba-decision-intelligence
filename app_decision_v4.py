"""NBA Decision Intelligence: player analysis, shot charts, density heatmaps, zone efficiency, and lineups."""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analysis import player_summary
from lineup_engine import initialize, matchup_rankings, data_quality
from team_branding import TEAMS, render_team_brand
from collect_shots import DDL as SHOT_DDL
from decision_center_v4 import render_decision_center
from roster_2026_27 import roster_for_team


# ==========================================
# NBA Shot Chart & Heatmap Configuration
# ==========================================

SHOT_CHART_HEIGHT = 780
HEATMAP_HEIGHT = 820
ZONE_MAP_HEIGHT = 760
DISTANCE_CHART_HEIGHT = 520
SHOT_MARKER_SIZE = 7

# NBA shot coordinates (LOC_X, LOC_Y)
COURT_X_RANGE = [-250, 250]
COURT_Y_RANGE = [-55, 360]
ZONE_ORDER = [
    'Restricted / rim',
    'Paint (non-rim)',
    'Mid-range 2',
    'Left corner 3',
    'Right corner 3',
    'Above-the-break 3',
]
ZONE_SHORT = {
    'Restricted / rim': 'Rim',
    'Paint (non-rim)': 'Paint',
    'Mid-range 2': 'Mid',
    'Left corner 3': 'L C3',
    'Right corner 3': 'R C3',
    'Above-the-break 3': 'ATB 3',
}
ZONE_POSITIONS = {
    'Restricted / rim': (0, 24),
    'Paint (non-rim)': (0, 90),
    'Mid-range 2': (0, 185),
    'Left corner 3': (-215, 40),
    'Right corner 3': (215, 40),
    'Above-the-break 3': (0, 280),
}


def choose_heatmap_bins(n_shots: int):
    """Choose a sensible spatial grid for the available sample."""
    return (45, 40) if n_shots < 200 else (65, 55) if n_shots < 800 else (75, 60)



def gaussian_blur(array, sigma=1.5):
    """Smooth a small 2D array with NumPy only (no native Cairo/SciPy dependency)."""
    radius = max(1, int(np.ceil(3 * sigma)))
    xs = np.arange(-radius, radius + 1, dtype=float)
    kernel = np.exp(-0.5 * (xs / sigma) ** 2)
    kernel /= kernel.sum()
    padded = np.pad(array, ((radius, radius), (radius, radius)), mode='constant')
    horiz = np.apply_along_axis(lambda v: np.convolve(v, kernel, mode='valid'), 1, padded)
    smooth = np.apply_along_axis(lambda v: np.convolve(v, kernel, mode='valid'), 0, horiz)
    return smooth



def spatial_shot_maps(frame, nx, ny, sigma=1.6):
    """Return smoothed attempts and makes on an identical, fixed court grid."""
    xedges = np.linspace(*COURT_X_RANGE, nx + 1)
    yedges = np.linspace(*COURT_Y_RANGE, ny + 1)
    xy = [frame['loc_x'].to_numpy(), frame['loc_y'].to_numpy()]
    counts, _, _ = np.histogram2d(*xy, bins=[xedges, yedges])
    makes, _, _ = np.histogram2d(
        *xy, bins=[xedges, yedges], weights=frame['shot_made'].to_numpy()
    )
    return (
        (xedges[:-1] + xedges[1:]) / 2,
        (yedges[:-1] + yedges[1:]) / 2,
        gaussian_blur(counts, sigma),
        gaussian_blur(makes, sigma),
    )



def shot_zone(row):
    """Mutually exclusive approximate NBA shot zones using source shot type."""
    x, y = float(row.loc_x), float(row.loc_y)
    r = np.hypot(x, y)
    shot_type = str(row.shot_type).upper()
    is_three = '3PT' in shot_type or '3-POINT' in shot_type or shot_type.strip().startswith('3')
    if is_three:
        if abs(x) >= 220 and y <= 92.5:
            return 'Left corner 3' if x < 0 else 'Right corner 3'
        return 'Above-the-break 3'
    if r < 40:
        return 'Restricted / rim'
    if abs(x) <= 80 and y <= 137.5:
        return 'Paint (non-rim)'
    return 'Mid-range 2'



def summarize_zones(frame: pd.DataFrame) -> pd.DataFrame:
    zone_frame = frame.copy()
    zone_frame['zone'] = zone_frame.apply(shot_zone, axis=1)
    zone_frame['shot_value'] = np.where(
        zone_frame['shot_type'].astype(str).str.upper().str.contains('3PT|3-POINT|^3', regex=True),
        3,
        2,
    )
    zone_frame['made_points'] = zone_frame['shot_made'] * zone_frame['shot_value']
    zone_frame['made_three'] = zone_frame['shot_made'] * (zone_frame['shot_value'] == 3).astype(int)

    summary = zone_frame.groupby('zone', as_index=False).agg(
        attempts=('shot_made', 'size'),
        makes=('shot_made', 'sum'),
        points=('made_points', 'sum'),
        made_threes=('made_three', 'sum'),
        shot_value=('shot_value', 'max'),
    )
    summary['misses'] = summary['attempts'] - summary['makes']
    summary['fg_pct'] = 100 * summary['makes'] / summary['attempts']
    summary['shot_share_pct'] = 100 * summary['attempts'] / len(zone_frame)
    summary['pps'] = summary['points'] / summary['attempts']
    summary['efg_pct'] = 100 * (summary['makes'] + 0.5 * summary['made_threes']) / summary['attempts']
    summary['zone'] = pd.Categorical(summary['zone'], categories=ZONE_ORDER, ordered=True)
    summary = summary.sort_values('zone').reset_index(drop=True)
    return summary



def add_half_court(fig, *, opacity=0.85):
    """Draw a scaled NBA half-court in NBA LOC_X/LOC_Y units (tenths of feet)."""
    style = dict(color=f"rgba(220,230,240,{opacity})", width=2)
    # Basket and backboard
    fig.add_shape(type='circle', x0=-7.5, x1=7.5, y0=-7.5, y1=7.5, line=style)
    fig.add_shape(type='line', x0=-30, x1=30, y0=-12.5, y1=-12.5, line=style)
    # Court edges and lane (NBA coordinates relative to hoop)
    fig.add_shape(type='rect', x0=-250, x1=250, y0=-52.5, y1=417.5, line=style)
    fig.add_shape(type='rect', x0=-80, x1=80, y0=-52.5, y1=137.5, line=style)
    # Free-throw circle and restricted semicircle
    for radius, min_angle, max_angle in [(60, 0, 180), (40, 0, 180)]:
        center_y = 137.5 if radius == 60 else 0
        angles = np.linspace(np.deg2rad(min_angle), np.deg2rad(max_angle), 100)
        fig.add_trace(go.Scatter(
            x=radius * np.cos(angles),
            y=center_y + radius * np.sin(angles),
            mode='lines', line=style, hoverinfo='skip', showlegend=False,
            name='Court'
        ))
    arc_y = float(np.sqrt(237.5**2 - 220**2))
    for x in (-220, 220):
        fig.add_shape(type='line', x0=x, x1=x, y0=-52.5, y1=arc_y, line=style)
    theta = np.linspace(np.arccos(220 / 237.5), np.pi - np.arccos(220 / 237.5), 180)
    fig.add_trace(go.Scatter(
        x=237.5 * np.cos(theta), y=237.5 * np.sin(theta),
        mode='lines', line=style, hoverinfo='skip', showlegend=False,
        name='Three-point arc'
    ))
    return fig



def style_shot_plot(fig, *, height, legend_title='Result'):
    fig.update_layout(
        height=height,
        margin=dict(l=15, r=15, t=60, b=35),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        legend_title_text=legend_title,
    )
    fig.update_xaxes(range=COURT_X_RANGE, title=None, showgrid=False, zeroline=False)
    fig.update_yaxes(range=COURT_Y_RANGE, title=None, showgrid=False,
                     zeroline=False, scaleanchor='x', scaleratio=1)
    return fig



def zone_efficiency_figure(summary: pd.DataFrame, player_label: str, min_attempts: int = 10):
    """A filled, court-shaped efficiency map, not circles placed over the court.

    Each point of the plotting grid is classified by NBA-style court geometry.
    Observed zone FG% is assigned to the corresponding *entire* region.
    Regions with no (or few) attempts remain neutral, not falsely hot/cold.
    """
    zone_stats = {str(r.zone): r for r in summary.itertuples(index=False)}
    xs = np.linspace(COURT_X_RANGE[0], COURT_X_RANGE[1], 351)
    ys = np.linspace(-52.5, COURT_Y_RANGE[1], 291)
    X, Y = np.meshgrid(xs, ys)
    R = np.hypot(X, Y)
    # Court-geometric approximation; underlying zone totals use provider shot type.
    corner = (np.abs(X) >= 220) & (Y <= np.sqrt(237.5**2 - 220**2))
    three = (R >= 237.5) | corner
    rim = (R < 40) & ~three
    paint = (np.abs(X) <= 80) & (Y <= 137.5) & ~rim & ~three
    masks = {
        'Restricted / rim': rim,
        'Paint (non-rim)': paint,
        'Mid-range 2': ~(rim | paint | three),
        'Left corner 3': corner & (X < 0),
        'Right corner 3': corner & (X >= 0),
        'Above-the-break 3': three & ~corner,
    }
    z = np.full(X.shape, np.nan)
    n_zone = np.full(X.shape, np.nan)
    for zone, mask in masks.items():
        item = zone_stats.get(zone)
        if item is None:
            continue
        n = int(item.attempts)
        n_zone[mask] = n
        if n >= min_attempts:
            z[mask] = float(item.fg_pct)

    fig = go.Figure()
    # Neutral base preserves the full zone layout, including insufficient-data areas.
    fig.add_shape(type='rect', x0=-250, x1=250, y0=-52.5, y1=360,
                  line=dict(width=0), fillcolor='rgba(125,135,150,0.21)', layer='below')
    fig.add_trace(go.Heatmap(
        x=xs, y=ys, z=z, zmin=20, zmax=80, zsmooth=False,
        colorscale='RdYlGn', opacity=0.9,
        colorbar=dict(title='Zone FG%'),
        hovertemplate='FG%: %{z:.1f}%<extra></extra>',
        showscale=True,
    ))
    add_half_court(fig, opacity=0.98)
    labels = {
        'Restricted / rim': (0, 24, 'Rim'),
        'Paint (non-rim)': (0, 92, 'Paint'),
        'Mid-range 2': (-140, 155, 'Mid-range'),
        'Left corner 3': (-232, 53, 'Corner 3'),
        'Right corner 3': (232, 53, 'Corner 3'),
        'Above-the-break 3': (0, 293, 'Above-break 3'),
    }
    # Add a second Mid-range label on the right for an intuitive court layout.
    for zone, (x, y, name) in labels.items():
        item = zone_stats.get(zone)
        if item is None:
            label = f'{name}<br>No shots'
        elif int(item.attempts) < min_attempts:
            label = f'{name}<br>{int(item.attempts)} att<br>Low sample'
        else:
            label = f'{name}<br>{float(item.fg_pct):.1f}%<br>{int(item.attempts)} FGA'
        fig.add_annotation(x=x, y=y, text=label, showarrow=False,
                           font=dict(color='white', size=11), align='center',
                           bgcolor='rgba(0,0,0,0.28)', borderpad=2)
    if 'Mid-range 2' in labels:
        item = zone_stats.get('Mid-range 2')
        if item is not None and int(item.attempts) >= min_attempts:
            text = f'Mid-range<br>{float(item.fg_pct):.1f}%<br>{int(item.attempts)} FGA'
        elif item is not None:
            text = f'Mid-range<br>{int(item.attempts)} att<br>Low sample'
        else:
            text = 'Mid-range<br>No shots'
        fig.add_annotation(x=140, y=155, text=text, showarrow=False,
                           font=dict(color='white', size=11), align='center',
                           bgcolor='rgba(0,0,0,0.28)', borderpad=2)
    style_shot_plot(fig, height=ZONE_MAP_HEIGHT)
    fig.update_layout(title=f'Filled shooting zones — {player_label}',
                      margin=dict(l=20, r=20, t=65, b=30))
    return fig


st.set_page_config(page_title='NBA Decision Intelligence', layout='wide')
st.title('NBA Decision Intelligence — Player & Lineup Analysis')
db = st.sidebar.text_input('DuckDB file', 'nba_current.duckdb')
seasons = st.sidebar.multiselect(
    'Seasons', ['2022-23', '2023-24', '2024-25', '2025-26', '2026-27'],
    default=['2026-27'])
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

with duckdb.connect(db) as con:
    initialize(con)
    con.execute(SHOT_DDL)
    tab_players, tab_shots, tab_decision, tab_roster, tab_coverage = st.tabs(
        ['Player profiles', 'Historical shooting', '5v5 Decision Center', '2026–27 Rosters', 'Data coverage'])
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
            choices = {}
            for _, frame in frames:
                for row in frame.itertuples(index=False):
                    choices[f'{row.player_name} ({int(row.player_id)})'] = int(row.player_id)
            st.subheader('Individual player trends')
            label = st.selectbox('Select player', sorted(choices))
            player_id = choices[label]
            st.markdown('**Player portrait**')
            st.image(f'https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png',width=150)
            st.caption('Headshot from NBA CDN; availability varies by player.')
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
                if pd.api.types.is_datetime64_any_dtype(plot_data['game_date']):
                    plot_data['game_label'] = plot_data['game_date'].dt.strftime('%Y-%m-%d')
                else:
                    plot_data['game_label'] = plot_data['game_date'].astype(str).str[:10]
                plot_data['game_label'] = plot_data['game_label'] + ' (' + plot_data['game_id'].astype(str) + ')'
                long_data = plot_data.melt(
                    id_vars=['game_label'],
                    value_vars=['points', 'rebounds', 'assists'],
                    var_name='Metric', value_name='Value')
                chart = px.line(
                    long_data, x='game_label', y='Value', color='Metric', markers=True,
                    title=f'Per-game production — {label}',
                    category_orders={'game_label': plot_data['game_label'].tolist()}
                )
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
                    totals = full[['fgm', 'fga', 'fg3m', 'fg3a', 'ftm', 'fta']].sum()
                    a, b, c = st.columns(3)
                    a.metric('FG%', f"{100*totals.fgm/totals.fga:.1f}%" if totals.fga else 'N/A')
                    b.metric('3PT%', f"{100*totals.fg3m/totals.fg3a:.1f}%" if totals.fg3a else 'N/A')
                    c.metric('FT%', f"{100*totals.ftm/totals.fta:.1f}%" if totals.fta else 'N/A')

    with tab_shots:
        st.subheader('Individual shot charts & shooting heatmaps')
        st.caption('Actual collected shot attempts. Density shows volume, while the zone map summarizes efficiency more reliably than a pixel-level FG% map.')
        players = con.execute(
            'SELECT DISTINCT player_id, player_name FROM player_games '
            'WHERE team_abbr=? ORDER BY player_name', [team]
        ).df()
        if players.empty:
            st.info('Import player box scores first to populate player selection.')
        else:
            options = {
                f'{r.player_name} ({int(r.player_id)})': int(r.player_id)
                for r in players.itertuples(index=False)
            }
            pick = st.selectbox('Player for shot-location analysis', list(options), key='shot_player')
            pid = options[pick]
            st.image(f'https://cdn.nba.com/headshots/nba/latest/1040x760/{pid}.png',width=130)
            placeholders = ','.join('?' for _ in seasons)
            tplaceholders = ','.join('?' for _ in season_types)
            opponent_filter = '''AND EXISTS (
                SELECT 1 FROM team_games opponent
                WHERE opponent.game_id=s.game_id AND opponent.team_abbr=?
            )''' if selected_opponent else ''
            params = [pid, TEAMS[team][1], *seasons, *season_types]
            if selected_opponent:
                params.append(selected_opponent)
            shots = con.execute(f'''
                SELECT s.season, s.season_type, s.game_id,
                       s.loc_x, s.loc_y, s.shot_distance,
                       s.shot_made, s.shot_type, s.action_type
                FROM shot_events s
                WHERE s.player_id=? AND s.team_id=?
                  AND s.season IN ({placeholders})
                  AND s.season_type IN ({tplaceholders})
                  {opponent_filter}
            ''', params).df()
            if shots.empty:
                st.info(
                    f'No shot events loaded for {pick} with the selected filters. '
                    f'Run collect_shots.py --player-id {pid} --season YYYY-YY '
                    'for the desired season, or choose All opponents.'
                )
            else:
                shots = shots.copy()
                for col in ('loc_x', 'loc_y', 'shot_distance', 'shot_made'):
                    shots[col] = pd.to_numeric(shots[col], errors='coerce')
                shots = shots.dropna(subset=['loc_x', 'loc_y', 'shot_made'])
                if shots.empty:
                    st.warning('Shot records exist, but none have valid coordinates and results.')
                else:
                    shots['Result'] = shots['shot_made'].astype(int).map({1: 'Made', 0: 'Missed'})
                    visible = shots[
                        shots['loc_x'].between(*COURT_X_RANGE)
                        & shots['loc_y'].between(*COURT_Y_RANGE)
                    ].copy()
                    a, b, c = st.columns(3)
                    a.metric('Recorded attempts', f'{len(shots):,}')
                    b.metric('FG% (recorded)', f"{100 * shots['shot_made'].mean():.1f}%")
                    c.metric('Shots within displayed court', f'{len(visible):,}')
                    if len(visible) != len(shots):
                        st.warning(
                            f'{len(shots)-len(visible)} shot(s) outside plotted limits. '
                            'Review provider coordinate conventions.'
                        )
                    if visible.empty:
                        st.info('No shot coordinates fall inside the court view.')
                    else:
                        st.subheader(f'Shot chart — {pick}')
                        scatter = px.scatter(
                            visible, x='loc_x', y='loc_y', color='Result', symbol='Result',
                            category_orders={'Result': ['Made', 'Missed']},
                            hover_data=['season', 'game_id', 'shot_distance', 'shot_type', 'action_type'],
                            opacity=0.78,
                        )
                        scatter.update_traces(marker=dict(size=SHOT_MARKER_SIZE))
                        add_half_court(scatter)
                        style_shot_plot(scatter, height=SHOT_CHART_HEIGHT)
                        st.plotly_chart(scatter, width='stretch', key='shot_court_plot')

                        st.subheader(f'Shot density heatmap — {pick}')
                        st.caption('Smoothed shot volume. Brighter areas represent more attempts, not higher accuracy.')
                        smoothing = st.slider(
                            'Heatmap smoothing', min_value=0.8, max_value=3.0,
                            value=1.6, step=0.2, key='shot_heat_sigma',
                            help='Larger values blend nearby shots more strongly.'
                        )
                        nbx, nby = choose_heatmap_bins(len(visible))
                        xcenters, ycenters, dense, _ = spatial_shot_maps(
                            visible, nbx, nby, sigma=smoothing
                        )
                        heat = go.Figure(go.Heatmap(
                            x=xcenters, y=ycenters, z=dense.T,
                            colorscale='Turbo', zsmooth='best',
                            colorbar=dict(title='Smoothed attempts'),
                            hovertemplate='X: %{x:.0f}<br>Y: %{y:.0f}<br>'
                                          'Smoothed attempts: %{z:.1f}<extra></extra>',
                        ))
                        add_half_court(heat)
                        style_shot_plot(heat, height=HEATMAP_HEIGHT, legend_title='Attempts')
                        st.plotly_chart(heat, width='stretch', key='shot_density_plot')
                        st.caption('Density represents smoothed shot volume per spatial area, not FG%.')

                        st.subheader(f'Zone-based efficiency map — {pick}')
                        st.caption('Entire court regions are colored by observed zone FG%. Gray regions lack enough shot attempts. Zone layout is approximate.')
                        min_zone_attempts = st.slider('Minimum attempts for a colored zone', min_value=1, max_value=50, value=10, step=1, key='zone_min_attempts')
                        zone_summary = summarize_zones(visible)
                        zone_fig = zone_efficiency_figure(zone_summary, pick, min_attempts=min_zone_attempts)
                        st.plotly_chart(zone_fig, width='stretch', key='zone_efficiency_plot')

                        zone_table = zone_summary.copy()
                        zone_table['zone'] = zone_table['zone'].astype(str)
                        zone_table['fg_pct'] = zone_table['fg_pct'].round(1)
                        zone_table['shot_share_pct'] = zone_table['shot_share_pct'].round(1)
                        zone_table['pps'] = zone_table['pps'].round(2)
                        zone_table['efg_pct'] = zone_table['efg_pct'].round(1)
                        zone_table = zone_table[[
                            'zone', 'attempts', 'makes', 'misses',
                            'fg_pct', 'shot_share_pct', 'pps', 'efg_pct'
                        ]]
                        st.dataframe(zone_table, width='stretch', hide_index=True)
                        st.caption('Zone boundaries are approximate. Colors show zone-level observed FG%, not league-relative efficiency or predictions. Court shapes are visual approximations; source 2PT/3PT data governs the table. Low samples require caution.')

                    st.subheader('Shooting by distance')
                    dist = shots.dropna(subset=['shot_distance']).copy()
                    dist['distance_band'] = pd.cut(
                        dist['shot_distance'],
                        bins=[0, 5, 10, 15, 20, 25, float('inf')],
                        labels=['0–4', '5–9', '10–14', '15–19', '20–24', '25+'],
                        right=False,
                    )
                    summary = dist.groupby('distance_band', observed=True).agg(
                        attempts=('shot_made', 'count'), makes=('shot_made', 'sum')
                    ).reset_index()
                    if summary.empty:
                        st.info('No shot-distance data is available.')
                    else:
                        summary['fg_pct'] = 100 * summary['makes'] / summary['attempts']
                        fig_dist = px.bar(
                            summary, x='distance_band', y='fg_pct', text='attempts',
                            title='Field goal percentage by distance',
                            labels={'distance_band': 'Distance (feet)', 'fg_pct': 'FG%'},
                        )
                        fig_dist.update_layout(height=DISTANCE_CHART_HEIGHT, yaxis_range=[0, 100])
                        st.plotly_chart(fig_dist, width='stretch')
                        st.dataframe(summary, width='stretch', hide_index=True)
                        st.caption('Bar labels show attempts. Small samples may be misleading.')

    with tab_decision:
        render_decision_center(con, team, opponent, seasons, season_types)

    with tab_roster:
        st.subheader('2026–27 roster snapshots')
        st.caption('Official NBA CommonTeamRoster snapshots downloaded on demand. These are not a live transaction, injury, or availability feed.')
        snapshot=roster_for_team(team)
        if snapshot.empty:
            st.info('No 2026–27 roster snapshot for this team yet. Run roster_2026_27.py from PowerShell, then refresh the app.')
        else:
            st.dataframe(snapshot[[c for c in ['player_name','position','jersey','player_id','retrieved_utc'] if c in snapshot]],hide_index=True,use_container_width=True)
            st.caption(f'{len(snapshot)} players in the local roster snapshot; not necessarily available for tonight’s game.')
            st.markdown('**Player portraits**')
            for start in range(0,len(snapshot),5):
                cols=st.columns(5)
                for col, (_,r) in zip(cols,snapshot.iloc[start:start+5].iterrows()):
                    with col:
                        st.image(f'https://cdn.nba.com/headshots/nba/latest/1040x760/{r.player_id}.png',use_container_width=True)
                        st.caption(str(r.player_name))

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
