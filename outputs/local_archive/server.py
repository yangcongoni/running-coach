from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
import sqlite3,json,secrets,gzip,re,subprocess,sys,threading
from archive_config import desktop_template, origin
from urllib.parse import urlsplit
from daily_store import init,submit
from session_feedback_store import submit_feedback
FEEDBACK_LOCK=threading.Lock()
ROOT=Path(__file__).resolve().parent
DB=ROOT.parent/'训练日志.sqlite3';PORT=8765;TOKEN=secrets.token_urlsafe(32)
ALLOWED_ORIGINS={
 f'localhost:{PORT}':f'http://localhost:{PORT}',
 f'127.0.0.1:{PORT}':f'http://127.0.0.1:{PORT}',
}
desktop_origin = origin('desktop_origin', f'http://localhost:{PORT}')
ALLOWED_ORIGINS[urlsplit(desktop_origin).netloc] = desktop_origin
TABLES=['metadata','sources','strength_baselines','planned_sessions','sessions','running_details','running_laps','strength_sets','daily_recovery','analyses','revisions','periodic_reviews','stretching_records','daily_submissions','daily_submission_history']
def page_data(data):
 # Page projection only. The database and full export retain every original field.
 for row in data['sessions']:
  if row['sport']=='running':
   original=json.loads(row['raw_json'] or '{}')
   row['raw_json']=json.dumps({k:original[k] for k in ('user_followup','user_followups','user_report','original_user_text') if k in original},ensure_ascii=False)
 for row in data['running_details']:
  raw=json.loads(row['details_json'])
  for key in ('userRoles','ownerProfileImageUrlSmall','ownerProfileImageUrlMedium','ownerProfileImageUrlLarge'):raw.pop(key,None)
  if 'splitSummaries' in raw:
   raw['splitSummaries']=[{k:v for k,v in s.items() if k in ('splitType','noOfSplits')} for s in raw['splitSummaries']]
  if raw.get('archived_curve',{}).get('points'):
   raw['archived_curve']['points']=[];raw['archived_curve']['deferred']=True
  row['details_json']=json.dumps(raw,ensure_ascii=False,separators=(',',':'))
 for row in data['revisions']:
  if not re.search('plan|计划',row['entity'] or ''):row['previous_json']=row['replacement_json']=None
 data['_page_projection']=True
 return data
class Handler(BaseHTTPRequestHandler):
 def allowed(self):return self.headers.get('Host') in ALLOWED_ORIGINS
 def send(self,payload,code=200,kind='application/json; charset=utf-8',attachment=None):
  if isinstance(payload,dict):payload=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
  encodings=[x.strip().split(';')[0] for x in self.headers.get('Accept-Encoding','').lower().split(',')]
  compressed=len(payload)>=1024 and 'gzip' in encodings and (kind.startswith('application/json') or kind.startswith('text/html'))
  if compressed:payload=gzip.compress(payload,compresslevel=5)
  self.send_response(code)
  self.send_header('Vary','Accept-Encoding')
  if compressed:self.send_header('Content-Encoding','gzip')
  self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(payload)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; connect-src 'self'")
  if attachment:self.send_header('Content-Disposition','attachment; filename="'+attachment+'"')
  self.end_headers();self.wfile.write(payload)
 def do_GET(self):
  if not self.allowed():self.send({'error':'Host not allowed'},403);return
  path=self.path.split('?')[0]
  if path=='/assets/strength-anatomy-v2.png':self.send((ROOT/'assets/strength-anatomy-v2.png').read_bytes(),kind='image/png');return
  if path=='/assets/strength-anatomy-back.png':self.send((ROOT/'assets/strength-anatomy-back.png').read_bytes(),kind='image/png');return
  if re.fullmatch(r'/assets/race-map-\d+\.png',path):
   target=ROOT/'assets'/path.rsplit('/',1)[-1]
   if target.is_file():self.send(target.read_bytes(),kind='image/png')
   else:self.send({'error':'Map not found'},404)
   return
  downloads={'/download/running-archive-light.html':('训练档案_手机轻量版.html','text/html; charset=utf-8','running-archive-light.html'),'/download/running-archive-light.zip':('running-archive-light.zip','application/zip','running-archive-light.zip')}
  if path in downloads:
   filename,kind,attachment=downloads[path];target=ROOT.parent/filename
   if not target.is_file():self.send({'error':'Offline file not ready'},404);return
   self.send(target.read_bytes(),kind=kind,attachment=attachment);return
  if path=='/api/health':self.send({'status':'ok','version':'tablet-20261023'});return
  if re.fullmatch(r'/api/running/\d+/raw',path):
   with sqlite3.connect(DB) as c:row=c.execute('SELECT details_json FROM running_details WHERE session_id=?',(int(path.split('/')[3]),)).fetchone()
   self.send({'raw':json.loads(row[0])} if row else {'error':'Not found'},200 if row else 404);return
  if path=='/api/session':self.send({'token':TOKEN});return
  if path in ('/api/data','/export.json'):
   with sqlite3.connect(DB) as c:
    c.row_factory=sqlite3.Row;data={t:[dict(r) for r in c.execute('SELECT * FROM '+t)] for t in TABLES}
   release_file=ROOT/'archive_release.json'
   if release_file.exists():
    try:data['_release']={**json.loads(release_file.read_text(encoding='utf-8')),'mode':'live'}
    except (OSError,ValueError):pass
   self.send(page_data(data) if path=='/api/data' else data,attachment='training-archive.json' if path=='/export.json' else None);return
  if path=='/backup.sqlite3':
   with sqlite3.connect(DB) as source,sqlite3.connect(':memory:') as target:source.backup(target);payload=target.serialize()
   self.send(payload,kind='application/vnd.sqlite3',attachment='training-backup.sqlite3');return
  if path in ('/','/index.html'):self.send(desktop_template().encode('utf-8'),kind='text/html; charset=utf-8');return
  self.send({'error':'Not found'},404)
 def do_POST(self):
  host=self.headers.get('Host','')
  if not self.allowed() or self.headers.get('Origin')!=ALLOWED_ORIGINS[host] or not secrets.compare_digest(self.headers.get('X-Archive-Token',''),TOKEN):self.send({'error':'请求来源或会话无效，请刷新页面后重试'},403);return
  if self.path not in ('/api/daily','/api/training-feedback'):self.send({'error':'Not found'},404);return
  if self.headers.get('Content-Type','').split(';')[0]!='application/json':self.send({'error':'请使用JSON提交'},415);return
  try:
   size=int(self.headers.get('Content-Length','0'))
   if not 0<size<=65536:self.send({'error':'提交内容为空或过大'},413);return
   data=json.loads(self.rfile.read(size).decode('utf-8'))
   if self.path=='/api/training-feedback':
    with FEEDBACK_LOCK:
     result=submit_feedback(DB,data)
     try:
      published=subprocess.run([sys.executable,str(ROOT/'export_page.py')],cwd=ROOT,capture_output=True,timeout=120)
      result['offline_updated']=published.returncode==0
      if result['offline_updated']:result['release']=json.loads((ROOT/'archive_release.json').read_text(encoding='utf-8'))
     except (OSError,subprocess.TimeoutExpired,ValueError):result['offline_updated']=False
    self.send(result)
   else:self.send(submit(DB,data))
  except (ValueError,UnicodeDecodeError) as e:self.send({'error':str(e)},400)
  except RuntimeError as e:self.send({'error':str(e)},409)
  except sqlite3.Error:self.send({'error':'数据库未能保存，请保留表单并重试'},500)
 def log_message(self,*args):pass
if __name__=='__main__':
 if not DB.is_file():raise SystemExit("请先运行 init_archive.py 创建空数据库。")
 init(DB);print(f'Training archive: http://127.0.0.1:{PORT}',flush=True);ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
