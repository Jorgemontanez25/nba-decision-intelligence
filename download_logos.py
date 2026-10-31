"""Optional official/third-party logo cache for Streamlit; respects failed requests."""
from pathlib import Path
from urllib.request import Request, urlopen
from team_branding import TEAMS

out = Path(__file__).parent / 'assets' / 'logos'
out.mkdir(parents=True, exist_ok=True)
for abbr in TEAMS:
    url = f'https://a.espncdn.com/i/teamlogos/nba/500/{abbr.lower()}.png'
    try:
        with urlopen(Request(url, headers={'User-Agent':'Mozilla/5.0'}), timeout=12) as response:
            data = response.read(1_000_000)
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            print(f'{abbr}: not a PNG; skipped')
            continue
        (out / f'{abbr}.png').write_bytes(data)
        print(f'{abbr}: cached')
    except Exception as e:
        print(f'{abbr}: unavailable ({e})')
print('Finished. Missing logos will continue to use the abbreviation fallback.')
