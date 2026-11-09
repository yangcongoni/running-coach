"""Offline Garmin response adapter. Produces review candidates; never writes SQLite.

All raw API responses remain immutable. Unknown units/dates stay raw, not guessed.
"""
from recovery_extras import project
from physiology import run_curve, sleep_vitals
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

TZ = dt.timezone(dt.timedelta(hours=8))

def divide(value, scale):
    return None if value is None else value / scale

def local_from_gmt_ms(value):
    return None if value is None else dt.datetime.fromtimestamp(value/1000, dt.timezone.utc).astimezone(TZ).isoformat()

def threshold_pace(raw_speed):
    # This endpoint's speed is in 10 m/s units, NOT activity-summary m/s.
    # Fail closed on a changed schema rather than guessing a unit from magnitude.
    if raw_speed is None or raw_speed <= 0:
        return None
    pace=100/raw_speed
    return pace if 120 <= pace <= 900 else None

def workout_step(step):
    result={'type':(step.get('stepType') or {}).get('stepTypeKey'),
            'end_condition':(step.get('endCondition') or {}).get('conditionTypeKey'),
            'end_value':step.get('endConditionValue'), 'raw':step}
    if step.get('type')=='RepeatGroupDTO':
        result.update(iterations=step.get('numberOfIterations'),skip_last_rest=step.get('skipLastRestStep'),
                      children=[workout_step(x) for x in step.get('workoutSteps') or []])
    target=(step.get('targetType') or {}).get('workoutTargetTypeKey')
    values=[step.get('targetValueOne'),step.get('targetValueTwo')]
    result['target_type']=target
    if target=='pace.zone' and all(v is not None and v>0 for v in values):
        result['pace_seconds_km']=sorted(1000/v for v in values)
    elif target=='heart.rate.zone':
        result['heart_rate_bpm']=values
    return result

def primary(mapping):
    records = list((mapping or {}).values())
    selected = [x for x in records if x.get('primaryTrainingDevice') is True]
    if len(selected) == 1:
        return selected[0]
    if len(records) == 1:
        return records[0]
    return {}  # Never silently pick a device from ambiguous data.

def completeness(fields):
    missing = [k for k,v in fields.items() if v is None]
    return {'status': 'partial' if missing else 'success', 'missing': missing}

def category_state(previous, attempted_at, data_date, fields):
    result = dict(previous)
    result.update(completeness(fields), last_attempt_at=attempted_at, data_date=data_date)
    if result['status'] == 'success':
        result['last_success_at'] = attempted_at
    result['reason'] = ', '.join(result['missing']) or 'required fields present'
    return result

def edge_segment(laps, kind, reverse=False):
    chosen=[]
    for lap in reversed(laps) if reverse else laps:
        if lap.get('intensityType') != kind:
            break
        chosen.append(lap)
    if reverse:
        chosen.reverse()
    return {'status':'explicit' if chosen else 'not_explicitly_marked',
            'seconds':sum(x['duration'] for x in chosen) if chosen and all(x.get('duration') is not None for x in chosen) else None,
            'meters':sum(x['distance'] for x in chosen) if chosen and all(x.get('distance') is not None for x in chosen) else None,
            'lap_indices':[x.get('lapIndex') for x in chosen]}

def dedupe_calendar(items, start, end):
    unique={}
    for item in items:
        if not start <= (item.get('date') or '') <= end:
            continue
        # Exact duplicates only. Conflicting versions are retained for review.
        key=json.dumps(item,sort_keys=True,ensure_ascii=False)
        unique[key]=item
    return sorted(unique.values(),key=lambda x:(x['date'],str(x.get('id'))))

class Adapter:
    def __init__(self, root):
        self.root=Path(root); self.sources={}

    def load(self, name, verification=False):
        folder=verification if isinstance(verification,str) else 'verification' if verification else 'results'
        path=self.root/folder/(name+'.json')
        if not path.exists():
            return {}
        raw=path.read_bytes(); envelope=json.loads(raw)
        key=str(path.relative_to(self.root)).replace('\\','/')
        self.sources[key]={'sha256':hashlib.sha256(raw).hexdigest(),
                           'read_at':envelope.get('read_at'), 'method':envelope.get('method')}
        return envelope.get('data')

    def recovery(self, day):
        sleep=self.load('sleep_'+day) or {}; s=sleep.get('dailySleepDTO') or {}
        h=(self.load('hrv_'+day) or {}).get('hrvSummary') or {}
        summary=self.load('summary_'+day) or {}
        # Date mismatch must not make an old response today's observation.
        if s.get('calendarDate')!=day: s={}
        if h.get('calendarDate')!=day: h={}
        if summary.get('calendarDate')!=day: summary={}
        b=h.get('baseline') or {}
        fields={'sleep_minutes':divide(s.get('sleepTimeSeconds'),60),
                'sleep_score':((s.get('sleepScores') or {}).get('overall') or {}).get('value'),
                'bedtime_local':local_from_gmt_ms(s.get('sleepStartTimestampGMT')),
                'wake_time_local':local_from_gmt_ms(s.get('sleepEndTimestampGMT')),
                'night_hrv_ms':h.get('lastNightAvg'),'seven_day_hrv_ms':h.get('weeklyAvg'),
                'hrv_status_raw':h.get('status'),'hrv_highest_5min_ms':h.get('lastNight5MinHigh'),
                'hrv_baseline_low':b.get('balancedLow'),'hrv_baseline_high':b.get('balancedUpper'),
                'resting_hr_bpm':summary.get('restingHeartRate')}
        for target,source in [('deep_sleep_minutes','deepSleepSeconds'),('light_sleep_minutes','lightSleepSeconds'),('rem_sleep_minutes','remSleepSeconds'),('awake_minutes','awakeSleepSeconds')]:
            fields[target]=divide(s.get(source),60)
        ready=[r for r in self.load('readiness_'+day) or [] if r.get('calendarDate')==day]
        morning=[r for r in ready if r.get('inputContext')=='AFTER_WAKEUP_RESET']
        return {'date':day,'fields':fields,'validation':completeness(fields),'recovery_extras':project(self,day),'night_vitals':sleep_vitals(sleep,day),
                'readiness_snapshots':ready,'morning_readiness':max(morning,key=lambda r:r.get('timestamp','')) if morning else None,
                'recovery_time_unit':'minutes',
                'daily_recovery_candidate':{'date':day,'sleep_minutes':fields['sleep_minutes'],'hrv_ms':fields['night_hrv_ms'],'resting_hr':fields['resting_hr_bpm']}}

    def monitoring(self, day):
        t=self.load('training_status_'+day) or {}
        s=primary((t.get('mostRecentTrainingStatus') or {}).get('latestTrainingStatusData'))
        f=primary((self.load('load_focus_'+day) or {}).get('metricsTrainingLoadBalanceDTOMap'))
        if s.get('calendarDate')!=day:s={}
        if f.get('calendarDate')!=day:f={}
        a=s.get('acuteTrainingLoadDTO') or {}
        fields={'training_status_raw':s.get('trainingStatus'),'feedback_raw':s.get('trainingStatusFeedbackPhrase'),
                'acute_load':a.get('dailyTrainingLoadAcute'),'chronic_load':a.get('dailyTrainingLoadChronic'),
                'load_ratio':a.get('dailyAcuteChronicWorkloadRatio')}
        focus={k:f.get(k) for k in ['monthlyLoadAerobicLow','monthlyLoadAerobicHigh','monthlyLoadAnaerobic',
                'monthlyLoadAerobicLowTargetMin','monthlyLoadAerobicLowTargetMax','monthlyLoadAerobicHighTargetMin',
                'monthlyLoadAerobicHighTargetMax','monthlyLoadAnaerobicTargetMin','monthlyLoadAnaerobicTargetMax','trainingBalanceFeedbackPhrase']}
        periods=self.load('load_focus_periods',True) or []
        evidence=next((x for x in periods if x.get('date')==day and x.get('period_end')==day),None)
        pairs=[('anaerobic','monthlyLoadAnaerobic'),('high_aerobic','monthlyLoadAerobicHigh'),('low_aerobic','monthlyLoadAerobicLow')]
        matched=bool(evidence and all(focus[k] is not None and evidence.get(w) is not None and abs(focus[k]-evidence[w])<=.51 for w,k in pairs))
        start=evidence.get('period_start') if matched else None
        end=evidence.get('period_end') if matched else None
        return {'date':day,'fields':fields,'validation':completeness(fields), 'load_focus':focus,
                'load_focus_validation':completeness(dict(focus,period_start=start,period_end=end)),
                'load_range':{'min':a.get('minTrainingLoadChronic'),'max':a.get('maxTrainingLoadChronic'),'chronic':a.get('dailyTrainingLoadChronic'),'status':a.get('acwrStatus'),'method':'api_load_bounds_divided_by_chronic'},
                'load_focus_scope':'device_rolling_balance_not_daily_load','device_id':s.get('deviceId'),
                'sport':s.get('sport'),'period_start':start,'period_end':end,
                'period_evidence':evidence if matched else None,'period_source':'verification/load_focus_periods.json' if matched else None}

    def activity(self, item):
        aid=str(item['activityId']); a=self.load('activity_'+aid) or {};s=a.get('summaryDTO') or {}
        laps=(self.load('laps_'+aid) or {}).get('lapDTOs') or []
        details=self.load('full_details_'+aid,True) or self.load('details_'+aid) or {}
        gears=self.load('gear_'+aid) or []
        mapped={k:s.get(k) for k in ['distance','duration','elapsedDuration','movingDuration','averageHR','maxHR','averagePower','maxPower','normalizedPower','elevationGain','elevationLoss','minElevation','maxElevation','activityTrainingLoad']}
        mapped.update(activityId=int(aid),activityName=a.get('activityName'),startTimeLocal=s.get('startTimeLocal'),
            aerobicTrainingEffect=s.get('trainingEffect'),anaerobicTrainingEffect=s.get('anaerobicTrainingEffect'),
            trainingExecutionScore=s.get('directWorkoutComplianceScore'),
            averageRunningCadenceInStepsPerMinute=s.get('averageRunCadence'),
            maxRunningCadenceInStepsPerMinute=s.get('maxRunCadence'),
            avgStrideLength_m=divide(s.get('strideLength'),100),avgVerticalOscillation_cm=s.get('verticalOscillation'),
            avgVerticalRatio=s.get('verticalRatio'),avgGroundContactTime_ms=s.get('groundContactTime'))
        expected=details.get('totalMetricsCount');actual=len(details.get('activityDetailMetrics') or [])
        return {'external_key':'garmin:'+aid,'date':str(s.get('startTimeLocal',''))[:10],
                'session_candidate':{'duration_minutes':divide(s.get('duration'),60)},
                'running_details_candidate':{'distance_km':divide(s.get('distance'),1000),'timer_seconds':s.get('duration'),
                 'elapsed_seconds':s.get('elapsedDuration'),'average_hr':s.get('averageHR'),'maximum_hr':s.get('maxHR'),'details_json':mapped},
                'laps':laps,'warmup':edge_segment(laps,'WARMUP'),'cooldown':edge_segment(laps,'COOLDOWN',True),
                'gear_observations':gears,'route_group':None,
                'archived_curve':run_curve(details,s),
                'curve_validation':{'status':'success' if expected and actual==expected==details.get('metricsCount') else 'partial','received_points':actual,'expected_points':expected},
                'device_rpe_raw':s.get('directWorkoutRpe'),'personal_record_flag':item.get('pr'),
                'activity_vo2_raw':item.get('vO2MaxValue'),'activity_vo2_measurement_date':None}

    def build(self,start,end):
        dates=[];day=dt.date.fromisoformat(start)
        while day.isoformat()<=end:dates.append(day.isoformat());day+=dt.timedelta(days=1)
        activities=[self.activity(x) for x in self.load('activities') or [] if start<=str(x.get('startTimeLocal',''))[:10]<=end]
        calendars=[]
        for name in ['calendar_previous','calendar_current']:
            calendars+=(self.load(name) or {}).get('calendarItems') or []
        types={x['id']:x for x in self.load('record_types',True) or []}
        records=[dict(x,type_definition=types.get(x.get('typeId'))) for x in self.load('records') or []]
        plans=[]
        plan_days={}
        for item in calendars:
            uid=item.get('workoutUuid')
            if uid:plan_days.setdefault(uid,set()).add(item.get('date'))
        for task in (self.load('adaptive_plan_1078155') or {}).get('taskList') or []:
            uid=(task.get('taskWorkout') or {}).get('workoutUuid')
            if uid:plan_days.setdefault(uid,set()).add(task.get('calendarDate'))
        for uid,days in plan_days.items():
            raw=self.load('adaptive_workout_'+uid,'verification_extra') or {}
            segments=[{'segment_order':s.get('segmentOrder'),'steps':[workout_step(x) for x in s.get('workoutSteps') or []]} for s in raw.get('workoutSegments') or []]
            plans.append({'uuid':uid,'schedule_dates':sorted(d for d in days if d),'name':raw.get('workoutName'),
                'description':raw.get('description'),'estimated_duration_seconds':raw.get('estimatedDurationInSecs'),
                'segments':segments,'status':'success' if segments and all(x['steps'] for x in segments) else 'partial',
                'adopted_into_coach_plan':False,'raw':raw})
        threshold_records=[]
        for row in self.load('threshold_raw','verification_extra') or []:
            date=row.get('calendarDate');speed=row.get('speed');hr=row.get('heartRate')
            if hr is None:hr=row.get('hearRate')
            threshold_records.append({'source_datetime':date,'date':date[:10] if date else None,
                'speed_raw':speed,'speed_unit':'10_m_per_second','pace_seconds_km':threshold_pace(speed),
                'heart_rate_bpm':hr,'raw':row})
        vo2=[]
        for day in dates:
            for x in self.load('vo2_'+day) or []:
                v=x.get('generic') or {}
                if v.get('calendarDate')==day:vo2.append(dict(v,source_file='results/vo2_'+day+'.json',status='api_dated_observation_pending_import_policy'))
        output={'schema_version':1,'mode':'dry_run','production_write_enabled':False,'range':[start,end],
                'recovery':[self.recovery(d) for d in dates], 'monitoring':[self.monitoring(d) for d in dates],
                'activities':activities,'vo2_observations':vo2,'personal_records':records,
                'record_candidates':self.load('record_candidates',True),
                'calendar':dedupe_calendar(calendars,start,end),
                'plan_details':plans,
                'plan_validation':{'status':'success' if plans and all(x['status']=='success' for x in plans) else 'partial','reason':'UUID adaptive endpoint; preserve schedule dates and distinct variants; never adopt automatically'},
                'threshold_observations':threshold_records,
                'threshold_raw':self.load('threshold_latest',True),'threshold_validation':{'status':'success' if threshold_records else 'partial','reason':'raw endpoint preserves independent dates'},
                'protected_fields':['session_rpe','fatigue_0_10','soreness_0_10','pain_note','user_followup','route_observation','completion_review','coach_focus_reviews','plan_version'],
                'release_gate':{'ready':False,'reasons':['production persistence and scheduled authentication not enabled']}}
        output['field_validation_ready']=all(x['validation']['status']=='success' for x in output['recovery']) and all(x['validation']['status']=='success' and x['load_focus_validation']['status']=='success' for x in output['monitoring']) and all(x['curve_validation']['status']=='success' for x in activities) and output['plan_validation']['status']=='success' and output['threshold_validation']['status']=='success'
        if not output['field_validation_ready']:output['release_gate']['reasons'].append('field validation incomplete')
        output['sources']=self.sources
        return output

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).parent);p.add_argument('--start',required=True);p.add_argument('--end',required=True);args=p.parse_args()
    result=Adapter(args.root).build(args.start,args.end)
    out=args.root/'verification'/'normalized_candidates.json'
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'activities':len(result['activities']),'recovery_days':len(result['recovery']),'release_gate':result['release_gate']},ensure_ascii=True))

if __name__=='__main__':main()
