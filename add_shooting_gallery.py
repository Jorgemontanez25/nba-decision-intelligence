"""Add a clearly labeled static shooting gallery to the existing cloud loader.

No raw shooting data is uploaded or bundled by this patch.
"""
from pathlib import Path

p = Path('cloud_data.py')
if not p.exists():
    raise SystemExit('ERROR: Run from your nba_platform_v5 project folder.')
s = p.read_text(encoding='utf-8')
anchor = "    st.info('To open the full NBA Decision Intelligence dashboard, upload a compatible .duckdb snapshot using the sidebar. The original application and its analytics have not been changed.')"
if 'SHOOTING_PORTFOLIO_GALLERY_V1' in s:
    print('Gallery already installed; nothing changed.')
    raise SystemExit(0)
if anchor not in s:
    raise SystemExit('ERROR: The expected cloud loader section was not found. No files changed.')
insert = '''    # SHOOTING_PORTFOLIO_GALLERY_V1 — static screenshots, not live event feeds.
    st.divider()
    st.subheader('Shooting Showcase — Research Screenshots')
    st.caption('Examples produced in the local research environment. These are static images, not interactive live shooting data. Published display is subject to underlying NBA data and image rights.')
    col1, col2 = st.columns(2)
    with col1:
        chart = ROOT / 'assets' / 'shooting-shot-chart.png'
        if chart.is_file():
            st.image(str(chart), caption='Example shot chart (local research dashboard)', use_container_width=True)
        else:
            st.info('Shot-chart image not included in this deployment.')
    with col2:
        heatmap = ROOT / 'assets' / 'shooting-heatmap.png'
        if heatmap.is_file():
            st.image(str(heatmap), caption='Example shot-density heatmap: brighter indicates greater attempt density, not accuracy', use_container_width=True)
        else:
            st.info('Heatmap image not included in this deployment.')
    st.caption('For the interactive shot-chart, heatmap, and zone-efficiency tools, a compatible authorized snapshot containing shot_events is required.')
'''
s = s.replace(anchor, insert + '\n' + anchor, 1)
import ast
ast.parse(s, filename=str(p))
p.write_text(s, encoding='utf-8')
print('Updated cloud_data.py. Static gallery will appear when no database is loaded.')
