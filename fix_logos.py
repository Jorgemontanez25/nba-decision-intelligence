
from pathlib import Path
from urllib.request import Request, urlopen

TEAMS = {
    "NOP": "1610612740",
    "UTA": "1610612762",
}

folder = Path("assets/logos")
folder.mkdir(parents=True, exist_ok=True)

for abbreviation, team_id in TEAMS.items():
    url = (
        f"https://cdn.nba.com/logos/nba/"
        f"{team_id}/primary/L/logo.svg"
    )

    try:
        request = Request(
            url, headers={"User-Agent": "Mozilla/5.0"}
        )
        with urlopen(request, timeout=20) as response:
            content = response.read()

        if b"<svg" not in content[:1000]:
            raise ValueError("Response is not an SVG image")

        destination = folder / f"{abbreviation}.svg"
        destination.write_bytes(content)

        print(f"{abbreviation}: saved {destination}")

    except Exception as exc:
        print(f"{abbreviation}: FAILED - {exc}")

