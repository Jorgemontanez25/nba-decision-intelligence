# GitHub repository cleanup plan

Do **not** delete or rewrite your local NBA database, models or audit evidence. The cleanup concerns Git tracking only.

## Recommended separation

- **Keep at repository root for now:** the working Streamlit app, its imported modules, current collection scripts, README, `.gitignore`, and documentation assets.
- **Keep locally but exclude from Git:** `*.duckdb`, `*.wal`, `*.env`, API keys, secrets, intermediate datasets, generated review folders and logs.
- **Move to `experiments/` later:** exploratory notebooks, obsolete app versions, unneeded proof-of-concept scripts (only after import dependency checking).
- **Move to `tests/` later:** stable and reproducible validation scripts, using small fixtures rather than full output folders.

## Important privacy/safety check

Adding paths to `.gitignore` prevents **new** Git tracking; it does not automatically remove previously committed content. Even removing a file in a later commit does not remove it from repository history. If secrets were previously pushed, rotate them and consider history rewriting with a backup.

## Safe one-line PowerShell checks

1. Show tracked generated files:

`git ls-files | Select-String -Pattern '\.duckdb|\.wal|\.env|secrets\.toml|v9_.*_review/|validation_.*/|history_backfill_.*'`

2. Show tracked files count:

`(git ls-files | Measure-Object -Line).Lines`

3. Preview repo changes after adding README and assets:

`git status --short`

4. Stage **only** documentation, rather than `git add .`:

`git add README.md assets REPOSITORY_CLEANUP.md`

5. Commit:

`git commit -m "docs: portfolio README and architecture visuals"`

6. Push:

`git push origin main`

If tracked sensitive files are found, do **not** push further changes until you review them; fix history exposure before enabling any public deployment.
