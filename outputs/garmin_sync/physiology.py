"""Dated archive projections; raw envelopes remain the audit source."""
import math,datetime as dt
FIELDS={'time':('sumElapsedDuration','second'),'distance':('sumDistance','meter'),'speed':('directSpeed','mps'),'hr':('directHeartRate','bpm'),'elevation':('directElevation','meter'),'cadence':('directDoubleCadence','stepsPerMinute'),'power':('directPower','watt'),'stride':('directStrideLength','centimeter'),'gct':('directGroundContactTime','ms'),'oscillation':('directVerticalOscillation','centimeter'),'ratio':('directVerticalRatio','dimensionless'),'pc':('directPerformanceCondition','dimensionless')}
def num(v):return isinstance(v,(float,int)) and not isinstance(v,bool) and math.isfinite(v)
def run_curve(details,summary):
 descriptors={x['key']:x for x in (details.get('metricDescriptors') or [])}
 columns=list(FIELDS);indexes={k:descriptors[v[0]]['metricsIndex'] for k,v in FIELDS.items() if v[0] in descriptors and descriptors[v[0]].get('unit',{}).get('key')==v[1]}
 rows=[]
 for row in (details.get('activityDetailMetrics') or []):
  values=row.get('metrics',[]);out=[]
  for k in columns:
   i=indexes.get(k);v=values[i] if i is not None and i<len(values) else None
   if not num(v) or (k not in ['pc','elevation'] and v<0):v=None
   out.append(v)
  if out[0] is not None:rows.append(out)
 if not rows:return None
 rows.sort(key=lambda r:r[0]);end=rows[-1]
 # Actual metric values are already SI; descriptor.factor is not reapplied.
 checks={'distance':summary.get('distance') is not None and end[1] is not None and abs(end[1]-summary['distance'])<=max(20,summary['distance']*.01),'duration':summary.get('elapsedDuration') is not None and abs(end[0]-summary['elapsedDuration'])<=5}
 pc=[r[columns.index('pc')] for r in rows if r[columns.index('pc')] is not None]
 return {'columns':columns,'points':rows,'received_points':len(rows),'expected_points':details.get('totalMetricsCount'),'complete':len(rows)==details.get('totalMetricsCount')==details.get('metricsCount'),'unit_checks':checks,'units':{k:v[1] for k,v in FIELDS.items()},'performance':{'first':pc[0] if pc else None,'last':pc[-1] if pc else None,'valid_points':len(pc)},'axis':'elapsed_seconds','sampling':'original_api_points'}
def sleep_vitals(data,day):
 s=data.get('dailySleepDTO') or {}
 if s.get('calendarDate')!=day:return None
 start,end=s.get('sleepStartTimestampGMT'),s.get('sleepEndTimestampGMT')
 if not num(start) or not num(end) or end<=start:return None
 def utc_ms(text):
  try:return dt.datetime.fromisoformat(text.replace('Z','+00:00')).replace(tzinfo=dt.timezone.utc).timestamp()*1000
  except (ValueError,TypeError,AttributeError):return None
 out={'date':day,'sleep_start_ms':start,'sleep_end_ms':end,'time_zone':'Asia/Shanghai'}
 for key,series,vkey,tkey,prefix in [('respiration','wellnessEpochRespirationDataDTOList','respirationValue','startTimeGMT','Respiration'),('spo2','wellnessEpochSPO2DataDTOList','spo2Reading','epochTimestamp','SpO2')]:
  points=[]
  for r in data.get(series) or []:
   stamp=r.get(tkey) if key=='respiration' else utc_ms(r.get(tkey));v=r.get(vkey)
   if num(stamp) and start<=stamp<=end:points.append([stamp,v if num(v) and v>0 and (key!='spo2' or v<=100) else None])
  points.sort(key=lambda x:x[0]);avg=s.get('average'+prefix+'Value');low=s.get('lowest'+prefix+'Value');high=s.get('highest'+prefix+'Value')
  out[key]={'average':avg if num(avg) and avg>0 else None,'lowest':low if num(low) and low>0 else None,'highest':high if num(high) and high>0 else None,'points':points,'valid_points':sum(x[1] is not None for x in points),'unit':'次/分钟' if key=='respiration' else '%'}
 return out
