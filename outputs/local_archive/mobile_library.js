const libraryViews={'纪录':prLibrary,'恢复':sleepLibrary,'负荷':loadLibrary,'知识库':bookLibrary};
const libFilters=Object.fromEntries(['纪录','恢复','负荷'].map(key=>[key,{range:key==='纪录'?'全部':'最近4周'}]));
let prType=null;
const nightCache=new Map();
function fold(title,body){return '<details><summary>'+esc(title)+'</summary>'+body+'</details>'}
function rangePanel(topic,first,metrics=null){
 const settings=libFilters[topic];
 const range=settings.range==='全部'?[first||data.day,data.day]:specBounds(settings);
 const metricMenu=metrics?trainingFilter('趋势指标','library-metric',metrics.map(([key,label])=>[key,label]),settings.metric||metrics[0][0]):'';
 const control='<div class="spec-filters">'+trainingFilter('时间范围','library-range',['最近4周','自然月','年','全部','自定义','训练周期'],settings.range)+metricMenu+dateInputs(settings)+'</div>';
 return {control:control.replaceAll('data-spec=','data-library='),range,inside:d=>d&&d>=range[0]&&d<=range[1]&&d<=data.day};
}
function prLibrary(pr){
 const {inside,control}=rangePanel('纪录',pr.history.map(r=>r.date).sort()[0]);
 const result=r=>!r?'—':r.pr_type===7?kmText(r.distance_km):Number.isFinite(r.seconds)?secsText(r.seconds).replace(/^0:/,'').replace(/^0(\d:)/,'$1'):'—';
 const sorted=pr.history.slice().sort((a,b)=>b.date.localeCompare(a.date)||a.rank-b.rank);
 const cards=pr.categories.map(category=>{
   const id=category.pr_type,current=pr.current.find(r=>r.pr_type===id||id===6&&r.km===42.195);
   const history=sorted.filter(r=>r.pr_type===id),filtered=history.filter(r=>inside(r.date));
   const open=prType===id;
   const entry='<button class="pr-tile" data-pr="'+id+'" aria-expanded="'+open+'"><small>'+esc(category.label)+'</small><b>'+esc(result(current))+'</b><small>'+esc(current?.date||'暂无官方纪录')+'</small><em>历史 PB · '+filtered.length+' 条 '+(open?'▴':'▾')+'</em></button>';
   if(!open)return entry;
   const rows=filtered.map(r=>{
     const prev=history.find(x=>x.date<r.date);
     const delta=!prev?'首条已保存纪录':id===7?(r.distance_km>prev.distance_km?'增加 '+kmText(r.distance_km-prev.distance_km):'—'):(Number.isFinite(prev.seconds)&&Number.isFinite(r.seconds)&&prev.seconds>r.seconds?'快 '+Math.round(prev.seconds-r.seconds)+' 秒':'—');
     const link=(r.session_id?button('查看这次训练','record:'+r.session_id):'')+button('查看年度报告','yearlink:'+r.date.slice(0,4))+(r.activity_id?'<a href="https://connect.garmin.cn/app/activity/'+encodeURIComponent(r.activity_id)+'" target="_blank" rel="noopener">'+esc(r.activity_name||'关联活动')+'</a>':'');
     return '<p data-pb-date="'+esc(r.date)+'"><b>'+esc(result(r))+'</b> · '+esc(r.date)+(current?.date===r.date&&String(current.activity_id)===String(r.activity_id)?' · 当前最佳':'')+'<br><small>'+esc(delta)+(prev?'（对比 '+esc(prev.date)+'）':'')+'</small><br>'+link+'</p>';
   }).join('');
   return entry+'<section class="pr-history"><b>'+esc(category.label)+' · 历史 PB</b>'+(rows||p('所选范围没有已归档的刷新记录。'))+'</section>';
 }).join('');
 return heading('个人纪录')+control+'<small>当前最佳按全部时间展示 · 核对 '+esc(pr.verified?.slice(0,10))+'</small><div class="pr-grid">'+cards+'</div>';
}
const sleepMetrics=[['sleep_minutes','睡眠时长','小时'],['sleep_score','睡眠评分','分'],['hrv_ms','单晚 HRV','ms'],['seven_day_hrv_ms','HRV 7 天平均','ms'],['resting_hr','静息心率','bpm']];
const loadMetrics=[['acute_load','短期负荷',''],['chronic_load','长期负荷',''],['load_ratio','负荷比','']];
function trend(rows,key,label,unit,scale=1,band=null){
 const points=rows.slice().sort((a,b)=>a.date.localeCompare(b.date)).map((r,i,all)=>({x:Date.parse(r.date),y:Number.isFinite(r[key])?r[key]/scale:null,label:r.date,breakBefore:i>0&&offsetDate(all[i-1].date,1)!==r.date}));
 return specPlot([{name:label,points}],{title:label+' '+unit,band,format:v=>Number(v.toFixed(scale===60||key==='load_ratio'?2:0)).toString()});
}
function datedDetails(title,rows,description,content){
 const entries=rows.map(r=>'<details class="health-day"><summary><time>'+esc(r.date)+'</time><span>'+esc(description(r))+'</span></summary>'+content(r)+'</details>').join('');
 return '<details class="spec-details"><summary>'+esc(title)+' · '+rows.length+' 天</summary>'+(entries||p('所选范围暂无记录。'))+'</details>';
}
function coverage(rows,key,range){
 return '<small class="coverage">'+esc(range.join(' — '))+' · 有效 '+rows.filter(r=>Number.isFinite(r[key])).length+' 天</small>';
}
function smallTiles(tiles){return '<div class="library-tiles">'+tiles.map(([name,value,day])=>'<section><small>'+esc(name)+'</small><b>'+esc(value)+'</b><small>'+esc(day||'')+'</small></section>').join('')+'</div>'}
function sleepLibrary(all){
 const sleepKey=libFilters['恢复'].metric||sleepMetrics[0][0];
 const {inside,control,range}=rangePanel('恢复',all.at(-1)?.date,sleepMetrics);
 const selected=all.filter(r=>inside(r.date)), latest=key=>all.find(r=>r[key]!=null);
 const tiles=sleepMetrics.map(([key,label,unit])=>{const r=latest(key);return [label,r?key==='sleep_minutes'?secsText(r[key]*60):metric(r[key],unit):'—',r?.[{sleep_minutes:'sleep_data_date',sleep_score:'sleep_data_date',hrv_ms:'hrv_data_date',seven_day_hrv_ms:'hrv_data_date',resting_hr:'resting_hr_data_date'}[key]]||r?.date]});
 const morning=all.find(r=>Number.isFinite(r.morning?.score)),clock=data.recovery.time;
 tiles.push(['晨间训练准备度',metric(morning?.morning.score,'/ 100'),morning?.date]);
 const now=clock?'<details><summary>恢复时间 · 预计剩余 <b id="recovery-left">'+remainingRecovery(clock)+'</b></summary>'+p('设备原估计 '+clock.minutes+' 分钟 · 测定 '+clock.measured_at+' · 读取 '+(clock.read_at||'—'))+'</details>':'';
 const selectedMetric=sleepMetrics.find(r=>r[0]===sleepKey);
 const report=r=>p('入睡 '+(r.bedtime_local||'—')+' · 起床 '+(r.wake_time_local||'—'))+p('深睡 / 浅睡 / REM / 清醒（分钟）　'+[r.deep_sleep_minutes,r.light_sleep_minutes,r.rem_sleep_minutes,r.awake_minutes].map(x=>x??'—').join(' / '))+p('HRV 最高 5 分钟 '+metric(r.hrv_highest_5min_ms,'ms')+' · 基准 '+(r.hrv_baseline_low??'—')+'–'+(r.hrv_baseline_high??'—')+' ms · '+(r.seven_day_hrv_status||'—'))+p('疲劳 '+(r.fatigue_0_10??'—')+' · 酸痛 '+(r.soreness_0_10??'—')+' · '+(r.pain_note||'无反馈记录'));
 const vitals=selected.filter(r=>r.night);
 const night=datedDetails('夜间呼吸与血氧',vitals,()=> '呼吸与血氧',r=>p('呼吸 平均 / 最低 / 最高（次/分）　'+['average','lowest','highest'].map(k=>r.night.respiration[k]??'—').join(' / '))+p('血氧 平均 / 最低 / 最高（%）　'+['average','lowest','highest'].map(k=>r.night.spo2[k]??'—').join(' / '))+'<button data-night="'+r.date+'">查看夜间曲线</button><div data-night-host></div>');
 const daily=datedDetails('逐日恢复记录',selected,r=>'睡眠 '+(r.sleep_minutes==null?'—':secsText(r.sleep_minutes*60))+' · HRV '+metric(r.hrv_ms,'ms'),report);
 const chart=trend(selected,...selectedMetric,sleepKey==='sleep_minutes'?60:1);
 const recovery='<article>'+now+(morning?fold('准备度评分依据',p('睡眠评分 '+(morning.morning.sleepScore??'—')+' · 7 天 HRV '+metric(morning.morning.hrvWeeklyAverage,'ms'))+p(['sleepScore','hrv','recoveryTime','acwr','sleepHistory','stressHistory'].map((k,i)=>['睡眠','HRV','恢复时间','负荷比','近期睡眠','近期压力'][i]+' '+metric(morning.morning[k+'FactorPercent'],'%')).join(' · '))):'')+'</article>';
 return heading('睡眠与恢复')+smallTiles(tiles)+recovery+sleepSchedule(all)+'<article class="ability-special health-trend">'+control+coverage(selected,sleepKey,range)+chart+daily+night+'</article>';
}
function loadLibrary(panel){
 const loadKey=libFilters['负荷'].metric||loadMetrics[0][0];
 const rows=panel.records.filter(r=>r.date<=data.day),{control,inside,range}=rangePanel('负荷',rows[0]?.date,loadMetrics);
 const selected=rows.filter(r=>inside(r.date)),last=k=>rows.filter(r=>r[k]!=null).at(-1);
 const tiles=[['training_status','训练状态'],...loadMetrics].map(([key,label])=>[label,last(key)?.[key]??'—',last(key)?.date]);
 const latestFocus=last('focus');
 const focus=f=>p((f.from||'—')+' — '+(f.to||'—')+' · '+(f.status||'—'))+['low_aerobic','high_aerobic','anaerobic'].map((k,i)=>p(['低强度有氧','高强度有氧','无氧'][i]+'　'+(Number.isFinite(f[k])?Math.round(f[k]):'—')+' · 最佳 '+(f.optimal_ranges?.[k]?.min??'—')+'–'+(f.optimal_ranges?.[k]?.max??'—'))).join('');
 const reviews=panel.reviews.filter(r=>r.date<=data.day),latest=reviews.find(r=>['daily','special'].includes(r.kind)),weekly=reviews.find(r=>r.kind==='weekly');
 const body=r=>p(r.summary)+p(r.next_action)+p('分析 '+r.date+' · 负荷数据 '+(r.monitor_date||'—'))+(r.sections||[]).map(s=>p(s.title+' · '+s.text)).join('')+(r.limitations||[]).map(p).join('');
 const coach=latest?card('最近教练简评',p(latest.title)+p(latest.display_next_action||latest.next_action)+fold('评估依据 · '+latest.date,body(latest))+(weekly?fold('最近一周完整分析 · '+weekly.date,body(weekly)):'')+fold('历史分析',reviews.filter(r=>r!==latest&&r!==weekly).map(r=>fold(r.date+' · '+r.title,body(r))).join(''))):'';
 const ref=selected.filter(r=>r.bounds?.chronic>0&&Number.isFinite(r.bounds.min)&&Number.isFinite(r.bounds.max)).at(-1);
 const chart=trend(selected,...loadMetrics.find(r=>r[0]===loadKey),1,loadKey==='load_ratio'&&ref?[ref.bounds.min/ref.bounds.chronic,ref.bounds.max/ref.bounds.chronic]:null)+(loadKey==='load_ratio'&&ref?p('最佳范围参考 '+(ref.bounds.min/ref.bounds.chronic).toFixed(2)+'–'+(ref.bounds.max/ref.bounds.chronic).toFixed(2)+' · '+ref.date):'');
 const history=selected.slice().reverse();
 const daily=specialtyDetails('训练状态与逐日负荷',history.map(r=>[r.date,(r.training_status||'—')+' · 短期 '+(r.acute_load??'—')+' · 长期 '+(r.chronic_load??'—')+' · 负荷比 '+(r.load_ratio??'—')]));
 const focusHistory=datedDetails('负荷重点历史',history.filter(r=>r.focus),r=>r.focus.status||'负荷重点',r=>focus(r.focus));
 return heading('训练状态与负荷')+smallTiles(tiles)+'<article class="ability-special health-trend">'+control+coverage(selected,loadKey,range)+chart+daily+focusHistory+'</article>'+coach+(latestFocus?card('滚动负荷重点',focus(latestFocus.focus)+'<small>快照 '+esc(latestFocus.date)+'</small>'):'');
}
function bookLibrary(book){
 const chapter=x=>fold(x.number+' '+x.title,p(x.lead)+p(x.lesson?.definition||x.concept)+(x.lesson?.sections||[]).map(s=>'<h3>'+esc(s.title)+'</h3>'+(s.paragraphs||[]).map(p).join('')).join('')+(x.points||[]).map(pt=>p(pt.text)).join('')+(x.steps||[]).filter(s=>typeof s==='string').map(p).join(''));
 return heading('跑步知识库')+section('目录')+'<div class="book-toc">'+book.modules.map(m=>'<article>'+fold(m.number+' '+m.title,p(m.description)+m.chapters.map(id=>book.chapters.find(x=>x.id===id)).filter(Boolean).map(chapter).join(''))+'</article>').join('')+'<article>'+fold('训练方法导读',book.guides.map(g=>fold(g.title,p(g.brief)+(g.steps||[]).map(p).join('')+p(g.check))).join(''))+'</article><article>'+fold('资料与方法索引',Object.values(book.sources).map(s=>fold(s.title||s.name,p(s.scope)+(s.url&&/^https?:/.test(s.url)?'<a href="'+esc(s.url)+'" target="_blank" rel="noopener">查看原文 ↗</a>':''))).join(''))+'</article></div>';
}
v.addEventListener('change',event=>{
 const key=event.target.dataset.library;
 if(!key||!event.target.value||!event.target.validity.valid)return;
 if(key==='year'&&!/^(19|20)[0-9]{2}$/.test(event.target.value))return;
 libFilters[state.topic][key]=event.target.value;render();
});
v.addEventListener('click',async event=>{
 const el=event.target.closest('[data-pr],[data-night]');if(!el)return;
 if(el.dataset.night){
   const host=el.parentNode.querySelector('[data-night-host]'),day=el.dataset.night;
   try{
     if(host.innerHTML&&el.textContent==='收起夜间曲线'){host.replaceChildren();el.textContent='查看夜间曲线';return}
     if(!nightCache.has(day))nightCache.set(day,await api('/api/topic/'+encodeURIComponent('夜间采样_'+day)));
     const n=nightCache.get(day);
     host.innerHTML=['respiration','spo2'].map((key,i)=>specPlot([{name:i?'血氧 %':'呼吸 次/分',points:(n[key]?.points||[]).filter(pt=>pt[1]>0).map(([x,y])=>({x,y,label:new Date(x).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai'})}))}],{title:i?'夜间血氧':'夜间呼吸',format:v=>v.toFixed(0),xf:x=>new Date(x).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit'})})).join('');
     el.textContent='收起夜间曲线';
   }catch(e){host.textContent=e.message}
   return;
 }
 if(el.dataset.pr)prType=prType===Number(el.dataset.pr)?null:Number(el.dataset.pr);
 render();
});
