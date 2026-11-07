#!/usr/bin/env python3
"""V9.9: Read-only multi-game validation orchestrator for V9.8.5.

This runner does not infer lineups or select attribution rules. It calls the
existing V9.8.5 audit independently for each manifest row and aggregates its
reported results. Any unverified game stays unverified, regardless of fit.
"""
import argparse
import csv
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

FIELDS = [
    'game_id', 'run_status', 'audit_status', 'source_actions',
    'substitutions_parsed', 'substitutions_applied', 'scoring_events',
    'boundary_scoring_events', 'events_with_before_after_assignment_difference',
    'unassigned_events', 'issue_count', 'recorded_matches', 'recorded_abs_error',
    'before_matches', 'before_abs_error', 'after_matches', 'after_abs_error',
    'verified_stints', 'publication_gate', 'final_LAL', 'final_GSW',
    'official_dir', 'timeline', 'results_dir', 'error'
]


def read_manifest(path):
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        required = {'game_id', 'official_dir', 'timeline'}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError('Manifest must have columns game_id,official_dir,timeline')
        rows = list(reader)
    if not rows:
        raise ValueError('Manifest has no game rows')
    ids = [str(r['game_id']).strip() for r in rows]
    if any(not re.fullmatch(r'\d{10}', x) for x in ids):
        raise ValueError('Every game_id must be a 10-digit text identifier (preserve leading zeros)')
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate game_id in manifest')
    return rows


def path_from_manifest(value, manifest_path):
    p = Path(value.strip()).expanduser()
    if p.is_absolute():
        return p.resolve()
    # Resolve relative to the working directory first, convenient for the
    # existing nba_platform_v5 PowerShell workflow. Fall back to manifest folder.
    cwd_candidate = (Path.cwd() / p).resolve()
    local_candidate = (manifest_path.parent / p).resolve()
    return cwd_candidate if cwd_candidate.exists() else local_candidate


def write_csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--manifest', required=True, type=Path, help='CSV: game_id,official_dir,timeline')
    ap.add_argument('--audit-script', default='v9_8_5_scoring_integrity.py', type=Path)
    ap.add_argument('--out', default='v9_9_multi_game_review', type=Path)
    ap.add_argument('--max-games', type=int, default=0, help='0 = all rows')
    args = ap.parse_args()
    manifest = args.manifest.resolve()
    audit_script = args.audit_script.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not audit_script.is_file():
        ap.error(f'Audit script not found: {audit_script}')
    try:
        games = read_manifest(manifest)
    except (OSError, ValueError) as exc:
        ap.error(str(exc))
    if args.max_games < 0:
        ap.error('--max-games must be >= 0')
    if args.max_games:
        games = games[:args.max_games]
    results = []
    for i, game in enumerate(games, 1):
        game_id = str(game['game_id']).strip()
        official_dir = path_from_manifest(game['official_dir'], manifest)
        timeline = path_from_manifest(game['timeline'], manifest)
        dest = out / game_id
        dest.mkdir(exist_ok=True)
        record = {name: '' for name in FIELDS}
        record.update(game_id=game_id, official_dir=str(official_dir), timeline=str(timeline), results_dir=str(dest))
        print(f'[{i}/{len(games)}] {game_id}', flush=True)
        missing = []
        if not official_dir.is_dir():
            missing.append(f'official_dir missing: {official_dir}')
        if not timeline.is_file():
            missing.append(f'timeline missing: {timeline}')
        if missing:
            record.update(run_status='MISSING_INPUT', error='; '.join(missing))
            results.append(record)
            continue
        cmd = [sys.executable, str(audit_script), '--game-id', game_id,
               '--official-dir', str(official_dir), '--timeline', str(timeline), '--out', str(dest)]
        try:
            process = subprocess.run(cmd, text=True, encoding='utf-8', errors='replace', capture_output=True, check=False)
            (dest / 'runner_stdout.txt').write_text(process.stdout, encoding='utf-8')
            (dest / 'runner_stderr.txt').write_text(process.stderr, encoding='utf-8')
        except OSError as exc:
            record.update(run_status='EXECUTION_ERROR', error=str(exc))
            results.append(record)
            continue
        summary_path = dest / 'SUMMARY.json'
        if process.returncode != 0 or not summary_path.is_file():
            record.update(run_status='AUDIT_FAILED', error=f'exit_code={process.returncode}; summary_present={summary_path.is_file()}')
            results.append(record)
            continue
        try:
            summary = json.loads(summary_path.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError) as exc:
            record.update(run_status='INVALID_SUMMARY', error=str(exc))
            results.append(record)
            continue
        if str(summary.get('game_id', '')) != game_id:
            record.update(run_status='GAME_ID_MISMATCH', error='SUMMARY.json game_id does not match manifest')
            results.append(record)
            continue
        if str(summary.get('version', '')) != '9.8.5':
            record.update(run_status='VERSION_MISMATCH', error=f"Expected V9.8.5; got {summary.get('version')!r}")
            results.append(record)
            continue
        scenario = summary.get('scenario_results') or {}
        score = summary.get('final_score') or {}
        record.update(
            run_status='COMPLETED', audit_status=summary.get('status', ''),
            source_actions=summary.get('source_actions', ''),
            substitutions_parsed=summary.get('substitutions_parsed', ''),
            substitutions_applied=summary.get('substitutions_applied', ''),
            scoring_events=summary.get('scoring_events', ''),
            boundary_scoring_events=summary.get('boundary_scoring_events', ''),
            events_with_before_after_assignment_difference=summary.get('events_with_before_after_assignment_difference', ''),
            unassigned_events=summary.get('unassigned_events', ''),
            issue_count=summary.get('issue_count', ''),
            verified_stints=summary.get('verified_stints', ''),
            publication_gate=summary.get('publication_gate', ''),
            final_LAL=score.get('LAL', ''), final_GSW=score.get('GSW', ''),
        )
        for name in ('recorded', 'before', 'after'):
            s = scenario.get(name) or {}
            record[f'{name}_matches'] = s.get('matched_players', '')
            record[f'{name}_abs_error'] = s.get('absolute_pm_error', '')
        results.append(record)

    write_csv(out / 'game_validation_summary.csv', results)
    completed = [r for r in results if r['run_status'] == 'COMPLETED']
    counters = {}
    for name in ('recorded', 'before', 'after'):
        matches, errors, counted = 0, 0, 0
        for r in completed:
            try:
                matches += int(r[f'{name}_matches'])
                errors += int(r[f'{name}_abs_error'])
                counted += 1
            except (ValueError, TypeError):
                continue
        counters[name] = {'games_with_metrics': counted, 'matched_player_entries': matches, 'sum_absolute_pm_error': errors}
    blocked = sum(1 for r in completed if str(r['publication_gate']).startswith('BLOCKED'))
    summary = {
        'version': '9.9', 'mode': 'READ_ONLY_MULTIGAME_ORCHESTRATOR',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'games_requested': len(games), 'games_completed': len(completed),
        'games_failed_or_missing': len(games)-len(completed),
        'games_with_publication_gate_blocked': blocked,
        'scenarios_aggregated_without_selecting_winner': counters,
        'independent_stint_certification': False,
        'production_ready': False,
        'disclaimer': 'Reuses V9.8.5; no independent source verification or scenario selection. A zero PM error is not stint certification.',
        'database_modified_by_runner': False,
    }
    (out / 'SUMMARY.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f'\nDetailed game results: {out / "game_validation_summary.csv"}')
    return 0 if len(completed) == len(games) else 2


if __name__ == '__main__':
    raise SystemExit(main())
