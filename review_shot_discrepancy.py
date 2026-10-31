"""Read-only shot discrepancy review: game-level reconciliation and event export.

Run with Python inside nba_platform_v5. Does not add, update, or remove DB rows.
"""
import argparse
import csv
from pathlib import Path

import duckdb


def write_csv(path, columns, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description='Audit a player-game shot count discrepancy; read-only.')
    parser.add_argument('--db', default='nba_current.duckdb')
    parser.add_argument('--game-id', default='0022500792')
    parser.add_argument('--player-id', type=int, default=1631095)
    parser.add_argument('--out', default='review_jabari_0022500792')
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(args.db, read_only=True) as con:
        required = {
            'player_games': {'game_id', 'player_id', 'fga', 'fgm', 'fg3a', 'fg3m', 'points'},
            'shot_events': {'game_id', 'player_id', 'event_id', 'shot_made', 'shot_type', 'period', 'minutes_remaining', 'seconds_remaining'}
        }
        tables = {r[0] for r in con.execute('SHOW TABLES').fetchall()}
        for table, fields in required.items():
            if table not in tables:
                raise ValueError(f'Missing table: {table}')
            cols = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")').fetchall()}
            missing = fields - cols
            if missing:
                raise ValueError(f'{table} missing required fields: {sorted(missing)}')
        box = con.execute('''
            SELECT game_id, player_id, player_name, team_abbr, game_date,
                   fga, fgm, fg3a, fg3m, points
            FROM player_games WHERE game_id=? AND player_id=?
        ''', [args.game_id, args.player_id]).fetchall()
        if len(box) != 1:
            raise ValueError(f'Expected one player box score; found {len(box)}')
        detail = con.execute('''
            SELECT game_id, player_id, event_id, period, minutes_remaining,
                   seconds_remaining, shot_made, shot_type, action_type,
                   loc_x, loc_y, shot_distance, season, season_type, team_id
            FROM shot_events WHERE game_id=? AND player_id=?
            ORDER BY period, minutes_remaining DESC, seconds_remaining DESC, event_id
        ''', [args.game_id, args.player_id]).fetchall()
        headers = ['game_id', 'player_id', 'event_id', 'period', 'minutes_remaining',
                   'seconds_remaining', 'shot_made', 'shot_type', 'action_type',
                   'loc_x', 'loc_y', 'shot_distance', 'season', 'season_type', 'team_id']
        write_csv(out / 'shot_events_review.csv', headers, detail)
        event_makes = sum(x[6] is True for x in detail)
        event_3a = sum('3PT' in str(x[7]).upper() or '3-POINT' in str(x[7]).upper() for x in detail)
        event_3m = sum((x[6] is True) and ('3PT' in str(x[7]).upper() or '3-POINT' in str(x[7]).upper()) for x in detail)
        b = box[0]
        metrics = [('FGA', b[5], len(detail)), ('FGM', b[6], event_makes),
                   ('3PA', b[7], event_3a), ('3PM', b[8], event_3m)]
        write_csv(out / 'comparison.csv', ['statistic', 'box_score', 'shot_events', 'delta_events_minus_box'],
                  [(label, expected, observed, observed - expected) for label, expected, observed in metrics])
        dupes = con.execute('''
            SELECT event_id, COUNT(*) AS n FROM shot_events
            WHERE game_id=? AND player_id=? GROUP BY event_id HAVING COUNT(*) > 1
            ORDER BY event_id
        ''', [args.game_id, args.player_id]).fetchall()
        write_csv(out / 'duplicate_event_ids.csv', ['event_id', 'count'], dupes)
        with (out / 'review_notes.txt').open('w', encoding='utf-8') as f:
            f.write(f'Game: {args.game_id}; player: {b[2]} ({args.player_id}); team: {b[3]}; date: {b[4]}\n')
            for label, expected, observed in metrics:
                f.write(f'{label}: box={expected}, shot_events={observed}, difference={observed - expected}\n')
            f.write(f'Duplicate event IDs: {len(dupes)}\n\n')
            f.write('Manual review required. Confirm event status against a final authoritative play-by-play.\n')
            f.write('Do NOT infer the excluded event solely from whether it is a missed shot.\n')
            f.write('Preserve original shot_events. A future analysis-specific exclusion should only be applied after verified review.\n')
        print(f'Player: {b[2]} | game {args.game_id}')
        for label, expected, observed in metrics:
            print(f'  {label}: box={expected}, events={observed}, difference={observed - expected:+d}')
        print(f'  Duplicate event IDs: {len(dupes)}')
        print(f'Read-only review exports: {out.resolve()}')


if __name__ == '__main__':
    main()
