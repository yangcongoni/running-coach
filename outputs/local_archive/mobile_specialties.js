const specialties=['最大摄氧量','乳酸阈值','有氧效率','长跑表现','跑姿指标'];
let activeSpecialty='乳酸阈值';
const specState={
 '最大摄氧量':{range:'最近4周',anchor:''},
 '有氧效率':{range:'最近4周',scene:'户外',type:'轻松跑',pace:'全部配速',view:'关系图',metric:'平均心率'},
 '长跑表现':{range:'最近4周',scene:'户外',minutes:'75',older:'',newer:''},
 '跑姿指标':{range:'最近4周',scene:'户外',type:'轻松跑',pace:'5:30–6:00',metric:'步频',grain:'单次'}
};
const paceBands={'全部配速':[0,9999],'快于5:00':[0,300],'5:00–5:30':[300,330],'5:30–6:00':[330,360],'6:00–6:30':[360,390],'6:30–7:00':[390,420],'7:00及以上':[420,9999]};
const formFields=[['步频','步/分',0],['步幅','m',2],['垂直振幅','cm',1],['垂直振幅比','%',1],['触地时间','ms',0]];
const ranges=['最近4周','最近6个月','最近1年','训练周期'];
function monday(day){const n=new Date(day).getUTCDay();return offsetDate(day,-((n+6)%7))}
function monthShift(day,n){const d=new Date(day.slice(0,7)+'-01T12:00:00Z');d.setUTCMonth(d.getUTCMonth()+n);return d.toISOString().slice(0,10)}
function specBounds(config,vo2=false){
 const day=vo2?(config.anchor||data.day):data.day;
 if(config.range==='自然月'){const month=config.month||day.slice(0,7);return [month+'-01',offsetDate(monthShift(month+'-01',1),-1)]}
 if(config.range==='年'){const year=config.year||day.slice(0,4);return [year+'-01-01',year+'-12-31']}
 if(config.range==='全部')return [topicRows.firstDay||day,day];
 if(config.range==='自定义')return [config.from||offsetDate(day,-27),config.to||day];
 if(config.range==='训练周期')return cycleBounds();
 if(config.range==='最近4周')return vo2?[offsetDate(monday(day),-21),offsetDate(monday(day),6)]:[offsetDate(day,-27),day];
 return [monthShift(day,config.range==='最近6个月'?-5:-11),vo2?offsetDate(monthShift(day,1),-1):day];
}
function specSelect(label,key,options,config){
 return trainingFilter(label,'spec-'+key,options,config[key]);
}
const sceneOf=r=>r.raw.activityType?.typeKey==='treadmill_running'||/跑步机/.test(r.name||'')?'跑步机':classifyRun(r).tags.includes('越野跑')?'越野':'户外';
const runPace=r=>r.distance_km>0&&r.timer_seconds>0?r.timer_seconds/r.distance_km:null;
const secsText=s=>Number.isFinite(s)?[Math.floor(s/3600),Math.floor(s/60)%60,Math.floor(s)%60].map((n,i)=>i?String(n).padStart(2,'0'):n).join(':'):'—';
function weighted(rows,i){
 const valid=rows.filter(r=>positive(r.form?.[i])!==null&&r.timer_seconds>0);
 const weight=valid.reduce((s,r)=>s+r.timer_seconds,0);
 return weight?valid.reduce((s,r)=>s+r.form[i]*r.timer_seconds,0)/weight:null;
}
function specPlot(series,{title,format,xf=x=>new Date(x).toISOString().slice(5,10),inverse=false,scatter=false,band=null}){
 const all=series.flatMap(s=>s.points).filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y));
 if(!all.length)return p('所选范围暂无有效记录。');
 const xs=all.map(p=>p.x),ys=all.map(p=>p.y);
 if(band)ys.push(...band);
 const xmin=Math.min(...xs),xmax=Math.max(...xs),min=Math.min(...ys),max=Math.max(...ys);
 const posX=x=>xmin===xmax?171:47+251*(x-xmin)/(xmax-xmin);
 const posY=y=>max===min?54:inverse?25+61*(y-min)/(max-min):86-61*(y-min)/(max-min);
 const colors=['#80273e','#318e82','#aa761e','#4b72ad','#72519d','#666'];
 const bodies=series.map((s,i)=>{
   const color=colors[i%colors.length];let path='',prev=null;
   const dots=s.points.map(point=>{
     if(!Number.isFinite(point.y)){prev=null;return ''}
     const x=posX(point.x),y=posY(point.y);
     path+=(prev&&!point.breakBefore?'L':'M')+x+' '+y+' ';prev=point;
     const label=s.name+' · '+point.label+' · '+format(point.y);
     return '<g tabindex="0" role="button" data-spec-point="'+esc(label)+'" aria-label="'+esc(label)+'"><circle cx="'+x+'" cy="'+y+'" r="9" fill="transparent"/><circle cx="'+x+'" cy="'+y+'" r="3.5" fill="'+color+'"/></g>';
   }).join('');
   return (scatter?'':'<path fill="none" stroke="'+color+'" stroke-width="1.6" d="'+path+'"/>')+dots;
 }).join('');
 const label=(x,y,t,anchor)=>'<text x="'+x+'" y="'+y+'" text-anchor="'+anchor+'">'+esc(t)+'</text>';
 return '<div class="spec-chart"><b>'+esc(title)+'</b><svg viewBox="0 0 312 115" width="100%" role="group" aria-label="'+esc(title)+'">'+(band?'<rect x="47" width="251" y="'+posY(band[1])+'" height="'+(posY(band[0])-posY(band[1]))+'" fill="#e2efe4"/>':'')+bodies+label(42,28,format(inverse?min:max),'end')+(max!==min?label(42,88,format(inverse?max:min),'end'):'')+label(47,110,xf(xmin),'start')+(xmin!==xmax?label(298,110,xf(xmax),'end'):'')+'</svg><small data-spec-readout aria-live="polite">'+series.map((s,i)=>'<span style="color:'+colors[i%colors.length]+'">● '+esc(s.name)+'</span>').join('　')+'</small></div>';
}
function specialtyDetails(title,rows){
 const body=rows.map(([date,value])=>'<li><time>'+esc(date)+'</time><span>'+esc(value)+'</span></li>').join('');
 return '<details class="spec-details"><summary>'+esc(title)+' · '+rows.length+' 条</summary>'+(body?'<ul>'+body+'</ul>':'<small>所选范围暂无记录。</small>')+'</details>';
}
function vo2Special(panel,c){
 const [start,end]=specBounds(c,true),weekly=['最近4周','训练周期'].includes(c.range);
 const label='最大摄氧量 · '+(weekly?'周汇总':'月汇总');
 const rows=panel.rows.filter(r=>r[1]===label&&r[0]>=start&&r[0]<=end).reverse();
 const points=rows.map((r,i)=>({x:Date.parse(r[0]),y:parseFloat(r[2]),label:r[0],breakBefore:i>0&&(weekly?monday(r[0])>offsetDate(monday(rows[i-1][0]),7):r[0].slice(0,7)>monthShift(rows[i-1][0],1).slice(0,7))}));
 return '<div class="spec-filters">'+specSelect('时间范围','range',ranges,c)+(c.range==='训练周期'?'':'<label>定位日期<input type="date" data-spec="anchor" max="'+data.day+'" value="'+(c.anchor||data.day)+'"></label>')+'</div>'+(c.range==='训练周期'?'':'<div class="cal-nav">'+button('‹ 上一时段','vo2move:-1')+button('回到最新','vo2move:0')+button('下一时段 ›','vo2move:1')+'</div>')+'<small>'+start+' — '+end+'</small>'+specPlot([{name:label,points}],{title:'最大摄氧量 · ml/kg/min',format:v=>v.toFixed(1)})+specialtyDetails('汇总明细',rows.slice().reverse().map(r=>[r[0],r[2]]));
}
const specCache=new Map();
function dateInputs(c){
 const input=(label,key,type,value)=>'<label>'+label+'<input data-spec="'+key+'" type="'+type+'" value="'+esc(value)+'"></label>';
 if(c.range==='自然月')return input('选择月份','month','month',c.month||data.day.slice(0,7));
 if(c.range==='年')return input('选择年份','year','number',c.year||data.day.slice(0,4));
 if(c.range==='自定义')return input('开始日期','from','date',c.from||offsetDate(data.day,-27))+input('结束日期','to','date',c.to||data.day);
 return '';
}
function specializedView(panel,threshold){
 const nav='<div class="spec-tabs">'+specialties.map(k=>button(k,'special:'+k,k===activeSpecialty)).join('')+'</div>';
 if(activeSpecialty==='乳酸阈值')return nav+threshold;
 const c=specState[activeSpecialty];
 if(activeSpecialty==='最大摄氧量')return nav+'<article class="ability-special">'+vo2Special(panel,c)+'</article>';
 const [start,end]=specBounds(c);
 const key=start+'_'+end;
 let all=panel.recent;
 if(start>end)return nav+p('开始日期应早于或等于结束日期。')+dateInputs(c);
 if(start<panel.start){
   let entry=specCache.get(key);
   if(!entry){
     entry={};specCache.set(key,entry);
     api('/api/topic/'+encodeURIComponent('能力区间_'+key)).then(rows=>{entry.rows=rows}).catch(e=>{entry.error=e.message}).finally(()=>render());
   }
   all=entry.rows;
 }
 const scene=c.scene, isForm=activeSpecialty==='跑姿指标',isLong=activeSpecialty==='长跑表现';
 let controls=specSelect('时间范围','range',['最近4周','自然月','年','全部','自定义','训练周期'],c)+dateInputs(c)+specSelect('场景','scene',isForm||isLong?['户外','跑步机','越野']:['户外','跑步机'],c);
 if(isLong)controls+=specSelect('最低时长','minutes',[['75','75 分钟'],['90','90 分钟'],['120','120 分钟']],c);
 else controls+=specSelect('类型','type',isForm?['全部','轻松跑','长距离轻松跑（LSD）','节奏/阈值跑','间歇/重复跑','比赛','越野跑','待分类']:['轻松跑','长距离轻松跑（LSD）'],c)+specSelect('配速 /km','pace',isForm?Object.keys(paceBands):['全部配速','5:00–5:30','5:30–6:00','6:00–6:30'],c);
 if(isForm)controls+=specSelect('跑姿指标','metric',formFields.map(f=>f[0]),c)+specSelect('汇总方式','grain',['单次','按周'],c);
 if(!isForm&&!isLong){
   controls+=specSelect('图表','view',['关系图','时间趋势'],c);
   if(c.view==='时间趋势')controls+=specSelect('趋势指标','metric',['平均心率','平均配速'],c);
 }
 const header=nav+'<article class="ability-special"><div class="spec-filters">'+controls+'</div><small>'+start+' — '+end+'</small>';
 if(!all)return header+(specCache.get(key)?.error?p(specCache.get(key).error)+button('重试','specretry:'+key):p('正在读取所选范围…'))+'</article>';
 const rows=all.filter(r=>r.date>=start&&r.date<=end&&r.date<=data.day&&sceneOf(r)===scene).reverse();
 const matches=rows.filter(r=>{
   if(isLong)return r.timer_seconds>=60*Number(c.minutes);
   if(c.type!=='全部'&&executionType(r)!==c.type)return false;
   const [lo,hi]=paceBands[c.pace],pace=runPace(r);
   return (c.pace==='全部配速'&&isForm||pace!==null&&pace>=lo&&pace<hi)&&(isForm||r.average_hr>0);
 });
 const detailRows=matches.slice().reverse().map(r=>{
   const values=[kmText(r.distance_km),secsText(r.timer_seconds),runPace(r)?paceLabel(Math.round(runPace(r)))+' /km':'—',metric(r.average_hr,'bpm')];
   if(isForm){
     const index=formFields.findIndex(f=>f[0]===c.metric);
     values.push(c.metric+' '+metric(positive(r.form?.[index]),formFields[index][1],formFields[index][2]));
   }
   return [r.date,values.join(' · ')];
 });
 const details=specialtyDetails('活动明细',detailRows);
 if(isLong)return header+longCompare(matches,c)+details+'</article>';
 if(isForm)return header+formTrend(matches,c)+details+'</article>';
 const relation=c.view==='关系图',hr=relation||c.metric==='平均心率';
 const points=matches.map(r=>({x:relation?runPace(r):Date.parse(r.date),y:hr?r.average_hr:runPace(r),label:r.date+' · '+paceLabel(Math.round(runPace(r)))+' /km'}));
 const span=(values,show)=>values.length?show(Math.min(...values))+'–'+show(Math.max(...values)):'—';
 const summary=p(matches.length+' 次有效 · '+span(matches.map(runPace),v=>paceLabel(Math.round(v)))+' /km · '+span(matches.map(r=>r.average_hr),Math.round)+' bpm');
 return header+summary+specPlot([{name:c.type,points}],{title:relation?'配速（分/km）与心率（bpm）':c.metric,format:hr?v=>String(Math.round(v)):v=>paceLabel(Math.round(v)),xf:relation?v=>paceLabel(Math.round(v)):undefined,inverse:!hr,scatter:true})+details+'</article>';
}
function formTrend(rows,c){
 const i=formFields.findIndex(f=>f[0]===c.metric),[,unit,digits]=formFields[i];
 const format=v=>v.toFixed(digits);
 const types=[...new Set(rows.map(executionType))];
 const series=types.map(type=>{
   const group=rows.filter(r=>executionType(r)===type);
   if(c.grain==='单次')return {name:type,points:group.map(r=>({x:Date.parse(r.date),y:positive(r.form?.[i]),label:r.date}))};
   const weeks=new Map();
   for(const r of group){const key=monday(r.date);if(!weeks.has(key))weeks.set(key,[]);weeks.get(key).push(r)}
   let previous='';
   return {name:type,points:[...weeks].map(([day,items])=>{const point={x:Date.parse(day),y:weighted(items,i),label:day+' 起一周',breakBefore:previous&&day!==offsetDate(previous,7)};previous=day;return point})};
 });
 return p('时长加权均值　'+metric(weighted(rows,i),unit,digits))+specPlot(series,{title:c.metric+' · '+unit,format});
}
function longCompare(rows,c){
 if(!rows.length)return p('所选范围暂无长跑记录。');
 const options=rows.slice().reverse().map(r=>[String(r.id),r.date+' · '+kmText(r.distance_km)]);
 const newer=rows.find(r=>String(r.id)===c.newer)||rows.at(-1);
 const older=rows.find(r=>String(r.id)===c.older&&r.id!==newer.id)||rows.filter(r=>r.id!==newer.id).at(-1);
 const selected=older?[older,newer]:[newer];
 const pace=v=>positive(v)?paceLabel(Math.round(v)):'—';
 const line=(name,get)=>'<tr><th scope="row">'+name+'</th>'+selected.map(r=>'<td>'+esc(get(r))+'</td>').join('')+'</tr>';
 const table=lines=>'<table class="long-values"><thead><tr><th scope="col">指标</th>'+selected.map(r=>'<th scope="col">'+esc(r.date)+'</th>').join('')+'</tr></thead><tbody>'+lines+'</tbody></table>';
 const far=Math.max(...rows.map(r=>r.distance_km||0)),duration=Math.max(...rows.map(r=>r.timer_seconds));
 const stats=[['符合条件',rows.length+' 次'],['最长距离',kmText(far||null)],['最长计时',secsText(duration)]].map(([k,v])=>'<div><small>'+k+'</small><b>'+esc(v)+'</b></div>').join('');
 const picks='<div class="spec-filters">'+(older?specSelect('对比记录','older',options.filter(x=>x[0]!==String(newer.id)),{older:String(older.id)}):'')+specSelect('当前记录','newer',options,{newer:String(newer.id)})+'</div>';
 const core=line('距离 · km',r=>kmText(r.distance_km).replace(' km',''))+line('计时',r=>secsText(r.timer_seconds))+line('配速 · /km',r=>pace(runPace(r)))+line('心率 · bpm',r=>metric(r.average_hr,'').trim());
 const extra=line('全程耗时',r=>secsText(r.elapsed))+line('RPE',r=>r.rpe??'—')+['front','rear'].map((key,i)=>{const label=i?'后段':'前段';return line(label+'配速 · /km',r=>pace(r.segments?.[key]?.pace_seconds_per_km))+line(label+'心率 · bpm',r=>metric(r.segments?.[key]?.average_hr,'').trim())}).join('');
 return '<div class="long-stats">'+stats+'</div><h3 class="long-heading">'+(older?'两次长跑对比':'本次长跑')+'</h3>'+picks+table(core)+'<details><summary>分段与补充指标</summary>'+table(extra)+'</details>'+specPlot([{name:'长跑距离',points:rows.filter(r=>r.distance_km>0).map(r=>({x:Date.parse(r.date),y:r.distance_km,label:r.date}))}],{title:'长跑距离 · km',format:v=>v.toFixed(2),scatter:true});
}
v.addEventListener('change',event=>{
 const key=event.target.dataset.spec;
 if(!key)return;
 const c=specState[activeSpecialty];if(!event.target.value||!event.target.validity.valid)return;
 if(key==='year'&&!/^(19|20)[0-9]{2}$/.test(event.target.value))return;
 c[key]=event.target.value;
 if(key==='newer'&&c.newer===c.older)c.older='';
 render();
});
v.addEventListener('click',event=>{
 const point=event.target.closest('[data-spec-point]');
 if(point)point.closest('.spec-chart').querySelector('[data-spec-readout]').textContent=point.dataset.specPoint;
});
v.addEventListener('keydown',event=>{
 if(event.target.matches('[data-spec-point]')&&['Enter',' '].includes(event.key)){event.preventDefault();event.target.dispatchEvent(new MouseEvent('click',{bubbles:true}))}
});
