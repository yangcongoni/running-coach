"""Live-only read projections. The offline archive and its template remain independent."""
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import json
import re
import sqlite3
from urllib.parse import parse_qs,urlsplit
from mobile_archive import open_read,meta
from strength_duration import enrich_sessions

ROOT=Path(__file__).resolve().parent
PREFIX='/api/desk-v3/'
TABLES='sessions running_details metadata daily_recovery daily_submissions daily_submission_history planned_sessions revisions sources analyses strength_sets strength_baselines stretching_records running_laps periodic_reviews stage_reviews'.split()

def enc(v):
    return json.dumps(v,ensure_ascii=False,separators=(',',':'))

def rows(c,sql,args=()):
    return [dict(r) for r in c.execute(sql,args)]

def overview(c):
    today=datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    d={k:[] for k in TABLES}
    d.update(_page_projection=True,_desk_lite=True)
    release=ROOT/'archive_release.json'
    if release.exists():
        d['_release']={**json.loads(release.read_text(encoding='utf8')),'mode':'live'}
    official=meta(c,'garmin_personal_records')
    refs=(official.get('records') or [])+((official.get('category_history') or {}).get('records') or [])
    ids={str(v['activity_id']) for v in refs if v.get('activity_id') is not None}
    latest=c.execute('SELECT MAX(s.date) FROM running_details r JOIN sessions s ON s.id=r.session_id WHERE s.date<=?',(today,)).fetchone()[0]
    d['careerDays']=[list(r) for r in c.execute("""SELECT s.date,COUNT(*),
        SUM(CASE WHEN r.distance_km>0 THEN r.distance_km ELSE 0 END),
        SUM(CASE WHEN r.timer_seconds>0 THEN r.timer_seconds ELSE 0 END),
        SUM(CASE WHEN r.timer_seconds>0 AND r.distance_km>0 THEN r.distance_km ELSE 0 END),
        SUM(CASE WHEN r.timer_seconds>0 AND r.distance_km>0 THEN r.timer_seconds ELSE 0 END)
        FROM running_details r JOIN sessions s ON s.id=r.session_id WHERE s.date<=? GROUP BY s.date ORDER BY s.date""",(today,))]
    d['career']=[list(r) for r in c.execute("""SELECT s.id,s.date,r.distance_km,r.timer_seconds,r.elapsed_seconds,
        json_extract(r.details_json,'$.activityId'),json_extract(r.details_json,'$.startTimeLocal'),
        json_extract(r.details_json,'$.api_list_summary.startTimeLocal'),json_extract(r.details_json,'$.duration'),
        CASE WHEN json_extract(r.details_json,'$.activityId') IS NOT NULL THEN json_extract(r.details_json,'$.activityName') END
        FROM running_details r JOIN sessions s ON s.id=r.session_id WHERE s.date<=? ORDER BY s.date DESC,s.id DESC""",(today,)) if r[1]==latest or str(r[5]) in ids]
    for k in ('garmin_personal_records','training_roadmap','goal_readiness_assessment','body_composition_history'):
        v=meta(c,k)
        if k=='body_composition_history':
            valid=[x for x in v.get('records',[]) if x.get('date','')<=today and x.get('weight_kg') is not None]
            v={'records':sorted(valid,key=lambda x:x['date'],reverse=True)[:1]}
        d['metadata'].append(dict(key=k,value_json=enc(v)))
    for r in rows(c,'SELECT date,sleep_minutes,hrv_ms,resting_hr,details_json FROM daily_recovery WHERE date<=? ORDER BY date DESC',(today,)):
        raw=json.loads(r['details_json'] or '{}')
        keys=('sleep_data_date','hrv_data_date','resting_hr_data_date','sleep_score','night_hrv_ms','seven_day_hrv_ms','user_recovery_feedback')
        small={k:raw[k] for k in keys if k in raw}
        extras=raw.get('recovery_extras') or {}
        small['recovery_extras']={k:extras[k] for k in ('morning','recovery_time') if k in extras}
        r['details_json']=enc(small)
        d['daily_recovery'].append(r)
    d['sessions']=rows(c,"SELECT * FROM sessions WHERE sport='strength' AND date<=? ORDER BY date DESC,id DESC LIMIT 1",(today,))
    if d['sessions']:
        d['strength_sets']=rows(c,'SELECT * FROM strength_sets WHERE session_id=?',(d['sessions'][0]['id'],))
        enrich_sessions(d['sessions'],d['strength_sets'])
    d['stretching_records']=rows(c,'SELECT date,status,duration_minutes FROM stretching_records WHERE date<=? ORDER BY date DESC,id DESC LIMIT 1',(today,))
    d['daily_submissions']=rows(c,'SELECT date,payload_json,revision FROM daily_submissions WHERE date>=coalesce((SELECT MAX(s.date) FROM sessions s JOIN running_details r ON r.session_id=s.id WHERE s.date<=?),?)',(today,today))
    return d

def run_list(c,q):
    def day(key,default):
        val=q.get(key,[default])[0]
        if date.fromisoformat(val).isoformat()!=val:raise ValueError()
        return val
    start,end=day('from','0001-01-01'),day('to','9999-12-31')
    if start>end:raise ValueError()
    found=rows(c,"""SELECT s.id,s.date,r.distance_km,r.timer_seconds,r.average_hr,
      json_extract(r.details_json,'$.activityName') AS name,
      json_extract(r.details_json,'$.classification_override.type') AS type,
      json_extract(r.details_json,'$.activityId') AS activity_id,json_extract(r.details_json,'$.activityType.typeKey') AS sport_key,
      json_extract(r.details_json,'$.eventType.typeKey') AS event_key,json_extract(r.details_json,'$.trainingEffectLabel') AS effect,
      json_extract(r.details_json,'$.splitSummaries') AS splits,json_extract(r.details_json,'$.averageHR') AS raw_hr
      FROM sessions s JOIN running_details r ON s.id=r.session_id
      WHERE s.date BETWEEN ? AND ? AND (s.date,s.id)<(?,?) ORDER BY s.date DESC,s.id DESC LIMIT 31""",
      (start,end,day('before','9999-12-31'),int(q.get('id',['2147483647'])[0])))
    items=found[:30]
    ids={str(x['id']) for x in items}
    for row in items:
        row['raw']=dict(activityId=row.pop('activity_id'),activityName=row['name'],averageHR=row.pop('raw_hr'),
            activityType={'typeKey':row.pop('sport_key')},eventType={'typeKey':row.pop('event_key')},
            classification_override={'type':row['type']},trainingEffectLabel=row.pop('effect'))
        row['raw']['splitSummaries']=[{'splitType':v.get('splitType'),'noOfSplits':v.get('noOfSplits')} for v in json.loads(row.pop('splits') or '[]') if v.get('splitType')=='INTERVAL_REST']
    policy=meta(c,'running_completion_policy')
    policy['legacy_results']=[x for x in policy.get('legacy_results',[]) if str(x.get('session_id')) in ids]
    metadata={'running_completion_policy':policy,
      'cycle_dashboard':{'activity_execution_reviews':[x for x in meta(c,'cycle_dashboard').get('activity_execution_reviews',[]) if str(x.get('session_id')) in ids]},
      'running_ability_evidence':{'field_reference':meta(c,'running_ability_evidence').get('field_reference')},
      'running_type_classification_rules':meta(c,'running_type_classification_rules')}
    # Completion reviews can be linked by the reviewed session rather than analyses.session_id.
    reviews=[]
    if ids:
        marks=','.join('?' for _ in ids)
        sql="SELECT id,created_at,json_extract(evidence_json,'$.completion_review') AS review FROM analyses WHERE CAST(json_extract(evidence_json,'$.completion_review.session_id') AS TEXT) IN ("+marks+")"
        reviews=[dict(id=x[0],created_at=x[1],evidence_json=enc({'completion_review':json.loads(x[2])})) for x in c.execute(sql,tuple(ids))]
    return dict(items=items,more=len(found)>30,metadata=[dict(key=k,value_json=enc(v)) for k,v in metadata.items()],analyses=reviews)

def one_run(c,sid):
    from server import page_data
    s=rows(c,'SELECT * FROM sessions WHERE id=?',(sid,))
    run=rows(c,'SELECT * FROM running_details WHERE session_id=?',(sid,))
    if not s or not run:return None
    d=page_data(dict(sessions=s,running_details=run,revisions=[]))
    day=s[0]['date']
    tomorrow=(date.fromisoformat(day)+timedelta(days=1)).isoformat()
    d['analyses']=rows(c,"SELECT * FROM analyses WHERE session_id=? OR json_extract(evidence_json,'$.completion_review.session_id') IN (?,?)",(sid,sid,str(sid)))
    d['daily_recovery']=rows(c,'SELECT * FROM daily_recovery WHERE date IN (?,?)',(day,tomorrow))
    d['daily_submissions']=rows(c,'SELECT date,revision,payload_json FROM daily_submissions WHERE date IN (?,?)',(day,tomorrow))
    d['calculation_laps']=[]
    for lap in rows(c,'SELECT lap_number,details_json FROM running_laps WHERE session_id=? ORDER BY lap_number,id',(sid,)):
        raw=json.loads(lap['details_json'])
        fields={k:raw[k] for k in ('distance_km','time_seconds','average_hr','step','step_type','average_power_w') if k in raw}
        fields['visible_row']={k:v for k,v in (raw.get('visible_row') or {}).items() if k in ('step','步骤类型')}
        fields['api_raw']={k:v for k,v in (raw.get('api_raw') or {}).items() if k in ('intensityType','averagePower','startTimeGMT','elapsedDuration')}
        d['calculation_laps'].append(dict(session_id=sid,lap_number=lap['lap_number'],details_json=enc(fields)))
    d['metadata']=[]
    for k in ('running_type_classification_rules','running_completion_policy','cycle_dashboard','running_ability_evidence','training_session_feedback'):
        v=meta(c,k)
        if k=='cycle_dashboard':v={'activity_execution_reviews':[x for x in v.get('activity_execution_reviews',[]) if str(x.get('session_id'))==str(sid)]}
        if k=='running_ability_evidence':v={'field_reference':v.get('field_reference')}
        if k=='training_session_feedback':v={str(sid):v[str(sid)]} if str(sid) in v else {}
        d['metadata'].append(dict(key=k,value_json=enc(v)))
    return d

def dispatch(c,url):
    parts=urlsplit(url)
    route=parts.path.removeprefix(PREFIX)
    q=parse_qs(parts.query,max_num_fields=6)
    if route=='map':
        from archive_config import desktop_template
        from desk_views import geometry
        line=geometry(desktop_template())
        return json.loads(line[1]) if line else None
    if route=='home':return overview(c)
    if route=='runs':return run_list(c,q)
    if route=='revisions':
        before=int(q.get('before',['9223372036854775807'])[0])
        found=rows(c,'SELECT id,created_at,entity,entity_key,reason FROM revisions WHERE id<? ORDER BY id DESC LIMIT 31',(before,))
        return {'items':found[:30],'more':len(found)>30}
    match=re.fullmatch(r'(run|laps|curve|revision)/([0-9]{1,10})',route)
    if match:
        kind,sid=match[1],int(match[2])
        if kind=='run':return one_run(c,sid)
        if kind=='curve':
            row=c.execute("SELECT json_extract(details_json,'$.archived_curve') FROM running_details WHERE session_id=?",(sid,)).fetchone()
            return {'raw':{'archived_curve':json.loads(row[0]) if row[0] else None}} if row else None
        if kind=='laps':return dict(items=rows(c,'SELECT * FROM running_laps WHERE session_id=? ORDER BY lap_number,id',(sid,)))
        found=rows(c,'SELECT * FROM revisions WHERE id=?',(sid,))
        # Match the existing desktop projection's treatment of private revision snapshots.
        if found and not re.search('plan|计划',found[0]['entity'] or ''):
            found[0]['previous_json']=found[0]['replacement_json']=None
        return found[0] if found else None

def serve(url,send):
    try:
        with closing(open_read()) as c:
            c.execute('BEGIN')
            value=dispatch(c,url)
        return send(404,{'error':'没有此记录'}) if value is None else send(200,value)
    except (ValueError,OverflowError):
        return send(400,{'error':'查询条件无效'})
    except (sqlite3.Error,OSError):
        return send(503,{'error':'暂时无法读取档案'})

