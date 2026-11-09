"""Compact dated projection of archived recovery API responses."""
READY=['calendarDate','timestampLocal','score','level','inputContext','recoveryTime','feedbackLong','feedbackShort','sleepScore','hrvWeeklyAverage']+[p+s for p in ['sleepScore','recoveryTime','acwr','stressHistory','hrv','sleepHistory'] for s in ['FactorPercent','FactorFeedback']]

def project(adapter,day):
    snapshots=[r for r in adapter.load('readiness_'+day) or [] if r.get('calendarDate')==day]
    primary=[r for r in snapshots if r.get('primaryActivityTracker') is True]
    if primary:snapshots=primary
    elif len({r.get('deviceId') for r in snapshots})>1:snapshots=[]
    morning=[r for r in snapshots if r.get('inputContext')=='AFTER_WAKEUP_RESET']
    r=max(morning,key=lambda x:x.get('timestampLocal') or '') if morning else None
    result={'date':day}
    if r:
        result['morning']={k:r[k] for k in READY if r.get(k) is not None}
        result['morning']['recovery_time_unit']='minutes'
        result['morning']['read_at']=adapter.sources['results/readiness_'+day+'.json'].get('read_at')
    timed=[x for x in snapshots if isinstance(x.get('recoveryTime'),(int,float)) and x['recoveryTime']>=0 and x.get('timestampLocal') and x['timestampLocal'][:10]==day]
    if timed:
        newest=max(timed,key=lambda x:x['timestampLocal'])
        result['recovery_time']={'minutes':newest['recoveryTime'],'measured_at':newest['timestampLocal'],'data_date':day,'input_context':newest.get('inputContext'),'read_at':adapter.sources['results/readiness_'+day+'.json'].get('read_at')}
    return result if len(result)>1 else None
