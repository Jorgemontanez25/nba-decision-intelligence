from pathlib import Path
import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st
from analysis import player_summary,player_trend,candidate_starters

st.set_page_config(page_title='NBA Player Intelligence',layout='wide')
st.title('NBA Player Intelligence')
st.caption('Historical profiles + current-season performance • Verified game box scores only')
path=st.sidebar.text_input('DuckDB path','sports.duckdb')
if not Path(path).exists():
    st.warning('Database not found. Run the collector first.')
    st.stop()
con=duckdb.connect(path,read_only=True)
seasons=[x[0] for x in con.execute('SELECT DISTINCT season FROM player_games ORDER BY season').fetchall()]
if not seasons:
    st.warning('No collected player games yet.')
    st.stop()
selected=st.sidebar.multiselect('Seasons',seasons,default=[seasons[-1]])
teams=[x[0] for x in con.execute('SELECT DISTINCT team_abbr FROM player_games ORDER BY 1').fetchall()]
team=st.sidebar.selectbox('Team',['All teams',*teams])
opponent=st.sidebar.selectbox('Opponent',['All opponents',*teams])
season_type=st.sidebar.selectbox('Season type',['Both','Regular Season','Playoffs'])
if not selected:
    st.info('Choose at least one season.');st.stop()
team_filter=None if team=='All teams' else team
opp_filter=None if opponent=='All opponents' else opponent
stype_filter=None if season_type=='Both' else season_type
summary=player_summary(con,selected,team_filter,opp_filter,stype_filter)
st.subheader('Player performance (selected period)')
st.dataframe(summary,use_container_width=True,hide_index=True)
if summary.empty:
    st.info('No games match the current filters.');st.stop()
options={f"{r.player_name} ({r.team_abbr}, ID {r.player_id})":int(r.player_id) for r in summary.itertuples()}
choice=st.selectbox('Individual player',list(options))
player_id=options[choice]
trend=player_trend(con,player_id,selected,team_filter)
if opp_filter:
    matching=con.execute('''SELECT DISTINCT p.game_id FROM player_games p JOIN team_games t ON p.game_id=t.game_id WHERE p.player_id=? AND t.team_abbr=?''',[player_id,opp_filter]).df()
    trend=trend[trend.game_id.isin(matching.game_id)]
if stype_filter:
    trend=trend[trend.season_type==stype_filter]
if not trend.empty:
    a,b,c=st.columns(3)
    a.metric('Points / game',f'{trend.points.mean():.1f}')
    b.metric('Rebounds / game',f'{trend.rebounds.mean():.1f}')
    c.metric('Assists / game',f'{trend.assists.mean():.1f}')
    st.plotly_chart(px.line(trend,x='game_date',y=['points','rebounds','assists'],markers=True,title='Per-game trends'),use_container_width=True)
    st.dataframe(trend,use_container_width=True,hide_index=True)
st.subheader('Current-season starter evidence')
st.caption('This lists recent recorded starters, NOT a projected optimal five. Availability, injuries, and matchup-aware predictions have not been integrated.')
current='2026-27'
team_for_candidate = team_filter or 'LAL'
if current in seasons:
    st.dataframe(candidate_starters(con,team_for_candidate,current,min_games=1),hide_index=True,use_container_width=True)
else:
    st.info('Collect 2026-27 regular-season games to see current starter evidence.')
con.close()
