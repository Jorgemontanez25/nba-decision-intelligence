"""Read-only, local-data player and roster UI. No invented ratings or player availability."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from io import BytesIO
import base64, json, html
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


def _rating_tier_meta(rating):
    """Map sourced NBA 2K27 OVR to a presentation tier and accent colors."""
    if rating is None or pd.isna(rating):
        return 'NOT AVAILABLE', ('#334155', '#111827')
    rating=float(rating)
    if rating >= 95:
        return 'ELITE', ('#7c3aed', '#35106d')
    if rating >= 90:
        return 'SUPERSTAR', ('#e8b458', '#8b4b18')
    if rating >= 85:
        return 'STAR', ('#e96767', '#822132')
    if rating >= 80:
        return 'IMPACT', ('#36b5a1', '#125a62')
    if rating >= 75:
        return 'ROTATION', ('#5d97db', '#243b7c')
    return 'DEVELOPING', ('#748094', '#303848')



def render_2k_style_ovr(rating, player_name):
    """Presentation-only badge for an externally sourced NBA 2K27 OVR."""
    if rating is None:
        number = 'N/A'
        tier, colors = _rating_tier_meta(None)
    else:
        number = str(int(rating))
        tier, colors = _rating_tier_meta(rating)
    safe_name = html.escape(str(player_name))
    st.markdown(f"""
    <div style="max-width:270px;min-height:146px;border-radius:17px;padding:15px 16px;
      color:white;background:linear-gradient(140deg,{colors[0]}, {colors[1]});
      border:1px solid rgba(255,255,255,.28);box-shadow:0 8px 18px rgba(0,0,0,.28);
      text-align:center;font-family:system-ui,sans-serif;">
      <div style="font-weight:800;letter-spacing:.22em;font-size:12px;opacity:.94">NBA 2K27 · OVR</div>
      <div style="font-size:64px;font-weight:950;line-height:1.04;letter-spacing:-.06em;
        text-shadow:0 3px 10px rgba(0,0,0,.22)">{number}</div>
      <div style="display:inline-block;font-weight:800;font-size:11px;letter-spacing:.1em;
        border-radius:50px;padding:4px 13px;background:rgba(0,0,0,.24)">{tier}</div>
      <div style="font-size:11px;margin-top:9px;opacity:.85">{safe_name}</div>
    </div>""",unsafe_allow_html=True)



@st.cache_data(show_spinner=False, ttl=86400)
def _v483_headshot(player_id):
    """Embed a small NBA headshot in the iframe; keep the source code independent of CDN availability."""
    from urllib.request import Request, urlopen
    try:
        url=f'https://cdn.nba.com/headshots/nba/latest/1040x760/{int(player_id)}.png'
        with urlopen(Request(url, headers={'User-Agent':'Mozilla/5.0'}),timeout=5) as response:
            raw=response.read(1_500_000)
        from PIL import Image
        with Image.open(BytesIO(raw)) as im:
            im.thumbnail((430,320))
            buf=BytesIO(); im.convert('RGBA').save(buf,format='PNG')
            return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')
    except Exception:
        return ''


def render_roster_viewer_header(player_name, player_id, rating, stats, career):
    """NBA 2K roster-viewer-inspired player banner. Display graphics are not official 2K UI assets."""
    import streamlit.components.v1 as components
    import math
    safe_name=html.escape(str(player_name))
    photo=_v483_headshot(player_id)
    r=int(rating) if rating is not None and pd.notna(rating) else None
    r=max(0,min(99,r)) if r is not None else None
    dial='N/A' if r is None else str(r)
    frac=r/99 if r is not None else 0
    circumference=2*math.pi*64
    dash=f'{circumference*frac:.2f} {circumference:.2f}'
    tier_label, tier_colors = _rating_tier_meta(r)
    clr=('#f6d739' if r is not None and r>=85 else '#46d2c2' if r is not None and r>=75 else '#90a4bd')
    surname=safe_name.split(' ')[-1]
    first=' '.join(safe_name.split(' ')[:-1])
    games=int(career.game_id.nunique())
    seasons=int(career.season.nunique())
    teams=int(career.team_abbr.nunique()) if 'team_abbr' in career else 0
    portrait=f'<img class="portrait" src="{photo}" alt="{safe_name} portrait"/>' if photo else '<div class="portrait-placeholder">PLAYER</div>'
    sample=f'{games} games · {seasons} seasons · {teams} historical team(s)'
    html_markup=f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
    *{{box-sizing:border-box}}
    body{{margin:0;background:transparent;font-family:Inter,Arial,system-ui,sans-serif;color:#f5f8ff}}
    .banner{{position:relative;display:flex;align-items:center;min-height:263px;overflow:hidden;border:1px solid #1d5064;border-radius:12px;background:linear-gradient(105deg,#183e58 0%,#0b2439 42%,#07192b 100%);box-shadow:0 12px 34px #0005}}
    .banner::before{{content:'';position:absolute;inset:0;background:repeating-linear-gradient(120deg,transparent 0px,transparent 43px,#ffffff08 44px,#ffffff08 45px);pointer-events:none}}
    .topline{{position:absolute;top:14px;left:22px;letter-spacing:.2em;font-size:11px;font-weight:850;color:#d2e4ee}}
    .photo-area{{height:244px;width:30%;min-width:200px;position:relative;display:flex;align-items:flex-end;justify-content:center;z-index:1;overflow:hidden}}
    .portrait{{width:96%;height:225px;object-fit:contain;object-position:bottom center;filter:drop-shadow(0 12px 15px #0009)}}
    .portrait-placeholder{{font-size:25px;font-weight:850;color:#547084;margin-bottom:80px}}
    .ring{{position:relative;flex:0 0 158px;height:158px;display:grid;place-items:center;z-index:2;margin-left:-10px}}
    .ring svg{{position:absolute;inset:0;width:100%;height:100%;transform:rotate(-90deg)}}
    .ring-inner{{z-index:2;display:flex;flex-direction:column;align-items:center;justify-content:center;border-radius:50%;width:120px;height:120px;background:#091723ee}}
    .ring-label{{font-size:12px;font-weight:900;letter-spacing:.12em;color:#dbe9f3}}
    .ring-num{{font-size:54px;letter-spacing:-.04em;font-weight:950;line-height:1.05}}
    .details{{padding:32px 22px 21px 28px;flex:1;z-index:1;min-width:0}}
    .firstname{{font-size:19px;color:#d3dfec;line-height:1.08}}
    .lastname{{font-size:clamp(24px,3vw,38px);font-weight:900;line-height:1.06;overflow-wrap:anywhere}}
    .subline{{font-size:12px;color:#9eb4c8;margin-top:12px;line-height:1.7}}
    .tier-pill{{margin-top:10px;display:inline-block;padding:5px 10px;border-radius:999px;background:linear-gradient(135deg,{tier_colors[0]}, {tier_colors[1]});font-size:11px;font-weight:900;letter-spacing:.08em;color:#fff;box-shadow:0 6px 16px #0004}}
    .sample{{margin-top:15px;display:inline-block;padding:8px 12px;background:#062338;border-left:3px solid {clr};border-radius:3px;font-size:12px;font-weight:700;color:#d7e9f5}}
    .source{{font-size:10px;margin-top:11px;color:#9db7c7}}
    @media(max-width:660px){{.banner{{min-height:215px}}.photo-area{{width:28%;min-width:105px;height:205px}}.portrait{{height:172px}}.ring{{flex-basis:112px;height:112px;margin-left:-10px}}.ring-inner{{width:84px;height:84px}}.ring-num{{font-size:34px}}.details{{padding:27px 8px 12px 8px}}.firstname{{font-size:13px}}.lastname{{font-size:22px}}.sample{{font-size:10px}}}}
    </style></head><body><div class="banner">
      <div class="topline">PLAYER PROFILE · NBA 2K27</div>
      <div class="photo-area">{portrait}</div>
      <div class="ring"><svg viewBox="0 0 158 158" aria-hidden="true"><circle cx="79" cy="79" r="64" fill="none" stroke="#334454" stroke-width="13"/><circle cx="79" cy="79" r="64" fill="none" stroke="{clr}" stroke-width="13" stroke-linecap="round" stroke-dasharray="{dash}"/></svg><div class="ring-inner"><span class="ring-label">OVR</span><span class="ring-num">{dial}</span></div></div>
      <div class="details"><div class="firstname">{first}</div><div class="lastname">{surname}</div><div class="subline">2K27 roster OVR · {('Sourced rating' if r is not None else 'Rating unavailable')}</div><div class="tier-pill">{tier_label}</div><div class="sample">{sample}</div><div class="source">OVR from your local 2K27 ratings CSV · performance stats below from DuckDB</div></div>
    </div></body></html>"""
    components.html(html_markup,height=273,scrolling=False)


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
    # Ratings from independently sourced 2K27 roster cache only. Never derive
    # a game rating from points, rebounds or other NBA box-score metrics.
    import unicodedata
    def norm_name(s): return ''.join(c for c in unicodedata.normalize('NFKD', str(s)).casefold() if c.isalnum())
    rating=None
    cache=Path('nba_2k27_ratings.csv')
    if cache.exists():
        ratings=pd.read_csv(cache)
        matches=ratings[ratings.name_key==norm_name(label.split(' (')[0])] if 'name_key' in ratings else pd.DataFrame()
        if len(matches)==1:rating=int(matches.iloc[0].overall)
    st.markdown('#### Player')
    render_roster_viewer_header(label.split(' (')[0], player_id, rating, stats, df)
    st.markdown('**Career statistics from collected NBA games**')
    cols=st.columns(6)
    for col,(k,v) in zip(cols,stats.items()):
        col.metric(k, '—' if v is None else f'{v:.1f}')
    names=['Scoring','Playmaking','Rebounding','Defense act.','3PT volume','Efficiency']
    anchors=[35,12,17,5,6,75]
    vals=[stats[k] for k in stats]
    normal=[min(100,max(0,v/a*100)) if v is not None else 0 for v,a in zip(vals,anchors)]
    with st.expander('Career statistical radar · box-score data (not official 2K ratings)',expanded=False):
        fig=go.Figure(go.Scatterpolar(r=normal+normal[:1],theta=names+names[:1],fill='toself',line=dict(color='#A78BFA',width=3),fillcolor='rgba(167,139,250,.27)',customdata=vals+vals[:1],hovertemplate='%{theta}<br>Actual: %{customdata:.1f}<extra></extra>'))
        fig.update_layout(height=350,margin=dict(l=55,r=55,t=22,b=38),showlegend=False,polar=dict(radialaxis=dict(range=[0,100],visible=False)),paper_bgcolor='rgba(0,0,0,0)',font=dict(color='#e9edf4'))
        st.plotly_chart(fig,use_container_width=True)
    st.caption('The OVR is sourced from the local NBA 2K27 cache, not inferred from box scores. The career rates are computed separately from available NBA game records.')


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
    mode=st.segmented_control('Sort roster by',options=['Jersey','Games','MPG','PTS','REB','AST','Name'],default='PTS',key='v45_roster_sort')
    if mode=='Games':merged=merged.sort_values('games',ascending=False)
    elif mode in {'MPG','PTS','REB','AST'}:merged=merged.sort_values({'MPG':'mpg','PTS':'ppg','REB':'rpg','AST':'apg'}[mode],ascending=False,na_position='last')
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
    st.caption('MPG, PTS, REB and AST are per-game averages across locally collected seasons and prior franchises; missing values sort last. Roster dates come from the local snapshot; displayed performance uses all locally stored seasons and franchises. No real-time injury or active-game lineup status is implied.')


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
