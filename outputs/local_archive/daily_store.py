import sqlite3,json,datetime,uuid
FIELDS={'overall','fatigue','running','strength','stretching','nutrition','recovery','body'}
def init(db):
 with sqlite3.connect(db) as c:
  c.execute('''CREATE TABLE IF NOT EXISTS daily_submissions(date TEXT PRIMARY KEY,payload_json TEXT NOT NULL,revision INTEGER NOT NULL,submission_id TEXT NOT NULL,request_id TEXT UNIQUE NOT NULL,status TEXT NOT NULL DEFAULT '待分析',created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''')
  c.execute('''CREATE TABLE IF NOT EXISTS daily_submission_history(id INTEGER PRIMARY KEY,date TEXT NOT NULL,revision INTEGER NOT NULL,payload_json TEXT NOT NULL,request_id TEXT UNIQUE NOT NULL,submitted_at TEXT NOT NULL,UNIQUE(date,revision))''')
def submit(db,data):
 if not isinstance(data,dict):raise ValueError('提交格式错误')
 day=data.get('date','')
 try:
  if datetime.date.fromisoformat(day).isoformat()!=day:raise ValueError()
 except (ValueError,TypeError):raise ValueError('日期无效')
 today=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date()
 if datetime.date.fromisoformat(day)>today:raise ValueError('不能提交未来日期的完成记录')
 payload=data.get('fields');rid=data.get('request_id');expected=data.get('expected_revision',0)
 if not isinstance(payload,dict) or set(payload)-FIELDS:raise ValueError('存在不支持的字段')
 if not isinstance(expected,int) or isinstance(expected,bool) or expected<0:raise ValueError('版本号无效')
 try:uuid.UUID(rid)
 except (ValueError,TypeError,AttributeError):raise ValueError('请求编号无效')
 clean={}
 for key in FIELDS:
  value=payload.get(key,'')
  if not isinstance(value,str) or len(value)>6000:raise ValueError('字段过长或格式错误')
  clean[key]=value.strip()
 if not any(clean.values()):raise ValueError('请至少填写一项实际记录')
 if clean['fatigue']:
  try:v=float(clean['fatigue'])
  except ValueError:raise ValueError('疲劳程度应为0–10')
  if not 0<=v<=10:raise ValueError('疲劳程度应为0–10')
 encoded=json.dumps(clean,ensure_ascii=False,sort_keys=True)
 now=datetime.datetime.now(datetime.timezone.utc).isoformat()
 with sqlite3.connect(db,timeout=10) as c:
  c.row_factory=sqlite3.Row;c.execute('BEGIN IMMEDIATE')
  replay=c.execute('SELECT * FROM daily_submission_history WHERE request_id=?',(rid,)).fetchone()
  if replay:
   if replay['date']!=day or replay['payload_json']!=encoded:raise ValueError('请求编号重复但内容不同')
   row=dict(c.execute('SELECT * FROM daily_submissions WHERE date=?',(day,)).fetchone());return {'ok':True,'date':day,'revision':replay['revision'],'submission_id':row['submission_id'],'replayed':True}
  old=c.execute('SELECT * FROM daily_submissions WHERE date=?',(day,)).fetchone()
  if (old['revision'] if old else 0)!=expected:raise RuntimeError('此日期记录已更新，请重新读取后补充，避免覆盖其他设备的修改')
  rev=expected+1;sid=old['submission_id'] if old else str(uuid.uuid4())
  c.execute('INSERT INTO daily_submission_history(date,revision,payload_json,request_id,submitted_at) VALUES(?,?,?,?,?)',(day,rev,encoded,rid,now))
  c.execute('''INSERT INTO daily_submissions VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(date) DO UPDATE SET payload_json=excluded.payload_json,revision=excluded.revision,request_id=excluded.request_id,status='待分析',updated_at=excluded.updated_at''',(day,encoded,rev,sid,rid,'待分析',old['created_at'] if old else now,now))
 return {'ok':True,'date':day,'revision':rev,'submission_id':sid,'replayed':False}
