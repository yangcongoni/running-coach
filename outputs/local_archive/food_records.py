"""Meal storage for this installation's sole coach account (including after a password reset)."""
import base64
from contextlib import closing
from datetime import date
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlsplit, parse_qs

DB = Path(os.environ['LOCALAPPDATA']) / 'RunningCoach' / 'food-meals.sqlite3'
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}\Z')
def identifier(value):
    return isinstance(value, str) and value not in ('constructor','prototype','__proto__') and ID.fullmatch(value)

def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=8)
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS meals(id TEXT PRIMARY KEY, rev INTEGER NOT NULL, body TEXT, photo_id TEXT, photo BLOB, mime TEXT, seq INTEGER NOT NULL UNIQUE, day TEXT)')
    db.execute('CREATE INDEX IF NOT EXISTS meal_day ON meals(day)')
    if db.execute('PRAGMA user_version').fetchone()[0]<1:
        with db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('PRAGMA user_version').fetchone()[0]<1:
                db.execute('CREATE TABLE photo_blobs(id TEXT PRIMARY KEY,data BLOB NOT NULL,mime TEXT NOT NULL,touched INTEGER NOT NULL)')
                db.execute('CREATE TABLE meal_photo_refs(meal_id TEXT,photo_id TEXT,PRIMARY KEY(meal_id,photo_id))')
                db.execute('CREATE INDEX photo_refs_by_id ON meal_photo_refs(photo_id)')
                db.execute('INSERT OR IGNORE INTO photo_blobs SELECT photo_id,photo,mime,? FROM meals WHERE photo IS NOT NULL AND photo_id IS NOT NULL',(int(time.time()),))
                db.execute('INSERT OR IGNORE INTO meal_photo_refs SELECT id,photo_id FROM meals WHERE photo_id IS NOT NULL AND body IS NOT NULL')
                db.execute('PRAGMA user_version=1')
    return db

def record(row):
    return dict(id=row['id'], rev=row['rev'], meal=json.loads(row['body']) if row['body'] else None)

def listing(query):
    after=int(query.get('after',['0'])[0])
    if after<0:raise ValueError('同步位置无效')
    day=query.get('day',[None])[0]
    with closing(connect()) as db:
        db.execute('BEGIN')
        if day:
            if date.fromisoformat(day).isoformat()!=day:raise ValueError('日期无效')
            rows=db.execute('SELECT id,rev,body FROM meals WHERE day=? AND body IS NOT NULL',(day,))
            records=[record(r) for r in rows]
            more=db.execute('SELECT 1 FROM meals WHERE day IS NOT ? OR body IS NULL LIMIT 1',(day,)).fetchone()
            cursor=db.execute('SELECT COALESCE(MAX(seq),0) FROM meals').fetchone()[0]
            return dict(records=records,cursor=0 if more else cursor,more=bool(more))
        rows=db.execute('SELECT id,rev,body,seq FROM meals WHERE seq>? ORDER BY seq LIMIT 65',(after,)).fetchall()
        page=rows[:64]
        return dict(records=[record(r) for r in page],cursor=page[-1]['seq'] if page else after,more=len(rows)>64)

def validate(meal, key):
    if not isinstance(meal,dict) or meal.get('id')!=key or meal.get('kind') not in ('早餐','午餐','晚餐','加餐'):
        raise ValueError('餐次无效')
    if not isinstance(meal.get('date'),str) or date.fromisoformat(meal['date']).isoformat()!=meal['date']:
        raise ValueError('日期无效')
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',str(meal.get('time',''))):raise ValueError('时间无效')
    if not isinstance(meal.get('items'),list) or len(meal['items'])>500:raise ValueError('食物列表无效')
    for item in meal['items']:
        if not isinstance(item,dict) or not isinstance(item.get('food'),str):raise ValueError('食物无效')
        g=item.get('grams')
        if item.get('food')=='drypot':
            count=item.get('servings',1)
            parts=item.get('ingredients',[])
            if type(count) not in (int,float) or not 0<count<=100 or not isinstance(parts,list) or len(parts)>100:raise ValueError('干锅份量无效')
            for x in parts:
                if not isinstance(x,dict) or not isinstance(x.get('food'),str) or not isinstance(x.get('name'),str):raise ValueError('配料无效')
                weight=x.get('grams')
                if weight is not None and (type(weight) not in (int,float) or not .1<=weight<=5000):raise ValueError('配料重量无效')
            if g is None:continue
        if type(g) not in (int,float) or not math.isfinite(g) or not .1<=g<=5000:raise ValueError('份量无效')
        if 'amountRange' in item:
            v=item['amountRange']
            if not isinstance(v,list) or len(v)!=2 or not all(type(n) in (int,float) for n in v) or not .1<=v[0]<=g<=v[1]<=5000:raise ValueError('范围无效')
    if meal.get('photoId') is not None and not identifier(meal['photoId']):raise ValueError('照片编号无效')

    if 'photoIds' in meal:
        ids=meal['photoIds']
        if (not isinstance(ids,list) or len(ids)>9 or not all(identifier(i) for i in ids)
            or len(set(ids))!=len(ids) or meal.get('photoId')!=(ids[0] if ids else None)):
            raise ValueError('照片列表无效')

def store_photo(db,key,image,mime):
    db.execute('INSERT INTO photo_blobs VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET touched=excluded.touched',
               (key,image,mime,int(time.time())))

def upload_photo(key,image,mime):
    if not identifier(key) or mime not in ('image/jpeg','image/png','image/webp') or not 0<len(image)<=4_000_000:
        raise ValueError('照片格式或大小无效')
    with closing(connect()) as db,db:
        db.execute('BEGIN IMMEDIATE')
        existing=db.execute('SELECT data=? AND mime=? AS same FROM photo_blobs WHERE id=?',(image,mime,key)).fetchone()
        if existing and not existing['same']:return 409,{'error':'照片编号已存在'}
        store_photo(db,key,image,mime)
        db.execute('DELETE FROM photo_blobs WHERE touched<? AND NOT EXISTS (SELECT 1 FROM meal_photo_refs r WHERE r.photo_id=photo_blobs.id)',(int(time.time())-86400,))
    return 200,{'id':key}

def unpack_photo(value):
    if not isinstance(value,str):raise ValueError('照片格式无效')
    prefix,_,encoded=value.partition(',')
    types={'data:image/jpeg;base64':'image/jpeg','data:image/png;base64':'image/png','data:image/webp;base64':'image/webp'}
    if prefix not in types:raise ValueError('照片格式无效')
    data=base64.b64decode(encoded,validate=True)
    if not 0<len(data)<=4_000_000:raise ValueError('照片过大')
    return data,types[prefix]

def update(change):
    if not isinstance(change,dict):raise ValueError('餐食无效')
    key=change.get('id');base=change.get('base');meal=change.get('meal')
    if not identifier(key) or type(base)!=int or base<0 or 'meal' not in change:raise ValueError('餐食编号无效')
    if meal is not None:validate(meal,key)
    body=json.dumps(meal,ensure_ascii=False,separators=(',',':'),allow_nan=False) if meal is not None else None
    if body and len(body)>500_000:raise ValueError('餐食过大')
    pid=meal.get('photoId') if meal else None
    image,mime=unpack_photo(change['photo']) if pid and change.get('photo') else (None,None)
    with closing(connect()) as db, db:
        db.execute('BEGIN IMMEDIATE')
        old=db.execute('SELECT id,rev,body,photo_id,photo IS NOT NULL AS has_photo FROM meals WHERE id=?',(key,)).fetchone()
        prev=record(old) if old else dict(id=key,rev=0,meal=None)
        prior=prev['meal'] or {}
        if meal and 'photoIds' not in meal and prior.get('photoIds') and pid==prior.get('photoId'):
            meal=dict(meal,photoIds=prior['photoIds'])
            body=json.dumps(meal,ensure_ascii=False,separators=(',',':'),allow_nan=False)
        if base!=prev['rev'] and prev['meal']!=meal:return 409,prev
        if image:store_photo(db,pid,image,mime)
        ids=(meal or {}).get('photoIds',[pid] if pid else [])
        if meal and 'photoIds' in meal:
            missing=[i for i in ids if not db.execute('SELECT 1 FROM photo_blobs WHERE id=?',(i,)).fetchone()]
            if missing:return 422,{'missingPhotos':missing}
        if prev['meal']==meal:return 200,prev
        removed={r[0] for r in db.execute('SELECT photo_id FROM meal_photo_refs WHERE meal_id=?',(key,))}-set(ids)
        db.execute('DELETE FROM meal_photo_refs WHERE meal_id=?',(key,))
        db.executemany('INSERT INTO meal_photo_refs VALUES(?,?)',[(key,i) for i in ids])
        db.executemany('DELETE FROM photo_blobs WHERE id=? AND NOT EXISTS (SELECT 1 FROM meal_photo_refs WHERE photo_id=?)',[(i,i) for i in removed])
        rev=base+1
        seq=db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM meals').fetchone()[0]
        db.execute('''INSERT INTO meals VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
            rev=excluded.rev,body=excluded.body,seq=excluded.seq,day=excluded.day,
            photo=CASE WHEN meals.photo_id=excluded.photo_id THEN COALESCE(excluded.photo,meals.photo) ELSE excluded.photo END,
            mime=CASE WHEN meals.photo_id=excluded.photo_id THEN COALESCE(excluded.mime,meals.mime) ELSE excluded.mime END,
            photo_id=excluded.photo_id''',(key,rev,body,pid,image,mime,seq,meal.get('date') if meal else None))
        return 200,dict(id=key,rev=rev,meal=meal)

_READ_PROFILE = object()

def goal_history(db):
    db.execute('''CREATE TABLE IF NOT EXISTS food_goal_history (
        rev INTEGER PRIMARY KEY, day TEXT NOT NULL, previous TEXT, goal TEXT NOT NULL, source TEXT NOT NULL)''')
    return [dict(r) for r in db.execute('SELECT day, previous, goal, source FROM food_goal_history ORDER BY rev')]

def profile_goal(profile):
    goal=profile.get('goal')
    return goal if goal in ('维持体重','减重','增肌','增重') else '暂不设目标'

def account_profile(change=_READ_PROFILE):
    if change is not _READ_PROFILE:
        if not isinstance(change, dict):
            raise ValueError('档案格式无效')
        base, profile = change.get('base'), change.get('profile')
        if type(base) is not int or base < 0 or not isinstance(profile, dict):
            raise ValueError('档案格式无效')
        allowed = {'age','cm','kg','name','sex','goal','pattern','dislike','allergy','limit','activity','scene','mealScenes','special','rmr','rmrDate'}
        if bool(profile.get('rmr'))!=bool(profile.get('rmrDate')):raise ValueError('检测值与日期需同时填写')
        if profile.keys() - allowed:
            raise ValueError('不支持的档案字段')
        for key, value in profile.items():
            if value is None:
                continue
            if key == 'mealScenes':
                if not isinstance(value,dict) or value.keys()-{'早餐','午餐','晚餐'} or any(not isinstance(v,str) or len(v)>60 for v in value.values()):
                    raise ValueError('就餐场景无效')
            elif key == 'rmr':
                if type(value) not in (int,float) or not 1<=value<=10000:raise ValueError('静息代谢检测值无效')
            elif key == 'rmrDate':
                if value and (not isinstance(value,str) or date.fromisoformat(value)>date.today()):raise ValueError('检测日期无效')
            elif key == 'special':
                if type(value) is not bool: raise ValueError('专属方案无效')
            elif key in ('age','cm','kg','activity'):
                if value != '' and (type(value) not in (str,int,float) or not math.isfinite(float(value))):
                    raise ValueError('档案数值无效')
            elif not isinstance(value,str) or len(value)>500:
                raise ValueError('档案文字无效')
    with closing(connect()) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS account_profile (id INTEGER PRIMARY KEY CHECK(id=1), rev INTEGER NOT NULL, body TEXT NOT NULL)')
        if change is not _READ_PROFILE:
            db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT rev,body FROM account_profile WHERE id=1').fetchone()
        current=dict(rev=row[0],profile=json.loads(row[1])) if row else dict(rev=0,profile={})
        current['goalHistory']=goal_history(db)
        if change is _READ_PROFILE or current['profile']==profile:
            return 200,current
        if base!=current['rev']:
            return 409,current
        db.execute('INSERT OR REPLACE INTO account_profile VALUES (1,?,?)',(base+1,json.dumps(profile,ensure_ascii=False,allow_nan=False)))
        previous=profile_goal(current['profile'])
        goal=profile_goal(profile)
        if previous!=goal or not current['goalHistory'] and profile.get('goal'):
            today=date.today().isoformat()
            day=change.get('goalDate') or today
            if not isinstance(day,str) or date.fromisoformat(day).isoformat()!=day or day>today:
                raise ValueError('目标日期无效')
            if current['goalHistory']:day=max(day,current['goalHistory'][-1]['day'])
            transition=previous!=goal and bool(current['profile'].get('goal'))
            db.execute('INSERT INTO food_goal_history VALUES (?,?,?,?,?)',
                       (base+1,day,previous if transition else None,goal,'change' if transition else 'profile'))
        return 200,dict(rev=base+1,profile=profile,goalHistory=goal_history(db))

def shared_table(db):
    db.execute('CREATE TABLE IF NOT EXISTS diary_shared (key TEXT PRIMARY KEY, rev INTEGER NOT NULL, seq INTEGER UNIQUE NOT NULL, body TEXT)')

def shared_list(after):
    with closing(connect()) as db, db:
        shared_table(db)
        rows=db.execute('SELECT key,rev,seq,body FROM diary_shared WHERE seq>? ORDER BY seq LIMIT 65',(after,)).fetchall()
        return dict(records=[dict(key=k,rev=r,value=json.loads(b) if b else None) for k,r,_,b in rows[:64]],
                    cursor=rows[min(len(rows),64)-1][2] if rows else after,more=len(rows)>64)

def update_shared(change):
    if not isinstance(change,dict) or 'value' not in change:raise ValueError('缺少记录')
    key=change.get('key','');base=change.get('base');v=change['value']
    if not isinstance(key,str) or ':' not in key or type(base)!=int or base<0:raise ValueError('记录编号无效')
    kind,ident=key.split(':',1)
    if kind not in ('weights','sports','rest','favorites') or not identifier(ident):raise ValueError('记录类型无效')
    if kind in ('weights','rest') and date.fromisoformat(ident).isoformat()!=ident:raise ValueError('日期无效')
    if v is not None:
        if kind=='rest':
            if v!=ident:raise ValueError('休息日无效')
        elif not isinstance(v,dict):raise ValueError('记录无效')
        elif kind=='favorites':
            if v.get('id')!=ident or not isinstance(v.get('name'),str) or not 0<len(v['name'])<=80:raise ValueError('常吃食物名称无效')
            validate(dict(id=ident,date='2000-01-01',time='12:00',kind='午餐',items=[v.get('item')]),ident)
        else:
            if not isinstance(v.get('date'),str) or date.fromisoformat(v['date']).isoformat()!=v['date']:raise ValueError('日期无效')
            if kind=='weights':
                if v['date']!=ident or type(v.get('kg')) not in (float,int) or not 5<=v['kg']<=500 or type(v.get('morning')) is not bool:raise ValueError('体重无效')
            elif v.get('id')!=ident or not isinstance(v.get('type'),str) or not 0<len(v['type'])<=65:raise ValueError('运动无效')
    body=None if v is None else json.dumps(v,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    if body and len(body)>100000:raise ValueError('记录过大')
    with closing(connect()) as db, db:
        shared_table(db);db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT rev,body FROM diary_shared WHERE key=?',(key,)).fetchone()
        rev=row[0] if row else 0
        old=json.loads(row[1]) if row and row[1] else None
        if old==v or base!=rev:return (200 if old==v else 409),dict(key=key,rev=rev,value=old)
        seq=db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM diary_shared').fetchone()[0]
        db.execute('INSERT OR REPLACE INTO diary_shared VALUES(?,?,?,?)',(key,rev+1,seq,body))
        return 200,dict(key=key,rev=rev+1,value=v)

def serve_get(handler,path):
    try:
        if path=='/api/food/shared':
            after=int(parse_qs(urlsplit(handler.path).query).get('after',['0'])[0]);return handler.reply(200,{**shared_list(after),'token':handler.csrf()})
        if path=='/api/food/meals':
            return handler.reply(200,{**listing(parse_qs(urlsplit(handler.path).query)),'token':handler.csrf()})
        key=path.removeprefix('/api/food/photo/')
        if identifier(key):
            with closing(connect()) as db:
                row=db.execute('SELECT data AS photo,mime FROM photo_blobs WHERE id=? AND EXISTS (SELECT 1 FROM meal_photo_refs WHERE photo_id=?)',(key,key)).fetchone()
            if row:return handler.reply(200,row['photo'],row['mime'])
        return handler.reply(404,{})
    except (ConnectionAbortedError,ConnectionResetError,BrokenPipeError):return
    except ValueError:return handler.reply(400,{'error':'同步参数无效'})
    except (sqlite3.Error,OSError):return handler.reply(503,{'error':'餐食暂时无法读取'})

