let annualYear='',prReturn=null,routeParent=null,selectedNight='';
let stageRunReturn=null;
function stageReviewView(s){
 const fields=stageMetrics(s), hero=fields.values().next().value;
 const days=new Map();
 function day(date){
   if(!days.has(date))days.set(date,{runs:[],strength:[]});
   return days.get(date);
 }
 for(const r of s.runs)day(r.date).runs.push(r);
 for(const r of s.strength||[])day(r.date).strength.push(r);
 for(const r of s.recoveries)day(r.date).recovery=r;
 if(s.followingRun)day(s.followingRun.date).following=s.followingRun;
 for(const run of s.runs){
   const next=offsetDate(run.date,1);
   if(next>data.day)continue;
   const row=day(next);
   row.afterRun=true;
   if(!row.recovery&&s.followingMorning?.date===next)row.recovery=s.followingMorning;
 }
 const runRow=(r,following=false)=>{
   const title=r.test?r.test.km+' 公里测试':following?'下次跑步':journalRunName(r);
   const values=[Number.isFinite(r.km)?kmText(r.km):'',Number.isFinite(r.seconds)?clock(r.seconds):'',following&&r.hr!=null?'均心 '+r.hr:'',following&&r.rpe!=null?'RPE '+r.rpe:''].filter(Boolean);
   return '<div class="journal-run"><button data-action="stage-run:'+Number(r.id)+'">'+esc(title)+'<span aria-hidden="true">›</span></button>'+p(values.join(' · '))+
     (r.test?p('测试段 '+clock(r.test.seconds)+' · '+clock(r.test.seconds/r.test.km)+'/km'):'')+(r.note?p(r.note):'')+'</div>';
 };
 const timeline=[...days].sort(([a],[b])=>a.localeCompare(b)).map(([date,row])=>{
   const blocks=[];
   if(row.recovery||row.afterRun){
     const r=row.recovery||{}, feedback=r.feedback||r.feeling;
     const cells=[['睡眠',r.sleep==null?null:Math.floor(r.sleep/60)+' 小时 '+Math.round(r.sleep%60)+' 分'],['静息心率',r.hr==null?null:r.hr+' 次/分'],
       ['单晚 HRV',r.hrv==null?null:r.hrv+' ms'],['准备度',r.readiness==null?null:r.readiness+' / 100']].filter(([,v])=>v!=null);
     blocks.push('<details class="journal-recovery"><summary>'+(row.afterRun?'次晨恢复':'当日恢复')+'</summary>'+
       (cells.length?'<dl>'+cells.map(([k,v])=>'<div><dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd></div>').join('')+'</dl>':p('暂无设备读数'))+
       (feedback?p(feedback):row.afterRun?(pastLegReviewWeek(date)?p('起床腿感：正常（默认）'):button('补充次晨腿感 ›','stage-feedback:'+date)):'')+'</details>');
   }
   for(const r of row.runs){
     blocks.push(runRow(r));
     const post=recoveryAfterRun(r,row.recovery);
     if(post)blocks.push('<p class="post-estimate">跑后预计恢复 '+Math.floor(post.minutes/60)+' 小时 '+post.minutes%60+' 分</p>');
   }
   if(row.strength.length)blocks.push('<b>力量训练</b>'+p(row.strength.length+' 次'));
   if(row.following&&!row.runs.some(r=>r.id===row.following.id))blocks.push(runRow(row.following,true));
   return '<div class="journal-node"><time datetime="'+esc(date)+'">'+esc(journalDate(date))+'</time>'+blocks.join('')+'</div>';
 }).join('');
 return button('‹ 复盘报告','topic:报告')+heading(s.custom?'自选时段':'阶段复盘')+'<article class="stage-head"><small>'+esc(stageRange(s))+'</small><h2>'+esc(s.title)+'</h2>'+
   (s.custom?'<p>'+fields.get('runs')[1]+'跑步 · '+(fields.get('km')?.[1]||'里程待核')+'</p>':hero?'<div class="stage-result"><strong>'+esc(hero[1])+'</strong><span>'+esc(hero[0])+'</span></div>':'')+
   (fields.size>=2&&(!s.custom||s.runs.length)?button('阶段分享','stage-share'):'')+'</article>'+stageJourney(s,section('训练时间线')+
   '<div class="stage-timeline">'+timeline+(s.custom&&!s.runs.length?p('这段时间没有归档跑步。'):'')+'</div>'+
   (s.custom?(s.related.length?section('相关阶段复盘')+s.related.map(r=>button(r.title+' ›','topic:阶段_'+r.id)).join(''):''):
   card('教练复盘',p(s.assessment)+p(s.recommendation)+(s.through?'<small>数据截至 '+esc(s.through)+'</small>':''))));
}


let routeList=false;
const routeFilter={period:'最近4周',type:'全部类型',scope:'全程'};
const routeCache=new Map();
function annualView(data){
 const year=data.years.some(r=>r[0]===annualYear)?annualYear:data.years[0]?.[0];
 if(!year)return heading('跑步年度报告')+p('暂无跑步记录');
 const row=data.years.find(r=>r[0]===year);
 const history=data.history.filter(r=>r.date.startsWith(year)).sort((a,b)=>b.date.localeCompare(a.date));
 const milestones=history.map(r=>{
   const result=r.pr_type===7?kmText(r.distance_km):clock(r.seconds);
   return '<button class="row" data-journal="pr" data-kind="'+r.pr_type+'" data-date="'+esc(r.date)+'"><small>'+esc(r.date)+'</small><b>'+esc(r.label||'个人纪录')+' PB</b><span>'+esc(result)+' ›</span></button>';
 }).join('');
 return heading('跑步年度报告')+trainingFilter('报告年份','annual-year',data.years.map(r=>r[0]),year)+card(year+' 年',p(row[1]+' · '+kmText(parseFloat(row[2]))))+section('年度里程碑','已归档的个人纪录')+'<div class="panel">'+(milestones||p('本年暂无已归档的个人纪录。'))+'</div>';
}
async function backToPr(){
 const kind=prReturn;prReturn=null;state.selected=null;editing=null;tab='我的';
 await openTopic('纪录');prType=kind;render();
}
function nightPeriod(row,day){
 if(!row||row.sleep_data_date&&row.sleep_data_date!==day)return null;
 const start=Date.parse(row.bedtime_local),end=Date.parse(row.wake_time_local);
 const midnight=Date.parse(day+'T00:00:00+08:00');
 if(!Number.isFinite(start)||!Number.isFinite(end)||end<=start||end<midnight||end>=midnight+86400000||end-start>86400000)return null;
 return [(start-midnight)/3600000,(end-midnight)/3600000];
}
function nightTime(hour){const m=((Math.round(hour*60)%1440)+1440)%1440;return String(Math.floor(m/60)).padStart(2,'0')+':'+String(m%60).padStart(2,'0')}
function sleepSchedule(all){
 const byDate=new Map(all.map(r=>[r.date,r]));
 const nights=Array.from({length:28},(_,i)=>{const date=offsetDate(data.day,i-27);return {date,interval:nightPeriod(byDate.get(date),date)}});
 const valid=nights.filter(n=>n.interval);
 const low=Math.min(-3,...valid.map(n=>Math.floor(n.interval[0]/3)*3)),high=Math.max(9,...valid.map(n=>Math.ceil(n.interval[1]/3)*3));
 const percent=h=>100*(h-low)/(high-low);
 const ticks=Array.from({length:(high-low)/3+1},(_,i)=>'<small>'+nightTime(low+3*i)+'</small>').join('');
 const bars=nights.map(({date,interval},i)=>{
   const bar=interval?'<i style="left:'+percent(interval[0])+'%;width:'+(percent(interval[1])-percent(interval[0]))+'%"></i>':'<small>缺记录</small>';
   return '<button class="night-line'+(i%7===0?' week-start':'')+'" '+(interval?'data-journal="night" data-date="'+date+'" aria-label="'+date+' '+interval.map(nightTime).join('至')+'"':'disabled')+' aria-pressed="'+(date===selectedNight)+'"><time>'+date.slice(5)+'</time><span>'+bar+'</span></button>';
 }).join('');
 const entry=valid.find(n=>n.date===selectedNight);
 const details=entry?'<div class="night-note"><b>'+entry.date+' · 按起床日</b>'+p('入睡 '+nightTime(entry.interval[0])+' · 起床 '+nightTime(entry.interval[1])+ ' · 实睡 '+(byDate.get(entry.date).sleep_minutes==null?'—':secsText(byDate.get(entry.date).sleep_minutes*60)))+p('深睡 / 浅睡 / REM / 清醒（分钟）　'+['deep_sleep_minutes','light_sleep_minutes','rem_sleep_minutes','awake_minutes'].map(k=>byDate.get(entry.date)[k]??'—').join(' / '))+'</div>':'';
 return '<article class="ability-special"><details<summary>四周作息 · '+valid.length+' / 28 晚</summary><div class="sleep-axis">'+ticks+'</div>'+bars+details+'</details></article>';
}
function routeDetail(a){
 let data=routeCache.get(a.id);
 if(!data){
   data={};routeCache.set(a.id,data);
   api('/api/topic/'+encodeURIComponent('路线_'+a.id)).then(rows=>{for(const r of rows.related)r.type=executionType(r);data.rows=rows}).catch(e=>{data.error=e.message}).finally(()=>{if(state.selected===a.id&&state.sub==='路线装备')render()});
 }
 if(data.error)return p(data.error)+button('重试','routeretry:'+a.id);
 if(!data.rows)return p('正在读取归档路线…');
 const r=data.rows;
 if(routeList)return routeRecords(r,a);
 const map=r.has_map?'<img class="route-map" alt="本次活动的归档路线核对图" src="/api/route-map/'+a.id+'">':'';
 const plot=trackPlot(r.gps);
 return card('路线与装备',stat('路线',r.name||'待核对')+stat('跑鞋',a.shoe||'未归档')+(map||plot||p('本次暂无归档轨迹。'))+(map&&plot?fold('查看本次 GPS 轨迹',plot):'')+(r.variant?p(r.variant):'')+(r.has_group?'<button data-journal="routes">查看同路线记录 ›</button>':''));
}
function trackPlot(segs){
 const points=segs.flat();if(!points.length)return '';
 const lat=points.map(p=>p[0]),lon=points.map(p=>p[1]),west=Math.min(...lon),east=Math.max(...lon),south=Math.min(...lat),north=Math.max(...lat);
 const cos=Math.cos((north+south)*Math.PI/360),dx=(east-west)*cos,dy=north-south,scale=Math.min(288/(dx||1e-9),154/(dy||1e-9));
 const xy=([y,x])=>[(156+((x-west)*cos-dx/2)*scale).toFixed(2),(87+((north-y)-dy/2)*scale).toFixed(2)];
 const lines=segs.map(s=>'<polyline points="'+s.map(p=>xy(p).join(',')).join(' ')+'" fill="none" stroke="#80273e" stroke-width="2"/>').join('');
 const marker=(p,color)=>{const [x,y]=xy(p);return '<circle cx="'+x+'" cy="'+y+'" r="4" fill="'+color+'"/>'};
 return '<svg class="route-map" viewBox="0 0 312 174" aria-label="归档 GPS 轨迹">'+lines+marker(points[0],'#318e82')+marker(points.at(-1),'#80273e')+'</svg><small>北向上 · 绿色起点 / 酒红终点 · 采样缺口断开</small>';
}
function routeRecords(route,a){
 const options=trainingFilter('时间范围','route-period',['最近4周','今年','全部历史'],routeFilter.period)+trainingFilter('训练类型','route-type',['全部类型',...new Set(route.related.map(r=>r.type))],routeFilter.type);
 const start=routeFilter.period==='最近4周'?offsetDate(data.day,-27):routeFilter.period==='今年'?data.day.slice(0,4)+'-01-01':'';
 const rows=route.related.filter(r=>r.date>=start&&r.date<=data.day&&(routeFilter.type==='全部类型'||r.type===routeFilter.type));
 return '<article class="ability-special"><button data-journal="map">‹ 返回路线地图</button><h2>'+esc(route.name)+'</h2><div class="spec-filters">'+options+'</div>'+trainingFilter('比较范围','route-scope',['全程','工作段'],routeFilter.scope)+rows.map(r=>{
   const work=routeFilter.scope==='工作段',km=work?r.work_km:r.distance_km,sec=work?r.work_sec:r.timer_seconds;
   return '<button class="row" data-journal="related" data-id="'+r.id+'"><small>'+r.date+'</small><b>'+esc(r.type)+'</b><span>'+(work&&km==null?'未标注工作段':kmText(km)+' · '+clock(sec))+'</span></button>';
 }).join('')+(!rows.length?p('所选范围暂无同路线记录。'):'')+'</article>';
}
async function backToRoute(){
 const id=routeParent;routeParent=null;state.selected=id;selectedRecord=await api('/api/activity/'+id);state.sub='路线装备';routeList=true;render();
}
v.addEventListener('click',async e=>{
 const b=e.target.closest('[data-journal]');if(!b)return;
 try{
 switch(b.dataset.journal){
 case 'pr': await openTopic('纪录');libFilters['纪录'].range='全部';prType=Number(b.dataset.kind);render();v.querySelector('[data-pb-date="'+b.dataset.date+'"]')?.scrollIntoView({block:'center'});return;
 case 'night': selectedNight=b.dataset.date===selectedNight?'':b.dataset.date;render();const n=v.querySelector('.sleep-axis').closest('details');n.open=true;v.querySelector('.night-note')?.scrollIntoView({block:'nearest'});return;
 case 'routes': routeFilter.type='全部类型';routeList=true;break;
 case 'map': routeList=false;break;
 case 'related': if(Number(b.dataset.id)===state.selected){routeList=false;break}
   routeParent=state.selected;state.selected=Number(b.dataset.id);selectedRecord=await api('/api/activity/'+state.selected);state.sub='分段';curveData=null;routeList=false;break;
 }render();
 }catch(error){msg.textContent=error.message}
});
document.querySelector('nav').addEventListener('click',()=>{prReturn=null;routeParent=null;routeList=false;stageRunReturn=null});

