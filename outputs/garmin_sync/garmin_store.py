from contextlib import closing
"""Transactional, replay-safe Garmin imports into the existing coach archive."""
import copy, datetime as dt, hashlib, json, sqlite3, uuid
from pathlib import Path

from garmin_verified import merge_records

TZ=dt.timezone(dt.timedelta(hours=8))
def now():return dt.datetime.now(TZ).isoformat(timespec='seconds')
def encode(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(x):return hashlib.sha256(encode(x).encode()).hexdigest()
def meta(c,key,default=None):
    row=c.execute('SELECT value_json FROM metadata WHERE key=?',(key,)).fetchone()
    return json.loads(row[0]) if row else copy.deepcopy(default)

class Writer:
    def __init__(self,c,batch,source):self.c=c;self.batch=batch;self.source=source;self.changes=0
    def revision(self,entity,key,old,new):
        if old==new:return False
        self.c.execute('INSERT INTO revisions(created_at,entity,entity_key,previous_json,replacement_json,reason) VALUES(?,?,?,?,?,?)',(now(),entity,str(key),encode(old),encode(new),'Garmin API revision; batch='+self.batch))
        self.changes+=1;return True
    def metadata(self,key,value):
        old=meta(self.c,key)
        if self.revision('metadata',key,old,value):self.c.execute('INSERT INTO metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json',(key,encode(value)))
    def row(self,table,keycol,key,updates):
        # Table and column identifiers are internal constants, never external data.
        r=self.c.execute(f'SELECT * FROM {table} WHERE {keycol}=?',(key,)).fetchone();old=dict(r) if r else None
        new=dict(old or {keycol:key});new.update(updates)
        if self.revision(table,key,old,new):
            cols=list(new); sql=','.join(cols); placeholders=','.join('?' for _ in cols)
            self.c.execute(f'INSERT INTO {table} ({sql}) VALUES({placeholders}) ON CONFLICT({keycol}) DO UPDATE SET '+','.join(f'{x}=excluded.{x}' for x in cols if x!=keycol),[new[k] for k in cols])
    def observation(self,kind,key,value):
        mk='garmin_api_'+kind;data=meta(self.c,mk,{'records':{}});old=data['records'].get(key)
        if old and old.get('content_hash')==digest(value):return False
        data['records'][key]={'content_hash':digest(value),'value':value,'source_id':self.source,'batch_id':self.batch}
        self.metadata(mk,data);return True

def apply_device_rpe(w, session, detail, raw, source, day):
    """Adopt the watch self-evaluation only under explicit user policy."""
    import math
    policy=meta(w.c,'rpe_source_policy',{})
    if policy.get('preferred_source')!='garmin_watch_self_evaluation':return
    feedback=meta(w.c,'training_session_feedback',{}).get(str(session),{})
    manual=feedback.get('fields',{}).get('rpe')
    if manual is not None and feedback.get('rpe_source')!='garmin_watch_self_evaluation':return
    if isinstance(raw,bool) or not isinstance(raw,(int,float)) or not math.isfinite(raw) or not 0<=raw<=100:return
    current=w.c.execute('SELECT session_rpe FROM sessions WHERE id=?',(session,)).fetchone()[0]
    prior=detail.get('rpe_provenance',{})
    if current is not None and prior.get('source')!='garmin_watch_self_evaluation':return
    value=raw/10
    w.row('sessions','id',session,{'session_rpe':value})
    detail['rpe_provenance']={'source':'garmin_watch_self_evaluation','label':'佳明手表主观反馈','raw_field':'summaryDTO.directWorkoutRpe','raw_value':raw,'scale':'0–10','value':value,'conversion':'raw / 10','source_id':source,'data_date':day,'adopted_at':now()}

def import_batch(db,bundle,backup_dir,fail_after=None):
    db=Path(db).resolve()
    if not db.is_file():raise ValueError('Existing database required')
    # Content-addressed batch identity; a retry cannot duplicate a completed import.
    dt.datetime.fromisoformat(bundle['read_at'])
    for group in ['recovery','monitoring']:
        if any(not r.get('date') or r['date']>bundle['data_date'] for r in bundle.get(group,[])):raise ValueError('Future or missing observation date')
    for name,entry in bundle.get('sources',{}).items():
        path=(Path(bundle['source_root'])/name).resolve()
        if not path.is_relative_to(Path(bundle['source_root']).resolve()):raise ValueError('Invalid source path')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('Source integrity mismatch')
    batch=digest(bundle);c=sqlite3.connect(db,timeout=30);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
    c.execute('BEGIN IMMEDIATE')
    try:
        runs=meta(c,'garmin_sync_runs',{'records':[]})
        if any(r.get('api_batch_id')==batch for r in runs['records']):
            c.rollback();return {'replayed':True,'batch_id':batch,'changes':0}
        # Lock blocks writers; a second read connection backs up the pre-transaction DB including WAL.
        directory=Path(backup_dir);directory.mkdir(parents=True,exist_ok=True)
        backup=directory/('garmin_'+dt.datetime.now(TZ).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]+'.sqlite3')
        with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(backup)) as dst:src.backup(dst)
        with closing(sqlite3.connect(backup)) as b:
            if b.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Backup integrity failure')
        source=c.execute('INSERT INTO sources(source_key,kind,reference,note) VALUES(?,?,?,?)',('garmin-api:'+batch,bundle.get('source_kind','garmin_api'),bundle['source_root'],encode({'read_at':bundle['read_at'],'source_manifest':bundle.get('sources',{}),'scope':bundle['scope']}))).lastrowid
        w=Writer(c,batch,source)
        for r in bundle.get('recovery',[]):
            day=r['date'];fields=r['fields'];values={k:v for k,v in fields.items() if v is not None}
            if not values and not r.get('recovery_extras') and not r.get('night_vitals'):continue
            changed=w.observation('recovery',day,r)
            if not changed:continue
            row=c.execute('SELECT * FROM daily_recovery WHERE date=?',(day,)).fetchone();detail=json.loads(row['details_json'] or '{}') if row else {}
            detail.update(values);detail['api_source_id']=source;detail['last_verified_at']=bundle['read_at']
            if fields.get('hrv_baseline_low') is not None and fields.get('hrv_baseline_high') is not None:
                detail['hrv_baseline_ms']={'low':fields['hrv_baseline_low'],'high':fields['hrv_baseline_high']}
            if fields.get('hrv_status_raw') is not None:detail['seven_day_hrv_status']={'BALANCED':'平衡','LOW':'低','UNBALANCED':'不平衡','POOR':'较差'}.get(fields['hrv_status_raw'],fields['hrv_status_raw'])
            for name,field in [('sleep','sleep_minutes'),('hrv','night_hrv_ms'),('resting_hr','resting_hr_bpm')]:
                if fields.get(field) is not None:detail[name+'_data_date']=day;detail[name+'_source_id']=source
            if r.get('readiness_snapshots'):detail['api_readiness_snapshots']=r['readiness_snapshots']
            if r.get('recovery_extras'):
                extra=detail.get('recovery_extras',{});extra.update(r['recovery_extras']);extra['source_id']=source;detail['recovery_extras']=extra
            if r.get('night_vitals'):detail['night_vitals']={**r['night_vitals'],'source_id':source,'read_at':bundle['read_at']}
            updates={k:v for k,v in r['daily_recovery_candidate'].items() if k!='date' and v is not None}
            updates['details_json']=encode(detail)
            if not row:updates['source_id']=source
            w.row('daily_recovery','date',day,updates)
        if fail_after=='recovery':raise RuntimeError('Injected rollback test')
        for item in bundle.get('curve_backfill',[]):
            row=c.execute('SELECT session_id,details_json FROM running_details WHERE session_id=(SELECT id FROM sessions WHERE external_key=?)',(item['external_key'],)).fetchone()
            if not row:raise ValueError('Curve requires an existing activity')
            d=json.loads(row['details_json']);d['archived_curve']={**item['curve'],'source_id':source};w.row('running_details','session_id',row['session_id'],{'details_json':encode(d)})
        # Explicit one-time historical lap import; never changes activity totals or curated laps.
        for item in bundle.get('lap_backfill',[]):
            session=c.execute('SELECT id FROM sessions WHERE external_key=?',(item['external_key'],)).fetchone()
            if not session:raise ValueError('Lap backfill requires existing activity')
            sid=session['id']
            existing=c.execute('SELECT COUNT(*) FROM running_laps WHERE session_id=?',(sid,)).fetchone()[0]
            if existing:raise ValueError('Refusing to overwrite existing laps')
            numbers=[p['lap'] for p in item['laps']]
            if len(numbers)!=len(set(numbers)) or any(not isinstance(n,int) or n<1 for n in numbers):raise ValueError('Invalid lap numbering')
            for payload in item['laps']:
                payload=dict(payload,source_id=source,observed_at=bundle['read_at'])
                lid=c.execute('INSERT INTO running_laps(session_id,lap_number,details_json) VALUES(?,?,?)',(sid,payload['lap'],encode(payload))).lastrowid
                w.revision('running_laps',lid,None,payload)
            if item.get('archive_info'):
                row=c.execute('SELECT details_json FROM running_details WHERE session_id=?',(sid,)).fetchone()
                detail=json.loads(row['details_json']);detail['lap_archive']={**item['archive_info'],'source_id':source}
                w.row('running_details','session_id',sid,{'details_json':encode(detail)})
        for a in bundle.get('activities',[]):
            if not a['date'] or not a['date']<=bundle['data_date']:raise ValueError('Activity date invalid')
            if not w.observation('activities',a['external_key'],a):continue
            row=c.execute('SELECT * FROM sessions WHERE external_key=?',(a['external_key'],)).fetchone()
            if row:session=row['id']
            else:
                session=c.execute('INSERT INTO sessions(external_key,date,sport,duration_minutes,source_id,raw_json) VALUES(?,?,?,?,?,?)',(a['external_key'],a['date'],'running',a['session_candidate']['duration_minutes'],source,'{}')).lastrowid
                w.revision('sessions',session,None,dict(c.execute('SELECT * FROM sessions WHERE id=?',(session,)).fetchone()))
            r=c.execute('SELECT * FROM running_details WHERE session_id=?',(session,)).fetchone();d=json.loads(r['details_json'] or '{}') if r else {}
            # Existing curated/CSV values retain their original precision; API revisions remain queryable separately.
            candidate=a['running_details_candidate'];mapped=candidate['details_json']
            d.update({k:v for k,v in mapped.items() if v is not None and d.get(k) is None})
            d['api_observation']={'fields':mapped,'source_id':source,'device_rpe_raw':a.get('device_rpe_raw'),'curve_validation':a.get('curve_validation'),'warmup':a['warmup'],'cooldown':a['cooldown']}
            if a.get('archived_curve'):d['archived_curve']={**a['archived_curve'],'source_id':source}
            if not d.get('gear_name'):
                names=[x.get('customMakeModel') or x.get('displayName') for x in a['gear_observations'] if x.get('gearTypeName')=='Shoes']
                if len(names)==1:d['gear_name']=names[0]
            d['api_gear_observations']=a['gear_observations']
            if a.get('list_summary'):d['api_list_summary']=a['list_summary']
            apply_device_rpe(w,session,d,a.get('device_rpe_raw'),source,a['date'])
            updates={k:v for k,v in candidate.items() if k!='details_json' and v is not None and (not r or r[k] is None)};updates['details_json']=encode(d)
            w.row('running_details','session_id',session,updates)
            for lap in a['laps']:
                n=lap.get('lapIndex');old=c.execute('SELECT * FROM running_laps WHERE session_id=? AND lap_number=?',(session,n)).fetchone()
                payload=json.loads(old['details_json']) if old else {'lap':n,'distance_km':None if lap.get('distance') is None else lap['distance']/1000,'time_seconds':lap.get('duration'),'average_hr':lap.get('averageHR'),'maximum_hr':lap.get('maxHR')}
                payload['api_raw']=lap
                # Keep manual visible-row labels; fill only an absent explicit step label.
                if not payload.get('step_type'):payload['step_type']={'WARMUP':'热身','COOLDOWN':'缓和','RECOVERY':'恢复','INTERVAL':'跑步','ACTIVE':'跑步'}.get(lap.get('intensityType'),'')
                if old:w.row('running_laps','id',old['id'],{'details_json':encode(payload)})
                else:
                    lid=c.execute('INSERT INTO running_laps(session_id,lap_number,details_json) VALUES(?,?,?)',(session,n,encode(payload))).lastrowid;w.revision('running_laps',lid,None,payload)
        for m in bundle.get('monitoring',[]):
            if not any(v is not None for v in m['fields'].values()):continue
            if not w.observation('monitoring',m['date'],m):continue
            data=meta(c,'garmin_training_monitoring',{'records':[]});rows=data.setdefault('records',[]);r=next((x for x in reversed(rows) if x.get('date')==m['date']),None)
            if r is None:r={'date':m['date'],'measurement_date':m['date'],'report_scope':'device_api'};rows.append(r)
            f=m['fields'];r['api_observation']=m;r['api_source_id']=source
            for k in ['acute_load','chronic_load','load_ratio']:
                if f.get(k) is not None:r[k]=f[k]
            # Only independently verified code 7 is labelled here; other codes require review.
            if f.get('training_status_raw')==7:r['training_status']='高效训练'
            elif f.get('training_status_raw') is not None:r['training_status']='待核对（设备代码'+str(f['training_status_raw'])+'）'
            r['last_verified_at']=bundle['read_at']
            if m.get('period_start'):
                focus=m['load_focus'];r['focus']={'from':m['period_start'],'to':m['period_end'],'anaerobic':focus['monthlyLoadAnaerobic'],'high_aerobic':focus['monthlyLoadAerobicHigh'],'low_aerobic':focus['monthlyLoadAerobicLow'],'status':{'ANAEROBIC_SHORTAGE':'缺乏无氧','HIGH_AEROBIC_SHORTAGE':'缺乏高强度有氧'}.get(focus['trainingBalanceFeedbackPhrase'],focus['trainingBalanceFeedbackPhrase']),'optimal_ranges':{label:{'min':focus['monthlyLoad'+part+'TargetMin'],'max':focus['monthlyLoad'+part+'TargetMax']} for label,part in [('anaerobic','Anaerobic'),('high_aerobic','AerobicHigh'),('low_aerobic','AerobicLow')]}}
                r['focus_scope']='device_api'
                r['focus']['period_method']=m.get('period_method','web_verified')
                r['focus']['period_source']=m.get('period_source')
            w.metadata('garmin_training_monitoring',data)
        # Device plans and unapproved observations remain separate from coach prescriptions.
        for key in ['calendar','plan_details','threshold_observations','personal_records','record_candidates','vo2_observations']:
            if bundle.get(key):w.observation(key,bundle['data_date'],bundle[key])
        if bundle.get('record_types') is not None and 'personal_records' in bundle:
            previous=meta(c,'garmin_personal_records',{'records':[],'history':[]})
            updated,errors=merge_records(previous,bundle['personal_records'],bundle['record_types'],bundle['read_at'],source)
            w.metadata('garmin_personal_records',updated)
            candidates=bundle.get('record_candidates')
            if isinstance(candidates,list):w.metadata('garmin_personal_record_candidates',{'records':candidates,'observed_at':bundle['read_at'],'source_id':source,'note':'候选未自动接受；不混入已接受个人纪录'})
            if errors:
                bundle=copy.deepcopy(bundle);bundle.setdefault('categories',{})['personal_records']={'status':'partial','reason':'；'.join(errors)}
                w.metadata('personal_record_api_conflicts',{'records':errors,'checked_at':bundle['read_at'],'source_id':source})
        if 'weekly_reports' in bundle:
            reports=meta(c,'garmin_weekly_api_reports',{'records':{}})
            reports['records'][bundle['data_date']]={'reports':bundle['weekly_reports'],'read_at':bundle['read_at'],'source_id':source,'note':'汇总日期不作为日测定日期；原始精度保留；不参与本地日值均值'}
            w.metadata('garmin_weekly_api_reports',reports)
        if 'training_plan' in bundle.get('categories',{}):
            day=bundle['data_date'];days=[]
            for offset in range(7):
                date=(dt.date.fromisoformat(day)+dt.timedelta(days=offset)).isoformat()
                items=[x for x in bundle.get('calendar',[]) if x.get('date')==date and x.get('itemType') not in ['activity','weight','sleep']]
                plans=[p for p in bundle.get('plan_details',[]) if date in p.get('schedule_dates',[])]
                days.append({'date':date,'title':'；'.join(x.get('title','') for x in items) if items else '日历无课程条目','status':'published' if items else 'not_listed','source_id':source,'observed_at':bundle['read_at'],'details':'设备接口快照；具体步骤见原始课程，未自动采用。' if items else '未列出课程，不推断为休息。','api_workouts':plans,'api_calendar_items':items})
            w.metadata('garmin_plan_snapshot_'+day,{'from':day,'to':days[-1]['date'],'observed_at':bundle['read_at'],'source':'Garmin CN API','source_id':source,'status':bundle['categories']['training_plan']['status'],'days':days})
        schedule=meta(c,'garmin_sync_schedule',{'categories':{}})
        for key,state in bundle.get('categories',{}).items():
            old=schedule['categories'].get(key,{})
            # Historical backfill must never roll current category state backwards.
            if bundle['read_at'] < old.get('last_attempt_at',''):continue
            new=dict(old,last_attempt_at=bundle['read_at'],status=state['status'],reason=state.get('reason',''),attempted_data_date=bundle['data_date'],pending_catchup=state['status']!='success')
            if state['status']=='success':new.update(last_success_at=bundle['read_at'],data_date=bundle['data_date'])
            schedule['categories'][key]=new
        w.metadata('garmin_sync_schedule',schedule)
        runs['records'].append({'api_batch_id':batch,'batch_key':bundle['data_date']+'_'+bundle['scope'],'checked_at':bundle['read_at'],'imported_at':now(),'status':'success' if bundle.get('categories') and all(x['status']=='success' for x in bundle['categories'].values()) else 'partial','categories':bundle.get('categories',{}),'backup':str(backup),'source_id':source,'followups':bundle.get('followups',[])})
        w.metadata('garmin_sync_runs',runs)
        if c.execute('PRAGMA foreign_key_check').fetchone():raise RuntimeError('Foreign key failure')
        c.commit();return {'replayed':False,'batch_id':batch,'changes':w.changes,'backup':str(backup),'followups':bundle.get('followups',[])}
    except Exception:c.rollback();raise
    finally:c.close()
