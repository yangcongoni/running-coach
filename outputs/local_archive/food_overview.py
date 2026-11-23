"""Small, read-only projection for the signed-in food diary."""
import json
import math
import re
from contextlib import closing
from datetime import date, timedelta
from statistics import median
import mobile_archive as archive


def positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def plan_distance(plan):
    if positive(plan.get('distance_km')):
        return plan['distance_km']
    # Only an explicitly stated whole-session distance. Never use a warm-up or a pace.
    match = re.search(r'(?:全课|总计|全程|共计|总量)\s*(?:约|为)?\s*(\d+(?:\.\d+)?)(?:\s*[–—~～至-]\s*(\d+(?:\.\d+)?))?\s*(?:公里|km)', plan.get('content', ''), re.I)
    if match:
        return (float(match[1]) + float(match[2] or match[1])) / 2
    return None


def activities_between(conn, start, end):
    labels = {'running':'跑步', 'strength':'力量训练', 'walking':'步行', 'hiking':'徒步',
              'cycling':'骑行', 'swimming':'游泳'}
    rows = conn.execute("""SELECT s.id,s.date,s.sport,s.duration_minutes,s.session_rpe,
                   r.distance_km,r.timer_seconds,
                   substr(json_extract(r.details_json,'$.startTimeLocal'),12,5) AS time,
                   json_extract(r.details_json,'$.activityType.typeKey') AS kind
            FROM sessions s LEFT JOIN running_details r ON r.session_id=s.id
            WHERE s.date BETWEEN ? AND ? ORDER BY s.date,s.id""", (start,end))
    activities = []
    for row in rows:
        sport = row['sport']
        if sport == 'running' and row['kind'] in ('walking','hiking','cycling','swimming'):
            sport = row['kind']
        minutes = row['duration_minutes']
        if minutes is None and positive(row['timer_seconds']):
            minutes = row['timer_seconds']/60
        activities.append(dict(source='跑步训练档案',externalId='session:'+str(row['id']),
            date=row['date'],type=labels.get(sport,sport),km=row['distance_km'],
            minutes=minutes,time=row['time'] or '',
            intensity='RPE '+format(row['session_rpe'],'g') if row['session_rpe'] is not None else ''))
    return activities


def archive_weights(conn, start, end):
    rows=archive.meta(conn,'body_composition_history').get('records',[])
    return [dict(date=r['date'],kg=r['weight_kg'],morning=r.get('morning') is True,source='跑步训练档案') for r in rows
            if start<=str(r.get('date',''))<=end and positive(r.get('weight_kg'))]

def read_activity_period(start, end):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first.isoformat()!=start or last.isoformat()!=end or not 0 <= (last-first).days <= 30:
        raise ValueError('日期范围无效')
    with closing(archive.open_read()) as conn:
        weights=archive_weights(conn,start,end)
        return dict(start=start,end=end,activities=activities_between(conn,start,end),weights=weights,morningWeights=[w for w in weights if w['morning']])


def read_day(key):
    day = date.fromisoformat(key)
    if day.isoformat() != key:
        raise ValueError('日期无效')
    with closing(archive.open_read()) as conn:
        conn.execute('BEGIN')
        profile = archive.meta(conn, 'current_profile')
        records = sorted((r for r in archive.meta(conn, 'body_composition_history').get('records', [])
                          if r.get('date') and r['date'] <= key), key=lambda r: r['date'])
        weight = next((r for r in reversed(records) if positive(r.get('weight_kg'))), {})
        basal = [r for r in records if positive(r.get('bmr_device_kcal')) and r['date'] >= (day - timedelta(days=90)).isoformat()][-3:]
        row = conn.execute("SELECT prescription_json FROM planned_sessions WHERE date=? AND sport='running' ORDER BY id DESC LIMIT 1", (key,)).fetchone()
        prescription = json.loads(row[0]) if row else {}
        activities = activities_between(conn,key,key)
        runs = [a for a in activities if a['type']=='跑步']
        start = (day - timedelta(days=13)).isoformat()
        strength_dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT date FROM sessions WHERE sport='strength' AND date BETWEEN ? AND ?",
            (start, key))]
        history_start=(day-timedelta(days=21)).isoformat()
        morning_weights=[w for w in archive_weights(conn,history_start,key) if w['morning']]
        running_history=[dict(date=a['date'],km=a['km'],time=a['time'],minutes=a['minutes'],externalId=a['externalId'],type='跑步',source=a['source']) for a in activities_between(conn,history_start,(day-timedelta(days=1)).isoformat()) if a['type']=='跑步']
    race = profile.get('primary_race') or {}
    return dict(date=key, runningHistory=running_history, strengthDates=strength_dates, morningWeights=morning_weights, weight=weight.get('weight_kg'), weightDate=weight.get('date'),
                age=profile.get('age'), height=profile.get('height_cm'), raceDate=race.get('date'),
                raceKm=race.get('distance_km'), basal=median(r['bmr_device_kcal'] for r in basal) if basal else None,
                basalDate=basal[-1]['date'] if basal else None, runs=runs, activities=activities, plan=(dict(
                    text=prescription.get('content',''), km=plan_distance(prescription),
                    rest=prescription.get('content','').strip() in ('休息','休息日','跑步休息')) if row else None))

