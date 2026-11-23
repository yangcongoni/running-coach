const overviewPeriods=[['thisWeek','本周'],['thisMonth','本月'],['thisYear','今年'],['7','最近 7 天'],['28','最近 4 周'],['cycle','当前训练周期'],['all','全部历史'],['month','按月选择'],['year','按年选择'],['custom','自定义日期']];
const overviewPeriodLabels=new Map(overviewPeriods);
const overviewSelections=new Map();
const overviewStorage='training-overview-dates-v2';
function ovDay(value){
 if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value))return false;
 const d=new Date(value+'T12:00:00Z');return Number.isFinite(d.getTime())&&d.toISOString().slice(0,10)===value;
}
function ovFields(choice){
 if(choice.mode==='year'){
   if(![choice.yearFrom,choice.yearTo].every(y=>/^\d{4}$/.test(y)&&+y>=1900&&+y<=2100))return [];
   return [choice.yearFrom+'-01-01',choice.yearTo+'-12-31'];
 }
 if(choice.mode==='month'){
   if(![choice.monthFrom,choice.monthTo].every(m=>/^\d{4}-(0[1-9]|1[0-2])$/.test(m)))return [];
   const [y,m]=choice.monthTo.split('-').map(Number);
   return [choice.monthFrom+'-01',new Date(Date.UTC(y,m,0)).toISOString().slice(0,10)];
 }
 return [choice.from,choice.to];
}
function ovValid(choice){
 if(!choice||!overviewPeriodLabels.has(choice.mode))return false;
 if(!['month','year','custom'].includes(choice.mode))return true;
 const [a,b]=ovFields(choice);return ovDay(a)&&ovDay(b)&&a<=b;
}
try{for(const [key,value] of JSON.parse(localStorage.getItem(overviewStorage)||'[]'))if(typeof key==='string'&&ovValid(value))overviewSelections.set(key,value)}catch{}
function overviewChoice(key){return overviewSelections.get(key)||{mode:key==='global'?'thisWeek':'follow'}}
function overviewBounds(choice){
 const {today,first,last,cycle}=overviewDateContext();
 const d=new Date(today+'T12:00:00Z');
 let from,to=today;
 switch(choice.mode){
 case 'thisWeek':case '7':case '28':
   d.setUTCDate(d.getUTCDate()-(choice.mode==='thisWeek'?(d.getUTCDay()+6)%7:choice.mode==='7'?6:27));from=d.toISOString().slice(0,10);break;
 case 'thisMonth':from=today.slice(0,7)+'-01';break;
 case 'thisYear':from=today.slice(0,4)+'-01-01';break;
 case 'cycle':[from,to]=cycle;break;
 case 'all':from=first;to=last;break;
 default:[from,to]=ovFields(choice);
 }
 return {from,to,valid:ovDay(from)&&ovDay(to)&&from<=to};
}
function overviewScope(key){
 const own=overviewChoice(key);
 const parent=key.includes('/')?'group:'+key.split('/')[0]:'global';
 const inherited=overviewChoice(parent);
 const choice=own.mode!=='follow'?own:inherited.mode!=='follow'?inherited:overviewChoice('global');
 const requested=overviewBounds(choice),{today,last}=overviewDateContext();
 const to=[requested.to,today,last].filter(Boolean).sort()[0];
 return {...requested,to,valid:requested.valid&&requested.from<=to,mode:choice.mode,requested,independent:key.includes('/')&&own.mode!=='follow'};
}
function overviewCaption(key){
 const r=overviewScope(key),mode=r.mode,{from:a,to:b}=r.requested;
 const prefix=r.independent?'独立 · ':'',name=overviewPeriodLabels.get(mode);
 if(['thisWeek','thisMonth','thisYear'].includes(mode))return prefix+name;
 if(!r.requested.valid)return prefix+name+' · 暂无日期';
 const full=d=>d.replaceAll('-','/'),sameYear=a.slice(0,4)===b.slice(0,4);
 if(mode==='month'){const x=full(a.slice(0,7)),y=full(b.slice(0,7));return prefix+x+(x===y?'':'–'+y)}
 if(mode==='year'){const x=a.slice(0,4),y=b.slice(0,4);return prefix+x+(x===y?'':'–'+y)+' 年'}
 const rolling=mode==='7'||mode==='28',left=rolling&&sameYear?full(a.slice(5)):full(a);
 const right=mode==='all'||!sameYear?full(b):full(b.slice(5));
 const title=!key.includes('/')&&mode!=='custom'?name+' · ':'';
 return prefix+title+left+(a===b?'':'–'+right);
}
function overviewDateRow(key,title){
 const global=key==='global',label=global?'总览时间':'统计时间';
 const follows=!global&&overviewChoice(key).mode==='follow';
 const caption=follows?'跟随总览 · '+overviewCaption('global'):overviewCaption(key);
 return '<div class="ov-date-row"><small>'+label+'</small><button type="button" class="ov-range" data-ov-range="'+esc(key)+'" aria-label="'+esc(title+'，'+label+'，'+caption)+'" aria-haspopup="dialog" aria-expanded="false">'+esc(caption)+'<span aria-hidden="true"></span></button></div>';
}
function overviewMetricLabel(key,title){
 const note=overviewChoice(key).mode==='follow'?'':'<small class="ov-own-date">'+esc(overviewCaption(key))+'</small>';
 return '<span class="ov-metric-name" data-ov-metric="'+esc(key)+'">'+esc(title)+'</span>'+note;
}
let closeOverviewPicker;
function openOverviewRange(trigger){
 const anchor=trigger.dataset.ovRange,wasOpen=trigger.getAttribute('aria-expanded')==='true';
 closeOverviewPicker?.();
 if(wasOpen)return;
 const global=anchor==='global';
 let key=anchor;
 const popup=document.createElement('div'),events=new AbortController(),signal=events.signal;
 popup.className='ov-picker';popup.id='overview-date-options';popup.setAttribute('role','dialog');popup.setAttribute('aria-label',trigger.getAttribute('aria-label'));
 document.body.append(popup);trigger.setAttribute('aria-expanded','true');trigger.setAttribute('aria-controls',popup.id);
 function close(focus=false){
   events.abort();popup.remove();trigger.setAttribute('aria-expanded','false');trigger.removeAttribute('aria-controls');closeOverviewPicker=null;
   if(focus)trigger.focus({preventScroll:true});
 }
 closeOverviewPicker=close;
 function position(){
   if(!trigger.isConnected){close();return}
   const r=trigger.getBoundingClientRect(),w=document.documentElement.clientWidth,h=innerHeight;
   const below=h-r.bottom-12,above=r.top-12,up=popup.scrollHeight>below&&above>below;
   popup.style.maxHeight=Math.max(80,up?above:below)+'px';
   popup.style.left=Math.max(6,Math.min(r.left,w-popup.offsetWidth-6))+'px';
   popup.style.top=(up?Math.max(6,r.top-5-popup.offsetHeight):Math.max(6,r.bottom+5))+'px';
 }
 function apply(draft){
   if(draft.mode==='follow')overviewSelections.delete(key);
   else overviewSelections.set(key,draft);
   try{localStorage.setItem(overviewStorage,JSON.stringify([...overviewSelections]))}catch{}
   close();overviewRefresh();
   document.querySelector('[data-ov-range="'+CSS.escape(anchor)+'"]')?.focus({preventScroll:true});
 }
 function menuButton(label,action){
   const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=action;popup.append(b);return b;
 }
 function metrics(){
   popup.replaceChildren();
   const back=menuButton('‹ 分区时间',()=>{key=anchor;list()});
   const section=trigger.closest('.overview-module,.ov-stat-group');
   for(const node of section.querySelectorAll('[data-ov-metric]')){
     const metricKey=node.dataset.ovMetric;
     const button=menuButton(node.textContent,()=>{key=metricKey;list()});
     const status=document.createElement('small');
     status.textContent=overviewChoice(metricKey).mode==='follow'?'跟随分区':overviewCaption(metricKey);
     button.append(status);button.dataset.metric=metricKey;
   }
   position();back.focus({preventScroll:true});
 }
 function list(focus=true){
   const metric=key!==anchor,saved=overviewChoice(key);
   const inherited=metric?'跟随分区 · '+overviewCaption(anchor):'跟随总览 · '+overviewCaption('global');
   const options=global?overviewPeriods:[['follow',inherited],...overviewPeriods];
   popup.replaceChildren();
   if(metric){
     menuButton('‹ 单独设置指标',metrics);
     const heading=document.createElement('strong');heading.className='ov-menu-title';
     heading.textContent=trigger.closest('.overview-module,.ov-stat-group').querySelector('[data-ov-metric="'+CSS.escape(key)+'"]').textContent;
     popup.append(heading);
   }
   for(const [mode,label] of options){
     const editor=['month','year','custom'].includes(mode),selected=mode===saved.mode;
     const b=document.createElement('button');b.type='button';b.dataset.mode=mode;b.textContent=label;
     b.setAttribute('aria-pressed',String(selected));
     if(mode==='month'||mode==='default'||mode==='thisWeek'&&!global)b.classList.add('ov-divider');
     const mark=document.createElement('span');mark.setAttribute('aria-hidden','true');mark.textContent=selected?'✓':editor?'›':'';b.append(mark);
     b.onclick=()=>editor?edit(mode):apply({mode});popup.append(b);
   }
   if(!global&&!metric){
     const manage=menuButton('单独设置指标 ›',metrics);manage.dataset.manageMetrics='';manage.className='ov-divider';
   }
   position();if(focus)(popup.querySelector('[aria-pressed=true]')||popup.firstElementChild).focus({preventScroll:true});
 }
 function edit(mode){
   const range=overviewScope(key).requested,saved=overviewChoice(key);
   popup.innerHTML='<form><button type="button" class="ov-back">‹ 返回</button><strong>'+esc(overviewPeriodLabels.get(mode))+'</strong><div class="ov-inputs"></div><p role="alert"></p><button type="submit">应用</button></form>';
   popup.querySelector('.ov-back').onclick=()=>list();
   const form=popup.querySelector('form');
   for(const side of ['from','to']){
     const label=document.createElement('label'),input=document.createElement('input');
     label.textContent=side==='from'?'开始':'结束';input.required=true;
     input.type={month:'month',year:'number',custom:'date'}[mode];
     input.name=mode==='custom'?side:mode+(side==='from'?'From':'To');
     const day=range.valid?range[side]:overviewDateContext().today;
     input.value=saved.mode===mode&&saved[input.name]||day.slice(0,mode==='year'?4:mode==='month'?7:10);
     if(mode==='year'){input.min='1900';input.max='2100'}
     label.append(input);form.querySelector('.ov-inputs').append(label);
   }
   form.onsubmit=e=>{
     e.preventDefault();const draft={mode,...Object.fromEntries(new FormData(form))};
     if(!ovValid(draft)){form.querySelector('[role=alert]').textContent='开始日期不能晚于结束日期';position();return}
     apply(draft);
   };
   position();form.querySelector('input').focus({preventScroll:true});
 }
 popup.style.minWidth=Math.min(Math.max(216,trigger.offsetWidth),innerWidth-16)+'px';
 document.addEventListener('pointerdown',e=>{if(!popup.contains(e.target)&&!trigger.contains(e.target))close()},{capture:true,signal});
 document.addEventListener('focusin',e=>{if(!popup.contains(e.target)&&!trigger.contains(e.target))close()},{signal});
 popup.onkeydown=e=>{
   if(e.key==='Escape'){e.preventDefault();close(true);return}
   if(!popup.querySelector('form')&&['ArrowDown','ArrowUp','Home','End'].includes(e.key)){
     e.preventDefault();const items=[...popup.querySelectorAll('button')],i=items.indexOf(document.activeElement);
     const n=e.key==='Home'?0:e.key==='End'?items.length-1:(i+(e.key==='ArrowUp'?-1:1)+items.length)%items.length;
     items[n].focus();
   }
 };
 window.addEventListener('resize',position,{signal});window.addEventListener('scroll',e=>{if(!popup.contains(e.target))position()},{capture:true,signal});
 list();
}
const overviewRecordKeys=['recovery/平均睡眠时长','recovery/平均静息心率','body/体重'];
function overviewRecordsLink(key){
 return overviewRecordKeys.includes(key)?'<button type="button" class="ov-record-link" data-ov-records="'+esc(key)+'">查看记录 ›</button>':'';
}
function openOverviewRecords(trigger){
 const key=trigger.dataset.ovRecords,r=overviewScope(key);
 const rows=overviewRecordRows(key).filter(([d,n])=>r.valid&&d>=r.from&&d<=r.to&&Number.isFinite(n)).sort((a,b)=>b[0].localeCompare(a[0]));
 const dlg=document.createElement('dialog');dlg.className='ov-records';dlg.setAttribute('aria-label',key.split('/')[1]+'记录');
 const name=key.split('/')[1],index=overviewRecordKeys.indexOf(key);
 const display=n=>[Math.floor(Math.round(n)/60)+' 小时 '+Math.round(n)%60+' 分',n+' 次/分',n.toFixed(2)+' kg'][index];
 dlg.innerHTML='<header><b>'+esc(name)+'</b><button type="button" aria-label="关闭">×</button></header><p>'+esc(overviewCaption(key))+'</p>'+(rows.length?'<table><thead><tr><th>日期</th><th>'+esc(['睡眠时长','静息心率','体重'][index])+'</th></tr></thead><tbody>'+rows.map(([d,n])=>'<tr><td>'+esc(d)+'</td><td>'+esc(display(n))+'</td></tr>').join('')+'</tbody></table>':'<p>此范围暂无记录</p>');
 dlg.querySelector('button').onclick=()=>dlg.close();dlg.onclose=()=>{dlg.remove();trigger.focus({preventScroll:true})};
 document.body.append(dlg);dlg.showModal();
}
document.addEventListener('click',e=>{const b=e.target.closest('[data-ov-records]');if(b)openOverviewRecords(b)});
