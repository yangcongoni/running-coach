const q=s=>document.querySelector(s),v=q('#view'),msg=q('#msg'),esc=s=>String(s??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),sport=s=>s==='running'?'跑步':s==='strength'?'力量':s;
let data,tab='今天',editing=null,busy=false;
const card=(title,body)=>'<article><h2>'+esc(title)+'</h2>'+body+'</article>',p=s=>'<p>'+esc(s)+'</p>',safe=s=>s==null?'—':s;
async function api(url,opt){
  const controller=new AbortController(),timer=opt?null:setTimeout(()=>controller.abort(),15000);
  try{
    const response=await fetch(url,{...opt,signal:controller.signal});
    if(response.status===401){throw Error('登录已过期，请重新打开训练手记登录。')}
    const result=await response.json();if(!response.ok)throw Error(result.error||'读取失败');return result;
  }catch(e){
    if(e.name==='AbortError'||e instanceof TypeError)throw Error('连接暂时没有响应，请点刷新重试。');
    throw e;
  }finally{clearTimeout(timer)}
}
function showHome(snapshot){data=snapshot;q('#stamp').textContent=data.time+' 读取';msg.textContent='';render()}
async function refresh(){try{await Promise.resolve();showHome(await api('/api/home'))}catch(e){msg.textContent=e.message}}
function start(){
  const snapshot=q('#initial-data');
  if(!snapshot){refresh();return}
  try{showHome(JSON.parse(snapshot.content.textContent))}catch(e){refresh()}
  snapshot.remove();
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
  if(value)value.textContent=remainingRecovery(data?.recovery?.time);
}
setInterval(updateRecoveryClock,30000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)updateRecoveryClock()});
window.addEventListener('pageshow',updateRecoveryClock);
function todayView(d) {
  const today=d.plans.filter(x=>x.date===d.day);
  const hero=today.map((x,index)=>{
    const [name,...conditions]=String(x.name||'课表').split(/[；;]/);
    const notes=conditions.join('；');
    return '<section class="session session-'+index+'"><small>'+esc(sport(x.sport))+'</small><h2>'+esc(name)+'</h2>'+(notes?'<div class="condition">'+esc(notes)+'</div>':'')+(x.detail?'<details><summary>训练说明</summary>'+p(x.detail)+'</details>':'')+'</section>';
  }).join('');
  const r=d.recovery, mins=r.sleep_minutes==null?null:Math.round(r.sleep_minutes);
  const metrics=[['睡眠',mins==null?'—':Math.floor(mins/60)+'<span>时</span>'+mins%60+'<span>分</span>'],['HRV',esc(r.hrv_ms)+'<span>ms</span>'],['静息心率',esc(r.resting_hr)+'<span>次/分</span>']];
  const estimate=r.time;
  const score=r.readiness;
  const readiness='<section><small>训练准备度 · 晨间</small><b>'+(score==null?'—':esc(score)+'<span> / 100</span>')+'</b></section>';
  const timeLabel='<small>恢复时间 · 预计剩余</small><b id="recovery-left">'+remainingRecovery(estimate)+'</b>';
  const clock=estimate?'<details><summary>'+timeLabel+'</summary><small>设备原估计 '+esc(estimate.minutes)+' 分钟<br>测定 '+esc(estimate.measured_at.replace('T',' '))+'<br>读取 '+esc(estimate.read_at?.replace('T',' '))+'</small></details>':'<section>'+timeLabel+'</section>';
  const details='<section class="recovery-pair">'+readiness+clock+'</section>';
  return heading('今天',d.day)+'<div class="hero">'+(hero||'当天没有已归档课表')+'</div>'+section('最近恢复',r.date||'暂无记录')+'<div class="panel metrics">'+metrics.map(([label,value])=>'<div><small>'+label+'</small><strong>'+value+'</strong></div>').join('')+details+'</div>';
}
function homeGoals(goal){
  if(!goal)return '';
  const time=Number.isFinite(goal.target_seconds)?Math.floor(goal.target_seconds/3600)+':'+String(Math.floor(goal.target_seconds/60)%60).padStart(2,'0'):'';
  const range=goal.range_percent?.length===2?goal.range_percent.join('%–')+'%':'待评估';
  const renderAction=(item,archived=false)=>'<p><b>'+esc(item.title)+'</b> · '+esc(archived?'已归档':item.status||'待观察')+'<br>'+esc(item.conclusion||'尚待相关证据')+'<br><small>依据截至 '+esc(item.date||'—')+(item.reviewed_at?' · 复核 '+esc(item.reviewed_at.slice(0,10)):'')+'</small></p>'+p(item.next_action||'')+(!archived&&item.next_check_on?'<small>下次复核 '+esc(item.next_check_on)+' · '+esc(item.next_check_label||'')+'</small>':'')+'<details><summary>依据与复核记录</summary>'+p(item.check||'')+p(item.limits||'')+(item.history||[]).slice(0,-1).reverse().map(r=>'<p><small>'+esc(r.date)+' · '+esc(r.status)+'</small><br>'+esc(r.conclusion)+'</p>').join('')+'</details>';
  const actions=goal.actions.map(item=>renderAction(item)).join('')+((goal.archived_actions||[]).length?'<details><summary>已结束的跟踪 · '+goal.archived_actions.length+'项</summary>'+goal.archived_actions.map(item=>renderAction(item,true)).join('')+'</details>':'');
  const node=goal.next_review_node;
  return section('目标与行动')+'<article><b>'+esc([goal.target_event,time].filter(Boolean).join(' · ')||'训练目标')+'</b><p>教练估计达成把握 '+esc(range)+'</p><details><summary>评估依据与行动跟踪</summary><small>最近评估 '+esc(goal.last_reviewed_on)+'</small>'+p(goal.summary)+(node?.label?p('评估记录中的复核节点 · '+(node.date||'')+' '+node.label):'')+actions+'</details></article>';
}
function render(){
  if(!data)return;
  document.querySelectorAll('nav button').forEach(b=>{
    if(b.textContent===tab)b.setAttribute('aria-current','page');
    else b.removeAttribute('aria-current');
  });
  if(tab==='今天'){if(feedbackDay)dailyView();else v.innerHTML=todayView(data)+weekView(data)+homeGoals(data.goals);return}
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
