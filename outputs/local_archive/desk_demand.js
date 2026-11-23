/* Live desktop data access; the existing overview and detail renderers remain authoritative. */
let deskHomeAt=0,deskSequence=0, deskBulk=null, deskMapTask=null, deskDetailSequence=0;
let deskListFrom='',deskListTo='',deskLapsTask=null;
const deskLightPages=new Set(['总览','跑步记录','归档维护']);
async function deskGet(path,signal){
  const response=await fetch('/api/desk-v3/'+path,{cache:'no-store',signal:signal||AbortSignal.timeout(45000)});
  if(!response.ok)throw Error('读取失败 '+response.status);
  return response.json();
}
function deskMap(){
  if(!deskMapTask)deskMapTask=deskGet('map').then(rows=>{footprintRegions=rows}).catch(e=>{deskMapTask=null;throw e});
  return deskMapTask;
}
async function deskInitial(signal,progress){
  const params=new URLSearchParams(location.search);
  if((D&&!D._desk_lite)||!deskLightPages.has(page)||params.has('review')||params.has('stage')||location.hash==='#kb'){
    const [data]=await Promise.all([fetchArchive(signal,progress),deskMap()]);return data;
  }
  const data=await deskGet('home',signal);
  for(const [id,date,km,seconds,elapsed,activityId,startTimeLocal,apiStart,duration,activityName] of data.career){
    data.sessions.push({id,date,sport:'running'});
    data.running_details.push({session_id:id,distance_km:km,timer_seconds:seconds,elapsed_seconds:elapsed,
      details_json:JSON.stringify({activityId,activityName,startTimeLocal,api_list_summary:{startTimeLocal:apiStart},duration})});
  }
  delete data.career;deskHomeAt=Date.now();
  return data;
}
function deskError(host,retry,error){
  const p=document.createElement('p'),button=document.createElement('button');
  p.textContent='暂时未能读取数据。'+(error?.message||'');
  button.type='button';button.textContent='重试';button.onclick=retry;
  host.replaceChildren(p,button);
}
async function deskFull(target,seq){
  const host=$('#view');
  host.innerHTML='<p role="status">正在读取分析所需的历史档案…</p>';
  try{
    if(!deskBulk)deskBulk=Promise.all([fetchArchive(AbortSignal.timeout(180000)),deskMap()])
      .then(([data])=>data).finally(()=>{deskBulk=null});
    const data=await deskBulk;
    if(seq!==deskSequence)return;
    D=data;navigate(target);
  }catch(e){if(seq===deskSequence)deskError(host,()=>deskFull(target,++deskSequence),e)}
}
function deskGuard(p){
  const seq=++deskSequence;
  deskDetailSequence++;
  if(D?._desk_lite&&p==='总览'&&page!=='总览'&&Date.now()-deskHomeAt>60000){
    deskHomeAt=Date.now();
    deskInitial(AbortSignal.timeout(45000)).then(data=>{if(seq===deskSequence){D=data;navigate(p)}}).catch(e=>{if(seq===deskSequence){deskHomeAt=0;deskError($('#view'),()=>navigate(p),e)}});
    return true;
  }
  if(!D?._desk_lite||deskLightPages.has(p))return false;
  deskFull(p,seq);return true;
}
function deskPaged(){
  if(!D?._desk_lite||!['跑步记录','归档维护'].includes(page))return false;
  const host=$('#view'),list=page==='跑步记录';
  const filter=$('#time-filter');if(host.contains(filter))host.before(filter);filter.hidden=true;
  document.body.classList.remove('overview-theme');
  if(list){
    host.innerHTML='<section class="panel"><div class="design-heading"><h2>跑步记录</h2><button data-advanced>完整筛选与对比</button></div><div class="design-filter"><label>从 <input type="date" data-from></label> <label>至 <input type="date" data-to></label></div><div data-paged></div></section>';
    host.querySelector('[data-advanced]').onclick=()=>deskFull(page,++deskSequence);
  }else{
    renderDataSection();
    const box=Array.from(host.querySelectorAll('details')).find(el=>el.querySelector('summary')?.textContent==='修改历史');
    if(!box)return true;
    box.innerHTML='<summary>修改历史</summary><div data-paged></div>';
    box.ontoggle=()=>{if(box.open&&!box.dataset.started){box.dataset.started='1';read(null)}};
  }
  const box=host.querySelector('[data-paged]'),stack=[];
  let cursor=null,tick=0;
  async function read(next){
    cursor=next;
    const token=++tick,q=new URLSearchParams(next||{});
    if(list&&deskListFrom)q.set('from',deskListFrom);
    if(list&&deskListTo)q.set('to',deskListTo);
    box.textContent='正在读取…';
    try{
      const data=await deskGet((list?'runs':'revisions')+'?'+q);
      if(!box.isConnected||token!==tick)return;
      const items=data.items;
      if(list){const base=D;try{D={...D,metadata:data.metadata,analyses:data.analyses};for(const row of items){row.label=executionType(row);row.status=activityCompletion(row).status}}finally{D=base}}
      const cells=list?['日期','训练','课型','距离','用时','平均心率','完成状态']:['时间','对象','原因'];
      const body=items.map(x=>list?'<tr><td>'+esc(x.date)+'</td><td><button data-open="'+Number(x.id)+'">'+esc(x.name||x.type||'跑步')+'</button></td><td>'+esc(x.label)+'</td><td>'+esc(x.distance_km==null?'—':fmt(x.distance_km,2)+' km')+'</td><td>'+esc(x.timer_seconds==null?'—':durationText(x.timer_seconds))+'</td><td>'+esc(x.average_hr??'—')+'</td><td>'+esc(x.status)+'</td></tr>':'<tr><td>'+esc(x.created_at)+'</td><td><button data-rev="'+Number(x.id)+'">'+esc(x.entity)+' · '+esc(x.entity_key)+'</button></td><td>'+esc(x.reason)+'</td></tr>');
      box.innerHTML=(items.length?table(cells,body):'<p>当前范围没有记录。</p>')+'<p><button data-prev>上一页</button> <button data-next>下一页</button></p>';
      const prev=box.querySelector('[data-prev]'),more=box.querySelector('[data-next]');
      prev.disabled=!stack.length;more.disabled=!data.more;
      prev.onclick=()=>read(stack.pop());
      more.onclick=()=>{stack.push(cursor);const x=items.at(-1);read(list?{before:x.date,id:x.id}:{before:x.id})};
      box.querySelectorAll('[data-open]').forEach(el=>el.onclick=()=>deskRun({id:Number(el.dataset.open)},'data'));
      box.querySelectorAll('[data-rev]').forEach(el=>el.onclick=async()=>{
        try{const row=await deskGet('revision/'+el.dataset.rev);if(el.isConnected)showDetail('修订记录','<p>'+esc(row.reason)+'</p>'+['previous_json','replacement_json'].map((k,i)=>row[k]?'<details><summary>'+['修订前','修订后'][i]+'</summary><pre>'+esc(row[k])+'</pre></details>':'').join(''))}
        catch(e){if(el.isConnected)deskError(box,()=>read(cursor),e)}
      });
    }catch(e){if(box.isConnected&&tick===token)deskError(box,()=>read(next),e)}
  }
  if(list){
    const from=host.querySelector('[data-from]'),to=host.querySelector('[data-to]');
    from.value=deskListFrom;to.value=deskListTo;
    from.onchange=to.onchange=()=>{deskListFrom=from.value;deskListTo=to.value;stack.length=0;read(null)};
    read(null);
  }
  return true;
}
async function deskRun(row,entry){
  const id=Number(row.id),token=++deskDetailSequence,base=D;
  const dialog=$('#detail'),body=$('#detailBody');
  if(!dialog.open)showDetail('训练详情','<p role="status">正在读取本次活动…</p>');
  else body.textContent='正在读取本次活动…';
  try{
    const detail=await deskGet('run/'+id);
    if(token!==deskDetailSequence||!dialog.open||D!==base)return;
    const keys={sessions:'id',running_details:'session_id',metadata:'key',daily_recovery:'date',daily_submissions:'date',analyses:'id'};
    for(const [table,key] of Object.entries(keys)){
      const rows=detail[table],ids=new Set(rows.map(r=>r[key]));
      D[table]=D[table].filter(r=>!ids.has(r[key])).concat(rows);
    }
    const current=runs().find(r=>r.id===id);
    if(!current)throw Error('未找到训练记录');
    current._deskReady=true;
    deskLapsTask=null;D.running_laps=detail.calculation_laps;
    try{runDetails(current,entry)}finally{delete current._deskReady}
    const work=body.querySelector('[data-desk-work]');
    if(work)work.onclick=()=>deskLaps(current,work);
  }catch(e){if(token===deskDetailSequence&&dialog.open)deskError(body,()=>deskRun(row,entry),e)}
}
async function deskLaps(run,work){
  const pane=work||$('#run-pane-1'),seq=deskDetailSequence,base=D;
  if(!pane||pane.dataset.loaded)return;
  if(!work)pane.textContent='正在读取分段…';
  try{
    if(!deskLapsTask)deskLapsTask=deskGet('laps/'+run.id).catch(e=>{if(seq===deskDetailSequence)deskLapsTask=null;throw e});
    const {items}=await deskLapsTask;
    if(seq!==deskDetailSequence||D!==base||!pane.isConnected)return;
    D.running_laps=items;
    if(work){const section=document.createElement('section');section.innerHTML=workReview(deskWorkData(run)||{})||'<p>本次没有可显示的工作段复盘。</p>';work.replaceWith(section)}
    else {pane.innerHTML=runLapSection(run,items);pane.dataset.loaded='1'}
  }catch(e){if(seq===deskDetailSequence&&pane.isConnected){
    if(work){work.textContent='工作段读取失败，点此重试';return}
    deskError(pane,()=>deskLaps(run),e)
  }}
}
