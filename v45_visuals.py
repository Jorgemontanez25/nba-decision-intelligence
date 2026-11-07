"""Read-only, local-data player and roster UI. No invented ratings or player availability."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from io import BytesIO
import base64, json
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


def render_player_snapshot(career: pd.DataFrame, label: str, player_id):
    """NBA video-game-inspired visual; all values measured box-score statistics."""
    df = career.copy()
    for c in ('points','assists','rebounds','steals','blocks','turnovers','fga','fta','fgm','fg3m','fg3a','minutes'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    minutes = df['minutes'].sum()
    if not minutes or pd.isna(minutes):
        return
    rate=lambda c: float(df[c].sum()/minutes*36)
    ts_den = 2*(df.fga.sum() + .44*df.fta.sum())
    ts = float(df.points.sum()/ts_den*100) if ts_den else None
    stats = {
        'PTS / 36': rate('points'), 'AST / 36': rate('assists'),
        'REB / 36': rate('rebounds'), 'STL+BLK /36': rate('steals')+rate('blocks'),
        '3PM /36': rate('fg3m'), 'TS%': ts,
    }
    st.markdown('#### Player Snapshot · career sample')
    left,right=st.columns([1,3])
    with left:
        st.image(f'https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png', width=165)
        st.markdown('**'+label.split(' (')[0]+'**')
        st.caption(f'{df.game_id.nunique()} local games · {df.season.nunique()} seasons · {df.team_abbr.nunique()} teams')
    with right:
        cols=st.columns(3)
        for i,(k,v) in enumerate(stats.items()):
            cols[i%3].metric(k, '—' if v is None else f'{v:.1f}')
        # No fake 0–99 game ratings. Descriptive metrics normalized relative to
        # fixed display anchors, with actual values visible in hover and metrics.
        names=['Scoring','Playmaking','Rebounding','Defense act.','3PT volume','Efficiency']
        anchors=[35,12,17,5,6,75]
        vals=[stats[k] for k in stats]
        normal=[min(100,max(0,v/a*100)) if v is not None else 0 for v,a in zip(vals,anchors)]
        fig=go.Figure(go.Scatterpolar(r=normal+normal[:1],theta=names+names[:1],fill='toself',line=dict(color='#A78BFA',width=3),fillcolor='rgba(167,139,250,.27)',customdata=vals+vals[:1],hovertemplate='%{theta}<br>Actual: %{customdata:.1f}<extra></extra>'))
        fig.update_layout(height=330,margin=dict(l=45,r=45,t=12,b=35),showlegend=False,polar=dict(radialaxis=dict(range=[0,100],visible=False)),paper_bgcolor='rgba(0,0,0,0)',font=dict(color='#e9edf4'))
        st.plotly_chart(fig,use_container_width=True)
    st.caption('Video-game-inspired presentation only. Values are observed box-score rates, not official NBA 2K attributes, player ratings, or predictions. Chart axes are illustrative scales.')


def render_fantasy_roster(con, roster:pd.DataFrame, team:str):
    roster=roster.copy();roster['player_id']=roster.player_id.astype(str)
    ids=roster.player_id.tolist()
    hist=con.execute('''SELECT CAST(player_id AS VARCHAR) AS player_id, COUNT(DISTINCT game_id) AS games,
           COUNT(DISTINCT season) AS seasons, MAX(game_date) AS last_game,
           ROUND(AVG(points),1) AS ppg, ROUND(AVG(rebounds),1) AS rpg, ROUND(AVG(assists),1) AS apg,
           ROUND(AVG(minutes),1) AS mpg
           FROM player_games WHERE minutes>0 GROUP BY player_id''').df()
    merged=roster.merge(hist,on='player_id',how='left',validate='one_to_one')
    shots=con.execute('SELECT CAST(player_id AS VARCHAR) player_id, COUNT(*) AS shots FROM shot_events GROUP BY player_id').df()
    merged=merged.merge(shots,on='player_id',how='left',validate='one_to_one')
    merged['games']=pd.to_numeric(merged['games'],errors='coerce').fillna(0).astype(int)
    merged['shots']=pd.to_numeric(merged['shots'],errors='coerce').fillna(0).astype(int)
    st.metric('Players on roster snapshot',len(merged))
    mode=st.segmented_control('Sort roster by',options=['Jersey','Games','Name'],default='Jersey',key='v45_roster_sort')
    if mode=='Games':merged=merged.sort_values('games',ascending=False)
    elif mode=='Name':merged=merged.sort_values('player_name')
    else:
        merged['_num']=pd.to_numeric(merged.jersey,errors='coerce');merged=merged.sort_values(['_num','player_name'],na_position='last')
    hdr=st.columns([.6,3,1.1,1.1,1.1,1.1,1.1,1.2])
    for col,title in zip(hdr,['SLOT','PLAYER','GP','MPG','PTS','REB','AST','DATA']):col.markdown('**'+title+'**')
    for r in merged.itertuples():
        cols=st.columns([.6,3,1.1,1.1,1.1,1.1,1.1,1.2],vertical_alignment='center')
        cols[0].write('#'+str(r.jersey).replace('.0','') if str(r.jersey).strip() else '—')
        with cols[1]:
            photo,name=st.columns([1,3],vertical_alignment='center')
            with photo:st.image(f'https://cdn.nba.com/headshots/nba/latest/260x190/{r.player_id}.png',use_container_width=True)
            with name:
                st.markdown('**'+str(r.player_name)+'**')
                st.caption(f'{team} · {r.position or "Position N/A"}')
        for col,v in zip(cols[2:7],[r.games,r.mpg,r.ppg,r.rpg,r.apg]):
            col.write('—' if pd.isna(v) else str(v))
        with cols[7]:
            if r.games==0:st.caption('No games')
            elif r.shots==0:st.caption('Box only')
            else:st.caption('Box + shots')
    st.caption('Roster dates come from the local snapshot; displayed performance uses all locally stored seasons and franchises. No real-time injury or active-game lineup status is implied.')


def add_face_markers(fig, player_id, x, y, team_color, cached_image_fn):
    """Plotly receives a circular PNG data URI; no browser-side CDN embedding."""
    raw=cached_image_fn(player_id)
    if not raw:return
    try:
        from PIL import Image,ImageDraw,ImageOps
        if raw.startswith('data:'):raw=raw.split(',',1)[1]
        image=Image.open(BytesIO(base64.b64decode(raw))).convert('RGBA')
        # Full NBA headshots have a lot of padding. Crop around upper face/torso.
        w,h=image.size
        crop=image.crop((int(w*.17),0,int(w*.83),int(h*.78)))
        crop=ImageOps.fit(crop,(108,108),centering=(.5,.18))
        mask=Image.new('L',(108,108),0);d=ImageDraw.Draw(mask);d.ellipse((1,1,106,106),fill=255)
        bg=Image.new('RGBA',(108,108),team_color);bg.putalpha(mask)
        bg.alpha_composite(crop)
        # Crop outside circle after composing.
        bg.putalpha(mask)
        draw=ImageDraw.Draw(bg);draw.ellipse((2,2,105,105),outline='white',width=4)
        buf=BytesIO();bg.save(buf,format='PNG')
        source='data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()
        fig.add_layout_image(dict(source=source,x=x,y=y,sizex=10,sizey=10,xanchor='center',yanchor='middle',sizing='contain',layer='above'))
    except Exception:
        return


def show_refresh_health():
    path=Path('data_refresh_v45')/'latest.json'
    with st.expander('Data refresh status',expanded=False):
        if not path.exists():
            st.info('No local daily refresh report yet. Run v45_daily_refresh.py after configuring collection.')
            return
        try:
            r=json.loads(path.read_text(encoding='utf-8'))
            st.write('Last refresh:',r.get('ended_utc','Unknown'))
            st.write('Status:',r.get('status','Unknown'))
            st.dataframe(pd.DataFrame(r.get('jobs',[])),hide_index=True,use_container_width=True)
        except Exception as e:
            st.error(f'Could not read refresh report: {e}')
