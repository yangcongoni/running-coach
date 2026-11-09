"""Verified API semantics; missing/changed schemas fail closed."""
import copy,datetime as dt,math

STATUS_MAP={7:'高效训练'}
RECORD_TYPES={1:('1 公里',1,'pr.label.1k.run'),2:('1英里',1.609344,'pr.label.1mile.run'),3:('5 公里',5,'pr.label.5k.run'),4:('10 公里',10,'pr.label.10k.run'),5:('半马',21.0975,'pr.label.half.marathon'),6:('全马',42.195,'pr.label.full.marathon'),7:('最长跑步纪录',None,'pr.label.farthest.run')}

def focus_period(m):
    m=copy.deepcopy(m)
    if m.get('period_evidence'):return m
    f=m.get('load_focus',{})
    required=['monthlyLoadAerobicLow','monthlyLoadAerobicHigh','monthlyLoadAnaerobic']
    required += ['monthlyLoad'+part+'Target'+edge for part in ['AerobicLow','AerobicHigh','Anaerobic'] for edge in ['Min','Max']]
    valid=all(isinstance(f.get(k),(int,float)) and not isinstance(f[k],bool) and math.isfinite(f[k]) and f[k]>=0 for k in required)
    valid=valid and bool(f.get('trainingBalanceFeedbackPhrase')) and m.get('sport')=='RUNNING'
    valid=valid and all(f['monthlyLoad'+p+'TargetMin']<=f['monthlyLoad'+p+'TargetMax'] for p in ['AerobicLow','AerobicHigh','Anaerobic'])
    if valid:
        date=dt.date.fromisoformat(m['date']);m.update(period_start=(date-dt.timedelta(days=28)).isoformat(),period_end=date.isoformat(),period_source='verified_rule_20261030',period_method='rule_derived_not_api_raw')
        m['load_focus_validation']={'status':'success','missing':[]}
    return m

def records_projection(records,types):
    if not isinstance(records,list) or not isinstance(types,list):return [],['接口未返回纪录或类型列表']
    definitions={x.get('id'):x for x in types};out=[];errors=[];seen=set()
    for r in records:
        tid=r.get('typeId');definition=definitions.get(tid)
        if not definition:errors.append('未知纪录类型 '+str(tid));continue
        if tid not in RECORD_TYPES:
            if definition.get('sport')=='RUNNING':errors.append('未适配跑步纪录类型 '+str(tid))
            continue
        label,km,key=RECORD_TYPES[tid]
        if definition.get('key')!=key or definition.get('sport')!='RUNNING':errors.append('纪录类型映射变化 '+str(tid));continue
        if r.get('status')!='ACCEPTED':continue
        try:
            date=r['activityStartDateTimeLocalFormatted'][:10];dt.date.fromisoformat(date)
            value=r['value'];aid=r['activityId']
            if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or value<=0 or not isinstance(aid,int) or aid<=0:raise ValueError()
            if tid in seen:raise ValueError()
            seen.add(tid)
        except (KeyError,TypeError,ValueError):errors.append('纪录缺项或同项目冲突 '+str(tid));continue
        out.append({'label':label,'km':km,'pr_type':tid,'rank':1,'date':date,'activity_id':aid,'activity_name':r.get('activityName'),'seconds':value if tid!=7 else None,'distance_km':value/1000 if tid==7 else None,'api_record_id':r.get('id'),'api_status':'ACCEPTED','source_url':'https://connect.garmin.cn/app/activity/'+str(aid)})
    return out,errors

def merge_records(previous,records,types,read_at,source_id):
    result=copy.deepcopy(previous);projected,errors=records_projection(records,types)
    if errors:return result,errors
    current=result.setdefault('records',[]);history=result.setdefault('history',[])
    for item in projected:
        old=next((r for r in current if r.get('pr_type')==item['pr_type'] or r.get('label')==item['label']),None)
        fields=['date','activity_id','seconds','distance_km','api_record_id']
        if old and all(old.get(k)==item.get(k) for k in fields):continue
        if old:
            history.append({'record':copy.deepcopy(old),'superseded_on':read_at[:10],'verified_at':read_at,'source_id':source_id,'reason':'已接受个人纪录API更新，保留旧值及精度来源'})
            current.remove(old)
        current.append(dict(item,source_id=source_id,verified_at=read_at))
    # Absence is not permission to delete an old record; preserve and flag inconsistencies.
    present={r['pr_type'] for r in projected}
    for old in current:
        if old.get('pr_type') in RECORD_TYPES and old.get('pr_type') not in present and (old.get('seconds') or old.get('distance_km')):errors.append('接口未返回既有纪录 '+str(old['pr_type']))
    result.update(observed_on=read_at[:10],verified_at=read_at,source_id=source_id,source='Garmin CN API',scope='全部时间',note='已接受纪录由接口更新；候选另存，缺失不自动删除旧纪录。')
    return result,errors
