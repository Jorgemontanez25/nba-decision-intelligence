"""Team names and robust logo display; fallback shows team abbreviation."""
from pathlib import Path
from urllib.request import Request, urlopen

import streamlit as st

TEAMS = {
'ATL':('Atlanta Hawks',1610612737),'BOS':('Boston Celtics',1610612738),
'BKN':('Brooklyn Nets',1610612751),'CHA':('Charlotte Hornets',1610612766),
'CHI':('Chicago Bulls',1610612741),'CLE':('Cleveland Cavaliers',1610612739),
'DAL':('Dallas Mavericks',1610612742),'DEN':('Denver Nuggets',1610612743),
'DET':('Detroit Pistons',1610612765),'GSW':('Golden State Warriors',1610612744),
'HOU':('Houston Rockets',1610612745),'IND':('Indiana Pacers',1610612754),
'LAC':('LA Clippers',1610612746),'LAL':('Los Angeles Lakers',1610612747),
'MEM':('Memphis Grizzlies',1610612763),'MIA':('Miami Heat',1610612748),
'MIL':('Milwaukee Bucks',1610612749),'MIN':('Minnesota Timberwolves',1610612750),
'NOP':('New Orleans Pelicans',1610612740),'NYK':('New York Knicks',1610612752),
'OKC':('Oklahoma City Thunder',1610612760),'ORL':('Orlando Magic',1610612753),
'PHI':('Philadelphia 76ers',1610612755),'PHX':('Phoenix Suns',1610612756),
'POR':('Portland Trail Blazers',1610612757),'SAC':('Sacramento Kings',1610612758),
'SAS':('San Antonio Spurs',1610612759),'TOR':('Toronto Raptors',1610612761),
'UTA':('Utah Jazz',1610612762),'WAS':('Washington Wizards',1610612764)
}

def logo_url(abbr):
    info = TEAMS.get(abbr)
    return f'https://cdn.nba.com/logos/nba/{info[1]}/primary/L/logo.svg' if info else None

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_logo(abbr):
    """Download image bytes server-side; no external URL passed to Streamlit client."""
    if abbr not in TEAMS:
        return None
    team_id = TEAMS[abbr][1]
    urls = [
        f'https://cdn.nba.com/logos/nba/{team_id}/primary/L/logo.svg',
        f'https://a.espncdn.com/i/teamlogos/nba/500/{abbr.lower()}.png',
    ]
    for url in urls:
        try:
            req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urlopen(req, timeout=5) as response:
                content = response.read(1_000_000)
                ctype = response.headers.get('Content-Type', '')
            if content and ('image/' in ctype or content.startswith((b'\x89PNG', b'<svg', b'<?xml'))):
                return content
        except Exception:
            continue
    return None


def render_team_brand(abbr):
    label = TEAMS[abbr][0]

    # First try locally stored logos
    local_folder = Path("assets/logos")

    for extension in (".png", ".svg"):
        local_file = local_folder / f"{abbr}{extension}"

        if local_file.is_file():
            try:
                st.image(str(local_file), width=96)
                st.subheader(label)
                return
            except Exception:
                pass

    # If no local logo works, try downloading it
    image_bytes = fetch_logo(abbr)

    if image_bytes is not None:
        try:
            st.image(image_bytes, width=96)
            st.subheader(label)
            return
        except Exception:
            pass

    # Final fallback
    st.markdown(f"### {abbr}")
    st.subheader(label)
