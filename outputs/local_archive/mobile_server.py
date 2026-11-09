"""Authenticated, limited mobile frontend. Never serve arbitrary files or proxy arbitrary paths."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
import mobile_archive as archive
from archive_config import origin, desktop_template
import re, subprocess, sys, gzip, html
from daily_store import submit as submit_day
from pathlib import Path
from datetime import datetime, timezone, timedelta
import json, sqlite3, os, secrets, time, threading, http.client, urllib.parse
ROOT=Path(__file__).resolve().parent
DB=ROOT.parent/'训练日志.sqlite3'
BASE=origin('mobile_origin', 'http://localhost:8876')
LOCAL='http://127.0.0.1:8765'
LOCK=threading.Lock()
sessions={}
failures=[]
def latest_recovery_time(conn, day):
    latest = None
    latest_stamp = None
    for (raw,) in conn.execute("""SELECT json_extract(details_json,'$.recovery_extras.recovery_time')
                                  FROM daily_recovery WHERE date<=?""", (day,)):
        if not raw:
            continue
        item = json.loads(raw)
        minutes = item.get('minutes')
        if not isinstance(minutes,(int,float)) or minutes < 0:
            continue
        try:
            stamp = datetime.fromisoformat(item['measured_at'])
        except (ValueError, KeyError, TypeError):
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone(timedelta(hours=8)))
        if latest_stamp is None or stamp > latest_stamp:
            latest_stamp = stamp
            latest = dict(minutes=minutes, measured_at=stamp.isoformat(), read_at=item.get('read_at'))
    return latest

def training_week(conn, start):
    bounds=(start.isoformat(), (start+timedelta(days=6)).isoformat())
    plans=conn.execute("SELECT date,prescription_json FROM planned_sessions WHERE date BETWEEN ? AND ? ORDER BY date,id", bounds)
    activities=conn.execute("""SELECT date,sport,duration_minutes,session_rpe FROM sessions
                               WHERE date BETWEEN ? AND ? AND sport IN ('running','strength') ORDER BY date,id""", bounds)
    return dict(start=bounds[0], weekPlans=[dict(date=row[0],name=json.loads(row[1]).get('content')) for row in plans],
                activities=[dict(row) for row in activities])

def home_goals(conn):
    goal=archive.meta(conn,'goal_readiness_assessment')
    actions=[];archived=[]
    today=datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    for item in archive.meta(conn,'coach_action_followups').get('items',[]):
        if item.get('created_on','')>today:continue
        history=[entry for entry in item.get('history',[]) if entry.get('date','')<=today]
        last=max(enumerate(history),key=lambda pair:(pair[1].get('date',''),pair[1].get('reviewed_at') or pair[1].get('updated_at') or '',pair[0]),default=(-1,{}))[1]
        value={'title':item.get('title'),'closed_on':item.get('closed_on'),**{key:last.get(key) for key in ('date','status','conclusion','next_action','next_check_on','next_check_label','reviewed_at','check','limits')},'history':history}
        (archived if item.get('archived') else actions).append(value)
    return {**{key:goal.get(key) for key in ('target_event','target_seconds','range_percent','last_reviewed_on','summary','next_review_node')},'actions':actions[:3],'archived_actions':archived}


def dashboard():
    now=datetime.now(timezone(timedelta(hours=8))); day=now.date().isoformat()
    with sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True) as c:
        c.row_factory=sqlite3.Row
        plans=[]
        for r in c.execute('select date,sport,prescription_json from planned_sessions where date between ? and ? order by date,id',(day,(now.date()+timedelta(days=6)).isoformat())):
            p=json.loads(r[2]);plans.append(dict(date=r[0],sport=r[1],name=p.get('content'),detail=p.get('details')))
        r=c.execute('select date,sleep_minutes,hrv_ms,resting_hr, json_extract(details_json,\'$.recovery_extras.morning.score\') as readiness from daily_recovery where date<=? order by date desc limit 1',(day,)).fetchone()
        fb=c.execute("select value_json from metadata where key='training_session_feedback'").fetchone()
        feedback=json.loads(fb[0]) if fb else {}
        activities=[]
        for s in c.execute("select id,date,sport,duration_minutes,session_rpe from sessions where sport in ('running','strength') and date<=? order by date desc,id desc limit 30",(day,)):
            f=feedback.get(str(s['id']),{});activities.append(dict(dict(s),fields=f.get('fields',{}),revision=f.get('revision',0),status=f.get('status')))
        reviews=[dict(x) for x in c.execute('select created_at,assessment,recommendation from analyses order by id desc limit 5')]
        week_start=now.date()-timedelta(days=now.weekday())
        cycle=archive.meta(c,'cycle_dashboard')
        reference=archive.meta(c,'running_ability_evidence').get('field_reference') or {}
        return dict(day=day,cycle=[cycle.get('from'),cycle.get('to')],fieldActivity=reference.get('activity_id'),goals=home_goals(c),week=training_week(c,week_start),time=now.strftime('%H:%M'),plans=plans,recovery={**(dict(r) if r else {}),"time":latest_recovery_time(c,day)},activities=activities,reviews=reviews)
def home_document(nonce):
    # Ship the initial snapshot and both local scripts in the authenticated HTML.
    page=(ROOT/'mobile.html').read_text(encoding='utf-8')
    snapshot=json.dumps(dashboard(),ensure_ascii=False,separators=(',',':'))
    scripts='\n'.join((ROOT/f).read_text(encoding='utf-8-sig') for f in ('mobile.js','mobile_archive.js','mobile_specialties.js','mobile_library.js','mobile_journal.js'))
    desktop=desktop_template()
    period_script=desktop.split('/* run-period:start */',1)[1].split('/* run-period:end */',1)[0]
    period_style=desktop.split('/* run-period-style:start */',1)[1].split('/* run-period-style:end */',1)[0]
    scripts=period_script+'\n'+scripts
    page=page.replace('</style>',period_style+'</style>',1)
    assert '</script' not in scripts.lower()
    block='<template id="initial-data">'+html.escape(snapshot,quote=False)+'</template><script nonce="'+nonce+'">'+scripts+'</script>'
    start=page.index('<script src="/mobile.js"')
    end=page.index('</script>',page.index('<script src="/archive.js"',start))+len('</script>')
    return (page[:start]+block+page[end:]).encode('utf-8')

def upstream(data):
    def call(method,path,body=None,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',8765,timeout=180)
        try:
            conn.request(method,path,body,headers or {});r=conn.getresponse();return r.status,json.loads(r.read())
        finally:conn.close()
    code,token=call('GET','/api/session')
    if code!=200:raise OSError()
    return call('POST','/api/training-feedback',json.dumps(data).encode(),{'Content-Type':'application/json','Origin':LOCAL,'X-Archive-Token':token['token']})
class H(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,status,obj,kind='application/json; charset=utf-8',cookie=None,nonce=None):
        data=obj if isinstance(obj,bytes) else json.dumps(obj,ensure_ascii=False,separators=(',',':')).encode()
        accepted=self.headers.get('Accept-Encoding','')
        compressed=len(data)>1024 and bool(re.search(r'(?:^|,)\s*gzip\s*(?:,|$)',accepted,re.I))
        if compressed:data=gzip.compress(data,compresslevel=4)
        self.send_response(status)
        self.send_header('Vary','Accept-Encoding')
        if compressed:self.send_header('Content-Encoding','gzip')
        self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store')
        script_policy="'self'"+(" 'nonce-"+nonce+"'" if nonce else '')
        self.send_header('Content-Security-Policy',f"default-src 'none'; script-src {script_policy}; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','same-origin')
        if cookie:self.send_header('Set-Cookie',cookie)
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def key(self):
        c=SimpleCookie()
        try:c.load(self.headers.get('Cookie',''));return c['__Host-mobile'].value
        except Exception:return ''
    def authed(self):
        with LOCK:return sessions.get(self.key(),0)>time.time()
    def do_GET(self):
        path=self.path.split('?')[0]
        if path=='/':
            if not self.authed():
                return self.reply(200,LOGIN.encode(),'text/html; charset=utf-8')
            nonce=secrets.token_urlsafe(24)
            return self.reply(200,home_document(nonce),'text/html; charset=utf-8',nonce=nonce)
        if not self.authed():return self.reply(401,{'error':'请先登录'})
        if path=='/footprint.js':
            template=desktop_template()
            shared=template.split('/* footprint-shared:start */',1)[1].split('/* footprint-shared:end */',1)[0]
            return self.reply(200,shared.encode('utf-8'),'application/javascript')
        if path=='/mobile.js':return self.reply(200,(ROOT/'mobile.js').read_bytes(),'application/javascript')
        if path=='/api/home':return self.reply(200,dashboard())
        if re.fullmatch(r'/api/week/[0-9]{4}-[0-9]{2}-[0-9]{2}',path):
            try:
                start=datetime.fromisoformat(path[10:]).date()
                if start.weekday()!=0:
                    raise ValueError
                with archive.open_read() as conn:
                    week=training_week(conn,start)
            except (ValueError,OverflowError):
                return self.reply(400,{'error':'请选择有效的周一日期'})
            return self.reply(200,week)
        if path=='/archive.js':
            return self.reply(200,(ROOT/'mobile_archive.js').read_bytes(),'application/javascript')
        if re.fullmatch(r'/api/route-map/[0-9]{1,10}',path):
            with archive.open_read() as conn:
                image=archive.route_image(conn,int(path.rsplit('/',1)[1]))
            return self.reply(200,image.read_bytes(),'image/png') if image else self.reply(404,{})
        if path.startswith(('/api/archive','/api/activity/','/api/curve/','/api/topic/','/api/day/')):
            with archive.open_read() as conn:
                if path=='/api/archive':
                    return self.reply(200,archive.index(conn))
                if re.fullmatch(r'/api/(activity|curve)/[0-9]{1,10}',path):
                    value=archive.detail(conn,int(path.rsplit('/',1)[1]),path.startswith('/api/curve/'))
                elif path.startswith('/api/topic/'):
                    value=archive.topics(conn,urllib.parse.unquote(path.removeprefix('/api/topic/')))
                elif re.fullmatch(r'/api/day/[0-9]{4}-[0-9]{2}-[0-9]{2}',path):
                    row=conn.execute('SELECT revision,payload_json FROM daily_submissions WHERE date=?',(path[9:],)).fetchone()
                    value={'revision':row[0] if row else 0,'fields':json.loads(row[1]) if row else {}}
                else:
                    value=None
                return self.reply(200,value) if value is not None else self.reply(404,{})
        return self.reply(404,{})
    def do_POST(self):
        if self.headers.get('Origin')!=BASE:return self.reply(403,{'error':'来源无效'})
        try:
            n=int(self.headers.get('Content-Length','0'))
            if not 0<=n<=32768:return self.reply(413,{})
            if self.path=='/login':
                if self.headers.get_content_type()!='application/x-www-form-urlencoded':return self.reply(415,{})
                val=urllib.parse.parse_qs(self.rfile.read(n).decode()).get('code',[''])[0]
                with LOCK:
                    t=time.time();failures[:]=[x for x in failures if x>t-300]
                    if len(failures)>=12:return self.reply(429,{'error':'请五分钟后重试'})
                    if not secrets.compare_digest(val.encode(),PASSWORD.encode()):
                        failures.append(t);return self.reply(403,{'error':'口令不正确，请返回重试'})
                    for k in list(sessions):
                        if sessions[k]<=t:del sessions[k]
                    k=secrets.token_urlsafe(32);sessions[k]=t+604800
                self.send_response(303);self.send_header('Location','/');self.send_header('Cache-Control','no-store');self.send_header('Set-Cookie',f'__Host-mobile={k}; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age=604800');self.end_headers();return
            if not self.authed():return self.reply(401,{'error':'请重新登录'})
            if self.path=='/logout':
                with LOCK:sessions.pop(self.key(),None)
                return self.reply(200,{},cookie='__Host-mobile=; Max-Age=0; Secure; HttpOnly; SameSite=Strict; Path=/')
            if self.path not in ('/api/feedback','/api/day-feedback'):return self.reply(404,{})
            if self.headers.get_content_type()!='application/json':return self.reply(415,{})
            if self.path=='/api/day-feedback':
                data=json.loads(self.rfile.read(n))
                stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                with archive.open_read() as source, sqlite3.connect(DB.parent/'backups'/('mobile_daily_'+stamp+'.sqlite3')) as target:
                    source.backup(target)
                result=submit_day(DB,data)
                published=subprocess.run([sys.executable,str(ROOT/'export_page.py')],cwd=ROOT,capture_output=True)
                result['offline_updated']=published.returncode==0
                return self.reply(200,result)
            status,result=upstream(json.loads(self.rfile.read(n)));return self.reply(status,result)
        except RuntimeError as err:return self.reply(409,{'error':str(err)})
        except (ValueError,UnicodeError):return self.reply(400,{'error':'表单格式无效'})
        except (OSError,http.client.HTTPException):return self.reply(503,{'error':'训练档案暂时不可用，请保留表单后重试'})
LOGIN='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>训练手记 · 登录</title><style>body{background:#faf7f3;color:#30292b;font:16px system-ui;margin:12vh auto;padding:24px;max-width:24rem}h1{color:#81263d}input,button{font:inherit;padding:12px;border-radius:8px;border:1px solid #d8c9c9;box-sizing:border-box;width:100%;margin-top:12px}button{background:#81263d;color:white}</style><h1>训练手记</h1><form action="/login" method="post"><label>私人访问口令<input name="code" type="password" autocomplete="current-password" required></label><button>进入训练档案</button></form></html>'''
if __name__=='__main__':
    folder=Path(os.environ['LOCALAPPDATA'])/'RunningCoach';folder.mkdir(exist_ok=True)
    f=folder/'手机访问口令.txt'
    if not f.exists():
        with f.open('x',encoding='utf8') as out:out.write(secrets.token_urlsafe(24))
    PASSWORD=f.read_text(encoding='utf8').strip()
    if len(PASSWORD)<24:raise RuntimeError('访问口令无效')
    ThreadingHTTPServer(('127.0.0.1',8876),H).serve_forever()

