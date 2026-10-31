#!/usr/bin/env python3
"""V9.9.2: audit and reuse existing NBA evidence, without fetching or modifying it."""
import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

CORE = {'playbyplayv3': 'playbyplayv3_dataset_0.csv', 'boxscoretraditionalv3': 'boxscoretraditionalv3_dataset_0.csv'}
COLUMNS = ['game_id','core_source_status','pbp_rows','box_rows','rotation_status','rotation_error','timeline_status','timeline_rows','team_pair','v9_9_compatibility','ready_for_v9_9','official_dir','timeline','reason']


def rows_and_header(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rdr = csv.DictReader(stream)
        header = set(rdr.fieldnames or [])
        rows = list(rdr)
    return header, rows


def save_csv(path, rows, header):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        w = csv.DictWriter(stream, fieldnames=header, extrasaction='ignore')
        w.writeheader(); w.writerows(rows)


def choose_path(p, project):
    if not p:
        return None
    path = Path(p).expanduser()
    return (path if path.is_absolute() else project / path).resolve()


def inspect(gid, evidence, timeline, permit_other_teams=False):
    row = dict.fromkeys(COLUMNS, '')
    row.update(game_id=gid, official_dir=str(evidence) if evidence else '',timeline=str(timeline) if timeline else '',ready_for_v9_9='False',v9_9_compatibility='NOT_CHECKED')
    reasons=[]
    if not evidence or not evidence.is_dir():
        row['core_source_status']='MISSING'; reasons.append('Evidence directory missing')
    else:
        f=evidence/'SUMMARY.json'
        try:
            summary=json.loads(f.read_text(encoding='utf-8-sig'))
            if str(summary.get('game_id',''))!=gid:
                raise ValueError('Evidence game_id does not match manifest')
            endpoints=summary.get('endpoints',{})
            row['rotation_status']=endpoints.get('gamerotation',{}).get('status','NOT_REPORTED')
            row['rotation_error']=endpoints.get('gamerotation',{}).get('error','')
            ok=True
            for k,filename in CORE.items():
                path=evidence/filename
                status=endpoints.get(k,{}).get('status')
                try:
                    head,data=rows_and_header(path)
                    if k=='playbyplayv3':
                        required={'gameId','actionNumber','period','clock','actionType','teamTricode'}
                        row['pbp_rows']=len(data)
                        teams=sorted({x.get('teamTricode','') for x in data if x.get('teamTricode','') not in ('','0')})
                        row['team_pair']='|'.join(teams)
                    else:
                        required={'gameId','personId','teamTricode','plusMinusPoints'}
                        row['box_rows']=len(data)
                    if status != 'SUCCESS' or not data or not required.issubset(head) or any(str(x.get('gameId',''))!=gid for x in data):
                        raise ValueError('Status, rows, columns, or gameId validation failed')
                except (OSError, ValueError, UnicodeError, csv.Error) as exc:
                    ok=False; reasons.append(f'{k}: {exc}')
            row['core_source_status']='READY' if ok else 'INCOMPLETE'
            if row['rotation_status']!='SUCCESS':
                row['rotation_status']='OPTIONAL_UNAVAILABLE ('+row['rotation_status']+')'
        except (OSError, ValueError, KeyError, TypeError) as exc:
            row['core_source_status']='INCOMPLETE'; reasons.append(f'Collector summary: {exc}')
    if not timeline or not timeline.is_file():
        row['timeline_status']='MISSING'; reasons.append('Timeline not linked/found')
    else:
        try:
            head, data=rows_and_header(timeline)
            required={'period','start_seconds','end_seconds','LAL_lineup','GSW_lineup'}
            if not data or not required.issubset(head):
                raise ValueError('Missing required conditional timeline fields or intervals')
            # Timeline has no game_id in older versions. The user must explicitly map it;
            # reject conflicting embedded IDs if present, and never call it certified.
            if 'game_id' in head and any(str(r['game_id']) != gid for r in data):
                raise ValueError('Timeline embedded game_id mismatch')
            for r in data:
                if float(r['end_seconds']) <= float(r['start_seconds']):
                    raise ValueError('Non-positive interval')
                for team in ('LAL','GSW'):
                    ids=r[f'{team}_lineup'].split('|')
                    if len(ids)!=5 or len(set(ids))!=5:
                        raise ValueError(f'Invalid five-player {team} lineup')
            row['timeline_rows']=len(data)
            row['timeline_status']='LINKED_CONDITIONAL_UNVERIFIED'
        except (ValueError, OSError, UnicodeError, csv.Error) as exc:
            row['timeline_status']='INVALID'; reasons.append(f'Timeline: {exc}')
    # Current V9.8.5 depends on LAL/GSW lineup schema and score orientation.
    # Explicitly block other teams even when input files exist.
    if row['team_pair'] != 'GSW|LAL':
        row['v9_9_compatibility']='BLOCKED_NON_LAL_GSW'
        reasons.append('V9.8.5 scoring audit still specific to LAL-GSW; no generalized validation')
    else:
        row['v9_9_compatibility']='LAL_GSW_SCHEMA_ONLY'
    # Only a known mapped timeline with complete existing core sources becomes runnable.
    runnable=(row['core_source_status']=='READY' and row['timeline_status']=='LINKED_CONDITIONAL_UNVERIFIED' and row['v9_9_compatibility']=='LAL_GSW_SCHEMA_ONLY')
    row['ready_for_v9_9']=str(runnable)
    row['reason']='; '.join(reasons)
    return row


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--games', default='v9_9_2_game_map.csv', type=Path, help='CSV: game_id,official_dir,timeline')
    ap.add_argument('--out', default='v9_9_2_review', type=Path)
    args=ap.parse_args()
    project=Path.cwd()
    try:
        head, entries=rows_and_header(args.games.resolve())
    except (OSError,csv.Error) as exc:
        ap.error(f'Game map could not be read: {exc}')
    if not {'game_id','official_dir','timeline'}.issubset(head):
        ap.error('Game map columns must include game_id,official_dir,timeline')
    ids=[r.get('game_id','').strip() for r in entries]
    if not ids or any(not re.fullmatch(r'\d{10}',x) for x in ids) or len(set(ids))!=len(ids):
        ap.error('Game IDs must be unique 10-digit strings')
    out=args.out.resolve(); out.mkdir(parents=True,exist_ok=True)
    results=[]; ready=[]; pending=[]
    for e in entries:
        gid=e['game_id'].strip()
        evidence=choose_path(e.get('official_dir','').strip(),project)
        timeline=choose_path(e.get('timeline','').strip(),project)
        r=inspect(gid,evidence,timeline)
        results.append(r)
        manifest={'game_id':gid,'official_dir':r['official_dir'],'timeline':r['timeline']}
        (ready if r['ready_for_v9_9']=='True' else pending).append(manifest)
        print(f'{gid}: core={r["core_source_status"]} rotation={r["rotation_status"]} timeline={r["timeline_status"]} v9.9={r["ready_for_v9_9"]}',flush=True)
    save_csv(out/'PREPARATION_STATUS.csv',results,COLUMNS)
    hdr=['game_id','official_dir','timeline']
    save_csv(out/'v9_9_READY_manifest.csv',ready,hdr)
    save_csv(out/'v9_9_PENDING_manifest.csv',pending,hdr)
    summary={'version':'9.9.2','mode':'REUSE_EXISTING_EVIDENCE_READ_ONLY','created_utc':datetime.now(timezone.utc).isoformat(), 'games_requested':len(results),'core_sources_ready':sum(r['core_source_status']=='READY' for r in results),'games_ready_for_v9_9':len(ready),'games_pending':len(pending),'rotation_optional':True,'independent_stint_certification':False,'production_ready':False,'database_modified':False,'warning':'A runnable manifest does not verify lineups. V9.8.5 only supports LAL-GSW as currently coded. Existing input files are never changed.'}
    (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':
    main()
