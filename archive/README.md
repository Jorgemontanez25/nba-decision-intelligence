# Archive — moved, not deleted

Nothing in this folder was deleted. Files were moved here on 2026-11-06
from the repository root to keep the live app easy to navigate. Everything
is still tracked in Git, and full history is preserved — use
`git log --follow -- <path>` to see a file's earlier history.

## What is here

- `v9-audits/` — 36 `v9_*` stint-reconstruction pilots, solvers, and audit
  scripts (v9.1 through v9.9.10). They are historical audit evidence for
  lineup reconstruction, not imported by the live app. They import each
  other by bare module name, so run them from inside `v9-audits/` if you
  need to re-run one, not from the repository root.
- `legacy-apps/` — the old `app.py` NBA Lineup Lab MVP, the superseded
  `decision_center_v481.py` (replaced by `decision_center_v492.py`), and
  the separate `nba_web_mvp/` app.
- `legacy-scripts/` — v45/v46/v47 refresh, coverage, visuals, and audit
  scripts that the live app no longer imports (`v46_coverage_and_backfill.py`, `v46_visuals.py`, `v47_2k27_refresh.py`,
  `v47_history_audit.py`, `v47_history_audit_fixed.py`). The live app
  uses `v45_visuals.py` and `v47_visuals.py` at the root.
- `notes/gitignore-duplicate.txt` — the stray file formerly named
  `gitignore` at the root. It duplicated `.gitignore` and was not itself
  a gitignore file. `.gitignore` at the root is the real one.


> Note: `v45_daily_refresh.py` was initially moved here and then restored to the repository root on 2026-11-07 — it is the live current-season updater (default season 2026–27) and sets `ROOT` from its own location, so it must stay at the root to find `roster_2026_27.py`, `collect_schedule_v7.py`, and `nba_current.duckdb`.

## What was untracked, not moved

`data_refresh_v45/` and `history_backfill_v46/` (8 log/CSV/JSON files)
were removed from Git tracking with `git rm --cached`. They were already
listed in `.gitignore`. The files were **not** deleted from disk — they
stay in a local checkout — and they remain in Git history. Do not commit
generated logs, coverage CSVs, or DuckDB files.

## What stays live at the root

`app_decision_cloud.py` (hosted) and `app_decision_v492.py` (local),
plus the modules they import: `analysis`, `collect_shots`,
`decision_center_v492`, `lineup_engine`, `roster_2026_27`,
`team_branding`, `v45_visuals`, `v47_visuals`, `collector`, and
`reconstruct_lineups` (used by the tests). Collection and validation
scripts that are still usable were left at the root for now — moving
them would require fixing their bare imports, and is a separate step.

## Restoring something

To restore a file to the root: `git mv archive/<folder>/<file> ./<file>`
on a branch, run the tests, and open a pull request. Do not copy files
by hand — that loses the rename history.
