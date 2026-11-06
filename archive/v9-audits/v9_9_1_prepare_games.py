#!/usr/bin/env python3
"""V9.9.1: read-only batch preparation of NBA game evidence and V9.9 manifests.

Uses existing V9.4e collector in a child process. Does NOT infer, certify or
fabricate timelines; never modifies DuckDB or an existing official evidence file.
"""
import argparse
import csv
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ['game_id', 'source_status', 'pbp_rows', 'box_rows', 'rotation_status',
          'timeline_status', 'ready_for_v9_9', 'official_dir', 'timeline', 'error']
REQUIRED_FILES = ['playbyplayv3_dataset_0.csv', 'boxscoretraditionalv3_dataset_0.csv']


def read_games(path):
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or 'game_id' not in reader.fieldnames:
            raise ValueError('Input CSV must contain game_id header')
        rows = list(reader)
    if not rows:
        raise ValueError('No game IDs in input')
    ids = [str(row['game_id']).strip() for row in rows]
    if any(not re.fullmatch(r'[0-9]{10}', game_id) for game_id in ids):
        raise ValueError('All game IDs must be exactly 10 digits, preserving leading zeros')
    if len(ids) != len(set(ids)):
        raise ValueError('Input contains duplicate game IDs')
    return ids


def csv_size(path):
    if not path.is_file() or path.stat().st_size == 0:
        return 0
    try:
        with path.open('r', encoding='utf-8-sig', newline='') as f:
            return sum(1 for _ in csv.DictReader(f))
    except (OSError, UnicodeError, csv.Error):
        return 0


def inspect_evidence(folder, allow_rotation_missing):
    summary_file = folder / 'SUMMARY.json'
    if not summary_file.is_file():
        return 'MISSING_SUMMARY', 0, 0, 'UNKNOWN', 'Collector SUMMARY.json absent'
    try:
        data = json.loads(summary_file.read_text(encoding='utf-8-sig'))
        endpoints = data['endpoints']
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return 'BAD_SUMMARY', 0, 0, 'UNKNOWN', str(exc)
    pbp = csv_size(folder / REQUIRED_FILES[0]); box = csv_size(folder / REQUIRED_FILES[1])
    rot = endpoints.get('gamerotation', {}).get('status', 'NOT_REQUESTED')
    required_ok = (endpoints.get('playbyplayv3', {}).get('status') == 'SUCCESS' and
                   endpoints.get('boxscoretraditionalv3', {}).get('status') == 'SUCCESS' and
                   pbp > 0 and box > 0)
    if not required_ok:
        return 'INCOMPLETE', pbp, box, rot, 'Missing/empty essential datasets or endpoint failed'
    if not allow_rotation_missing and rot != 'SUCCESS':
        return 'ROTATION_INCOMPLETE', pbp, box, rot, 'GameRotation not successful'
    return 'READY', pbp, box, rot, ''


def save_csv(path, rows, fields):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader(); writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--games', required=True, type=Path, help='CSV with game_id column')
    parser.add_argument('--collector', default='v9_4e_collect_official.py', type=Path)
    parser.add_argument('--out', default='v9_9_1_prepared', type=Path)
    parser.add_argument('--timelines-root', default='.', type=Path,
                        help='Directory containing {game_id}/lineup_timeline_CONDITIONAL_UNVERIFIED.csv')
    parser.add_argument('--timeout', type=int, default=30)
    parser.add_argument('--retries', type=int, default=1)
    parser.add_argument('--skip-rotation', action='store_true')
    parser.add_argument('--dry-run', action='store_true', help='Do not retrieve anything')
    parser.add_argument('--refresh', action='store_true', help='Fetch into a NEW timestamped directory')
    parser.add_argument('--max-games', type=int, default=0)
    args = parser.parse_args()
    try:
        ids = read_games(args.games.resolve())
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.timeout < 1 or args.retries < 0 or args.max_games < 0:
        parser.error('--timeout >= 1, --retries >= 0, --max-games >= 0 required')
    if args.max_games:
        ids = ids[:args.max_games]
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    collector = args.collector.resolve()
    if not args.dry_run and not collector.is_file():
        parser.error(f'Collector script not found: {collector}')
    timelines_root = args.timelines_root.resolve()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    results=[]; ready=[]; pending=[]
    for count, gid in enumerate(ids, 1):
        print(f'[{count}/{len(ids)}] {gid}', flush=True)
        evidence = out / 'evidence' / gid
        error = ''
        if args.refresh and evidence.exists():
            evidence = out / 'evidence' / f'{gid}_refresh_{stamp}'
        summary_path = evidence / 'SUMMARY.json'
        if args.dry_run:
            status, pbp_rows, box_rows, rot, error = ('DRY_RUN', 0, 0, 'NOT_CHECKED', '')
        else:
            if not summary_path.exists():
                evidence.mkdir(parents=True, exist_ok=True)
                command = [sys.executable, str(collector), '--game-id', gid,
                           '--out', str(evidence), '--timeout', str(args.timeout),
                           '--retries', str(args.retries)]
                if args.skip_rotation:
                    command.append('--skip-rotation')
                try:
                    proc = subprocess.run(command, capture_output=True, text=True, timeout=3600)
                    (evidence / 'COLLECTOR.stdout.txt').write_text(proc.stdout, encoding='utf-8')
                    (evidence / 'COLLECTOR.stderr.txt').write_text(proc.stderr, encoding='utf-8')
                    if proc.returncode != 0:
                        error = f'Collector returned code {proc.returncode}; see COLLECTOR.stderr.txt'
                except (OSError, subprocess.TimeoutExpired) as exc:
                    error = f'Collector failed: {exc}'
            status, pbp_rows, box_rows, rot, inspected_error = inspect_evidence(evidence, args.skip_rotation)
            error = error or inspected_error
        # No inferred lineups are created. Only explicit local files are accepted.
        timeline = timelines_root / gid / 'lineup_timeline_CONDITIONAL_UNVERIFIED.csv'
        has_timeline = timeline.is_file() and csv_size(timeline) > 0
        timeline_status = 'EXISTING_CONDITIONAL' if has_timeline else 'MISSING_NOT_RECONSTRUCTED'
        is_ready = (status == 'READY' and has_timeline)
        result = dict(game_id=gid, source_status=status, pbp_rows=pbp_rows,
                      box_rows=box_rows, rotation_status=rot,
                      timeline_status=timeline_status, ready_for_v9_9=str(is_ready),
                      official_dir=str(evidence), timeline=str(timeline), error=error)
        results.append(result)
        (ready if is_ready else pending).append(dict(game_id=gid, official_dir=str(evidence), timeline=str(timeline)))
        save_csv(out / 'PREPARATION_STATUS.csv', results, FIELDS)
    save_csv(out / 'v9_9_READY_manifest.csv', ready, ['game_id','official_dir','timeline'])
    save_csv(out / 'v9_9_PENDING_manifest.csv', pending, ['game_id','official_dir','timeline'])
    summary = dict(version='9.9.1', mode='READ_ONLY_GAME_DATA_PREPARATION',
                   games_requested=len(ids), games_source_ready=sum(x['source_status']=='READY' for x in results),
                   games_ready_for_v9_9=len(ready), games_pending=len(pending),
                   dry_run=args.dry_run, independent_stint_certification=False,
                   production_ready=False, database_modified=False,
                   note='READY means required inputs exist, NOT that any lineup is verified or that V9.9 supports other team pairs.')
    (out / 'SUMMARY.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
