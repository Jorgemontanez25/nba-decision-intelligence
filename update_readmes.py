"""Idempotently add accurate cloud/shooting showcase notes to branch READMEs.

Run on each branch separately; does not overwrite other sections.
"""
from pathlib import Path

START = '<!-- CLOUD_SHOWCASE_STATUS_START -->'
END = '<!-- CLOUD_SHOWCASE_STATUS_END -->'
BLOCK = '''<!-- CLOUD_SHOWCASE_STATUS_START -->
## Hosted portfolio and shooting-data status (November 2026)

**Live app:** https://nba-decision-intelligence.streamlit.app/  
**Deployment branch:** `release/streamlit-cloud`  
**Entrypoint:** `app_decision_cloud.py`

The original Streamlit dashboard has been launched online. With a compatible,
authorized `.duckdb` file supplied through the session uploader, its player-game
analytics and box-score-based decision-support views can be explored. **A freshly
opened session does not automatically have a populated database**: the cloud
loader expects an authorized private snapshot or a compatible file supplied by
an authorized user. The session upload is temporary, not a persistent public
dataset. The public link alone does not guarantee populated data for visitors.

### Shooting showcase

The original research environment includes actual NBA.com-derived shot-event
coordinates, makes/misses and shot distances, used for shot charts, density
heatmaps and zone-efficiency maps. The currently tested cloud-compatible
game-log snapshot has **no `shot_events`**, so these visuals are unavailable
when that snapshot is selected. No shot coordinates are simulated.

`build_shooting_showcase.py` creates a **local-only** extract of selected player
shot events and their corresponding game/box-score records from an existing
local DuckDB database. Example:

```powershell
.\\.venv\\Scripts\\python.exe .\\build_shooting_showcase.py --source nba_current.duckdb --out nba_shooting_showcase_LOCAL_ONLY.duckdb --seasons 2025-26 2026-27
```

This file must **not** be committed to a public repository or uploaded to
third-party hosting without confirming the necessary rights. A noncommercial
portfolio purpose, crediting the source, or extracting a small sample does not
alone confer rights to republish NBA-derived event-level records or charts.

The 5v5 Decision Center includes *experimental box-score-based rankings*;
it is not a validated lineup win-probability or certified historical lineup
impact model. Verified stint coverage and the availability of roster snapshots
are separately reported in the app.

**Deployment next steps:** establish an authorized source for persistent cloud
player-game and shot-event data; verify row counts, missing coverage and feature
rendering after deployment; keep secrets and raw research databases out of Git.
<!-- CLOUD_SHOWCASE_STATUS_END -->'''


def update(path: Path):
    if not path.exists():
        raise FileNotFoundError(path)
    original = path.read_text(encoding='utf-8')
    if START in original and END in original:
        a = original.index(START)
        b = original.index(END, a) + len(END)
        updated = original[:a] + BLOCK + original[b:]
    else:
        anchor = '## Technology'
        if anchor in original:
            updated = original.replace(anchor, BLOCK + '\n\n' + anchor, 1)
        else:
            updated = original.rstrip() + '\n\n' + BLOCK + '\n'
    # Only remove an outdated deployment claim when present.
    updated = updated.replace('**Streamlit Community Cloud is not deployed yet.**', '**Streamlit Community Cloud deployment exists.**')
    updated = updated.replace('- [ ] Hosted Streamlit dashboard', '- [x] Hosted Streamlit app deployed (authorized data must be supplied separately)')
    path.write_text(updated, encoding='utf-8')
    print('Updated:', path)


if __name__ == '__main__':
    update(Path('README.md'))
