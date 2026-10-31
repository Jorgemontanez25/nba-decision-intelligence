"""V9.4e: read-only acquisition of independent NBA Stats responses.

No DuckDB modifications, no certified lineup inference.
"""
import argparse
import csv
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from nba_api.stats.endpoints import playbyplayv3, boxscoretraditionalv3, gamerotation


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding='utf-8')


def save_dataframe_csv(df, path):
    df.to_csv(path, index=False, encoding='utf-8-sig')


def fetch(name, cls, params, out, timeout, retries):
    last_error = None
    for attempt in range(1, retries + 2):
        try:
            endpoint = cls(**params, timeout=timeout)
            raw = endpoint.get_json()
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(parsed, dict):
                raise ValueError('Unexpected non-object API response')
            raw_path = out / f'{name}_raw.json'
            write_json(raw_path, parsed)
            datasets = endpoint.get_data_frames()
            csv_files = []
            row_counts = []
            for ix, df in enumerate(datasets):
                path = out / f'{name}_dataset_{ix}.csv'
                save_dataframe_csv(df, path)
                csv_files.append(str(path.name))
                row_counts.append(len(df))
            return {
                'status': 'SUCCESS', 'attempts': attempt,
                'raw_file': raw_path.name,
                'sha256': hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                'dataset_files': csv_files, 'dataset_row_counts': row_counts,
                'dataset_columns': [list(df.columns) for df in datasets],
            }
        except Exception as exc:
            last_error = f'{type(exc).__name__}: {exc}'
            if attempt <= retries:
                time.sleep(min(2 * attempt, 6))
    return {'status': 'FAILED', 'attempts': retries + 1, 'error': last_error}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game-id', default='0022500002')
    ap.add_argument('--out', default='v9_4e_official_evidence')
    ap.add_argument('--timeout', type=int, default=30)
    ap.add_argument('--retries', type=int, default=1)
    ap.add_argument('--skip-rotation', action='store_true')
    args = ap.parse_args()
    if not re.fullmatch(r'\d{10}', args.game_id):
        ap.error('--game-id must be exactly 10 digits')
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    targets = [
        ('playbyplayv3', playbyplayv3.PlayByPlayV3, {'game_id': args.game_id, 'start_period': 0, 'end_period': 0}),
        ('boxscoretraditionalv3', boxscoretraditionalv3.BoxScoreTraditionalV3, {'game_id': args.game_id}),
    ]
    if not args.skip_rotation:
        targets.append(('gamerotation', gamerotation.GameRotation, {'game_id': args.game_id, 'league_id': '00'}))
    summary = {
        'game_id': args.game_id,
        'retrieved_at_utc': datetime.now(timezone.utc).isoformat(),
        'mode': 'READ_ONLY_SOURCE_ACQUISITION',
        'endpoints': {},
        'caveats': [
            'Import success does not guarantee NBA endpoints respond.',
            'GameRotation may be unavailable or incomplete for this game.',
            'Rotation in/out time units must be validated before transforming them.',
            'NBA V3 and local data may derive from the same underlying NBA records; matching does not necessarily prove independent substitution effective-time accuracy.',
            'No game stints or player plus/minus values are certified by this collector.',
        ],
    }
    for name, cls, params in targets:
        print(f'Fetching {name} for {args.game_id} ...', flush=True)
        result = fetch(name, cls, params, out, args.timeout, args.retries)
        summary['endpoints'][name] = result
        print(f'  {result["status"]}; rows={result.get("dataset_row_counts", [])}; {result.get("error", "")}', flush=True)
        write_json(out / 'SUMMARY.json', summary)
        time.sleep(1)
    print(f'Reports: {out}')
    if any(r['status'] == 'FAILED' for r in summary['endpoints'].values()):
        print('One or more endpoints failed; successful responses have been preserved. See SUMMARY.json.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
