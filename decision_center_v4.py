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
             SUM(CASE WHEN starter THEN 1 ELSE 0 END) AS starts
      FROM player_games WHERE team_abbr=? AND season IN ({ss})
        AND season_type IN ({tt}) AND minutes>0
      GROUP BY player_id ORDER BY MAX(game_date) DESC, games DESC
    """, [team,*seasons,*types]).df()


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


def show_court_lineup(group, names, team, title):
    """Illustrative arrangement only: these are display slots, not assigned positions."""
    fig=go.Figure()
    fig.add_shape(type='rect',x0=0,y0=0,x1=50,y1=94,line=dict(color='#d1a56d',width=3),fillcolor='#162d36')
    fig.add_shape(type='circle',x0=17,y0=3,x1=33,y1=19,line=dict(color='#d1a56d',width=2))
    fig.add_shape(type='line',x0=5,y0=47,x1=45,y1=47,line=dict(color='#d1a56d',width=1))
    fig.add_shape(type='circle',x0=17,y0=34,x1=33,y1=60,line=dict(color='#d1a56d',width=1))
    fig.add_shape(type='circle',x0=17,y0=75,x1=33,y1=91,line=dict(color='#d1a56d',width=2))
    coords=[(25,13),(11,37),(39,37),(13,68),(37,68)]
    for i,(pid,(x,y)) in enumerate(zip(group,coords)):
        fig.add_trace(go.Scatter(x=[x],y=[y],mode='markers+text',marker=dict(size=52,color='#7f66c6',line=dict(color='white',width=2)),text=[str(i+1)],textposition='middle center',textfont=dict(color='white',size=16),hovertemplate=names.get(pid,pid)+'<extra></extra>',showlegend=False))
        fig.add_annotation(x=x,y=y+8,text=names.get(pid,pid).replace(' ','<br>',1),showarrow=False,font=dict(color='white',size=11),bgcolor='rgba(8,17,24,.8)')
    fig.update_xaxes(range=[-3,53],visible=False,scaleanchor='y',scaleratio=1)
    fig.update_yaxes(range=[-5,100],visible=False)
    fig.update_layout(title=title,height=610,margin=dict(l=10,r=10,t=50,b=10),paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig,use_container_width=True)
    st.caption('Illustrative formation; no positional assignment or tracking coordinates inferred.')


def render_oncourt_comparison(our_ids, opp_ids, home_df, away_df, home, away):
    fields=[('pts36','Points /36'),('ast36','Assists /36'),('reb36','Rebounds /36'),('stocks36','Steals+blocks /36')]
    ours=home_df[home_df.player_id.astype(str).isin(our_ids)]
    theirs=away_df[away_df.player_id.astype(str).isin(opp_ids)]
    fig=go.Figure()
    fig.add_trace(go.Bar(name=home,x=[v[1] for v in fields],y=[float(ours[k].fillna(0).sum()) for k,_ in fields],marker_color='#9b75eb'))
    fig.add_trace(go.Bar(name=away,x=[v[1] for v in fields],y=[float(theirs[k].fillna(0).sum()) for k,_ in fields],marker_color='#39b6b2'))
    fig.update_layout(barmode='group',height=360,title='On-court five: offensive production and defensive activity',yaxis_title='Sum of per-36 individual rates (descriptive)',margin=dict(l=20,r=20,t=45,b=20),paper_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig,use_container_width=True)
    st.caption('Not five-player team possessions or opponent-adjusted ratings. Per-36 rates are summed across the selected five and used only as a descriptive reference.')


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
    current_roster_home=roster_for_team(home) if '2026-27' in seasons else pd.DataFrame()
    current_roster_away=roster_for_team(away) if '2026-27' in seasons else pd.DataFrame()
    if '2026-27' in seasons:
        if current_roster_home.empty or current_roster_away.empty:
            st.warning('2026–27 roster snapshots are missing for one or both teams. The model will not assume historical box-score players are on the current roster. Refresh snapshots first for current-season recommendations.')
            return
        home_df=home_df[home_df.player_id.astype(str).isin(current_roster_home.player_id.astype(str))]
        away_df=away_df[away_df.player_id.astype(str).isin(current_roster_away.player_id.astype(str))]
        missing_home=set(current_roster_home.player_id.astype(str))-set(home_df.player_id.astype(str))
        if missing_home:
            st.info(f'{len(missing_home)} current-roster players have no matching box-score profile for the selected filters and are excluded from rankings, not assigned invented metrics.')
    if len(home_df)<5 or len(away_df)<5:
        st.warning(f'Insufficient player coverage: {home} {len(home_df)}/5, {away} {len(away_df)}/5. Change filters or collect more games.')
        return
    with st.expander('Roster coverage and model assumptions',expanded=False):
        st.write('Player pool = official historical box-score appearances in selected seasons; not current contractual roster. A player traded between selected seasons can remain listed. Exclude unavailable players manually.')
        st.dataframe(home_df[['player_name','games','mpg','pts36','reb36','ast36','stocks36','ts_pct']],hide_index=True,use_container_width=True)
        st.write('No verified player-on-player defensive assignments, five-man synergy, injuries, or real-time provider connection. Scores below are relative decision indices, not win probabilities or projected point differentials.')
    mode=st.radio('Analysis mode',['Pregame','In-game (manual)'],horizontal=True,key='dc_mode')
    pool=home_df.sort_values(['games','mpg'],ascending=False).head(14).copy()
    full_home_names=dict(zip(home_df.player_id.astype(str),home_df.player_name.astype(str)))
    full_away_names=dict(zip(away_df.player_id.astype(str),away_df.player_name.astype(str)))
    pool_ids=pool.player_id.astype(str).tolist()
    exclusions=st.multiselect('Unavailable / restricted players (exclude)',pool_ids,format_func=lambda x:full_home_names.get(x,x),key='dc_excluded')
    pool=pool[~pool.player_id.astype(str).isin(exclusions)].copy()
    if len(pool)<5:
        st.warning('Fewer than five eligible players remain.');return
    opponent_options=away_df.sort_values(['games','mpg'],ascending=False).head(16).player_id.astype(str).tolist()
    opponent_five=st.multiselect('Opponent five currently on court (choose exactly 5)',opponent_options,default=opponent_options[:5],format_func=lambda x:full_away_names.get(x,x),max_selections=5,key='dc_opp_five')
    if len(opponent_five)!=5:
        st.warning('Select exactly five opposing players to continue.');return
    opp_now=away_df[away_df.player_id.astype(str).isin(opponent_five)].copy()
    # High-scoring rival lineups motivate extra defense; aggregate box-score form only.
    threat=float(opp_now['pts36'].fillna(0).sum())/5
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
    chosen=ranked[selected_rank-1]
    st.subheader('Recommended formation')
    leftcourt, rightcourt=st.columns([1,1])
    with leftcourt:
        show_court_lineup(chosen['ids'],full_home_names,home,f'{home} — candidate #{selected_rank}')
    with rightcourt:
        st.markdown('**Player headshots**')
        portrait_cols=st.columns(3)
        for i,pid in enumerate(chosen['ids']):
            with portrait_cols[i%3]:
                st.image(f'https://cdn.nba.com/headshots/nba/latest/1040x760/{pid}.png',use_container_width=True)
                st.caption(full_home_names[pid])
        st.markdown('**Opponent five**')
        st.write(' · '.join(full_away_names[p] for p in opponent_five))
    render_oncourt_comparison(chosen['ids'],opponent_five,home_df,away_df,home,away)
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
