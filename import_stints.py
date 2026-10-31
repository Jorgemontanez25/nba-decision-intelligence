import argparse
import duckdb
from lineup_engine import import_stints
p=argparse.ArgumentParser()
p.add_argument('csv_path');p.add_argument('--db',default='nba_current.duckdb')
a=p.parse_args()
with duckdb.connect(a.db) as con:
    print('Imported verified rows:',import_stints(con,a.csv_path))
