"""Fetch third-party NBA 2K27 launch/current roster OVR snapshot with provenance.
Does not alter DuckDB and does not assume a rating when a name fails to match.
Requires user-owned NBA2KAPI_KEY in environment, per publisher API documentation.
"""
import argparse,csv,datetime,json,os,urllib.request,unicodedata
from pathlib import Path

def key(s):
    return ''.join(ch for ch in unicodedata.normalize('NFKD',s or '').casefold() if ch.isalnum())

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',default='nba_2k27_ratings.csv');a=p.parse_args()
    token=os.getenv('NBA2KAPI_KEY')
    if not token:p.error('Set NBA2KAPI_KEY environment variable first (key from nba2kapi.com). No ratings were invented.')
    url='https://api.nba2kapi.com/api/versions/2K27/players/bulk?teamType=curr'
    request=urllib.request.Request(url,headers={'X-API-Key':token,'User-Agent':'NBA-Decision-Intelligence/4.7'})
    with urllib.request.urlopen(request,timeout=40) as f:data=json.load(f)
    if not data.get('success') or not isinstance(data.get('data'),list):raise RuntimeError('Unexpected response; no file written')
    rows=[]
    for r in data['data']:
        if r.get('name') and isinstance(r.get('overall'),int):rows.append({'name':r['name'],'name_key':key(r['name']),'overall':r['overall'],'team':r.get('team',''),'edition':'2K27','retrieved_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source':url})
    if len(rows)<100:raise RuntimeError('Suspiciously few ratings; refusing to replace cache')
    tmp=Path(a.out).with_suffix('.tmp')
    with tmp.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    tmp.replace(a.out)
    print(f'Cached {len(rows)} sourced 2K27 OVR records to {a.out}. Historical box-score records unchanged.')
if __name__=='__main__':main()
