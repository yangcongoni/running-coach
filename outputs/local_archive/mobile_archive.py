"""Read-only projections for the authenticated mobile archive."""
from pathlib import Path
from strength_duration import enrich_mobile
from archive_config import settings
import math
import json
import sqlite3
from bisect import bisect_left
from datetime import date, datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parent
DB = ROOT.parent / '训练日志.sqlite3'


def meta(conn, key):
    row = conn.execute('SELECT value_json FROM metadata WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else {}


def open_read():
    conn = sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def index(conn, start="0001-01-01", end="9999-12-31"):
    rows = []
    for s in conn.execute("""SELECT s.id,s.date,s.sport,s.duration_minutes,json_extract(s.raw_json,'$.duration_is_approximate') duration_is_approximate,r.distance_km,r.timer_seconds,r.average_hr,
          json_extract(r.details_json,'$.activityName') name,
          json_extract(r.details_json,'$.averageRunningCadenceInStepsPerMinute') cadence,
          coalesce(json_extract(r.details_json,'$.avgStrideLength_m'),json_extract(r.details_json,'$.avgStrideLength') / 100.0) stride,
          coalesce(json_extract(r.details_json,'$.avgVerticalOscillation_cm'),json_extract(r.details_json,'$.avgVerticalOscillation')) vertical,
          json_extract(r.details_json,'$.avgVerticalRatio') ratio,
          coalesce(json_extract(r.details_json,'$.graphGroundContactTime_ms'),json_extract(r.details_json,'$.avgGroundContactTime_ms'),json_extract(r.details_json,'$.avgGroundContactTime')) contact,
          json_extract(r.details_json,'$.elevationGain') climb,
          json_extract(r.details_json,'$.startLatitude') lat,
          json_extract(r.details_json,'$.startLongitude') lon,
          json_extract(r.details_json,'$.api_list_summary.startLatitude') api_lat,
          json_extract(r.details_json,'$.api_list_summary.startLongitude') api_lon,
          substr(json_extract(r.details_json,'$.zepp_raw_detail.longitude_latitude'),1,72) track_head,
          json_extract(r.details_json,'$.route_observation.status') route_status,
          json_extract(r.details_json,'$.route_observation.group_id') route_group,
          json_extract(r.details_json,'$.activityType.typeKey') sport_key,
          json_extract(r.details_json,'$.classification_override.type') override_type,
          json_extract(r.details_json,'$.eventType.typeKey') event_type,
          json_extract(r.details_json,'$.activityId') activity_id,
          json_extract(r.details_json,'$.trainingEffectLabel') effect,
          json_extract(r.details_json,'$.splitSummaries') splits,
          CASE WHEN s.sport='strength' THEN json_extract(s.raw_json,'$.strength_classification.exercises') END exercises
        FROM sessions s LEFT JOIN running_details r ON r.session_id=s.id
        WHERE s.sport IN ('running','strength') AND s.date BETWEEN ? AND ? ORDER BY s.date DESC,s.id DESC""", (start,end)):
        row = dict(s)
        splits=json.loads(row.pop('splits') or '[]')
        rests=[{'splitType':'INTERVAL_REST','noOfSplits':x['noOfSplits']} for x in splits
               if x.get('splitType')=='INTERVAL_REST' and (x.get('noOfSplits') or 0)>1]
        row['raw'] = dict(activityName=row['name'], activityType={'typeKey':row.pop('sport_key')},
            classification_override={'type':row.pop('override_type')}, eventType={'typeKey':row.pop('event_type')},
            activityId=row.pop('activity_id'), trainingEffectLabel=row.pop('effect'),
            splitSummaries=rests[:1])
        lat,lon=row.pop('lat'),row.pop('lon')
        api_lat,api_lon=row.pop('api_lat'),row.pop('api_lon')
        track=row.pop('track_head')
        route_group,route_status=row.pop('route_group'),row.pop('route_status')
        if lat is not None and lon is not None:
            row['raw'].update(startLatitude=lat,startLongitude=lon)
        if api_lat is not None and api_lon is not None:
            row['raw']['api_list_summary']={'startLatitude':api_lat,'startLongitude':api_lon}
        if track:
            row['raw']['zepp_raw_detail']={'longitude_latitude':track.partition(';')[0]}
        if route_group and route_status=='reviewed':
            row['raw']['route_observation']={'group_id':route_group,'status':route_status}
        exercises=json.loads(row.pop('exercises') or '[]')
        row['types']=sorted({tag for x in exercises for tag in x.get('ability',[])}) or ['待分类']
        rows.append(row)
    enrich_mobile(conn, rows)
    return {'items':rows,'rules':meta(conn,'running_type_classification_rules')}


def personal_record_history(conn):
    pr=meta(conn,'garmin_personal_records')
    h=pr.get('category_history') or {}
    # The category report and accepted-record updates are read on different dates.
    history={}
    saved=[x.get('record') or {} for x in pr.get('history',[])]
    for r in [*saved,*h.get('records',[]),*pr.get('records',[])]:
        kind=r.get('pr_type') or {1:1,1.609344:2,5:3,10:4,21.0975:5,42.195:6}.get(r.get('km'))
        if kind and r.get('date') and (r.get('seconds') is not None or r.get('distance_km') is not None):
            key=(kind,r['date'],str(r.get('activity_id') or ''))
            history[key]={**history.get(key,{}),**r,'pr_type':kind}
    return pr,h,history


def work_groups(laps):
    """Consecutive active auto-laps form one rep; only tagged breaks separate reps."""
    groups = []
    active = None
    for lap in laps:
        kind = lap.get('kind') or lap.get('stage')
        if kind in ('RECOVERY', 'REST', '恢复', '休息', 'WARMUP', 'COOLDOWN', '热身', '缓和'):
            active = None
        elif kind in ('ACTIVE', 'INTERVAL', 'RUN', 'INTERVAL_ACTIVE', '跑步', '主段', '工作段', '主训练', '间歇'):
            if active is None:
                active = []
                groups.append(active)
            active.append(lap)
        else:
            return []
    if len(groups) < 2:
        return []
    result = []
    for group in groups:
        def total(key):
            values = [lap.get(key) for lap in group]
            return sum(values) if all(isinstance(x,(int,float)) and x>0 for x in values) else None
        sec, km = total('sec'), total('km')
        hr = None
        if sec and all(isinstance(l.get('hr'),(int,float)) and l['hr']>0 for l in group):
            hr = sum(l['sec']*l['hr'] for l in group)/sec
        result.append(dict(first=group[0]['number'],last=group[-1]['number'],km=km,sec=sec,hr=hr))
    return result


def work_curves(conn, sid):
    row = conn.execute("SELECT details_json FROM running_details WHERE session_id=?", (sid,)).fetchone()
    if not row:
        return []
    raw = json.loads(row[0])
    curve = raw.get('archived_curve') or {}
    if curve.get('axis') != 'elapsed_seconds' or (curve.get('units') or {}).get('time') != 'second':
        return []
    def stamp(value):
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace('Z','+00:00'))
            return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()
        except (ValueError, TypeError):
            return None
    origin = stamp(raw.get('startTimeGMT') or (raw.get('api_list_summary') or {}).get('startTimeGMT'))
    laps = []
    for number, encoded in conn.execute('SELECT lap_number,details_json FROM running_laps WHERE session_id=? ORDER BY lap_number,id',(sid,)):
        d = json.loads(encoded)
        api = d.get('api_raw') or {}
        laps.append(dict(number=number,stage=d.get('step_type'),kind=api.get('intensityType'),
                         start=stamp(api.get('startTimeGMT')),elapsed=api.get('elapsedDuration')))
    if not laps:
        return []
    if origin is None and laps[0]['number']==1:
        origin = laps[0]['start']
    if origin is None:
        return []
    by_number = {lap['number']:lap for lap in laps}
    cols = curve.get('columns') or []
    def index(col,unit):
        return cols.index(col) if col in cols and curve['units'].get(col)==unit else None
    ti,vi,hi = index('time','second'),index('speed','mps'),index('hr','bpm')
    if ti is None:
        return []
    points = curve.get('points') or []
    times = [point[ti] for point in points]
    result = []
    for group in work_groups(laps):
        first,last = by_number[group['first']],by_number[group['last']]
        if first['start'] is None or last['start'] is None:
            continue
        start = first['start']-origin
        next_start = (by_number.get(last['number']+1) or {}).get('start')
        ends = [v for v in [next_start,last['start']+last['elapsed'] if isinstance(last['elapsed'],(int,float)) and last['elapsed']>0 else None] if v is not None]
        # Garmin lap start timestamps may be rounded to whole seconds. Preserve
        # the precise elapsed lap durations when successive starts agree with them.
        offset = 0.0
        for lap in laps:
            if first['number']<=lap['number']<=last['number']:
                elapsed = lap['elapsed']
                if lap['start'] is None or abs(lap['start']-first['start']-offset)>2 or not isinstance(elapsed,(int,float)) or elapsed<=0:
                    break
                offset += elapsed
        else:
            ends = [first['start']+offset]
            if next_start is not None:
                ends.append(next_start)
        if not ends or start<0:
            continue
        end = min(ends)-origin
        if end<=start:
            continue
        samples = []
        for point in points[bisect_left(times,start):bisect_left(times,end)]:
            speed = point[vi] if vi is not None else None
            hr = point[hi] if hi is not None else None
            samples.append([point[ti]-start,1000/speed if speed and speed>0 else None,hr if hr and hr>0 else None])
        result.append(dict(first=group['first'],last=group['last'],span=end-start,points=samples))
    return result






def detail(conn, sid, curve=False):
    s=conn.execute("SELECT id,date,sport,duration_minutes,json_extract(raw_json,'$.duration_is_approximate') duration_is_approximate,session_rpe FROM sessions WHERE id=?",(sid,)).fetchone()
    if not s:
        return None
    result=dict(s)
    f=meta(conn,'training_session_feedback').get(str(sid),{})
    result.update(fields=f.get('fields',{}), revision=f.get('revision',0),status=f.get('status'))
    if s['sport']=='strength':
        enrich_mobile(conn, [result])
        result['sets']=[dict(x) for x in conn.execute('SELECT exercise,set_kind,set_number,load_kg,load_basis,reps,side,rir,notes FROM strength_sets WHERE session_id=? ORDER BY id',(sid,))]
        return result
    r=conn.execute('SELECT * FROM running_details WHERE session_id=?',(sid,)).fetchone()
    if not r:
        return result
    raw=json.loads(r['details_json'])
    if curve:
        c=raw.get('archived_curve') or {}
        return {'columns':c.get('columns',[]),'points':c.get('points',[])}
    result.update(name=raw.get('activityName'),distance=r['distance_km'],seconds=r['timer_seconds'],hr=r['average_hr'],
        power=raw.get('averagePower'),route=(raw.get('route_observation') or {}).get('name'),shoe=raw.get('gear_name'))
    laps=[]
    for x in conn.execute('SELECT lap_number,details_json FROM running_laps WHERE session_id=? ORDER BY lap_number,id',(sid,)):
        d=json.loads(x[1]); orig=d.get('api_raw') or {}
        laps.append(dict(number=x[0],stage=d.get('step_type'),kind=orig.get('intensityType'),km=d.get('distance_km'),sec=d.get('time_seconds'),hr=d.get('average_hr'),power=orig.get('averagePower',d.get('average_power_w',d.get('averagePower')))))
    activity_id = raw.get('activityId')
    result['climb'] = raw.get('elevationGain')
    result['trail'] = (raw.get('activityType') or {}).get('typeKey') == 'trail_running'
    result['poster_records'] = []
    if activity_id:
        _, _, history = personal_record_history(conn)
        for record in history.values():
            if str(record.get('activity_id')) != str(activity_id) or record.get('date') != s['date']:
                continue
            if record.get('label') and (isinstance(record.get('seconds'), (int,float)) or
                                        isinstance(record.get('distance_km'), (int,float))):
                result['poster_records'].append({k:record.get(k) for k in ('label','seconds','km','distance_km')})
    result['workGroups']=work_groups(laps)
    result['laps']=laps
    return result


def measure(value, unit='', places=0):
    if not isinstance(value,(int,float)) or not math.isfinite(value): return '—'
    return f'{value:.{places}f}'+(' '+unit if unit else '')


def duration(seconds):
    if not isinstance(seconds,(int,float)) or not math.isfinite(seconds) or seconds<0: return '—'
    h, rem = divmod(int(seconds+0.5),3600)
    m, sec = divmod(rem,60)
    return f'{h}:{m:02}:{sec:02}' if h else f'{m}:{sec:02}'


def sleep_text(minutes):
    if minutes is None: return '—'
    h,m=divmod(int(minutes+0.5),60)
    return f'{h}小时{m}分'


def ability_runs(conn,start,end):
    recent=index(conn,start.isoformat(),end.isoformat())
    runs=[r for r in recent['items'] if r['sport']=='running']
    form_rows=conn.execute("""SELECT r.session_id,
        json_extract(r.details_json,'$.averageRunningCadenceInStepsPerMinute'),
        coalesce(json_extract(r.details_json,'$.avgStrideLength_m'),json_extract(r.details_json,'$.avgStrideLength')/100.0),
        coalesce(json_extract(r.details_json,'$.avgVerticalOscillation_cm'),json_extract(r.details_json,'$.avgVerticalOscillation')),
        json_extract(r.details_json,'$.avgVerticalRatio'),
        coalesce(json_extract(r.details_json,'$.graphGroundContactTime_ms'),json_extract(r.details_json,'$.avgGroundContactTime_ms'),json_extract(r.details_json,'$.avgGroundContactTime')),
        json_extract(r.details_json,'$.long_run_segment_comparison'),r.elapsed_seconds,s.session_rpe
        FROM running_details r JOIN sessions s ON s.id=r.session_id WHERE s.date BETWEEN ? AND ?""",(start.isoformat(),end.isoformat()))
    by_id={r['id']:r for r in runs}
    for row in form_rows:
        if row[0] in by_id:
            by_id[row[0]].update(form=list(row[1:6]),segments=json.loads(row[6] or '{}'),elapsed=row[7],rpe=row[8])
    return recent,runs

def route_view(conn, sid):
    row=conn.execute("SELECT s.date,r.details_json FROM sessions s JOIN running_details r ON r.session_id=s.id WHERE s.id=?", (sid,)).fetchone()
    if not row:
        return {}
    raw=json.loads(row['details_json'])
    route=raw.get('route_observation') or {}
    aid=str(raw.get('activityId') or '')
    base=(ROOT.parent/'sources').resolve()
    paths=[route.get('source_path')]
    if aid.isdecimal():
        paths.extend(sorted((base/'garmin_api').glob('history_curves_*/'+aid+'.json'),reverse=True))
        paths.extend(sorted((base/'garmin_api').glob('*/verification/full_details_'+aid+'.json'),reverse=True))
    segments=[]
    for path in paths:
        if not path: continue
        f=Path(path).resolve()
        if not f.is_relative_to(base) or not f.is_file(): continue
        doc=json.loads(f.read_bytes()).get('data') or {}
        if str(doc.get('activityId'))!=aid: continue
        segment=[]
        last=None
        for pt in (doc.get('geoPolylineDTO') or {}).get('polyline',[]):
            lat,lon,t=pt.get('lat'),pt.get('lon'),pt.get('time')
            valid=pt.get('valid') is not False and all(isinstance(n,(float,int)) and math.isfinite(n) for n in (lat,lon,t)) and abs(lat)<=90 and abs(lon)<=180
            if not valid or last is not None and (t-last>30000 or t<last):
                if segment: segments.append(segment)
                segment=[]
            if valid: segment.append([lat,lon])
            last=t if valid else None
        if segment: segments.append(segment)
        if segments: break
    # Sample each uninterrupted segment separately and retain both endpoints.
    gps=[]
    for seg in segments:
        stride=max(1,math.ceil(len(seg)/650))
        gps.append(seg[::stride]+([seg[-1]] if (len(seg)-1)%stride else []))
    group=route.get('group_id')
    related=[]
    if group:
        for r in conn.execute("""SELECT s.id,s.date,r.distance_km,r.timer_seconds,r.average_hr,json_extract(r.details_json,'$.activityName') name,
                json_extract(r.details_json,'$.activityType.typeKey') sport_key,
                json_extract(r.details_json,'$.classification_override.type') tagged,
                json_extract(r.details_json,'$.eventType.typeKey') event_type,
                json_extract(r.details_json,'$.trainingEffectLabel') effect,
                json_extract(r.details_json,'$.activityId') aid,
                json_extract(r.details_json,'$.splitSummaries') splits
            FROM sessions s JOIN running_details r ON r.session_id=s.id
            WHERE json_extract(r.details_json,'$.route_observation.group_id')=? ORDER BY s.date DESC,s.id DESC""",(group,)):
            entry=dict(r)
            entry['raw']=dict(activityName=entry['name'],activityType={'typeKey':entry.pop('sport_key')},classification_override={'type':entry.pop('tagged')},eventType={'typeKey':entry.pop('event_type')},trainingEffectLabel=entry.pop('effect'),activityId=entry.pop('aid'),splitSummaries=json.loads(entry.pop('splits') or '[]'))
            laps=conn.execute("SELECT details_json FROM running_laps WHERE session_id=?",(r['id'],))
            work=[l for l in (json.loads(x[0]) for x in laps) if l.get('step_type') in ('跑步','工作段','主段','主训练','间歇','RUN','INTERVAL_ACTIVE')]
            for col,key in [('distance_km','work_km'),('time_seconds','work_sec')]:
                entry[key]=sum(x[col] for x in work) if work and all(isinstance(x.get(col),(int,float)) for x in work) else None
            related.append(entry)
    return dict(gps=gps,related=related,name=route.get('name'),variant=route.get('variant'),has_group=bool(group),has_map=bool(route_image(conn,sid)))

def route_image(conn,sid):
    row=conn.execute("SELECT json_extract(details_json,'$.route_observation') FROM running_details WHERE session_id=?",(sid,)).fetchone()
    route=json.loads(row[0]) if row and row[0] else {}
    path=route.get('evidence_image') or route.get('screenshot')
    if path:
        f=Path(path).resolve()
        if f.is_relative_to((ROOT.parent/'sources').resolve()) and f.suffix.lower()=='.png' and f.is_file():
            return f

def stage_runs(conn, start, end):
    return [dict(row) for row in conn.execute("""
        SELECT s.id,s.date,r.distance_km km,r.timer_seconds seconds,json_extract(r.details_json,'$.elevationGain') climb,json_extract(r.details_json,'$.activityId') aid,
               json_extract(r.details_json,'$.activityName') name,
               json_extract(r.details_json,'$.route_observation.name') route, r.average_hr hr,s.session_rpe rpe,
               json_extract(r.details_json,'$.startTimeLocal') start,r.elapsed_seconds elapsed
        FROM sessions s JOIN running_details r ON r.session_id=s.id
        WHERE s.sport='running' AND s.date BETWEEN ? AND ? ORDER BY s.date,s.id
    """, (start, end))]


def stage_strength(conn, start, end):
    return [dict(row) for row in conn.execute(
        "SELECT id,date FROM sessions WHERE sport='strength' AND date BETWEEN ? AND ? ORDER BY date,id",
        (start, end))]


def stage_recoveries(conn, start, end, recovery_end):
    rows = []
    feelings={r[0]:json.loads(r[1] or '{}') for r in conn.execute(
        'SELECT date,payload_json FROM daily_submissions WHERE date BETWEEN ? AND ?', (start,recovery_end))}
    for recovery in conn.execute("SELECT * FROM daily_recovery WHERE date BETWEEN ? AND ? ORDER BY date",
                                 (start, recovery_end)):
        day = recovery['date']
        d = json.loads(recovery['details_json'] or '{}')
        def on_day(column, date_key):
            return recovery[column] if d.get(date_key) in (None,day) else None
        feedback = d.get('user_recovery_feedback') or {}
        rows.append(dict(date=day, after=day>end,
            score=d.get('sleep_score') if d.get('sleep_data_date') in (None, day) else None,
            sleep=on_day('sleep_minutes','sleep_data_date'), hrv=on_day('hrv_ms','hrv_data_date'),
            hr=on_day('resting_hr','resting_hr_data_date'),
            readiness=((d.get('recovery_extras') or {}).get('morning') or {}).get('score'),
            feedback=feedback.get('original') if feedback.get('date') == day else None,
            feeling=feelings.get(day,{}).get('overall') or feelings.get(day,{}).get('recovery'),
            post=(d.get('recovery_extras') or {}).get('recovery_time')))
    for day,entry in feelings.items():
        if not any(r['date']==day for r in rows) and (entry.get('overall') or entry.get('recovery')):
            rows.append(dict(date=day,after=day>end,feeling=entry.get('overall') or entry.get('recovery')))
    return rows


def stage_review_detail(conn, analysis_id):
    report = conn.execute(
        "SELECT assessment,recommendation,evidence_json FROM analyses WHERE id=? "
        "AND json_extract(evidence_json,'$.report_type')='stage_review'", (analysis_id,)
    ).fetchone()
    if not report:
        return None
    evidence = json.loads(report['evidence_json'])
    review = evidence.get('progress_review') or {}
    start = evidence.get('period_start') or review.get('from_date')
    end = evidence.get('period_end') or review.get('to_date')
    through = evidence.get('data_through') or review.get('data_through') or end
    result = dict(start=start, end=end, through=through, title=review.get('title') or '阶段复盘',
                  assessment=report['assessment'], recommendation=report['recommendation'],
                  status=review.get('status'), runs=[], recoveries=[], test=None, distance=None)
    if not start or not end:
        return result
    cutoff = min(end, through)
    runs = stage_runs(conn, start, cutoff)
    result['runs'] = runs
    result['strength'] = stage_strength(conn, start, cutoff)
    if all(r['km'] is not None for r in runs):
        result['distance'] = sum(r['km'] for r in runs)
    by_id = {r['id']:r for r in runs}
    refs = evidence.get('source_analysis_ids') or []
    analyses = conn.execute("""
        SELECT session_id,evidence_json FROM analyses WHERE id IN (SELECT value FROM json_each(?))
        ORDER BY id
    """, (json.dumps(refs),))
    for source in analyses:
        e = json.loads(source['evidence_json'] or '{}')
        test = e.get('test_result') or {}
        run = by_id.get(test.get('session_id') or source['session_id'])
        if not run:
            continue
        feedback = (e.get('user_feedback') or {}).get('fields') or {}
        if feedback.get('note'):
            run['note'] = feedback['note']
        metres, sec = test.get('distance_m'), test.get('timer_seconds')
        if not (metres and metres > 0 and sec and sec > 0):
            continue
        km = metres / 1000
        pr = next((p for p in personal_record_history(conn)[2].values()
                   if run['aid'] and str(p.get('activity_id')) == str(run['aid'])
                   and p.get('date') == run['date'] and p.get('km') == km and p.get('seconds')), None)
        performance = dict(km=km, seconds=sec, pb=pr['seconds'] if pr else None)
        run['test'] = performance
        result['test'] = performance
        result['title'] = f'{km:g} 公里测试阶段'
    next_day = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
    # A later review can reference the following morning. Its activity volume stays outside the stage.
    recovery_end = next_day if through >= next_day else cutoff
    result['recoveries'] = stage_recoveries(conn, start, end, recovery_end)
    result.update(following_stage_context(conn,cutoff))
    return result



def following_stage_context(conn,end):
    next_day=(date.fromisoformat(end)+timedelta(days=1)).isoformat() if end<'9999-12-31' else None
    morning=stage_recoveries(conn,next_day,end,next_day) if next_day else []
    run=conn.execute("""SELECT s.id,s.date,r.distance_km km,r.average_hr hr,s.session_rpe rpe
                        FROM sessions s JOIN running_details r ON r.session_id=s.id
                        WHERE s.date>? AND s.sport='running' ORDER BY s.date,s.id LIMIT 1""",(end,)).fetchone()
    return dict(followingMorning=morning[0] if morning else None,followingRun=dict(run) if run else None)


def custom_stage(conn, key):
    parts = key.split('_')
    if len(parts) != 3:
        return None
    start, end = parts[1:]
    try:
        if any(date.fromisoformat(v).isoformat() != v for v in (start, end)):
            return None
    except ValueError:
        return None
    if start > end:
        return None
    runs = stage_runs(conn, start, end)
    related = []
    for row in conn.execute("SELECT id,evidence_json FROM analyses WHERE json_extract(evidence_json,'$.report_type')='stage_review' ORDER BY id DESC"):
        ev = json.loads(row['evidence_json'])
        review = ev.get('progress_review') or {}
        first = ev.get('period_start') or review.get('from_date')
        last = ev.get('period_end') or review.get('to_date')
        through = ev.get('data_through') or review.get('data_through') or last
        if first and last and first <= end and min(last, through) >= start:
            related.append(dict(id=row['id'], title=review.get('title') or '阶段复盘', start=first, end=last))
    return dict(**following_stage_context(conn,end), custom=True, start=start, end=end, through=end, title='自选时段汇总',
                runs=runs, distance=sum(r['km'] for r in runs) if all(r['km'] is not None for r in runs) else None,
                recoveries=stage_recoveries(conn, start, end, end), related=related, strength=stage_strength(conn, start, end))


def stage_reviews(conn):
    ids = conn.execute("SELECT id FROM analyses WHERE json_extract(evidence_json,'$.report_type')='stage_review'")
    return {row['id']: stage_review_detail(conn, row['id']) for row in ids}


def topics(conn, key):
    if key.startswith('阶段_') and key.count('_') == 2:
        return custom_stage(conn, key)
    if key.startswith('阶段_') and key[3:].isascii() and key[3:].isdigit() and len(key[3:]) <= 10:
        return stage_review_detail(conn, int(key[3:]))
    def items(sql): return [dict(r) for r in conn.execute(sql)]
    if key=='计划':
        return [[r['date'],p.get('content'),p.get('details'),r['plan_version']] for r in items('SELECT * FROM planned_sessions ORDER BY date DESC,id DESC') for p in [json.loads(r['prescription_json'])]]
    if key=='恢复':
        rows=[]
        for row in items('SELECT * FROM daily_recovery ORDER BY date DESC'):
            details=json.loads(row.pop('details_json') or '{}')
            for field in ('sleep_score','bedtime_local','wake_time_local','deep_sleep_minutes','light_sleep_minutes','rem_sleep_minutes','awake_minutes','seven_day_hrv_ms','seven_day_hrv_status','hrv_highest_5min_ms','hrv_baseline_low','hrv_baseline_high','sleep_data_date','hrv_data_date','resting_hr_data_date'):
                row[field]=details.get(field)
            row['morning']=(details.get('recovery_extras') or {}).get('morning') or {}
            vitals=details.get('night_vitals') or {}
            row['night']={name:{k:v for k,v in (vitals.get(name) or {}).items() if k!='points'} for name in ('respiration','spo2')} if vitals else None
            rows.append(row)
        return rows
    if key.startswith('夜间采样_'):
        row=conn.execute("SELECT json_extract(details_json,'$.night_vitals') FROM daily_recovery WHERE date=?",(key.split('_',1)[1],)).fetchone()
        return json.loads(row[0]) if row and row[0] else {}
    if key=='拉伸':
        return [[r['date'],'明确未做' if r['status']=='explicitly_not_done' else '拉伸',measure(r['duration_minutes'],'分钟'),r['pain_note']] for r in items('SELECT * FROM stretching_records ORDER BY date DESC')]
    if key=='来源':
        return [[str(r['id']),r['kind'],r['note']] for r in items('SELECT id,kind,note FROM sources ORDER BY id DESC')]
    if key.startswith('工作段曲线_') and key[6:].isascii() and key[6:].isdigit() and len(key[6:])<=10:
        return work_curves(conn,int(key[6:]))
    if key=='报告':
        out=[]
        cycle=meta(conn,'cycle_dashboard')
        periods=items('SELECT * FROM periodic_reviews')
        week_analyses={(r['period_start'],r['period_end']):[] for r in periods if r['period_type']=='weekly'}
        lap_rows={}
        work_laps={}
        for lap in conn.execute("""SELECT l.session_id, json_extract(l.details_json,'$.distance_km'),
                        json_extract(l.details_json,'$.time_seconds'),json_extract(l.details_json,'$.average_hr'),
                        coalesce(nullif(json_extract(l.details_json,'$.api_raw.intensityType'),''),json_extract(l.details_json,'$.step_type')),l.lap_number
                        FROM running_laps l
                        WHERE l.session_id IN (SELECT session_id FROM analyses WHERE session_id IS NOT NULL)
                        ORDER BY l.session_id,l.lap_number"""):
            lap_rows.setdefault(lap[0],[]).append(list(lap[1:5]))
            work_laps.setdefault(lap[0],[]).append(dict(km=lap[1],sec=lap[2],hr=lap[3],kind=lap[4],number=lap[5]))
        by_run={sid:work_groups(laps) for sid,laps in work_laps.items()}
        for r in items("SELECT a.*, s.sport, json_extract(rd.details_json,'$.activityName') AS run_name, json_extract(rd.details_json,'$.route_observation.name') AS route, rd.distance_km AS run_distance, rd.timer_seconds AS run_seconds FROM analyses a LEFT JOIN sessions s ON a.session_id=s.id LEFT JOIN running_details rd ON rd.session_id=a.session_id ORDER BY a.id DESC"):
            e=json.loads(r['evidence_json'] or '{}'); lr=e.get('load_review',{})
            if e.get('journal_special_deleted'):continue
            spec=e.get('special_decision') or {}
            qualifies=isinstance(spec,dict) and all(isinstance(spec.get(k),str) and spec[k].strip() for k in ('question','decision','evidence','checkpoint','exit'))
            typ=e.get('report_type') or ''
            if typ=='stage_review' or (e.get('progress_review') or {}).get('kind')=='stage':
                kind='阶段'
            elif lr.get('kind')=='weekly' or typ in ('weekly','weekly_review','load_weekly'):
                kind='周'
                period=(lr.get('period_start') or e.get('period_start'),lr.get('period_end') or e.get('period_end'))
                if period in week_analyses:
                    week_analyses[period].append(dict(title=lr.get('title'),assessment=r['assessment'],recommendation=r['recommendation']))
                    continue
            elif lr.get('kind')=='monthly' or typ in ('monthly','monthly_review','load_monthly'):
                kind='月'
            elif qualifies:
                kind='专项'
            elif lr.get('kind')=='daily' or typ in ('daily','daily_review','load_daily'):
                kind='日评'
            else:
                kind='单次' if r['session_id'] or typ in ('activity_review','session_review','strength_review') else '日评'
            if kind=='阶段':
                start=e.get('period_start') or e.get('progress_review',{}).get('from_date')
                stage=next((x['name'] for x in cycle.get('stages',[]) if start and x['from']<=start<=x['to']),None)
                title='训练计划 · '+stage if stage else e.get('progress_review',{}).get('title') or '阶段复盘'
                out.append([e.get('period_end') or e.get('date'),kind,title,r['assessment'],r['recommendation'],r['id']])
                continue
            topic=lr.get('title') or e.get('specialist_topic') or (e.get('specialist_review') or {}).get('topic') or e.get('topic')
            fallback={'strength':'力量训练复盘','running':'跑步训练复盘'}.get(r['sport'],'训练复盘')
            if not isinstance(topic,str) or not topic.strip():
                topic='每日简评' if kind=='日评' else fallback
            out.append([e.get('date') or e.get('actual_date') or r['created_at'][:10],kind,topic,r['assessment'],r['recommendation'],
                        dict(focusKey=spec.get('key') if qualifies else None,loadAnalysis=kind in ('周','月'),run=r['session_id'] if r['sport']=='running' else None,km=r['run_distance'],seconds=r['run_seconds'],workGroups=by_run.get(r['session_id'],[]),name=r['run_name'],route=r['route'],
                             verdict=(e.get('coach_review') or {}).get('verdict'),laps=lap_rows.get(r['session_id'],[]))])
        for r in periods:
            a=json.loads(r['assessment_json'] or '{}')
            notes = {k:v for k,v in a.items() if not k.startswith('_') and isinstance(v,str)} if isinstance(a,dict) else {}
            review = (a.get('_progress_review') or a.get('_coach_review') or {}) if isinstance(a,dict) else {}
            verdict = review.get('verdict') or next((v for k,v in notes.items() if '结论' in k), None)
            if isinstance(a,str):
                verdict = a
            detail = dict(loadReports=week_analyses.get((r['period_start'],r['period_end']),[]) if r['period_type']=='weekly' else [],review=review, notes=notes, through=r['data_through'],
                          reviewed=review.get('updated_on') or review.get('reviewed_on'),
                          next_actions=json.loads(r['next_actions_json'] or '[]'),
                          limitations=json.loads(r['limitations_json'] or '[]'))
            day=date.fromisoformat(r['period_start'])
            weekly=r['period_type']=='weekly'
            if weekly:
                day-=timedelta(days=day.weekday())
            title=f'{day.year}年{day.month}月'
            if weekly:
                title+=f'第{(day.day-1)//7+1}周'
            out.append([r['period_end'],'周' if weekly else '月',title,r['period_start']+' — '+r['period_end'],verdict,detail])
        return sorted(out,key=lambda x:str(x[0]),reverse=True)
    if key.startswith('路线_') and key[3:].isdigit():
        return route_view(conn,int(key[3:]))
    if key=='年度':
        years=[list(r) for r in conn.execute("""SELECT substr(s.date,1,4),count(*) || ' 次跑步',round(sum(distance_km),2) || ' km' FROM sessions s JOIN running_details r ON r.session_id=s.id GROUP BY 1 ORDER BY 1 DESC""")]
        return dict(years=years,history=topics(conn,'纪录')['history'])
    if key=='知识库':
        book_path=ROOT/'knowledge_book.json'
        book=json.loads(book_path.read_text(encoding='utf-8-sig')) if book_path.is_file() else {}
        return {k:book.get(k,[]) for k in ('modules','chapters','guides','sources')}
    if key=='目标':
        g=meta(conn,'goal_readiness_assessment')
        return [[g.get('last_reviewed_on'),'目标达成把握',g.get('summary'),g.get('next_review_node')]]
    if key=='同步':
        return [[v.get('data_date'),k,v.get('status'),v.get('reason')] for k,v in meta(conn,'garmin_sync_schedule').get('categories',{}).items()]
    if key.startswith('能力区间_'):
        try:
            _,first,last=key.split('_')
            start,end=date.fromisoformat(first),date.fromisoformat(last)
        except ValueError:
            return None
        if start>end or start.year<1900 or end.year>2100:
            return None
        _,runs=ability_runs(conn,start,end)
        return runs
    if key=='跑步能力面板':
        thresholds=meta(conn,'running_ability_evidence').get('thresholds',[])
        reference=meta(conn,'archive_field_threshold') or settings().get('field_reference',{})
        evidence=conn.execute("SELECT date FROM sessions WHERE id=? AND date=? AND sport='running'",
                              (reference.get('session_id'),reference.get('date'))).fetchone()
        field={k:reference[k] for k in ('date','low','high')} if evidence else None
        end=date.today()
        start=end-timedelta(days=27)
        recent,runs=ability_runs(conn,start,end)
        return dict(rows=topics(conn,'能力'),firstDay=conn.execute("SELECT min(date) FROM sessions WHERE sport='running'").fetchone()[0],recent=runs,start=start.isoformat(),end=end.isoformat(),rules=recent['rules'],thresholds=[
            {k:r.get(k) for k in ('date','pace_seconds_km','hr_bpm')} for r in thresholds
        ],field=field)
    if key=='能力':
        m=meta(conn,'running_ability_evidence')
        out=[[v.get('date'),'设备阈值',(duration(v['pace_seconds_km'])+' /km') if v.get('pace_seconds_km') is not None else '—',measure(v.get('hr_bpm'),'bpm')] for v in m.get('thresholds',[])]
        reports={}
        windows=[]
        batches=meta(conn,'garmin_weekly_api_reports').get('records',{}).values()
        for batch in sorted(batches,key=lambda b:b.get('read_at') or ''):
            for key,grain in [('vo2_year','month'),('vo2_6month','month'),('vo2_4week','week')]:
                report=batch.get('reports',{}).get(key) or {}
                start,end=report.get('start',''),report.get('end','')
                accepted={}
                for row in report.get('data') or []:
                    g=row.get('generic') or {}
                    day=g.get('calendarDate') or ''
                    v=next((g.get(k) for k in ('vo2MaxPreciseValue','vo2MaxValue') if isinstance(g.get(k),(float,int)) and g[k]>0),None)
                    if v is not None and start<=day<=min(end,date.today().isoformat()):
                        accepted[grain,day]=v
                if accepted:
                    windows.append((grain,start,end))
                    reports={k:v for k,v in reports.items() if not (k[0]==grain and start<=k[1]<=end)}
                    reports.update(accepted)
        for r in m.get('vo2_report_history',{}).get('records',[]):
            grain=r.get('granularity')
            if r.get('value') is not None and not any(grain==g and r['period_end']>=start and r['period_start']<=end for g,start,end in windows):
                reports[grain,r.get('data_through') or r['period_end']]=r['value']
        for (grain,day),v in reports.items():
            out.append([day,'最大摄氧量 · '+{'week':'周汇总','month':'月汇总'}.get(grain,'汇总'),measure(v,'ml/kg/min',1),'佳明报告汇总日期'])
        return sorted(out,key=lambda x:str(x[0]),reverse=True)
    if key=='纪录':
        pr,h,history=personal_record_history(conn)
        activity_map={str(r[0]):r[1] for r in conn.execute("SELECT json_extract(details_json,'$.activityId'),session_id FROM running_details") if r[0]}
        for record in history.values():
            record['session_id']=activity_map.get(str(record.get('activity_id')))
        return dict(current=pr.get('records',[]),categories=h.get('categories',[]),history=list(history.values()),verified=pr.get('verified_at') or h.get('verified_at') or pr.get('observed_on'))

    if key=='体测':
        return [[r.get('date'),'体重 '+measure(r.get('weight_kg'),'kg',2),'体脂率 '+measure(r.get('body_fat_percent'),'%',1)] for r in reversed(meta(conn,'body_composition_history').get('records',[]))]
    if key=='负荷':
        monitor=meta(conn,'garmin_training_monitoring')
        records=[{**{k:r.get(k) for k in ('date','training_status','acute_load','chronic_load','load_ratio','focus')},'bounds':(r.get('api_observation') or {}).get('load_range')} for r in monitor.get('records',[])]
        ids=set(monitor.get('coach_review_analysis_ids',[]))
        reviews=[]
        for row in items('SELECT id,evidence_json FROM analyses ORDER BY id DESC'):
            review=json.loads(row['evidence_json'] or '{}').get('load_review')
            if row['id'] in ids and review:
                reviews.append(review)
        return dict(records=sorted(records,key=lambda x:x['date']),reviews=sorted(reviews,key=lambda x:x['date'],reverse=True))
    return None
