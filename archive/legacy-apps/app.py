"""NBA Lineup Lab — read-only Streamlit MVP for V9.9.9 / V9.9.10 reports."""
from pathlib import Path
import json
import pandas as pd
import streamlit as st

st.set_page_config(page_title='NBA Lineup Lab', page_icon='🏀', layout='wide')
st.title('🏀 NBA Lineup Lab')
st.caption('Reconstruction QA • Scoring scenarios • Conditional data only')
st.warning('Research mode: lineups and scoring-boundary attribution are NOT independently certified. Nothing on this page publishes to production.')

@st.cache_data(show_spinner=False)
def read_csv(path):
    return pd.read_csv(path, dtype={'game_id':str,'player_id':str,'period':str}, keep_default_na=False)
@st.cache_data(show_spinner=False)
def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def locate(base, file):
    p=base/file
    return p if p.is_file() else None

def table(df):
    st.dataframe(df, use_container_width=True, hide_index=True)

with st.sidebar:
    st.header('Local report folders')
    regression=Path(st.text_input('V9.9.9 regression', 'v9_9_9_regression_review')).expanduser()
    scoring=Path(st.text_input('V9.9.10 scoring', 'v9_9_10_scoring_review')).expanduser()
    st.caption('Paths are relative to the folder where you launch Streamlit. Read-only; no DB connection.')

regcsv=locate(regression,'GAME_RESULTS.csv')
scorecsv=locate(scoring,'GAME_RESULTS.csv')
if not regcsv and not scorecsv:
    st.error('No reports found. Run Streamlit from nba_platform_v5, or enter valid report paths in the sidebar.')
    st.code(r'.\.venv\Scripts\python.exe -m streamlit run .\nba_web_mvp\app.py',language='powershell')
    st.stop()
reg=read_csv(regcsv) if regcsv else pd.DataFrame()
sc=read_csv(scorecsv) if scorecsv else pd.DataFrame()
ids=sorted(set(reg['game_id'].astype(str)) if 'game_id' in reg else set() | set(sc['game_id'].astype(str)) if 'game_id' in sc else set())
# explicit union avoids precedence surprises
ids=sorted((set(reg['game_id'].astype(str)) if 'game_id' in reg else set()) | (set(sc['game_id'].astype(str)) if 'game_id' in sc else set()))
labels={}
if not reg.empty and 'label' in reg:
    labels=dict(zip(reg['game_id'].astype(str),reg['label'].astype(str)))

passed=reg['status'].eq('PASS_INTERNAL_UNVERIFIED').sum() if 'status' in reg else 0
subs=pd.to_numeric(reg.get('substitutions_applied', pd.Series(dtype=float)),errors='coerce').sum()
scored=pd.to_numeric(sc.get('score_events',pd.Series(dtype=float)),errors='coerce').sum()
missing=pd.to_numeric(sc.get('unassigned_events',pd.Series(dtype=float)),errors='coerce').sum()
a,b,c,d=st.columns(4)
a.metric('Internal reconstruction passes',f'{passed}/{len(reg)}' if len(reg) else '—')
b.metric('Applied substitutions', f'{int(subs)}' if len(reg) else '—')
c.metric('Scoring events assessed',f'{int(scored)}' if len(sc) else '—')
d.metric('Unassigned score events',f'{int(missing)}' if len(sc) else '—')

tabs=st.tabs(['Overview','Game explorer','Player ±','Scoring boundaries','Data / QA'])
with tabs[0]:
    st.subheader('Reconstruction regression')
    if len(reg):
        show=[x for x in ['game_id','label','status','substitutions_applied','substitutions_in_source','max_minutes_diff_seconds','regression_status'] if x in reg]
        table(reg[show])
    else:st.info('V9.9.9 report not found.')
    st.subheader('Scoring audit')
    if len(sc):
        table(sc[[x for x in ['game_id','status','score_events','boundary_events','unassigned_events','recorded_matches','before_matches','after_matches'] if x in sc]])
        match_cols=[x for x in ['recorded_matches','before_matches','after_matches'] if x in sc]
        if match_cols:
            plot=sc[match_cols].apply(pd.to_numeric,errors='coerce').sum()
            st.bar_chart(plot.rename(index=lambda x:x.replace('_matches','')).to_frame('Exact player ± matches'))
    else:st.info('V9.9.10 report not found.')
with tabs[1]:
    st.subheader('Inspect a game')
    if ids:
        gid=st.selectbox('Game',ids,format_func=lambda x:f'{x} — {labels.get(x, "")}'.strip(' —'))
        if len(reg) and gid in reg['game_id'].values:table(reg[reg['game_id']==gid])
        if len(sc) and gid in sc['game_id'].values:table(sc[sc['game_id']==gid])
        timeline=regression/gid/'reaudit'/'reconstruction'/'lineup_timeline_CONDITIONAL_UNVERIFIED.csv'
        if not timeline.exists():
            options=list((regression/gid).rglob('lineup_timeline_CONDITIONAL_UNVERIFIED.csv')) if (regression/gid).exists() else []
            timeline=options[0] if options else None
        if timeline and timeline.exists():
            x=read_csv(timeline)
            if 'period' in x:
                q=st.selectbox('Quarter',sorted(x['period'].astype(str).unique()),key='quarter')
                x=x[x['period'].astype(str)==q]
            st.caption('Event-level intervals, NOT independently certified stints.')
            table(x.head(500))
        else:st.info('No conditional lineup timeline found for this game.')
    else:st.info('No games in report folders.')
with tabs[2]:
    st.subheader('Official versus calculated player plus/minus')
    if ids:
        gid=st.selectbox('Game',ids,key='pm_game')
        pmfile=scoring/gid/'PLAYER_PLUS_MINUS_SCENARIOS.csv'
        if pmfile.is_file():
            pm=read_csv(pmfile)
            scenario=st.selectbox('Attribution scenario',list(pm['scenario'].drop_duplicates()))
            pm=pm[pm['scenario']==scenario].copy()
            for col in ['official_pm','calculated_pm','difference']:
                if col in pm:pm[col]=pd.to_numeric(pm[col],errors='coerce')
            team=st.selectbox('Team',['All']+sorted(pm['team'].dropna().unique().tolist()))
            if team!='All':pm=pm[pm['team']==team]
            table(pm)
            if 'difference' in pm:
                st.metric('Total absolute player ± error',f'{pm["difference"].abs().sum():.0f}')
        else:st.info('No detailed plus/minus CSV for this game.')
with tabs[3]:
    st.subheader('Events sharing a timestamp with substitutions')
    if ids:
        gid=st.selectbox('Game',ids,key='bound_game')
        p=scoring/gid/'SCORING_EVENTS.csv'
        if p.is_file():
            events=read_csv(p)
            if 'at_substitution_timestamp' in events:
                events=events[events['at_substitution_timestamp'].astype(str).str.lower().isin(['true','1'])]
            st.metric('Boundary scoring events',len(events))
            table(events)
            st.caption('Before/after/recorded assignments are scenarios; the actual legal substitution timing remains unresolved.')
        else:st.info('No event-level scoring CSV for this game.')
with tabs[4]:
    st.subheader('Source and quality gates')
    for name,path in [('Regression summary',regression/'SUMMARY.json'),('Scoring summary',scoring/'SUMMARY.json')]:
        if path.is_file():
            st.markdown(f'**{name}**')
            st.json(read_json(str(path)))
    st.info('Future phases: official score cross-check, independent stint evidence, lineup/opponent matchup explorer, and restricted publishing to a curated database.')
