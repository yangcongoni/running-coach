"""Authenticated, limited mobile frontend. Never serve arbitrary files or proxy arbitrary paths."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import closing
from http.cookies import SimpleCookie
import mobile_archive as archive
import public_desktop
from desk_demand import PREFIX, serve
import food_site
import food_records
import food_labels
import food_language
import web_account
import web_second_factor as second_factor
import hmac
from archive_config import origin, desktop_template
import re, subprocess, sys, gzip, html, hashlib
from daily_store import submit as submit_day
from pathlib import Path
from strength_duration import enrich_mobile
from datetime import datetime, timezone, timedelta
import json, sqlite3, os, secrets, time, threading, http.client, urllib.parse
ROOT=Path(__file__).resolve().parent
DB=ROOT.parent/'训练日志.sqlite3'
BASE=origin('mobile_origin', 'http://localhost:8876')
LOCAL='http://127.0.0.1:8765'
LOCK=threading.Lock()
sessions={}
CSRF_SECRET=secrets.token_bytes(32)
failures=[]
challenges={}
code_failures=[]
CHALLENGE_SECONDS=300
CHALLENGE_COOKIE="__Host-rc-check"
DEVICE_COOKIE="__Host-rc-device"
# A marker survives service restarts. Several saves during one export require
# only one more snapshot, taken after the most recent committed change.
publish_marker = ROOT / '.mobile-daily-publish-pending'
publish_state = threading.Lock()
publish_lock = threading.Lock()
publish_generation = 0

def mark_daily_publish():
    global publish_generation
    with publish_state:
        publish_marker.touch()
        publish_generation += 1

def publish_pending_daily():
    with publish_lock:
        while True:
            with publish_state:
                if not publish_marker.exists():
                    return
                generation = publish_generation
            result = subprocess.run([sys.executable, str(ROOT / 'export_page.py')], cwd=ROOT,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode:
                return
            with publish_state:
                if generation == publish_generation:
                    publish_marker.unlink(missing_ok=True)
                    return

def backup_daily():
    from uuid import uuid4
    folder = DB.parent / 'backups'
    folder.mkdir(exist_ok=True)
    name = 'mobile_daily_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '_' + uuid4().hex[:8]
    pending = folder / (name + '.partial')
    try:
        with closing(archive.open_read()) as source, closing(sqlite3.connect(pending)) as target:
            source.backup(target)
        pending.rename(folder / (name + '.sqlite3'))
    finally:
        pending.unlink(missing_ok=True)

def daily_strength_plan(conn, day):
    plans = []
    count = r'\d+(?:\s*[–—~-]\s*\d+)?'
    dose = re.compile(rf'(?P<side>每侧|各)?\s*(?P<sets>{count})\s*[×xX*]\s*'
                      rf'(?P<reps>{count})(?P<unit>次|秒|步)?')
    for title, details in conn.execute(
        """SELECT json_extract(prescription_json,'$.content'), json_extract(prescription_json,'$.details')
           FROM planned_sessions WHERE date=? AND sport='strength' ORDER BY id""", (day,)
    ):
        items = []
        if not re.match(r'^(?:力量)?休息|^取消', title or ''):
            for part in re.split(r'[。；;\n]', details or title or ''):
                part = part.strip()
                match = dose.search(part)
                if match:
                    name = part[:match.start()].strip(' ，,')
                    name = re.sub(r'^保留原上肢[：:]', '', name)
                    if not name or re.search(r'不做|不加|取消|若|休息|疲劳', name):
                        continue
                    names = [name]
                    if name == '直膝、屈膝提踵' and match['side'] == '各':
                        names = ['直膝提踵', '屈膝提踵']
                    for name in names:
                        if match['side'] == '每侧':
                            name += '（每侧）'
                        items.append({'name': name, 'dose': match['sets']+'×'+match['reps']+(match['unit'] or '次')})
                elif re.match(r'^[^：:，,]+[：:]每方向', part):
                    name, guidance = re.split(r'[：:]', part, maxsplit=1)
                    items.append({'name': name, 'dose': guidance})
        plans.append({'title': title or '', 'details': details or '', 'items': items})
    return plans


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
    plans=conn.execute("SELECT date,json_extract(prescription_json,'$.content'),sport,json_extract(prescription_json,'$.details') FROM planned_sessions WHERE date BETWEEN ? AND ? ORDER BY date,id", bounds)
    activities=conn.execute("""SELECT id,date,sport,duration_minutes,session_rpe FROM sessions
                               WHERE date BETWEEN ? AND ? AND sport IN ('running','strength') ORDER BY date,id""", bounds)
    activities=[dict(row) for row in activities]
    enrich_mobile(conn,activities)
    return dict(start=bounds[0], weekPlans=[dict(date=row[0],name=row[1],sport=row[2],detail=row[3]) for row in plans],
                activities=activities)

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
    fields=('reviewed_on','target_event','target_seconds','range_percent','summary','evidence','next_review_on','next_review_node')
    history=[{key:r.get(key) for key in fields} for r in archive.meta(conn,'goal_readiness_history').get('records',[])
             if r.get('reviewed_on') and r['reviewed_on']<=today]
    tests={}
    for (payload,) in conn.execute("""SELECT json_extract(evidence_json,'$.test_result') FROM analyses
                WHERE json_type(evidence_json,'$.test_result')='object' ORDER BY id"""):
        result=json.loads(payload)
        if result.get('activity_id'):
            tests[str(result['activity_id'])]={k:result.get(k) for k in ('distance_m','timer_seconds','first5_seconds','last5_seconds','laps')}
    return {'history':history,'tests':tests,**{key:goal.get(key) for key in ('target_event','target_seconds','range_percent','last_reviewed_on','summary','next_review_node','next_review_action','next_review_on','evidence','focus_topics')},'actions':actions[:3],'archived_actions':archived}


def home_recovery_history(conn, day):
    # Only send the readings used on the home screen; nightly samples stay in the archive.
    readings = []
    zone = timezone(timedelta(hours=8))
    for r in conn.execute("""SELECT date,sleep_minutes,hrv_ms,resting_hr,
            json_extract(details_json,'$.sleep_data_date') sleep_day,
            json_extract(details_json,'$.hrv_data_date') hrv_day,
            json_extract(details_json,'$.resting_hr_data_date') hr_day,
            json_extract(details_json,'$.recovery_extras.morning.calendarDate') ready_day,
            json_extract(details_json,'$.recovery_extras.morning.score') readiness,
            json_extract(details_json,'$.recovery_extras.recovery_time') estimate
            FROM daily_recovery WHERE date<=? ORDER BY date""",(day,)):
        row = dict(r)
        estimate = json.loads(row.pop('estimate') or '{}')
        stamp = estimate.get('measured_at')
        if isinstance(estimate.get('minutes'),(float,int)) and estimate['minutes']>=0 and stamp:
            try:
                measured = datetime.fromisoformat(stamp)
                measured = (measured if measured.tzinfo else measured.replace(tzinfo=zone)).astimezone(zone)
                if measured.date().isoformat()<=day:
                    row['time'] = dict(minutes=estimate['minutes'], measured_at=measured.isoformat(),
                                       read_at=estimate.get('read_at'))
            except (TypeError,ValueError):
                pass
        readings.append(row)
    return readings



def home_overview(conn, day):
    running = [list(row) for row in conn.execute("""
        SELECT s.date,SUM(r.distance_km),COUNT(*)
        FROM sessions s JOIN running_details r ON r.session_id=s.id
        WHERE s.sport='running' AND s.date<=? GROUP BY s.date ORDER BY s.date
    """, (day,))]
    records = archive.meta(conn, 'body_composition_history').get('records', [])
    weights = sorted(([r['date'],r['weight_kg']] for r in records
                      if r.get('date') and r['date']<=day and r.get('weight_kg') is not None),
                     key=lambda r:r[0])
    dates = [r[0] for r in conn.execute("""
        SELECT date FROM sessions WHERE date<=? UNION SELECT date FROM daily_recovery WHERE date<=?
        UNION SELECT date FROM stretching_records WHERE date<=?
    """,(day,day,day))]
    dates.extend(r['date'] for r in records if r.get('date') and r['date']<=day)
    return dict(first=min(dates,default=None),last=max(dates,default=None),running=running,weights=weights)

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
        enrich_mobile(c, activities)
        reviews=[dict(x) for x in c.execute('select created_at,assessment,recommendation from analyses order by id desc limit 5')]
        week_start=now.date()-timedelta(days=now.weekday())
        cycle=archive.meta(c,'cycle_dashboard')
        reference=archive.meta(c,'running_ability_evidence').get('field_reference') or {}
        return dict(day=day,overview=home_overview(c,day),cycle=[cycle.get('from'),cycle.get('to')],fieldActivity=reference.get('activity_id'),goals=home_goals(c),recoveryHistory=home_recovery_history(c,day),week=training_week(c,week_start),time=now.strftime('%H:%M'),plans=plans,recovery={**(dict(r) if r else {}),"time":latest_recovery_time(c,day)},activities=activities,reviews=reviews)
def home_document(nonce):
    # Ship the initial snapshot and both local scripts in the authenticated HTML.
    page=(ROOT/'mobile.html').read_text(encoding='utf-8')
    snapshot=json.dumps(dashboard(),ensure_ascii=False,separators=(',',':'))
    scripts='\n'.join((ROOT/f).read_text(encoding='utf-8-sig') for f in ('today_run.js','mobile.js','mobile_daily.js','mobile_archive.js','mobile_specialties.js','mobile_library.js','mobile_journal.js','mobile_posters.js'))
    desktop=desktop_template()
    period_script=desktop.split('/* run-period:start */',1)[1].split('/* run-period:end */',1)[0]
    period_style=desktop.split('/* run-period-style:start */',1)[1].split('/* run-period-style:end */',1)[0]
    _, marker, dates = desktop.partition('/* overview-dates:start */')
    if marker and '/* overview-dates:end */' in dates:
        dates_script = dates.partition('/* overview-dates:end */')[0]
    else:
        dates_script = (ROOT / 'overview_dates.js').read_text(encoding='utf-8')
    scripts=period_script+'\n'+dates_script+'\n'+scripts
    page=page.replace('</style>',period_style+(ROOT/'today_run.css').read_text(encoding='utf-8')+'</style>',1)
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
    def reply(self,status,obj,kind='application/json; charset=utf-8',cookie=None,nonce=None,policy=None,etag=None,poster_preview=False):
        data=obj if isinstance(obj,bytes) else json.dumps(obj,ensure_ascii=False,separators=(',',':')).encode()
        accepted=self.headers.get('Accept-Encoding','')
        compressed=len(data)>1024 and bool(re.search(r'(?:^|,)\s*gzip\s*(?:,|$)',accepted,re.I))
        if compressed:data=gzip.compress(data,compresslevel=4)
        self.send_response(status)
        self.send_header('Vary','Accept-Encoding')
        self.send_header('X-Archive-Load-Version','3')
        if compressed:self.send_header('Content-Encoding','gzip')
        self.send_header('Content-Type',kind);self.send_header('Cache-Control','private, no-cache' if etag else 'no-store')
        if etag:self.send_header('ETag',etag)
        script_policy="'self'"+(" 'nonce-"+nonce+"'" if nonce else '')
        image_sources = "'self' blob:" if poster_preview else "'self'"
        self.send_header('Content-Security-Policy',policy or f"default-src 'none'; script-src {script_policy}; style-src 'self' 'unsafe-inline'; worker-src 'self'; connect-src 'self'; img-src {image_sources}; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','same-origin')
        if cookie:self.send_header('Set-Cookie',cookie)
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def key(self, name="__Host-mobile"):
        c=SimpleCookie()
        try:c.load(self.headers.get('Cookie',''));return c[name].value
        except Exception:return ''
    def authed(self):
        item=web_account.read_account()
        with LOCK:
            session=sessions.get(self.key())
        if not item or not session or session[0]<=time.time() or session[1]!=item['verifier']:
            return False
        try:return second_factor.active(session[1],session[2],session[3])
        except sqlite3.Error:return False
    def csrf(self):
        return hmac.new(CSRF_SECRET,(self.key() or '').encode(),hashlib.sha256).hexdigest()
    def login_page(self, path='/', message='', status=200):
        if not web_account.read_account():message='请先在项目电脑上运行“设置公网登录账号”。'
        page=LOGIN.replace('<!--notice-->',html.escape(message)).replace('DESTINATION',path)
        if path in ('/workbench/','/workbench/health-workbench-1.2.apk'):
            page=page.replace('<h1>训练手记</h1>', '<h1>健康工作台</h1>').replace('登录训练手记</button>', '登录健康工作台</button>')
        if path=='/food/':
            page=page.replace('<h1>训练手记</h1>', '<h1>食衡 · 饮食手记</h1><div>使用跑步教练的账号和密码登录</div>').replace('登录训练手记</button>', '登录食衡</button>')
        return self.reply(status,page.encode(),'text/html; charset=utf-8')
    def code_page(self, message='', status=200, cookie=None):
        return self.reply(status,CODE_PAGE.replace('<!--notice-->',html.escape(message)).encode(),
                          'text/html; charset=utf-8',cookie=cookie)

    def complete_login(self, account, epoch, dest, trusted_digest, new_device=None):
        now=time.time()
        with LOCK:
            for key,session in list(sessions.items()):
                if session[0]<=now or session[1]!=account['verifier'] or session[2]!=epoch:
                    del sessions[key]
            sessions.pop(self.key(),None)
            session_id=secrets.token_urlsafe(32)
            sessions[session_id]=(now+604800,account['verifier'],epoch,trusted_digest)
        self.send_response(303)
        self.send_header('Location',dest)
        self.send_header('Cache-Control','no-store')
        flags='; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age='
        self.send_header('Set-Cookie','__Host-mobile='+session_id+flags+'604800')
        self.send_header('Set-Cookie',CHALLENGE_COOKIE+'='+flags+'0')
        if new_device:
            self.send_header('Set-Cookie',DEVICE_COOKIE+'='+new_device+flags+str(second_factor.TRUST_SECONDS))
        self.end_headers()

    def check_second_factor(self, form):
        account=web_account.read_account()
        nonce=self.key(CHALLENGE_COOKIE)
        now=time.time()
        # Reserve each attempt under the lock so parallel guesses share both limits.
        with LOCK:
            challenge=challenges.get(nonce)
            if (not challenge or challenge['until']<=now or not account or
                    challenge['owner']!=account['verifier'] or challenge['tries']>=5):
                challenges.pop(nonce,None)
                return self.login_page(message='验证已过期，请重新输入用户名和密码。',status=401)
            code_failures[:]=[stamp for stamp in code_failures if stamp>now-300]
            if len(code_failures)>=10:return self.code_page('尝试次数过多，请五分钟后重新登录。',429)
            if challenge.get('busy'):return self.code_page('正在核验，请稍后再试。',409)
            challenge['busy']=True
            code_failures.append(now)
            challenge['tries']+=1
        remember=form.get('remember',[''])[0]=='yes'
        label=form.get('device',[''])[0].strip()
        if not label:
            ua=self.headers.get('User-Agent','')
            label=next((name for name in ('iPhone','iPad','Android','Windows','Macintosh','Linux') if name in ua),'常用浏览器')
        ok,token=second_factor.verify_code(account['verifier'],challenge['epoch'],form.get('otp',[''])[0].strip(),remember,label)
        if not ok:
            with LOCK:challenge['busy']=False
            return self.code_page('验证码无效或已使用，请输入验证器显示的新验证码。',401)
        with LOCK:
            if challenges.pop(nonce,None) is not challenge:
                return self.login_page(message='本次验证已结束，请重新登录。',status=401)
            if now in code_failures:code_failures.remove(now)
        return self.complete_login(account,challenge['epoch'],challenge['dest'],second_factor.token_digest(token),token)

    def do_GET(self):
        path=self.path.split('?')[0]
        if path=='/workbench/health-workbench-1.2.apk':
            if not self.authed():return self.login_page(path)
            try:package=(ROOT/'health-workbench-1.2.apk').read_bytes()
            except OSError:return self.reply(503,{'error':'安装包暂时无法读取'})
            self.send_response(200)
            self.send_header('Content-Type','application/vnd.android.package-archive')
            self.send_header('Content-Disposition','attachment; filename="health-workbench-1.2.apk"')
            self.send_header('Content-Length',str(len(package)))
            self.send_header('Cache-Control','private, no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers()
            self.wfile.write(package)
            return
        # Personal workbench route
        if path in ('/workbench','/workbench/'):
            if not self.authed():
                return self.login_page('/workbench/')
            nonce=secrets.token_urlsafe(24)
            page=(ROOT/'workbench.html').read_text(encoding='utf-8').replace('<script>', '<script nonce="'+nonce+'">', 1)
            return self.reply(200,page.encode('utf-8'),'text/html; charset=utf-8',nonce=nonce)
        if path=='/food' or path.startswith('/food/'):
            return food_site.serve(self, path)
        if path=='/daily-worker.js':
            digest=hashlib.sha256()
            for name in ('mobile.html','mobile.js','mobile_daily.js'):
                digest.update((ROOT/name).read_bytes())
            worker=(ROOT/'daily-worker.js').read_bytes().replace(b'__SHELL_VERSION__',digest.hexdigest()[:16].encode())
            return self.reply(200,worker,'application/javascript')
        if path in ('/','/desktop','/mobile'):
            if not self.authed():return self.login_page(path)
            mobile=path=='/mobile' or (path=='/' and re.search('Android|iPhone|iPad|Mobile',self.headers.get('User-Agent',''),re.I))
            nonce=secrets.token_urlsafe(24)
            page=home_document(nonce) if mobile else public_desktop.document(nonce)
            return self.reply(200,page,'text/html; charset=utf-8',nonce=nonce,poster_preview=True)
        if not self.authed():return self.reply(401,{'error':'请先登录'})
        if path=='/api/food/profile':
            try:
                _,row=food_records.account_profile()
                return self.reply(200,{**row,'token':self.csrf()})
            except sqlite3.Error:return self.reply(503,{'error':'档案暂时不可用'})
        if path.startswith('/api/food/barcode/'): 
            return self.reply(*food_labels.catalog_lookup(path.removeprefix('/api/food/barcode/')))
        if path=='/api/food/period':
            from food_range import read
            try:return self.reply(200,read(self.path))
            except (ValueError,OverflowError):return self.reply(400,{'error':'日期范围无效'})
            except (sqlite3.Error,OSError):return self.reply(503,{'error':'餐食暂不可用'})
        if path in ('/api/food/meals','/api/food/shared') or path.startswith('/api/food/photo/'):
            return food_records.serve_get(self,path)
        if path=='/api/session':return self.reply(200,{'token':self.csrf()})
        if path.startswith(PREFIX):return serve(self.path,self.reply)
        if public_desktop.is_desktop_read(path):
            try:return public_desktop.serve_read(self,path)
            except (OSError,http.client.HTTPException):return self.reply(503,{'error':'桌面数据服务暂不可用'})
        if path=='/offline-feedback':
            # Cache only the form shell. All private daily data stays out of Cache Storage.
            nonce=secrets.token_urlsafe(24)
            head=(ROOT/'mobile.html').read_text(encoding='utf8').split('</style>',1)[0]
            scripts='\n'.join((ROOT/name).read_text(encoding='utf-8-sig') for name in ('mobile.js','mobile_daily.js'))
            page=head+'</style><header id="offline-shell"><strong>训练手记</strong><button id="refresh">返回在线版</button></header><p id="msg" role="status"></p><main id="view"></main>'
            page+='<script nonce="'+nonce+'">'+scripts+'</script></html>'
            return self.reply(200,page.encode(),'text/html; charset=utf-8',nonce=nonce)
        if re.fullmatch(r'/poster-art/[a-z]+-[a-z]+\.webp', path):
            art = ROOT / 'poster-art' / path.rsplit('/', 1)[1]
            if not art.is_file():
                return self.reply(404, {})
            etag = '"' + str(art.stat().st_mtime_ns) + '"'
            if self.headers.get('If-None-Match') == etag:
                self.send_response(304)
                self.send_header('ETag',etag)
                self.send_header('Cache-Control','private, no-cache')
                self.end_headers()
                return
            return self.reply(200, art.read_bytes(), 'image/webp', etag=etag)
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
                    value={'revision':row[0] if row else 0,'fields':json.loads(row[1]) if row else {},
                           'strengthPlans':daily_strength_plan(conn,path[9:])}
                else:
                    value=None
                return self.reply(200,value) if value is not None else self.reply(404,{})
        return self.reply(404,{})
    def do_POST(self):
        if self.headers.get('Origin')!=BASE:return self.reply(403,{'error':'来源无效'})
        try:
            n=int(self.headers.get('Content-Length','0'))
            if not 0<=n<=(4_000_000 if self.path.startswith('/api/food/photo/') else 2_500_000 if self.path in ('/api/food/label','/api/food/recognize-photo') else 6_000_000 if self.path=='/api/food/meals' else 65536 if self.path in ('/api/daily','/api/training-feedback') else 32768):return self.reply(413,{})
            if self.path in ('/login','/verify-device'):
                if self.headers.get_content_type()!='application/x-www-form-urlencoded':return self.reply(415,{})
                if n>4096:return self.reply(413,{})
                form=urllib.parse.parse_qs(self.rfile.read(n).decode(),max_num_fields=5)
                if self.path=='/verify-device':return self.check_second_factor(form)
                dest=form.get('next',['/'])[0]
                if dest not in ('/','/desktop','/mobile','/food/','/workbench/','/workbench/health-workbench-1.2.apk'):dest='/'
                account=web_account.read_account()
                if not account:return self.login_page(dest,status=503)
                with LOCK:
                    t=time.time();failures[:]=[x for x in failures if x>t-300]
                    if len(failures)>=12:return self.login_page(dest,'请五分钟后重试。',429)
                    failures.append(t)
                if not web_account.verify(account,form.get('username',[''])[0],form.get('password',[''])[0]):
                    return self.login_page(dest,'用户名或密码不正确。',401)
                with LOCK:
                    if t in failures:failures.remove(t)
                epoch=second_factor.generation()
                if not epoch:return self.login_page(dest,'本机验证器尚未就绪。',503)
                digest=second_factor.token_digest(self.key(DEVICE_COOKIE))
                if digest and second_factor.active(account['verifier'],epoch,digest):
                    return self.complete_login(account,epoch,dest,digest)
                nonce=secrets.token_urlsafe(32)
                with LOCK:
                    for key,item in list(challenges.items()):
                        if item['until']<=t:del challenges[key]
                    challenges.pop(self.key(CHALLENGE_COOKIE),None)
                    if len(challenges)>=256:challenges.pop(next(iter(challenges)))
                    challenges[nonce]=dict(owner=account['verifier'],epoch=epoch,dest=dest,until=t+CHALLENGE_SECONDS,tries=0)
                cookie=f'{CHALLENGE_COOKIE}={nonce}; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age={CHALLENGE_SECONDS}'
                return self.code_page(cookie=cookie)
            if not self.authed():return self.reply(401,{'error':'请重新登录'})
            if self.path.startswith('/api/food/photo/'):
                if not hmac.compare_digest(self.headers.get('X-Archive-Token','').encode(),self.csrf().encode()):return self.reply(403,{})
                return self.reply(*food_records.upload_photo(self.path.removeprefix('/api/food/photo/'),self.rfile.read(n),self.headers.get_content_type()))
            if self.path=='/api/food/recognize-photo':
                if not hmac.compare_digest(self.headers.get('X-Archive-Token','').encode(),self.csrf().encode()):return self.reply(403,{})
                if self.headers.get_content_type()!='image/jpeg':return self.reply(415,{'error':'请选择餐食照片。'})
                return self.reply(*food_language.recognize_photo(self.rfile.read(n)))
            if self.path=='/api/food/interpret':
                if not hmac.compare_digest(self.headers.get('X-Archive-Token','').encode(),self.csrf().encode()):return self.reply(403,{})
                if self.headers.get_content_type()!='application/json':return self.reply(415,{})
                return self.reply(*food_language.interpret(json.loads(self.rfile.read(n))))
            if self.path=='/api/food/label':
                if not hmac.compare_digest(self.headers.get('X-Archive-Token','').encode(),self.csrf().encode()):
                    return self.reply(403,{'error':'请刷新页面后再拍照。'})
                if self.headers.get_content_type()!='image/jpeg':return self.reply(415,{'error':'请选择营养表照片。'})
                return self.reply(*food_labels.recognize_photo(self.rfile.read(n)))
            if self.path in ('/api/food/meals','/api/food/profile','/api/food/shared'):
                if not hmac.compare_digest(self.headers.get('X-Archive-Token','').encode(),self.csrf().encode()):
                    return self.reply(403,{'error':'请刷新页面后重试'})
                if self.headers.get_content_type()!='application/json':return self.reply(415,{})
                update={'/api/food/profile':food_records.account_profile,'/api/food/meals':food_records.update,'/api/food/shared':food_records.update_shared}[self.path]
                status,row=update(json.loads(self.rfile.read(n)))
                return self.reply(status,row)
            if self.path=='/logout':
                with LOCK:sessions.pop(self.key(),None)
                if self.headers.get_content_type()=='application/x-www-form-urlencoded':
                    self.send_response(303);self.send_header('Location','/');self.send_header('Cache-Control','no-store')
                    self.send_header('Set-Cookie','__Host-mobile=; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
                    self.end_headers();return
                return self.reply(200,{},cookie='__Host-mobile=; Max-Age=0; Secure; HttpOnly; SameSite=Strict; Path=/')
            if self.path in ('/api/daily','/api/training-feedback') and not hmac.compare_digest(self.headers.get('X-Archive-Token','').encode(),self.csrf().encode()):
                return self.reply(403,{'error':'请刷新页面后重试'})
            if self.path not in ('/api/feedback','/api/day-feedback','/api/daily','/api/training-feedback'):return self.reply(404,{})
            if self.headers.get_content_type()!='application/json':return self.reply(415,{})
            if self.path in ('/api/day-feedback','/api/daily'):
                data=json.loads(self.rfile.read(n))
                result=submit_day(DB,data,before_change=backup_daily)
                if not result['replayed']:
                    mark_daily_publish()
                try:
                    self.reply(200, result)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
                finally:
                    publish_pending_daily()
                return
            status,result=upstream(json.loads(self.rfile.read(n)));return self.reply(status,result)
        except RuntimeError as err:return self.reply(409,{'error':str(err)})
        except (ValueError,UnicodeError):return self.reply(400,{'error':'表单格式无效'})
        except (OSError,sqlite3.Error,http.client.HTTPException):return self.reply(503,{'error':'训练档案暂时不可用，请保留表单后重试'})
LOGIN='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>训练手记 · 登录</title><style>*{box-sizing:border-box}body{margin:0;min-height:100svh;display:grid;place-content:center;padding:20px;background:#faf7f3;color:#30292b;font:16px/1.5 system-ui,sans-serif}h1,form,p{width:min(82vw,22rem)}h1{margin:0 0 16px;font-size:28px}label,input,button{display:block;width:100%}label+label{margin-top:14px}input,button{font:inherit;padding:11px 12px;border-radius:8px}input{margin-top:5px;border:1px solid #cfc4c0}button{margin-top:22px;background:#81263d;color:white;border:0;cursor:pointer}p{color:#81263d}p:empty{display:none}</style><h1>训练手记</h1><p role="status"><!--notice--></p><form action="/login" method="post"><input type="hidden" name="next" value="DESTINATION"><label>用户名<input name="username" autocomplete="username" maxlength="80" required></label><label>密码<input name="password" type="password" autocomplete="current-password" maxlength="256" required></label><button>登录训练手记</button></form></html>'''
CODE_PAGE=LOGIN.split('<h1>训练手记</h1>',1)[0]+'''<style>
.trust-field{display:flex;align-items:center;gap:8px;margin-top:16px}.trust-field input{width:auto;margin:0}
</style><h1>新设备验证</h1><p role="status"><!--notice--></p>
<form method="post" action="/verify-device">
<label>验证器中的 6 位验证码<input name="otp" inputmode="numeric" pattern="[0-9]{6}" minlength="6" maxlength="6" autocomplete="one-time-code" required autofocus></label>
<label class="trust-field"><input name="remember" type="checkbox" value="yes">记住此浏览器 90 天</label>
<details><summary>设备名称（选填）</summary><input name="device" aria-label="设备名称" placeholder="如：我的手机" maxlength="64"></details>
<button>验证并登录</button></form><p><small>也可在项目电脑打开「登录验证器与常用设备」查看验证码。</small></p></html>'''
if __name__=='__main__':
    server = ThreadingHTTPServer(('127.0.0.1',8876), H)
    if publish_marker.exists():
        threading.Thread(target=publish_pending_daily, daemon=True).start()
    server.serve_forever()

