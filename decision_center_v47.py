"""Read-only experimental pregame and manual live 5v5 decision support.

Only official box-score-derived player profiles are used here. This is NOT an
empirically validated lineup win-probability or certified five-player impact model.
"""
from __future__ import annotations
from itertools import combinations
from pathlib import Path
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from roster_2026_27 import roster_for_team
from v45_visuals import add_face_markers


def roster_profiles(con, team, seasons, types):
    if not seasons or not types:
        return pd.DataFrame()
    ss=','.join('?'*len(seasons)); tt=','.join('?'*len(types))
    return con.execute(f"""
      SELECT CAST(player_id AS VARCHAR) AS player_id,
             MAX_BY(player_name,game_date) AS player_name,
             COUNT(DISTINCT game_id) AS games,
             ROUND(SUM(minutes)/NULLIF(COUNT(DISTINCT game_id),0),2) AS mpg,
             ROUND(SUM(points)/NULLIF(SUM(minutes),0)*36,2) AS pts36,
             ROUND(SUM(rebounds)/NULLIF(SUM(minutes),0)*36,2) AS reb36,
             ROUND(SUM(assists)/NULLIF(SUM(minutes),0)*36,2) AS ast36,
             ROUND(SUM(steals+blocks)/NULLIF(SUM(minutes),0)*36,2) AS stocks36,
             ROUND(SUM(turnovers)/NULLIF(SUM(minutes),0)*36,2) AS tov36,
             ROUND(100*SUM(points)/NULLIF(2*(SUM(fga)+0.44*SUM(fta)),0),1) AS ts_pct,
             SUM(CASE WHEN starter THEN 1 ELSE 0 END) AS starts,
             STRING_AGG(DISTINCT team_abbr, ', ' ORDER BY team_abbr) AS historical_teams,
             STRING_AGG(DISTINCT season, ', ' ORDER BY season) AS history_seasons
      FROM player_games WHERE season IN ({ss})
        AND season_type IN ({tt}) AND minutes>0
      GROUP BY player_id ORDER BY MAX(game_date) DESC, games DESC
    """, [*seasons,*types]).df()


def team_profile(con, team, seasons, types):
    if not seasons or not types:
        return pd.Series(dtype=float)
    ss=','.join('?'*len(seasons)); tt=','.join('?'*len(types))
    df = con.execute(f"""
      SELECT game_id,
             SUM(points) AS points,
             SUM(rebounds) AS rebounds,
             SUM(assists) AS assists,
             SUM(steals) AS steals,
             SUM(blocks) AS blocks,
             SUM(turnovers) AS turnovers,
             SUM(fga) AS fga,
             SUM(fta) AS fta
      FROM player_games
      WHERE team_abbr=? AND season IN ({ss}) AND season_type IN ({tt})
      GROUP BY game_id
      ORDER BY game_id
    """, [team,*seasons,*types]).df()
    if df.empty:
        return pd.Series(dtype=float)
    out = {
        'Points': round(df['points'].mean(), 1),
        'Assists': round(df['assists'].mean(), 1),
        'Rebounds': round(df['rebounds'].mean(), 1),
        'Steals': round(df['steals'].mean(), 1),
        'Blocks': round(df['blocks'].mean(), 1),
        'Turnovers': round(df['turnovers'].mean(), 1),
    }
    denom = 2*(df['fga'].sum() + 0.44*df['fta'].sum())
    out['TS%'] = round(100*df['points'].sum()/denom, 1) if denom else 0.0
    out['Stocks'] = round((df['steals'] + df['blocks']).mean(), 1)
    return pd.Series(out)


def render_team_comparison_chart(home_team, away_team, home_profile, away_profile):
    """Relative radar comparison; box scores are not defensive ratings or 5v5 impact."""
    st.markdown('### Team comparison — offense and defensive activity')
    if home_profile.empty or away_profile.empty:
        st.info('Not enough team box-score data to build the comparison chart.')
        return

    # Metrics have different units. Express each as % of the two-team
    # arithmetic mean; 100 is the pair average, not a league percentile.
    # A fixed radial range avoids misleading autoscale differences.
    groups = [
        ('Offensive production', ['Points', 'Assists', 'TS%', 'Turnovers']),
        ('Defensive activity (box-score proxies)', ['Rebounds', 'Steals', 'Blocks', 'Stocks']),
    ]
    home_color = '#9770e7'
    away_color = '#37b3ae'
    cols = st.columns(2)
    for col, (heading, metrics) in zip(cols, groups):
        hvals = [float(home_profile.get(k, 0)) for k in metrics]
        avals = [float(away_profile.get(k, 0)) for k in metrics]
        means = [(h + a) / 2 for h, a in zip(hvals, avals)]
        hn = [100*h/m if m > 0 else 0 for h, m in zip(hvals, means)]
        an = [100*a/m if m > 0 else 0 for a, m in zip(avals, means)]
        fig = go.Figure()
        for name, vals, raw, color in (
            (home_team, hn, hvals, home_color),
            (away_team, an, avals, away_color),
        ):
            fig.add_trace(go.Scatterpolar(
                r=vals + vals[:1], theta=metrics + metrics[:1],
                fill='toself', name=name,
                line=dict(color=color, width=2),
                fillcolor='rgba(151,112,231,0.24)' if name==home_team else 'rgba(55,179,174,0.20)',
                customdata=raw + raw[:1],
                hovertemplate='%{theta}: %{customdata:.1f}<br>Relative to matchup average: %{r:.1f}%<extra>'+name+'</extra>',
            ))
        fig.update_layout(
            title=heading, height=420, margin=dict(l=48, r=48, t=54, b=45),
            polar=dict(radialaxis=dict(range=[0, 200], visible=True, ticksuffix='%', tickfont=dict(size=9)),
                       angularaxis=dict(direction='clockwise')),
            legend=dict(orientation='h', y=-0.1),
            paper_bgcolor='rgba(0,0,0,0)',
            font=dict(size=12),
        )
        with col:
            st.plotly_chart(fig, use_container_width=True)
    st.caption('Each axis is scaled to the average of these two teams (100%). This is a descriptive visual, not a calibrated strength rating. Higher turnovers are worse; rebounds, steals and blocks are only defensive-activity proxies, not defensive efficiency.')
    metrics = ['Points', 'Assists', 'TS%', 'Turnovers', 'Rebounds', 'Steals', 'Blocks', 'Stocks']
    st.dataframe(pd.DataFrame({
        'Metric': metrics,
        home_team: [home_profile.get(k, 0) for k in metrics],
        away_team: [away_profile.get(k, 0) for k in metrics],
    }), hide_index=True, use_container_width=True)


def player_score(row, weights):
    def n(k):
        v=row.get(k,0)
        return float(v) if pd.notna(v) else 0.0
    # Fixed, interpretable heuristic: per-36 box score contributions, not model predictions.
    off=0.9*n('pts36') + 1.2*n('ast36') + 0.13*(n('ts_pct')-54) - 1.4*n('tov36')
    defense=1.2*n('reb36') + 2.4*n('stocks36')
    return weights[0]*off + weights[1]*defense


@st.cache_data(show_spinner=False, ttl=86400)
def court_headshot_data(player_id):
    """Embed portrait data to avoid Plotly/browser cross-origin image failures."""
    import base64
    from io import BytesIO
    from urllib.request import Request, urlopen
    try:
        from PIL import Image
        url = f'https://cdn.nba.com/headshots/nba/latest/1040x760/{int(player_id)}.png'
        with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=5) as response:
            raw=response.read(1_500_000)
        with Image.open(BytesIO(raw)) as im:
            im.thumbnail((150,110))
            buff=BytesIO()
            im.convert('RGBA').save(buff,format='PNG',optimize=True)
            return 'data:image/png;base64,'+base64.b64encode(buff.getvalue()).decode('ascii')
    except Exception:
        return None


def show_full_court(our_ids, opp_ids, our_names, opp_names, home, away):
    """Self-contained SVG court; player photos are inline data URIs, not Plotly image overlays."""
    import html
    import streamlit.components.v1 as components
    def esc(v): return html.escape(str(v), quote=True)
    left=[(120,138),(120,362),(267,245),(392,140),(392,360)]
    right=[(940-x,y) for x,y in left]
    pieces=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 940 500" role="img" aria-label="Both teams on the basketball court" style="width:100%;height:auto;display:block;background:#102631;border-radius:12px">']
    pieces += ['<rect x="8" y="8" width="924" height="484" rx="8" fill="#122A36" stroke="#C99A5D" stroke-width="4"/>','<path d="M470 8V492" stroke="#C99A5D" stroke-width="2"/>','<circle cx="470" cy="250" r="65" fill="none" stroke="#C99A5D" stroke-width="2"/>','<rect x="8" y="156" width="180" height="188" fill="none" stroke="#C99A5D" stroke-width="2"/>','<rect x="752" y="156" width="180" height="188" fill="none" stroke="#C99A5D" stroke-width="2"/>','<circle cx="188" cy="250" r="60" fill="none" stroke="#C99A5D" stroke-width="2"/>','<circle cx="752" cy="250" r="60" fill="none" stroke="#C99A5D" stroke-width="2"/>','<path d="M8 66H92 A185 185 0 0 1 92 434H8 M932 66H848 A185 185 0 0 0 848 434H932" fill="none" stroke="#C99A5D" stroke-width="2"/>']
    images=0
    for ids,names,positions,color in ((our_ids,our_names,left,'#9872eb'),(opp_ids,opp_names,right,'#30b8b4')):
        for index,(pid,(x,y)) in enumerate(zip(ids,positions),1):
            nm=names.get(str(pid),str(pid)); short=nm.split()[-1]
            src=court_headshot_data(pid)
            pieces.append(f'<circle cx="{x}" cy="{y}" r="42" fill="{color}" stroke="white" stroke-width="3"/>')
            if src and src.startswith('data:image/png;base64,'):
                images+=1
                clipid=f'face_{esc(pid)}_{index}_{x}'
                pieces.append(f'<defs><clipPath id="{clipid}"><circle cx="{x}" cy="{y}" r="39"/></clipPath></defs>')
                pieces.append(f'<image href="{src}" x="{x-42}" y="{y-42}" width="84" height="84" preserveAspectRatio="xMidYMid slice" clip-path="url(#{clipid})"/>')
            else: pieces.append(f'<text x="{x}" y="{y+10}" fill="white" text-anchor="middle" font-size="28" font-weight="bold">{index}</text>')
            pieces.append(f'<rect x="{x-65}" y="{y+46}" width="130" height="26" rx="7" fill="#07121C" opacity=".96"/>')
            pieces.append(f'<text x="{x}" y="{y+64}" fill="white" text-anchor="middle" font-size="16" font-weight="bold">{esc(short[:17])}</text>')
    pieces.append('</svg>')
    components.html(''.join(pieces),height=520,scrolling=False)
    st.caption(f'Illustrative full-court positions · {home} vs {away} · {images}/10 portraits loaded. Not tracking-based or defensive assignments.')


def attach_current_roster(roster, profiles):
    """Membership comes only from roster snapshot; profiles are optional evidence."""
    base=roster[['player_id','player_name','position','jersey','retrieved_utc']].copy()
    base['player_id']=base.player_id.astype(str)
    base=base.drop_duplicates('player_id')
    out=base.merge(profiles.drop(columns=['player_name'],errors='ignore'),on='player_id',how='left',validate='one_to_one')
    out['profile_status']=np.where(pd.to_numeric(out.get('games',pd.Series(index=out.index,dtype=float)),errors='coerce').fillna(0)>0,'HISTORICAL_PROFILE','NO_HISTORICAL_PROFILE')
    return out


def render_oncourt_comparison(our_ids, opp_ids, home_df, away_df, home, away):
    fields=[('pts36','Points /36'),('ast36','Assists /36'),('reb36','Rebounds /36'),('stocks36','Steals+blocks /36')]
    ours=home_df[home_df.player_id.astype(str).isin(our_ids)]
    theirs=away_df[away_df.player_id.astype(str).isin(opp_ids)]
    fig=go.Figure()
    if ours[[k for k,_ in fields]].isna().any().any() or theirs[[k for k,_ in fields]].isna().any().any():
        st.warning('Some selected players lack statistical profiles; the on-court comparison excludes unavailable metrics and is incomplete.')
    fig.add_trace(go.Bar(name=home,x=[v[1] for v in fields],y=[float(ours[k].sum(min_count=5)) if ours[k].notna().sum()==5 else None for k,_ in fields],marker_color='#9b75eb'))
    fig.add_trace(go.Bar(name=away,x=[v[1] for v in fields],y=[float(theirs[k].sum(min_count=5)) if theirs[k].notna().sum()==5 else None for k,_ in fields],marker_color='#39b6b2'))
    fig.update_layout(barmode='group',height=360,title='On-court five: offensive production and defensive activity',yaxis_title='Sum of per-36 individual rates (descriptive)',margin=dict(l=20,r=20,t=45,b=20),paper_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig,use_container_width=True)
    st.caption('Not five-player team possessions or opponent-adjusted ratings. Per-36 rates are summed across the selected five and used only as a descriptive reference.')



def _on_court_radar(our_ids, opp_ids, home_df, away_df, home, away, mode):
    if mode=='Offense':
        columns=[('pts36','Scoring'),('ast36','Playmaking'),('ts_pct','Efficiency'),('tov36','Ball security')]
    else:
        columns=[('reb36','Rebounding'),('stocks36','Stocks'),('reb36','Board support'),('stocks36','Activity')]
    groups=[home_df[home_df.player_id.astype(str).isin(our_ids)],away_df[away_df.player_id.astype(str).isin(opp_ids)]]
    if any(len(g)!=5 for g in groups):
        st.info('Select five valid players for each team to compare.')
        return
    raw=[]
    for group in groups:
        values=[]
        for col, label in columns:
            x=pd.to_numeric(group[col],errors='coerce')
            if x.notna().sum()!=5:
                values.append(None)
            elif col=='ts_pct': values.append(float(x.mean()))
            elif col=='tov36': values.append(float(x.sum()))
            else: values.append(float(x.sum()))
        raw.append(values)
    valid=[i for i in range(len(columns)) if all(vals[i] is not None for vals in raw)]
    if len(valid)<3:
        st.info('Insufficient statistical profiles for a reliable five-player comparison.')
        return
    # Normalize to paired group averages; inverted axis for turnovers.
    scores=[[],[]]
    for i in valid:
        a,b=raw[0][i],raw[1][i]
        mean=(a+b)/2
        if mean<=0: x,y=100,100
        elif columns[i][0]=='tov36': x,y=200-a/mean*100,200-b/mean*100
        else: x,y=100*a/mean,100*b/mean
        scores[0].append(max(0,min(200,x)));scores[1].append(max(0,min(200,y)))
    theta=[columns[i][1] for i in valid]
    fig=go.Figure()
    for name,values,color in [(home,scores[0],'#9b75eb'),(away,scores[1],'#39b6b2')]:
        fig.add_trace(go.Scatterpolar(r=values+values[:1],theta=theta+theta[:1],fill='toself',name=name,line=dict(color=color,width=3),opacity=.72))
    fig.update_layout(height=405,margin=dict(l=20,r=20,t=36,b=36),title=mode,polar=dict(radialaxis=dict(range=[0,200],tickvals=[50,100,150,200],ticksuffix='%',gridcolor='#52606b',tickfont=dict(size=8)),angularaxis=dict(tickfont=dict(size=10))),paper_bgcolor='rgba(0,0,0,0)',legend=dict(orientation='h',y=-.16),font=dict(color='#e9edf4'))
    st.plotly_chart(fig,use_container_width=True)

def render_matchup_triptych(our_ids, opp_ids, home_df, away_df, our_names, opp_names, home, away):
    a,b,c=st.columns([1,2.65,1],gap='small')
    with a: _on_court_radar(our_ids,opp_ids,home_df,away_df,home,away,'Offense')
    with b: show_full_court(our_ids,opp_ids,our_names,opp_names,home,away)
    with c: _on_court_radar(our_ids,opp_ids,home_df,away_df,home,away,'Defense')
    st.caption('Two flank charts compare the chosen five against the opponent five using individual box-score proxies. 100% is the paired mean, not a league percentile or predictive win probability. Court positions are illustrative.')

def render_decision_center(con, default_team, default_opponent, seasons, season_types):
    st.subheader('5v5 Decision Center')
    st.caption('Experimental pregame and manually updated in-game lineup recommendations. This is a box-score heuristic, NOT certified matchup-adjusted lineup impact or a live NBA feed.')
    st.info('Historical 5v5 results remain excluded from predictions until validated. This tab explores hypothetical combinations and uses box-score data only.')
    teams=[r[0] for r in con.execute('SELECT DISTINCT team_abbr FROM player_games ORDER BY team_abbr').fetchall()]
    if len(teams)<2:
        st.warning('At least two teams with player box scores are required in DuckDB.')
        return
    home = default_team if default_team in teams else teams[0]
    if not default_opponent or default_opponent == 'ALL' or default_opponent == home:
        st.warning('Choose a specific opponent in the sidebar to use the 5v5 Decision Center.')
        return
    away = default_opponent
    latest=sorted(seasons)[-1] if seasons else ''
    available_seasons=[str(x[0]) for x in con.execute('SELECT DISTINCT season FROM player_games ORDER BY season').fetchall()]
    st.caption('Historical seasons currently present in DuckDB: '+(', '.join(available_seasons) if available_seasons else 'none'))
    seasons=available_seasons
    st.caption('Using all box-score seasons present in DuckDB: '+(', '.join(seasons) if seasons else 'none'))
    if not seasons:
        st.warning('Select one or more available historical seasons for lineup rankings.'); return
    missing_seasons=[x for x in ['2022-23','2023-24','2024-25','2025-26','2026-27'] if x not in available_seasons]
    if missing_seasons: st.info('Historical data not collected locally for: '+', '.join(missing_seasons)+'. Select seasons in the sidebar only after importing those box scores. The roster fetch does not backfill historical statistics.')
    hcol, acol = st.columns(2)
    with hcol:
        st.text_input('Your team', value=home, disabled=True, key='dc_home_display')
    with acol:
        st.text_input('Opponent', value=away, disabled=True, key='dc_away_display')
    st.caption(f'Using the sidebar matchup selection only: {home} vs {away}. Historical seasons: {", ".join(seasons)} · Season types: {", ".join(season_types)}. Player availability must be confirmed manually.')
    home_df=roster_profiles(con,home,seasons,season_types)
    away_df=roster_profiles(con,away,seasons,season_types)
    home_profile = team_profile(con, home, seasons, season_types)
    away_profile = team_profile(con, away, seasons, season_types)
    render_team_comparison_chart(home, away, home_profile, away_profile)
    current_roster_home=roster_for_team(home)
    current_roster_away=roster_for_team(away)
    if current_roster_home.empty or current_roster_away.empty:
        st.error('Current 2026–27 roster snapshots are required for 5v5. Run the roster refresh for both teams. Historical player lists are NOT a fallback.')
        return
    home_df=attach_current_roster(current_roster_home,home_df)
    away_df=attach_current_roster(current_roster_away,away_df)
    h_eligible=home_df[home_df.profile_status=='HISTORICAL_PROFILE'].copy()
    a_eligible=away_df[away_df.profile_status=='HISTORICAL_PROFILE'].copy()
    st.markdown('#### Current 2026–27 roster coverage')
    st.caption('Roster membership is a 2026–27 snapshot; player performance may come from earlier seasons and previous teams.')
    c1,c2=st.columns(2)
    with c1: st.metric(f'{home} roster',f'{len(home_df)} players',f'{len(h_eligible)} with usable selected-season profiles',delta_color='off')
    with c2: st.metric(f'{away} roster',f'{len(away_df)} players',f'{len(a_eligible)} with usable selected-season profiles',delta_color='off')
    with st.expander('All current roster players and evidence status', expanded=False):
        l,r=st.columns(2)
        with l:
            st.markdown(f'**{home}**')
            st.dataframe(home_df[[c for c in ['player_name','position','jersey','games','historical_teams','history_seasons','profile_status'] if c in home_df]],hide_index=True,use_container_width=True)
        with r:
            st.markdown(f'**{away}**')
            st.dataframe(away_df[[c for c in ['player_name','position','jersey','games','historical_teams','history_seasons','profile_status'] if c in away_df]],hide_index=True,use_container_width=True)
    if len(h_eligible)<5 or len(a_eligible)<5:
        st.warning(f'Current-roster players with usable stats: {home} {len(h_eligible)}/5, {away} {len(a_eligible)}/5. All roster players remain visible above; rankings require sufficient evidence. Select additional historical seasons or collect more box scores.')
        return
    with st.expander('Roster coverage and model assumptions',expanded=False):
        st.write('Membership = current 2026–27 roster snapshots ONLY. Performance = all available selected seasons for the player ID, regardless of historical team. One or more played games is required for heuristic ranking. Missing profiles are never treated as zero.')
        st.dataframe(home_df[['player_name','games','mpg','pts36','reb36','ast36','stocks36','ts_pct','historical_teams','history_seasons','profile_status']],hide_index=True,use_container_width=True)
        st.write('No verified player-on-player defensive assignments, five-man synergy, injuries, or real-time provider connection. Scores below are relative decision indices, not win probabilities or projected point differentials.')
    mode=st.radio('Analysis mode',['Pregame','In-game (manual)'],horizontal=True,key='dc_mode')
    pool=h_eligible.sort_values(['games','mpg'],ascending=False).copy()
    st.caption('Every current-roster player with at least one available historical box-score profile is eligible for the ranking pool, including those who played for other teams. The full roster remains visible above.')
    full_home_names=dict(zip(home_df.player_id.astype(str),home_df.player_name.astype(str)))
    full_away_names=dict(zip(away_df.player_id.astype(str),away_df.player_name.astype(str)))
    pool_ids=pool.player_id.astype(str).tolist()
    exclusions=st.multiselect('Unavailable / restricted players (exclude)',pool_ids,format_func=lambda x:full_home_names.get(x,x),key='dc_excluded')
    pool=pool[~pool.player_id.astype(str).isin(exclusions)].copy()
    if len(pool)<5:
        st.warning('Fewer than five eligible players remain.');return
    opponent_options=away_df.sort_values(['games','mpg'],ascending=False,na_position='last').player_id.astype(str).tolist()
    opponent_five=st.multiselect('Opponent five currently on court (choose exactly 5)',opponent_options,default=opponent_options[:5],format_func=lambda x:full_away_names.get(x,x),max_selections=5,key='dc_opp_five')
    if len(opponent_five)!=5:
        st.warning('Select exactly five opposing players to continue.');return
    opp_now=away_df[away_df.player_id.astype(str).isin(opponent_five)].copy()
    if opp_now['profile_status'].ne('HISTORICAL_PROFILE').any():
        st.warning('Some opposing players lack sufficient historical statistics. Threat estimates omit their unknown production; comparisons should be treated as incomplete.')
    # High-scoring rival lineups motivate extra defense; aggregate box-score form only.
    known_threat=opp_now['pts36'].dropna()
    threat=float(known_threat.mean()) if not known_threat.empty else 18.0
    score_margin=0; remaining=48; own_five=[]; max_swaps=5
    if mode.startswith('In-game'):
        x,y,z=st.columns(3)
        score_margin=x.number_input('Your lead (+) / deficit (−)',min_value=-70,max_value=70,value=0,step=1,key='dc_margin')
        quarter=y.selectbox('Quarter',[1,2,3,4,5,6],index=2,key='dc_q')
        clock=z.number_input('Minutes remaining this quarter',min_value=0.0,max_value=12.0,value=6.0,step=0.5,key='dc_clock')
        remaining=max(0,(4-quarter)*12+clock) if quarter<=4 else clock
        default_five=pool_ids[:5]
        existing=st.multiselect('Your current five (select exactly 5)',pool.player_id.astype(str).tolist(),default=[p for p in default_five if p in pool.player_id.astype(str).tolist()],format_func=lambda x:full_home_names.get(x,x),max_selections=5,key='dc_own_five')
        if len(existing)!=5:
            st.warning('Select exactly five current players before calculating substitutions.');return
        own_five=existing
        max_swaps=st.slider('Maximum simultaneous substitutions',0,5,2,key='dc_swaps')
        st.caption('The clock and score modify strategy weights. This is manual game state, not an automatically updated live feed.')
    off_weight=0.53; def_weight=0.47
    if mode.startswith('In-game'):
        urgency=min(1,max(0,(18-remaining)/18))
        # Trailing late -> offense; leading late -> defense. Display rule transparently.
        shift=np.clip(-score_margin/20,-1,1)*urgency*0.25
        off_weight=float(np.clip(off_weight+shift,.28,.78));def_weight=1-off_weight
    # Slight extra defensive weight when opponent roster's scoring intensity is high.
    defense_add=min(.06,max(0,(threat-18)*.004))
    off_weight=max(.20,off_weight-defense_add);def_weight=1-off_weight
    st.caption(f'Heuristic weights: offense {off_weight:.0%}, defense {def_weight:.0%}; opponent individual scoring profile {threat:.1f} pts/36 on average. No opponent-specific five-on-five outcome data used.')
    records=[]
    rows={str(r['player_id']):r for _,r in pool.iterrows()}
    for group in combinations(pool.player_id.astype(str).tolist(),5):
        swaps=len(set(group)-set(own_five)) if own_five else 0
        if swaps>max_swaps:continue
        samples=sum(float(rows[i]['games']) for i in group)
        base=sum(player_score(rows[i],(off_weight,def_weight)) for i in group)
        # Small penalty only for simultaneous substitutions in in-game mode.
        score=base-0.6*swaps
        records.append(dict(ids=group,score=score,swaps=swaps,sample_games=int(samples)))
    if not records:
        st.warning('No eligible five-player combination meets the substitution constraint.');return
    ranked=sorted(records,key=lambda x:(-x['score'],x['swaps'],x['ids']))[:5]
    max_val=max(x['score'] for x in records); min_val=min(x['score'] for x in records)
    display=[]
    for rank,r in enumerate(ranked,1):
        # 0-100 normalization only for within-query ranking; not calibrated probability.
        idx=50 if max_val==min_val else 100*(r['score']-min_val)/(max_val-min_val)
        display.append({'Rank':rank,'Five players':' · '.join(full_home_names[i] for i in r['ids']), 'Relative index':round(idx,1),'Changes':r['swaps'] if own_five else 'Pregame','Combined player-game samples':r['sample_games']})
    st.subheader('Top 5 candidate lineups')
    st.dataframe(pd.DataFrame(display),hide_index=True,use_container_width=True)
    selected_rank=st.selectbox('Visualize recommended lineup',list(range(1,len(ranked)+1)),format_func=lambda i:f'#{i} — '+', '.join(full_home_names[p] for p in ranked[i-1]['ids']),key='dc_rank_view')
    st.caption('Changing this selection redraws the selected five, player headshots, and both offensive and defensive radars.')
    chosen=ranked[selected_rank-1]
    st.subheader('Recommended formation')
    render_matchup_triptych(chosen['ids'],opponent_five,home_df,away_df,full_home_names,full_away_names,home,away)
    with st.expander('Selected players · NBA headshots',expanded=False):
        portraits=st.columns(5)
        for i,pid in enumerate(chosen['ids']):
            with portraits[i]:
                st.image(f'https://cdn.nba.com/headshots/nba/latest/1040x760/{pid}.png',use_container_width=True)
                st.caption(full_home_names[pid])
    best=chosen
    c1,c2,c3=st.columns(3)
    c1.metric('Candidate combinations evaluated',f'{len(records):,}')
    c2.metric('Recommended substitutions',str(best['swaps']) if own_five else 'Pregame')
    c3.metric('Historical evidence','Player box scores')
    if own_five:
        in_ids=set(best['ids'])-set(own_five);out_ids=set(own_five)-set(best['ids'])
        st.write('**Suggested entries:** '+(', '.join(full_home_names[i] for i in sorted(in_ids)) if in_ids else 'No substitution'))
        st.write('**Suggested exits:** '+(', '.join(full_home_names[i] for i in sorted(out_ids)) if out_ids else 'No substitution'))
    st.warning('Research output: this ranking is not a measured or certified NBA 5v5 matchup result. Do not interpret the relative index as a win probability. Live injuries, fouls and automatic substitutions are not connected.')
    with st.expander('Reconstruction QA — five audited historical games',expanded=False):
        root=Path('v9_9_9_regression_review')
        scoring=Path('v9_9_10_scoring_review')
        a=root/'GAME_RESULTS.csv';b=scoring/'GAME_RESULTS.csv'
        if a.exists():
            df=pd.read_csv(a,dtype={'game_id':'string'})
            st.dataframe(df[[c for c in ['game_id','status','substitutions_applied','substitutions_in_source','max_minutes_diff_seconds'] if c in df]],hide_index=True,use_container_width=True)
        else:st.info('V9.9.9 regression report not available in working directory.')
        if b.exists():
            q=pd.read_csv(b,dtype={'game_id':'string'})
            st.dataframe(q[[c for c in ['game_id','score_events','boundary_events','unassigned_events','before_matches'] if c in q]],hide_index=True,use_container_width=True)
        else:st.info('V9.9.10 scoring report not available in working directory.')
        st.caption('All reconstructed stints are conditional. Scoring substitution-boundary attribution is not independently certified and these QA games are not silently used as lineup training data.')
