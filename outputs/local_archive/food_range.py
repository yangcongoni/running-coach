"""Selected-period meal reads use the existing account storage and meal revisions."""
from contextlib import closing
from datetime import date
from urllib.parse import parse_qs,urlsplit
import food_records

def read(url):
    q=parse_qs(urlsplit(url).query,max_num_fields=2)
    first,last=(date.fromisoformat(q.get(k,[''])[0]) for k in ('from','to'))
    if not 0<=(last-first).days<=30:raise ValueError('日期范围无效')
    with closing(food_records.connect()) as db:
        return {'records':[food_records.record(r) for r in db.execute(
            'SELECT id,rev,body FROM meals WHERE day BETWEEN ? AND ? AND body IS NOT NULL ORDER BY day,id',
            (first.isoformat(),last.isoformat()))]}

