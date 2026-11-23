/* Shared homepage card. The host owns navigation and supplies offline snapshots. */
const TodayRun = (() => {
 let host, openRun, snapshot, current, selected, request, fallback, checked = 0;
 const dayNow = () => new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'});
 const valid = n => Number.isFinite(n) && n > 0;
 function clock(value){
   if(!valid(value))return '—';
   const s=Math.round(value),m=Math.floor(s/60),z=n=>String(n).padStart(2,'0');
   return (m>=60?Math.floor(m/60)+':'+z(m%60):m)+':'+z(s%60);
 }
 function stat(label,value,unit=''){
   return '<div><dt>'+label+'</dt><dd>'+esc(value)+(unit&&value!=='—'?' <small>'+unit+'</small>':'')+'</dd></div>';
 }
 function paint(){
   if(!host?.isConnected)return;
   const rows=current?.day===dayNow()?current.items:[];
   const run=rows.find(r=>r.id===selected)||rows[0];
   host.hidden=!run;
   if(!run){host.replaceChildren();selected=null;return}
   const distance=stat('距离',valid(run.km)?run.km.toFixed(2):'—','km');
   const choices=rows.length>1?'<select aria-label="选择当天跑步">'+rows.map((r,i)=>'<option value="'+r.id+'"'+(r.id===run.id?' selected':'')+'>'+esc((r.start?.slice(11,16)||'第 '+(rows.length-i)+' 次')+' · '+r.label)+'</option>').join('')+'</select>':'';
   const g=run.groups||[];
   host.innerHTML='<div class="tr-head"><h2>今日跑步</h2>'+(choices||'<span class="tr-type">'+esc(run.label)+'</span>')+'<time>'+esc(current.day.slice(5).replace('-',' 月 ')+' 日')+'</time></div>'
     +'<dl class="tr-stats">'+distance+stat('用时',clock(run.seconds))+stat('平均配速',clock(valid(run.km)&&valid(run.seconds)?run.seconds/run.km:null),'/km')+stat('平均心率',valid(run.hr)?Math.round(run.hr):'—','次/分')+stat('平均步频',valid(run.cadence)?Math.round(run.cadence):'—','步/分')+'</dl>'
     +(g.length?'<div class="tr-groups">'+g.map((x,i)=>'<span>第 '+(i+1)+' 组 <b>'+clock(valid(x.km)&&valid(x.sec)?x.sec/x.km:null)+'</b> /km · '+(valid(x.hr)?Math.round(x.hr)+' 次/分':'—')+'</span>').join('')+'</div>':'')
     +'<div class="tr-notes">'+(run.verdict?'<p><b>跑后点评</b> '+esc(run.verdict)+'</p>':'<p class="tr-pending">跑步已同步，教练点评待归档。</p>')+(run.feedback&&!String(run.verdict||'').includes(run.feedback)?'<p><b>跑后反馈</b> '+esc(run.feedback)+'</p>':'')+(run.next_action?'<p><b>下一步</b> '+esc(run.next_action)+'</p>':'')+'</div><button class="tr-open" type="button">查看本次复盘 <span aria-hidden="true">›</span></button>';
   if(host.closest('.design-home'))host.querySelector('.tr-head').append(host.querySelector('.tr-open'));
   const select=host.querySelector('select');
   if(select)select.onchange=()=>{selected=Number(select.value);paint();host.querySelector('select')?.focus()};
   host.querySelector('.tr-open').onclick=()=>openRun(run);
 }
 function accept(data){
   if(!data||!Array.isArray(data.items))return;
   if(current?.day!==data.day)selected=null;
   current=data;paint();
 }
 async function update(force=false){
   if(!host?.isConnected||document.hidden)return;
   if(current&&current.day!==dayNow()&&!host.hidden)paint();
   if(snapshot||request||(!force&&Date.now()-checked<55000))return;
   checked=Date.now();
   const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),15000);
   request=true;
   try{
     const response=await fetch('/api/today-runs',{cache:'no-store',signal:controller.signal});
     let data;
     if(response.ok)data=await response.json();
     else if(response.status===404&&fallback)data=await fallback(controller.signal);
     if(data&&!snapshot&&JSON.stringify(data)!==JSON.stringify(current))accept(data);
   }catch{}finally{request=false;clearTimeout(timeout)}
 }
 function mount(node,details,offline,legacyRead){
   if(!node)return;
   host=node;openRun=details;snapshot=offline;fallback=legacyRead;
   if(offline)accept(offline);else{paint();update()}
 }
 setInterval(()=>update(),15000);
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)update()});
 return {mount};
})();
