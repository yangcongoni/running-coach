const q=s=>document.querySelector(s),v=q('#view'),msg=q('#msg'),esc=s=>String(s??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),sport=s=>s==='running'?'跑步':s==='strength'?'力量':s;
let data,tab='今天',editing=null,busy=false;
const card=(title,body)=>'<article><h2>'+esc(title)+'</h2>'+body+'</article>',p=s=>'<p>'+esc(s)+'</p>',safe=s=>s==null?'—':s;
async function api(url,opt){
  const controller=new AbortController(),timer=opt && url!=='/api/day-feedback'?null:setTimeout(()=>controller.abort(),opt?45000:15000);
  try{
    const response=await fetch(url,{...opt,signal:controller.signal});
    if(response.status===401){throw Error('登录已过期，请重新打开训练手记登录。')}
    const result=await response.json();if(!response.ok)throw Object.assign(Error(result.error||'读取失败'),{status:response.status});return result;
  }catch(e){
    if(e.name==='AbortError'||e instanceof TypeError)throw Error(url==='/api/day-feedback'?'暂未收到保存确认，填写内容仍在，可再次点保存。':'连接暂时没有响应，请点刷新重试。');
    throw e;
  }finally{clearTimeout(timer)}
}
function showHome(snapshot){data=snapshot;q('#stamp').textContent=data.time+' 读取';msg.textContent='';render()}
async function refresh(){try{await Promise.resolve();showHome(await api('/api/home'))}catch(e){msg.textContent=e.message}}
function start(){
  const today=feedbackToday(),param=new URLSearchParams(location.search).get('feedback');
  const requested=/^\d{4}-\d{2}-\d{2}$/.test(param)&&param<=today?param:null;
  if(q('#offline-shell')){
    data={day:today};
    q('#refresh').onclick=()=>location.replace('/');
    v.onclick=e=>{if(e.target.closest('[data-action="dailyback"]'))location.replace('/')};
    openDay(requested||today);
    return;
  }
  if('serviceWorker' in navigator){
    navigator.serviceWorker.register('/daily-worker.js').catch(()=>{
      if(q('#dailyStatus'))q('#dailyStatus').textContent='当前浏览器无法准备离线页面。';
    });
  }
  const snapshot=q('#initial-data');
  if(!snapshot){refresh();return}
  try{showHome(JSON.parse(snapshot.content.textContent))}catch(e){refresh()}
  snapshot.remove();
  if(requested){openDay(requested);return}
  if(readDailyDraft(today)?.record)openDay(today);
}
function heading(title, note='') {
  return '<div class="heading"><h1>'+esc(title)+'</h1><small>'+esc(note)+'</small></div>';
}
function section(title, note='') {
  return '<div class="section"><h2>'+esc(title)+'</h2><small>'+esc(note)+'</small></div>';
}
function remainingRecovery(record, now=Date.now()){
  if(!record||!Number.isFinite(record.minutes))return '—';
  const end=Date.parse(record.measured_at)+record.minutes*60000;
  if(!Number.isFinite(end))return '—';
  const minutes=Math.ceil((end-now)/60000);
  return minutes<=0?'原估计时间已到':Math.floor(minutes/60)+' 小时 '+minutes%60+' 分';
}
function updateRecoveryClock(){
  const value=q('#recovery-left');
  if(value)value.textContent=remainingRecovery({minutes:Number(value.dataset.minutes),measured_at:value.dataset.measured});
}
setInterval(updateRecoveryClock,30000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)updateRecoveryClock()});
window.addEventListener('pageshow',updateRecoveryClock);

let homePlanDay=null,homePlanWeek=null,homePlanRequest=0,homePlanError='',homeGoalDate=null;
function shortHomeDay(day){return day?.startsWith(data.day.slice(0,4))?day.slice(5):day}
function dateButton(key,label,text){
 return '<button type="button" class="home-date" data-home-date="'+key+'" aria-haspopup="dialog" aria-label="'+esc(label+'日期：'+text)+'">'+esc(text)+'<span aria-hidden="true">⌄</span></button>';
}
function homeHeading(label,key,text,h='h2'){
 return '<div class="home-heading"><'+h+'>'+esc(label)+'</'+h+'>'+dateButton(key,label,text)+'</div>';
}
const homeMeasures=[
 ['sleep','平均睡眠时长','sleep_minutes','sleep_day','recovery/平均睡眠时长'],
 ['hrv','平均单晚HRV','hrv_ms','hrv_day','recovery/平均单晚HRV'],
 ['hr','平均静息心率','resting_hr','hr_day','recovery/平均静息心率'],
 ['ready','平均训练准备度','readiness','ready_day','recovery/训练准备度']
];
function overviewDateContext(){return {today:data.day,first:data.overview.first,last:data.overview.last,cycle:data.cycle}}
function overviewRefresh(){render()}
function overviewRecordRows(key){
 if(key.startsWith('data/'))return data.overview.running.map(r=>[r[0],r[key.endsWith('跑步次数')?2:1]]);
 if(key==='body/体重')return data.overview.weights;
 const sleep=key==='recovery/平均睡眠时长',field=sleep?'sleep_day':'hr_day';
 return data.recoveryHistory.filter(r=>!r[field]||r[field]===r.date).map(r=>[r.date,sleep?r.sleep_minutes:r.resting_hr]);
}
function homeReadingTile(key,label,value,note){
 return '<div class="home-reading"><div class="home-reading-head">'+overviewMetricLabel(key,label)+'</div><strong>'+value+'</strong>'+(note?'<small>'+esc(note)+'</small>':'')+overviewRecordsLink(key)+'</div>';
}
function homeReading(d,spec){
 const [,label,field,dateField,key]=spec,r=overviewScope(key),values=new Map();
 for(const row of d.recoveryHistory||[]){
   const day=row[dateField]||row.date,n=row[field];
   if(r.valid&&day===row.date&&day>=r.from&&day<=r.to&&Number.isFinite(n))values.set(day,n);
 }
 const count=values.size,average=count?[...values.values()].reduce((a,b)=>a+b,0)/count:null;
 const unit={hrv_ms:'ms',resting_hr:'次/分',readiness:'分'}[field];
 const mins=Math.round(average||0),value=average===null?'—':field==='sleep_minutes'?Math.floor(mins/60)+'<span> 小时 </span>'+mins%60+'<span> 分</span>':(field==='hrv_ms'?Number(average.toFixed(1)):Math.round(average))+'<span> '+unit+'</span>';
 const days=r.valid?Math.round((Date.parse(r.to)-Date.parse(r.from))/86400000)+1:0;
 return homeReadingTile(key,label,value,count?'有效 '+count+'/'+days+(field==='sleep_minutes'?' 晚':' 天'):'此范围暂无记录');
}
function homeOverviewTotals(d){
 const cards=[['data/累计跑量','累计跑量'],['data/跑步次数','跑步次数']].map(([key,label],index)=>{
   const r=overviewScope(key),runs=d.overview.running.filter(row=>r.valid&&row[0]>=r.from&&row[0]<=r.to);
   const sum=runs.reduce((total,row)=>total+row[index+1],0),value=!r.valid?'—':(index?sum:Math.round(sum))+'<span> '+(index?'次':'km')+'</span>';
   return homeReadingTile(key,label,value);
 });
 const weightKey='body/体重',r=overviewScope(weightKey),weight=d.overview.weights.filter(row=>r.valid&&row[0]>=r.from&&row[0]<=r.to).at(-1);
 const weightCard=homeReadingTile(weightKey,'最近一次体重',weight?Number(weight[1]).toFixed(2)+'<span> kg</span>':'—',weight?'测于 '+weight[0]:'此范围暂无记录');
 const time=d.recovery?.time;
 const snap=time&&Number.isFinite(time.minutes)?'<div class="home-reading"><small>预计剩余恢复时间</small><strong id="recovery-left" data-minutes="'+esc(time.minutes)+'" data-measured="'+esc(time.measured_at)+'">'+esc(remainingRecovery(time))+'</strong><details><summary>测定记录</summary><small>设备原估计 '+esc(time.minutes)+' 分钟<br>测定 '+esc(time.measured_at)+'<br>读取 '+esc(time.read_at||'未记录')+'</small></details></div>':'';
 function group(id,title,content){
   return '<section class="ov-stat-group"><div class="home-heading"><h2>'+esc(title)+'</h2></div>'+overviewDateRow('group:'+id,title)+'<div class="panel home-readings">'+content+'</div></section>';
 }
 return group('data','跑步记录','<div class="home-two">'+cards.join('')+'</div>')+
        group('recovery','睡眠与恢复','<div class="home-two">'+homeMeasures.map(s=>homeReading(d,s)).join('')+snap+'</div>')+
        group('body','身体测量',weightCard);
}
function todayView(d){
 const day=homePlanDay||d.day;
 const plans=day===d.day?d.plans.filter(x=>x.date===day):homePlanWeek?.weekPlans.filter(x=>x.date===day);
 const hero=plans?.map((x,index)=>{
   const [name,...conditions]=String(x.name||'课表').split(/[；;]/);
   return '<section class="session session-'+index+'"><small>'+esc(sport(x.sport))+'</small><h2>'+esc(name)+'</h2>'+(conditions.length?'<div class="condition">'+esc(conditions.join('；'))+'</div>':'')+(x.detail?'<details><summary>训练说明</summary>'+p(x.detail)+'</details>':'')+'</section>';
 }).join('');
 const title='<div class="home-heading"><h1>训练总览</h1></div>'+overviewDateRow('global','训练总览')+'<small>实绩截至 '+esc(d.overview.last||'暂无归档')+'</small>';
 return title+'<article class="today-run-card" id="home-today-run" aria-label="今日跑步" hidden></article>'+homeHeading(day===d.day?'当天课表':'训练安排','plan',shortHomeDay(day))+'<div class="hero">'+(hero||(plans?'当天没有已归档课表':esc(homePlanError||'正在读取课表…')))+'</div>'+homeOverviewTotals(d);
}
async function choosePlanDay(day){
 const ticket=++homePlanRequest;homePlanDay=day===data.day?null:day;homePlanWeek=null;homePlanError='';
 if(!homePlanDay){render();return}
 const start=homeMonday(day);
 if(start===data.week.start){homePlanWeek=data.week;render();return}
 render();
 try{const w=await api('/api/week/'+start);if(ticket===homePlanRequest)homePlanWeek=w}
 catch(e){if(ticket===homePlanRequest)homePlanError=e.message}render();
}
function homeMonday(day){return offsetDate(day,-((new Date(day+'T12:00:00Z').getUTCDay()+6)%7))}
function homeEditor(key,trigger){
 const week=key==='week',plan=key==='plan',goal=key==='goal',metric=homeMeasures.find(m=>m[0]===key);
 const title=week?'训练日历':plan?'训练安排':goal?'目标评估':metric?.[1]||'最近恢复';
 const box=document.createElement('dialog');box.className='home-date-editor';box.setAttribute('aria-label',title+'日期');
 const single=week||plan;
 const options=goal?[['','最新评估'],...[...new Set((data.goals?.history||[]).map(g=>g.reviewed_on))].sort().reverse().map(d=>[d,d])]:[];
 box.innerHTML='<form><h3>'+esc(title+'日期')+'</h3>'+(!single?'<label>'+(goal?'复核日期':'时间范围')+'<select name="mode">'+options.map(([k,t])=>'<option value="'+esc(k)+'">'+esc(t)+'</option>').join('')+'</select></label>':'')+'<div class="home-inputs"></div><p role="alert"></p><footer><button type="button" data-close>取消</button><button type="submit">应用</button></footer></form>';
 document.body.append(box);const f=box.querySelector('form'),sel=f.elements.mode,inputs=f.querySelector('.home-inputs');
 if(sel)sel.value=homeGoalDate||'';
 function fields(){
   inputs.replaceChildren();if(goal)return;
   const label=document.createElement('label'),input=document.createElement('input');input.type='date';input.required=true;input.name='from';label.textContent=week?'选择该周任意一天':'日期';
   input.value=week?(selectedWeek||data.week.start):(homePlanDay||data.day);label.append(input);inputs.append(label);
 }
 if(sel)sel.onchange=fields;fields();
 if(single){
   const shortcuts=document.createElement('div');shortcuts.className='home-week-shortcuts';
   const moves=week?[['‹ 上周',-7],['本周',0],['下周 ›',7]]:[['今天',0]];
   moves.forEach(([label,delta])=>{const b=document.createElement('button');b.type='button';b.textContent=label;
     b.onclick=()=>{const current=f.elements.from.value||data.day;f.elements.from.value=delta?offsetDate(homeMonday(current),delta):data.day};shortcuts.append(b)});
   inputs.after(shortcuts);
 }
 box.onclose=()=>{box.remove();v.querySelector('[data-home-date="'+key+'"]')?.focus({preventScroll:true})};f.querySelector('[data-close]').onclick=()=>box.close();
 f.onsubmit=e=>{
   e.preventDefault();const values=Object.fromEntries(new FormData(f)),mode=values.mode;
   if(values.to&&values.from>values.to){f.querySelector('[role=alert]').textContent='开始日期不能晚于结束日期';return}
   box.close();
   if(week){switchWeek('pick',homeMonday(values.from));return}
   if(plan){choosePlanDay(values.from);return}
   if(goal)homeGoalDate=mode||null;
   render();
 };
 box.showModal();
}
v.addEventListener('click',e=>{const range=e.target.closest('[data-ov-range]');if(range){openOverviewRange(range);return}const trigger=e.target.closest('[data-home-date]');if(trigger)homeEditor(trigger.dataset.homeDate,trigger)});


function homeGoals(goal){
  if(!goal)return '';
  const tests=goal.tests||{};
  const historical=homeGoalDate&&(goal.history||[]).filter(x=>x.reviewed_on===homeGoalDate).at(-1);
  if(historical)goal={...historical,last_reviewed_on:historical.reviewed_on,actions:[]};
  const time=goalTimeLabel(goal.target_seconds);
  const range=goal.range_percent?.length===2?goal.range_percent.join('%–')+'%':'待评估';
  const renderAction=(item,archived=false)=>'<p><b>'+esc(item.title)+'</b> · '+esc(archived?'已归档':item.status||'待观察')+'<br>'+esc(item.conclusion||'尚待相关证据')+'<br><small>依据截至 '+esc(item.date||'—')+(item.reviewed_at?' · 复核 '+esc(item.reviewed_at.slice(0,10)):'')+'</small></p>'+p(item.next_action||'')+(!archived&&item.next_check_on?'<small>下次复核 '+esc(item.next_check_on)+' · '+esc(item.next_check_label||'')+'</small>':'')+'<details><summary>依据与复核记录</summary>'+p(item.check||'')+p(item.limits||'')+(item.history||[]).slice(0,-1).reverse().map(r=>'<p><small>'+esc(r.date)+' · '+esc(r.status)+'</small><br>'+esc(r.conclusion)+'</p>').join('')+'</details>';
  const actions=goal.actions.map(item=>renderAction(item)).join('')+((goal.archived_actions||[]).length?'<details><summary>已结束的跟踪 · '+goal.archived_actions.length+'项</summary>'+goal.archived_actions.map(item=>renderAction(item,true)).join('')+'</details>':'');
  return homeHeading(historical?'历史目标评估':'目标与行动','goal',shortHomeDay(goal.last_reviewed_on)||'暂无评估')+'<article><b>'+esc([goal.target_event,time].filter(Boolean).join(' · ')||'训练目标')+'</b><p>教练估计达成把握 '+esc(range)+'</p><small>最近评估 '+esc(goal.last_reviewed_on)+'</small>'+goalDecisionView(goal,tests)+(actions?'<details><summary>行动跟踪</summary>'+actions+'</details>':'')+'</article>';
}
function render(){
  if(typeof closeOverviewPicker==='function')closeOverviewPicker();
  if(!data)return;
  document.querySelectorAll('nav button').forEach(b=>{
    if(b.textContent===tab)b.setAttribute('aria-current','page');
    else b.removeAttribute('aria-current');
  });
  if(tab==='今天'){
    if(feedbackDay)dailyView();
    else{
      v.innerHTML=todayView(data)+weekView(data)+homeGoals(data.goals);
      TodayRun.mount(q('#home-today-run'),async run=>{
        if(busy)return;
        tab='训练';editing=null;state.sport='running';state.topic=null;stageRunReturn=null;prReturn=null;
        try{await openArchiveRun(run.id)}
        catch(error){if(state.selected===run.id){state.selected=null;tab='今天';render();msg.textContent=error.message}}
      });
    }
    return;
  }
  if(tab==='训练'){training();return}
  if(tab==='跑步能力'){
    if(state.topic!=='能力'){openTopic('能力').catch(err=>msg.textContent=err.message);return}
    v.innerHTML=abilityView();return;
  }
  v.innerHTML=state.topic?topicView():directory();
}

function form(){let a=selectedRecord?.id===editing?selectedRecord:data.activities.find(x=>x.id===editing);if(!a){editing=null;render();return}let key='draft-'+editing,old=JSON.parse(sessionStorage.getItem(key)||'null'),f=old?.fields||a.fields||{},rev=old?.rev??a.revision;
v.innerHTML='<form><small>'+esc(a.date+' · '+sport(a.sport))+'</small><h2>训练后反馈</h2><label>整次 RPE（0–10 或范围）<input id="rpe"></label><label>不适<textarea id="pain" maxlength="4000"></textarea></label><label>特殊情况<textarea id="note" maxlength="4000"></textarea></label><button>提交反馈</button> <button type="button" id="back">返回</button></form>';q('#rpe').value=f.rpeInput??(f.rpe_range?.join('–')??f.rpe??a.session_rpe??'');q('#pain').value=f.pain||'';q('#note').value=f.note||'';
let rid=old?.rid||crypto.randomUUID();function collect(){return {...a.fields,rpeInput:q('#rpe').value.trim(),pain:q('#pain').value,note:q('#note').value}}
q('form').oninput=()=>{rid=crypto.randomUUID();sessionStorage.setItem(key,JSON.stringify({fields:collect(),rev,rid}))};q('#back').onclick=()=>{editing=null;render()};q('form').onsubmit=async e=>{e.preventDefault();if(busy)return;let fields=collect(),t=fields.rpeInput;delete fields.rpeInput;let range=t.match(/^(\d+(?:\.\d+)?)\s*[-–~至]\s*(\d+(?:\.\d+)?)$/);fields.rpe_range=range?[+range[1],+range[2]]:null;fields.rpe=t&&!range?Number(t):null;if(t&&!range&&!Number.isFinite(fields.rpe)){msg.textContent='RPE 请填写 0–10 或范围，如 7–8';return}
busy=true;let btn=e.target.querySelector('button');btn.disabled=true;msg.textContent='正在提交…';try{let j=await api('/api/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:a.id,expected_revision:rev,request_id:rid,fields})});sessionStorage.removeItem(key);editing=null;selectedRecord=j.record?{...selectedRecord,...j.record}:selectedRecord;await refresh();msg.textContent=j.offline_updated===false?'已归档，离线版发布待补。':'反馈已归档，待教练复核。'}catch(e){msg.textContent=e.message;if(rev!==a.revision&&confirm('其他设备已更新。丢弃本机旧草稿，重新载入这次训练？')){sessionStorage.removeItem(key);await refresh()}}finally{btn.disabled=false;busy=false}}}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{if(busy)return;editing=null;feedbackDay=null;state.topic=null;state.selected=null;tab=b.textContent;render();window.scrollTo(0,0)});q('#refresh').onclick=()=>{if(!busy)refresh()};document.addEventListener('DOMContentLoaded',start);

function button(text,action,active=false){return '<button class="'+(active?'chosen':'')+'" data-action="'+esc(action)+'">'+esc(text)+'</button>'}
