from contextlib import closing
"""Read-only Garmin CN fetching + audited local import. No remote mutation methods."""
import argparse, datetime as dt, json, logging, sqlite3, time, uuid
from pathlib import Path
from garmin_adapter import Adapter, completeness, workout_step
from garmin_verified import focus_period, records_projection, STATUS_MAP
from garmin_store import import_batch, meta, now, encode, digest
from garmin_secure_auth import connect, save, VAULT, crypt

ROOT=Path(__file__).resolve().parents[2]
DB=ROOT/'outputs'/'训练日志.sqlite3'
SOURCES=ROOT/'outputs'/'sources'/'garmin_api'
BACKUPS=ROOT/'outputs'/'backups'
TZ=dt.timezone(dt.timedelta(hours=8))
RECOVERY=[('sleep','get_sleep_data'),('hrv','get_hrv_data'),('summary','get_stats'),('readiness','get_training_readiness')]

class Fetcher:
    def __init__(self,api,folder):self.api=api;self.root=folder;self.results={}
    def call(self,name,method,*args,folder='results',**kwargs):
        dest=self.root/folder;dest.mkdir(parents=True,exist_ok=True)
        try:
            data=getattr(self.api,method)(*args,**kwargs)
            envelope={'method':method,'args':args,'kwargs':kwargs,'read_at':now(),'data':data}
            self.results[name]={'status':'success','read_at':envelope['read_at']}
        except Exception as e:
            code=getattr(getattr(e,'response',None),'status_code',None)
            envelope={'method':method,'read_at':now(),'data':None,'error_type':type(e).__name__,'http_status':code}
            self.results[name]={'status':'failed','error_type':type(e).__name__}
            if code in (401,429) or 'TooManyRequests' in type(e).__name__:raise RuntimeError('stop_auth_or_rate_limit') from None
        (dest/(name+'.json')).write_text(encode(envelope),encoding='utf-8');time.sleep(.4)
        return envelope['data']

def state(status,reason=''):return {'status':status,'reason':reason}
def recovery_categories(r):
    f=r['fields'];groups={'sleep':['sleep_minutes','sleep_score','bedtime_local','wake_time_local','deep_sleep_minutes','light_sleep_minutes','rem_sleep_minutes','awake_minutes'],'hrv':['night_hrv_ms','seven_day_hrv_ms','hrv_status_raw','hrv_highest_5min_ms','hrv_baseline_low','hrv_baseline_high'],'resting_hr':['resting_hr_bpm']}
    return {k:state(completeness({x:f.get(x) for x in names})['status'],'API按实际日期核对；缺项需网页补查') for k,names in groups.items()}

def pending_route_checks(c, day):
    """Carry unresolved route reviews forward without re-fetching full activities."""
    pending=[]
    for sid, date, key, raw in c.execute("SELECT s.id,s.date,s.external_key,d.details_json FROM sessions s JOIN running_details d ON d.session_id=s.id WHERE s.external_key LIKE 'garmin:%' AND s.date>=? AND s.date<=?", ('2026-10-23',day)):
        d=json.loads(raw or '{}'); route=d.get('route_observation') or {}
        if route.get('status')=='reviewed' and route.get('group_id') and route.get('name'):continue
        pending.append({'session_id':sid,'date':date,'activity_id':key.split(':',1)[1],'reason':route.get('limitation') or '路线尚未核对'})
    return pending

def fetch(day,scope,db=DB):
    folder=SOURCES/(day+'_'+scope+'_'+uuid.uuid4().hex[:10]);folder.mkdir(parents=True)
    b={'schema_version':1,'data_date':day,'scope':scope,'read_at':now(),'source_root':str(folder),'sources':{},'categories':{},'followups':[]}
    with closing(sqlite3.connect(db)) as c:
        schedule=meta(c,'garmin_sync_schedule',{'categories':{}})
        known={r[0]:r[1] for r in c.execute("SELECT s.external_key,d.details_json FROM sessions s JOIN running_details d ON d.session_id=s.id WHERE s.external_key LIKE 'garmin:%'")}
        pending=meta(c,'personal_record_pending_checks',{})
        route_pending=pending_route_checks(c,day)
        created_workouts=meta(c,'garmin_created_workouts',{'records':[]})['records']
        target_revisions={str(record['workout_id']):record['target_source_id']
                          for record in created_workouts if record.get('target_source_id')}
        previous_plans=meta(c,'garmin_api_plan_details',{'records':{}})['records']
    try:api=connect()
    except Exception as e:
        keys=['sleep','hrv','resting_hr','training_plan'] if scope=='morning' else ['running','training_status','training_load','load_focus']
        b['categories']={k:state('failed','本机登录不可用：'+type(e).__name__) for k in keys};b['followups']=['重新本机登录后补查，不推进成功时间'];return b
    f=Fetcher(api,folder);adapter=Adapter(folder)
    morning=scope=='morning'
    sunday=not morning and dt.date.fromisoformat(day).weekday()==6
    needs_recovery=morning or any(schedule['categories'].get(k,{}).get('data_date')!=day or schedule['categories'].get(k,{}).get('status')!='success' for k in ['sleep','hrv','resting_hr'])
    try:
        if needs_recovery:
            for prefix,method in RECOVERY:f.call(prefix+'_'+day,method,day)
            r=adapter.recovery(day);b['recovery']=[r];b['categories'].update(recovery_categories(r))
            vitals=r.get('night_vitals') or {}
            b['categories']['night_vitals']=state(completeness({k:(vitals.get(k) or {}).get('average') for k in ['respiration','spo2']})['status'],'睡眠起床日；夜间呼吸及血氧原始采样与设备汇总')
        elif not morning:
            # Refresh readiness/recovery time; daily battery and stress are retired.
            f.call('readiness_'+day,'get_training_readiness',day)
            b['recovery']=[adapter.recovery(day)]
        if b.get('recovery'):
            extra=b['recovery'][-1].get('recovery_extras') or {}
            indicators={'readiness':extra.get('morning',{}).get('score'),'recovery_time':extra.get('recovery_time',{}).get('minutes')}
            b['categories']['recovery_extras']=state(completeness(indicators)['status'],'准备程度按晨间快照，恢复时间按最新有效测定')
        needs_plan=morning or schedule['categories'].get('training_plan',{}).get('data_date')!=day or schedule['categories'].get('training_plan',{}).get('status')!='success'
        if needs_plan:
            end=(dt.date.fromisoformat(day)+dt.timedelta(days=6)).isoformat();items=[]
            for name,date in [('calendar_previous',day),('calendar_current',end)]:items+=(f.call(name,'get_calendar_week',date) or {}).get('calendarItems',[])
            selected={encode(x):x for x in items if day<=str(x.get('date',''))[:10]<=end};b['calendar']=list(selected.values());b['plan_details']=[]
            cache={x['uuid']:x for snapshot in previous_plans.values() for x in snapshot.get('value',[]) if x.get('uuid')}
            for item in b['calendar']:
                uid=item.get('workoutUuid');wid=item.get('workoutId')
                if not uid and not wid:continue
                key=uid or str(wid);summary_hash=digest(item);old=cache.get(key)
                # Editing step targets in Connect can leave the calendar summary unchanged.
                target_revision=target_revisions.get(str(wid))
                if (old and old.get('status')=='success' and old.get('summary_hash')==summary_hash
                        and old.get('target_source_id')==target_revision):
                    b['plan_details'].append(old);continue
                raw=f.call('adaptive_workout_'+key,'connectapi','/workout-service/fbt-adaptive/'+uid,folder='verification_extra') if uid else f.call('workout_'+key,'get_workout_by_id',wid,folder='verification_extra')
                raw=raw or {};segments=[{'steps':[workout_step(x) for x in segment.get('workoutSteps',[])]} for segment in raw.get('workoutSegments',[])]
                b['plan_details'].append({'uuid':key,'schedule_dates':[item['date']],'name':raw.get('workoutName'),'target_source_id':target_revision,'summary_hash':summary_hash,'segments':segments,'raw':raw,'status':'success' if segments and all(x['steps'] for x in segments) else 'partial','adopted_into_coach_plan':False})
            ok=all(f.results[n]['status']=='success' for n in ['calendar_previous','calendar_current']) and all(x['status']=='success' for x in b['plan_details'])
            b['categories']['training_plan']=state('success' if ok else 'partial','未来7天设备日历与课程已单独存档，课表未改；变化须教练核对')
            b['followups'].append('核对本批设备计划与已确认课表差异，以最新确认课表为准。')
        if not morning:
            for prefix,method in [('training_status','get_training_status'),('load_focus','get_training_four_week_load_balance')]:f.call(prefix+'_'+day,method,day)
            m=focus_period(adapter.monitoring(day));b['monitoring']=[m];fields=m['fields']
            b['categories']['training_status']=state('success' if fields.get('training_status_raw') in STATUS_MAP else 'partial','状态原始代码已保留；未知代码需网页核对')
            b['categories']['training_load']=state(completeness({k:fields[k] for k in ['acute_load','chronic_load','load_ratio']})['status'],'按接口原始短期/长期负荷与负荷比归档')
            b['categories']['load_focus']=state(m['load_focus_validation']['status'],'数值直接采集；日期按已验证规则计算，非接口原始字段')
            if m['load_focus_validation']['status']!='success':b['followups'].append('负荷重点缺项或规则不适用，网页补核一次。')
            last=schedule['categories'].get('running',{}).get('data_date') or day
            start=(dt.date.fromisoformat(day)-dt.timedelta(days=6)).isoformat() if sunday else min(last,day)
            activities=f.call('activities','get_activities_by_date',start,day) or [];b['activities']=[];pr_needed=sunday or bool(pending.get('records') if isinstance(pending,dict) else pending)
            for item in activities:
                kind=(item.get('activityType') or {}).get('typeKey','').lower()
                if 'running' not in kind and 'run' not in kind:continue
                aid=str(item.get('activityId'));date=str(item.get('startTimeLocal',''))[:10]
                if not start<=date<=day:continue
                old=json.loads(known.get('garmin:'+aid,'{}'));summary=old.get('api_list_summary')
                comparable=[('distance','distance',.51),('duration','duration',1.01),('averageHR','averageHR',.51)]
                changed=any(old.get(a) is not None and item.get(k) is not None and abs(old[a]-item[k])>tol for a,k,tol in comparable)
                if old and not changed and (not sunday or summary==item or summary is None):continue
                for name,method in [('activity','get_activity'),('laps','get_activity_laps'),('gear','get_activity_gear')]:f.call(name+'_'+aid,method,int(aid))
                f.call('full_details_'+aid,'get_activity_details',int(aid),maxchart=100000,maxpoly=100000,folder='verification')
                a=adapter.activity(item);a['list_summary']=item;b['activities'].append(a)
                if item.get('pr'):pr_needed=True
                f.call('vo2_'+date,'get_max_metrics',date)
                for value in adapter.load('vo2_'+date) or []:
                    value=value.get('generic') or {}
                    if value.get('calendarDate')==date:b.setdefault('vo2_observations',[]).append(dict(value,source_file='results/vo2_'+date+'.json',status='api_dated_observation_pending_import_policy'))
                b['followups'].append('活动'+aid+'：查看地图核对路线，核验分段/完成状态；记录教练结论，不能自动按契合度评分。')
            b['categories']['running']=state('partial' if b['activities'] or f.results['activities']['status']!='success' else 'success','新活动需完成地图及教练核对' if b['activities'] else '增量列表已核对，未发现新增；不推断休息')
            b['route_pending_checks']=route_pending
            if route_pending:
                b['categories']['running']=state('partial','存在历史路线待核对；本次增量读取结果独立保留，不因无新增解除旧待办')
                for item in route_pending:
                    b['followups'].append('活动'+item['activity_id']+'（'+item['date']+'）：历史路线待核对；优先使用已归档轨迹，缺项仅网页补查一次，不重复全量采集。')
            if pr_needed:
                b['personal_records']=f.call('records','get_personal_record')
                b['record_candidates']=f.call('record_candidates','get_personal_record_candidates',folder='verification')
                b['record_types']=f.call('record_types','get_personal_record_types',folder='verification')
                _,errors=records_projection(b['personal_records'],b['record_types'])
                if f.results['record_candidates']['status']!='success' or not isinstance(b['record_candidates'],list):errors.append('候选接口读取失败或结构变化')
                b['categories']['personal_records']=state('partial' if errors else 'success','；'.join(errors) if errors else '已接受纪录直接刷新；活动ID及实际日期由接口提供；候选单独保存')
                if errors:b['followups'].append('个人纪录缺项/冲突/接口变化：网页补核一次。')
            if sunday:
                b['threshold_observations']=f.call('threshold_raw','connectapi','/biometric-service/biometric/latestLactateThreshold',folder='verification_extra')
                date=dt.date.fromisoformat(day)
                def month_back(n):
                    import calendar
                    year,month=divmod(date.year*12+date.month-1-n,12);month+=1
                    return date.replace(year=year,month=month,day=min(date.day,calendar.monthrange(year,month)[1])).isoformat()
                reports={}
                for name,start_date,aggregation in [('vo2_daily',start,'daily'),('vo2_4week',(date-dt.timedelta(days=28)).isoformat(),'weekly'),('vo2_6month',month_back(6),'monthly'),('vo2_year',month_back(12),'monthly')]:
                    reports[name]={'start':start_date,'end':day,'aggregation':aggregation,'data':f.call(name,'get_max_metrics_range',start_date,day,aggregation=aggregation,sport='running')}
                reports['heart_daily']={'start':start,'end':day,'data':f.call('heart_daily','get_daily_heart_rate_stats',start,day),'max_field_meaning':'wellnessMaxAvgHR，最高平均心率，不等同瞬时最大心率'}
                b['weekly_reports']=reports
                weekly_ok=all(f.results[k]['status']=='success' and isinstance(v['data'],list) for k,v in reports.items()) and f.results['threshold_raw']['status']=='success' and isinstance(b['threshold_observations'],list)
                weekly_ok=weekly_ok and all(isinstance(row,dict) and isinstance(row.get('generic'),dict) and bool(row['generic'].get('calendarDate')) and row['generic'].get('vo2MaxValue') is not None for k,v in reports.items() if k.startswith('vo2_') for row in (v['data'] or []))
                weekly_ok=weekly_ok and all(isinstance(row,dict) and bool(row.get('calendarDate')) and isinstance(row.get('values'),dict) and row['values'].get('restingHR') is not None and row['values'].get('wellnessMaxAvgHR') is not None for row in (reports['heart_daily']['data'] or []))
                b['categories']['weekly']=state('success' if weekly_ok else 'partial','报告直接按日/周/月粒度保存；空测定区间不造值；教练复盘独立完成' if weekly_ok else '专项接口缺项，网页仅补失败部分')
                if not weekly_ok:b['followups'].append('周更报告接口缺项或结构变化，网页仅补对应项目。')
                b['followups'].append('完成近7天恢复修订回查、周复盘及到期目标把握复核；无需重复读取成功的网页报告。')
    except Exception as e:
        b['followups'].append('本批中断：'+type(e).__name__+'；仅保留已读取字段，不推进未完成类别')
        for key in (['sleep','hrv','resting_hr','training_plan'] if morning else ['running','training_status','training_load','load_focus']):
            if key not in b['categories']:b['categories'][key]=state('failed','读取中断')
    # Persist refreshed token via DPAPI, never plaintext.
    saved=json.loads(crypt(VAULT.read_bytes(),True));saved['tokens']=api.client.dumps();save(saved)
    for directory in ['results','verification','verification_extra']:
        for path in (folder/directory).glob('*.json') if (folder/directory).exists() else []:adapter.load(path.stem,directory)
    b['sources']=adapter.sources;b['read_at']=now();b['request_results']=f.results
    (folder/'bundle.json').write_text(encode(b),encoding='utf-8');return b

def main():
    p=argparse.ArgumentParser();p.add_argument('--date',default=dt.datetime.now(TZ).date().isoformat());p.add_argument('--scope',choices=['morning','evening']);p.add_argument('--import-bundle',type=Path);p.add_argument('--fetch-only',action='store_true');p.add_argument('--force',action='store_true');args=p.parse_args()
    scope=args.scope or ('morning' if dt.datetime.now(TZ).hour<21 else 'evening')
    if args.import_bundle:b=json.loads(args.import_bundle.read_text(encoding='utf-8'))
    else:
        with closing(sqlite3.connect(DB)) as c:runs=meta(c,'garmin_sync_runs',{'records':[]})['records']
        same=[r for r in runs if r.get('batch_key')==args.date+'_'+scope and r.get('api_batch_id')]
        if same and not args.force:
            print(encode({'skipped':'batch_already_attempted','followups':same[-1].get('followups',[]),'status':same[-1].get('status')}));return
        b=fetch(args.date,scope)
    if args.fetch_only:print(encode({'bundle':str(Path(b['source_root'])/'bundle.json'),'categories':b['categories']}));return
    print(encode(import_batch(DB,b,BACKUPS)))

if __name__=='__main__':main()
