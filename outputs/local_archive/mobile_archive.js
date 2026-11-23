function classifyRun(r){
 const a=r.raw,n=a.activityName||'',tags=[],why=[];let verified=false;
 if(a.activityType?.typeKey==='treadmill_running'||/跑步机/.test(n))return {tags:['轻松跑'],why:['用户规则：跑步机统一归入轻松跑；场景仍保留跑步机'],verified:true};
 if(a.classification_override?.type){const map={'长距离轻松跑（LSD）':'长距离轻松跑（LSD）','轻松跑':'轻松跑','节奏/阈值跑':'乳酸阈值跑','间歇/重复跑':'间歇跑','比赛':'比赛','越野跑':'越野跑'},tag=map[a.classification_override.type];if(tag)return {tags:[tag],why:['用户确认分类：'+a.classification_override.type+'；优先于自动识别'],verified:true}}
 if(a.activityType?.typeKey==='trail_running'||/越野/.test(n)){tags.push('越野跑');why.push('原始运动类型或活动名称：越野');}
 if(a.eventType?.typeKey==='race'||/比赛|精英赛|马拉松|竞赛/.test(n)){tags.push('比赛');why.push('原始赛事标签或活动名称；不代表全力程度已核实');}
 if(data.fieldActivity!=null && String(a.activityId)===String(data.fieldActivity)){tags.push('乳酸阈值跑');why.push('实跑参考活动已归档，结合分段和用户反馈核对');verified=true;}
 else if(/阈值|乳酸/.test(n)||a.trainingEffectLabel==='LACTATE_THRESHOLD'){tags.push('乳酸阈值跑');why.push('名称或佳明主要训练效果提示阈值，未逐段核实');}
 if(/间歇|重复/.test(n)||(a.splitSummaries||[]).some(s=>s.splitType==='INTERVAL_REST'&&s.noOfSplits>1)){tags.push('间歇跑');why.push('名称或多组工作/恢复结构；含短重复训练，不等同于丹尼尔斯I');}
 if(!tags.some(x=>['比赛','乳酸阈值跑','间歇跑'].includes(x))){if(/轻松|基础|恢复|基准|长距离|长跑/.test(n)||['AEROBIC_BASE','RECOVERY'].includes(a.trainingEffectLabel)){tags.push('轻松跑');why.push('名称或佳明基础/恢复训练标签');}else if(/节奏|目标配速|渐速/.test(n)||a.trainingEffectLabel==='TEMPO'){tags.push('节奏/目标配速跑');why.push('名称或TEMPO标签');}}
 if(!tags.length){const hr=positive(r.average_hr??a.averageHR),cutoff=Number(meta('running_type_classification_rules').heart_rate_fallback?.cutoff_bpm)||160;if(hr!==null){tags.push(hr<cutoff?'轻松跑':'节奏/目标配速跑');why.push('按平均心率推测：'+hr+' bpm，暂定分界'+cutoff+' bpm；低于分界归轻松跑，达到分界归节奏跑。仅用于补齐分类，不证明乳酸阈值或真实训练目的。')}else{tags.push('待分类');why.push('缺少有效平均心率，无法按心率归类，保留待分类')}}
 return {tags,why,verified};
}
function positive(v){return v!=null&&Number.isFinite(Number(v))&&Number(v)>0?Number(v):null}
function executionType(r){const tags=classifyRun(r).tags,n=r.raw.activityName||'';if(tags.includes('越野跑'))return '越野跑';if(tags.includes('比赛'))return '比赛';if(tags.includes('长距离轻松跑（LSD）'))return '长距离轻松跑（LSD）';if(/基准/.test(n))return '轻松跑';if(tags.includes('乳酸阈值跑')||tags.includes('节奏/目标配速跑'))return '节奏/阈值跑';if(tags.includes('间歇跑'))return '间歇/重复跑';if(/长距离|长跑/.test(n)||tags.includes('轻松跑'))return '轻松跑';return '待分类'}
function cycleBounds(){
 if(data.cycle?.length===2 && data.cycle.every(Boolean))return data.cycle;
 return [data.day,data.day];
}
const state={sport:'running',ranges:{running:'全部历史',strength:'训练周期'},get range(){return this.ranges[this.sport]},set range(value){this.ranges[this.sport]=value},types:{running:'全部类型',strength:'全部类型'},page:1,selected:null,topic:null,sub:'分段',report:'全部'};
let indexData=null,indexPromise=null,selectedRecord=null,topicRows=null,curveData=null,loadNumber=0;
const topicGroups={'训练记录':{'跑步年度报告':'年度'},'计划与复盘':{'当前与历史课表':'计划','复盘报告':'报告'},'能力与恢复':{'个人纪录':'纪录','睡眠与恢复':'恢复','拉伸记录':'拉伸','训练状态与负荷':'负荷','体重与体脂':'体测'},'资料与来源':{'跑步知识库':'知识库','同步状态':'同步','数据来源':'来源'}};
const meta=()=>indexData?.rules||topicRows?.rules||{};
let periodCustomStart='',periodCustomEnd='';
function rangeFor(rows){
 if(/^\d{4}$/.test(state.range))return [state.range+'-01-01',state.range+'-12-31'];
 if(state.range==='自定义')return [periodCustomStart||rows.at(-1)?.date,periodCustomEnd||data.day];
 const day=data.day,d=new Date(day+'T12:00:00Z');d.setUTCDate(d.getUTCDate()-27);
 return {'训练周期':cycleBounds(),'最近 4 周':[d.toISOString().slice(0,10),day],'今年':[day.slice(0,4)+'-01-01',day],'全部历史':[rows.at(-1)?.date,rows[0]?.date]}[state.range];
}
function trainingFilter(label,key,options,current){
 const pairs=options.map(item=>Array.isArray(item)?item:[item,item]);
 const selected=pairs.find(([value])=>String(value)===String(current))?.[1]??current;
 const choices=pairs.map(([value,name])=>'<button type="button" data-filter="'+key+'" value="'+esc(value)+'" aria-pressed="'+(String(value)===String(current))+'">'+esc(name)+'</button>').join('');
 return '<details class="training-filter" data-menu="'+key+'"><summary><small>'+esc(label)+'</small><b>'+esc(selected)+'</b></summary><div class="filter-menu">'+choices+'</div></details>';
}
v.addEventListener('toggle',event=>{
 const opened=event.target;
 if(opened.matches('.training-filter[open]'))v.querySelectorAll('.training-filter[open]').forEach(item=>{if(item!==opened)item.open=false});
},true);
document.addEventListener('click',event=>{
 const choice=event.target.closest('button[data-filter]');
 document.querySelectorAll('.training-filter[open]').forEach(item=>{if(!item.contains(event.target))item.open=false});
 if(!choice)return;
 const key=choice.dataset.filter;
 if(key==='annual-year'){annualYear=choice.value;render()}else if(key.startsWith('route-')){routeFilter[key.slice(6)]=choice.value;render()}else if(key.startsWith('spec-')){
   const field=key.slice(5), config=specState[activeSpecialty];
   config[field]=choice.value;
   if(field==='newer'&&config.newer===config.older)config.older='';
   render();
 }else if(key.startsWith('library-')){
   libFilters[state.topic][key.slice(8)]=choice.value;
   render();
 }else if(key==='threshold-scope'){
   abilityScope=choice.value;
   render();
 }else{
   if(key==='sport')state.sport=choice.value;
   if(key==='range')state.range=choice.value;
   if(key==='type')state.types[state.sport]=choice.value;
   state.page=1;
   training();
 }
 v.querySelector('[data-menu="'+key+'"] summary')?.focus({preventScroll:true});
});
document.addEventListener('keydown',event=>{
 if(event.key!=='Escape')return;
 const item=v.querySelector('.training-filter[open]');
 if(item){item.open=false;item.querySelector('summary').focus({preventScroll:true})}
});
let footprintLoad;
let footprintReady = false;
let footprintError = false;
let selectedProvince = '';

function loadFootprint() {
  if (footprintReady || footprintLoad || footprintError) return;
  const script = document.createElement('script');
  script.src = '/footprint.js';
  footprintLoad = script;
  script.onload = () => {
    footprintReady = typeof fpRegion === 'function';
    footprintError = !footprintReady;
    if (tab === '训练' && !state.selected) training();
  };
  script.onerror = () => {
    footprintError = true;
    if (tab === '训练' && !state.selected) training();
  };
  document.head.append(script);
}

function mobileFootprint(rows) {
  if (!footprintReady) {
    loadFootprint();
    const note = footprintError ? button('重新读取地图', 'footprint-retry') : p('正在读取地图…');
    return '<article class="phone-footprint"><h3>跑步地图</h3>' + note + '</article>';
  }
  const counts = new Map();
  for (const row of rows) {
    const code = fpRegion(row.raw);
    counts.set(code, (counts.get(code) || 0) + 1);
  }
  const places = footprintRegions.filter(region => region[1]);
  const visited = places.filter(([code]) => counts.has(code)).sort((a,b) => counts.get(b[0]) - counts.get(a[0]));
  const paths = fpShapes();
  const geometry = footprintRegions.map(([code, name], index) => {
    const action = name ? ' data-province="' + code + '"' : '';
    const selected = code === selectedProvince ? ' class="active-province"' : '';
    return '<path' + action + selected + ' fill="' + (counts.has(code) ? '#bbd86a' : '#48514f') + '" fill-rule="evenodd" d="' + paths[index] + '"><title>' + esc(name || '南海诸岛') + '</title></path>';
  }).join('');
  const choices = [['', '全部省份'], ...visited];
  if (selectedProvince && !visited.some(region => region[0] === selectedProvince)) {
    const selected = places.find(region => region[0] === selectedProvince);
    if (selected) choices.push(selected);
  }
  const chips = choices.map(([code, name]) => '<button type="button" data-province="' + code + '" aria-pressed="' + (code === selectedProvince) + '">' + esc(name) + (code ? ' ' + (counts.get(code) || 0) : '') + '</button>').join('');
  const located = rows.length - (counts.get('missing') || 0) - (counts.get('outside') || 0);
  return '<article class="phone-footprint"><div class="phone-footprint-head"><h3>跑步地图</h3><small><b>' + visited.length + '</b> / ' + places.length + ' 个省级地区</small></div>'
    + '<svg viewBox="0 0 650 438" role="img" aria-label="跑步省份分布"><svg width="650" height="433" viewBox="-5 -4 650 433"><g id="phone-provinces">' + geometry + '</g></svg>'
    + '<svg x="549" y="273" width="91" height="138" viewBox="323 343 210 253"><rect x="322" y="342" width="212" height="255" fill="#202725"/><use href="#phone-provinces"/></svg><rect x="549" y="273" width="91" height="138" fill="none" stroke="#66716b"/><text x="594" y="425" text-anchor="middle" fill="#c7d0c8" font-size="11">南海诸岛</text></svg>'
    + '<small>已定位 ' + located + ' / ' + rows.length + ' 次 · 点省份筛选下方记录</small><div class="province-chips">' + chips + '</div></article>';
}
v.addEventListener('click', event => {
  const place = event.target.closest('[data-province]');
  if (!place) return;
  selectedProvince = place.dataset.province;
  state.page = 1;
  training();
});

function training(){
 if(editing!==null){form();return}
 if(state.selected!==null){recordView();return}
 if(!indexData){v.innerHTML=p('正在读取训练索引…');if(!indexPromise)indexPromise=api('/api/archive').then(x=>{indexData=x;for(const r of x.items)if(r.sport==='running')r.types=[executionType(r)];if(tab==='训练')render()}).catch(e=>{msg.textContent=e.message;if(tab==='训练')v.innerHTML=button('重新读取训练记录','retry')}).finally(()=>indexPromise=null);return}
 const list=indexData.items.filter(x=>x.sport===state.sport&&x.date<=data.day);
 const [start,end]=rangeFor(list),type=state.types[state.sport];
 const matches=list.filter(x=>x.date>=start&&x.date<=end&&(type==='全部类型'||x.types.includes(type)));
 const showMap=state.sport==='running';
 const scoped=showMap ? RunPeriods.scoped(matches,[state.range,start,end,type].join('|')) : matches;
 const map=showMap ? mobileFootprint(scoped) : '';
 const province=showMap && footprintReady && selectedProvince ? footprintRegions.find(region=>region[0]===selectedProvince) : null;
 const visible=province ? scoped.filter(row=>fpRegion(row.raw)===selectedProvince) : scoped;
 const count=visible.length;
 const pages=Math.max(1,Math.ceil(count/25));
 state.page=Math.min(state.page,pages);
 const labels=['全部类型',...new Set(list.flatMap(x=>x.types))];
 const rows=visible.slice((state.page-1)*25,state.page*25).map(record=>{
   const value=record.distance_km!=null?kmText(record.distance_km):trainingMinutes(record)==null?'详情':trainingDurationText(record);
   return '<button class="row" data-action="record:'+record.id+'"><b>'+esc(record.name||sport(record.sport))+'<small>'+esc(record.date)+' · '+esc(record.types.join(' / '))+'</small></b><em>'+esc(value)+' ›</em></button>';
 });
 const filters=trainingFilter('运动项目','sport',[['running','跑步档案'],['strength','力量档案']],state.sport)
   +trainingFilter('时间范围','range',['全部历史','训练周期','最近 4 周','今年',...(showMap?[...new Set(list.map(r=>r.date.slice(0,4))),'自定义']:[])].map(name=>[name,name]),state.range)
   +trainingFilter('训练类型','type',labels.map(name=>[name,name]),type);
 const pager='<div class="pager"><button data-action="prev" '+(state.page===1?'disabled':'')+'>上一页</button><button data-action="next" '+(state.page===pages?'disabled':'')+'>下一页</button></div>';
 const custom=state.range==='自定义'?'<div class="spec-filters"><label>从<input type="date" data-period-date="start" value="'+(start||'')+'"></label><label>至<input type="date" data-period-date="end" value="'+(end||'')+'"></label></div>':'';
 const period=showMap?RunPeriods.render(visible,{asOf:data.day,from:start,to:end,scope:state.range==='全部历史'?'all':state.range.includes('训练周期')?'cycle':state.range,metric:(row,k)=>row[k],climb:r=>r.climb}):summaryCarousel(matches,start,end);
 v.innerHTML=heading('训练记录')+'<div class="training-filters">'+filters+'</div>'+custom+period+map+section(province ? province[1]+'跑步记录' : '记录列表',count+' 次 · 第 '+state.page+' / '+pages+' 页')+'<div class="panel">'+(rows.join('')||p('当前筛选范围内暂无记录。'))+'</div>'+pager;
 if(showMap)RunPeriods.bind(v.querySelector('.rp'),()=>{state.page=1;training()},id=>{
   openArchiveRun(id).catch(error=>{msg.textContent=error.message});
 });
 for(const field of v.querySelectorAll('[data-period-date]'))field.onchange=()=>{
   if(field.dataset.periodDate==='start')periodCustomStart=field.value;else periodCustomEnd=field.value;
   state.page=1;training();
 };
}
function summaryCarousel(records,start,end){
 const sum=(rows,key)=>rows.reduce((total,r)=>total+r[key],0);
 const slides=[['训练次数',records.length+' 次']];
 if(state.sport==='running'){
   const distances=records.filter(r=>r.distance_km>0), timed=records.filter(r=>r.timer_seconds>0);
   const paired=timed.filter(r=>r.distance_km>0);
   const weighted=timed.filter(r=>r.average_hr>0);
   slides.push(['距离合计',distances.length?kmText(sum(distances,'distance_km')):'—'],
     ['计时时间合计',timed.length?Math.round(sum(timed,'timer_seconds')/3600)+' 小时':'—'],
     ['综合配速',paired.length?paceLabel(Math.round(sum(paired,'timer_seconds')/sum(paired,'distance_km')))+' /km':'—'],
     ['平均心率',weighted.length?Math.round(weighted.reduce((n,r)=>n+r.average_hr*r.timer_seconds,0)/sum(weighted,'timer_seconds'))+' bpm':'—']);
 }else{
   const timed=records.filter(r=>trainingMinutes(r)!=null);
   const approximate=timed.some(r=>r.strength_duration_estimate_seconds!=null||r.duration_is_approximate);
   slides.push(['累计时长',timed.length?(approximate?'约 ':'')+Math.round(timed.reduce((s,r)=>s+trainingMinutes(r),0))+' 分钟':'—']);
 }
 return '<div class="hero summary-carousel" tabindex="0" aria-label="训练汇总，左右滑动切换指标">'+slides.map(([label,value],i)=>'<section><small>'+esc(label)+' · '+(i+1)+'/'+slides.length+'</small><h2>'+esc(value)+'</h2><small>'+esc(start)+' — '+esc(end)+'</small></section>').join('')+'</div>';
}
function kmText(value){
  if(value==null || String(value).trim()==='' || !Number.isFinite(Number(value)))return '—';
  return Number(value).toFixed(2)+' km';
}
function metric(value,unit,precision=0){
  return typeof value==='number'&&Number.isFinite(value)?value.toFixed(precision)+' '+unit:'—';
}
function trainingMinutes(row){
 if(row.duration_minutes!=null)return row.duration_minutes;
 return row.strength_duration_estimate_seconds==null?null:row.strength_duration_estimate_seconds/60;
}
function trainingDurationText(row){
 const minutes=trainingMinutes(row);
 if(minutes==null)return '—';
 const approx=row.strength_duration_estimate_seconds!=null;
 if(row.duration_is_approximate && !approx)return '约 '+Math.round(minutes)+' 分钟';
 return (approx?'约 ':'')+Math.round(minutes)+' 分钟'+(approx?'（估算）':'');
}
function strengthLoad(x){
  const basis=x.load_basis||'';
  if(x.load_kg===0&&/自重|无外加负重/.test(basis))return '自重';
  if(x.load_kg!=null&&/单只哑铃|单侧哑铃/.test(basis))return '每只 '+x.load_kg+' kg';
  return [x.load_kg==null?'':x.load_kg+' kg',basis].filter(Boolean).join(' · ');
}
function total(parts,k){return parts.length&&parts.every(l=>l[k]!=null)?parts.reduce((s,l)=>s+l[k],0):null}
function avg(parts,k){const seconds=total(parts,'sec');return seconds&&parts.every(l=>l[k]!=null)?Math.round(parts.reduce((s,l)=>s+l[k]*l.sec,0)/seconds):null}
function stat(label,val){return '<div class="row"><b>'+esc(label)+'</b><span>'+esc(val)+'</span></div>'}
function recordView(){
 let a=selectedRecord;if(!a||a.id!==state.selected){v.innerHTML=p('正在读取训练详情…');return}
 let html=button(routeParent?'‹ 同路线记录':stageRunReturn?'‹ 阶段复盘':prReturn?'‹ 个人纪录':'‹ 训练记录','list')+heading(a.sport==='strength'?'力量训练':a.name||'跑步详情',a.date);
 if(a.sport==='strength'){html+=stat('锻炼时长',trainingDurationText(a))+(a.strength_duration_estimate_seconds!=null?'<details><summary>时长估算依据</summary>'+p('动态动作每次按 3 秒，静态动作按记录秒数。左右连续做完算一组，组间及动作间按 2 分钟。')+'</details>':'')+section('动作与组次')+(a.sets||[]).map(x=>card(x.exercise,p([x.side,x.set_kind==='warmup'?'热身':'第 '+x.set_number+' 组',strengthLoad(x),x.reps==null?'':x.reps+' 次',x.rir==null?'':'RIR '+x.rir,x.notes].filter(Boolean).join(' · ')))).join('')}
 else{
 html+='<div class="tabs">'+['概览','分段','曲线','路线装备'].map(s=>button(s,'sub:'+s,state.sub===s)).join('')+'</div>';
 if(state.sub==='分段'){
 const laps=a.laps||[],parts=laps.filter(l=>/^(跑步|工作段?|主段|主训练|间歇)(?:$|[（(])|^(RUN|INTERVAL_ACTIVE)$/.test(l.stage||'')),km=total(parts,'km'),sec=total(parts,'sec');
 if(a.workGroups?.length)html+=workReview(a);
 if(km>0&&sec>0)html+=(a.workGroups?.length?'<details><summary>工作段汇总</summary>':'')+'<div class="hero"><small>明确标注的工作段 · '+kmText(km)+'</small><h2>'+clock(sec)+'</h2>'+clock(sec/km)+' /km</div>'+stat('主段平均心率',metric(avg(parts,'hr'),'bpm'))+stat('主段平均功率',metric(avg(parts,'power'),'W'))+(a.workGroups?.length?'</details>':'');
 html+=section('全程与分段')+stat('全程',kmText(a.distance)+' · '+clock(a.seconds))+(laps.length?'<details><summary>查看 '+laps.length+' 圈</summary>'+laps.map(l=>stat('第 '+l.number+' 圈 · '+(l.stage||'未标注'),kmText(l.km)+' · '+clock(l.sec))).join('')+'</details>':p('暂无归档分圈'));
 }else if(state.sub==='概览'){html+=card('全程',stat('距离',kmText(a.distance))+stat('计时',clock(a.seconds))+stat('平均心率',metric(a.hr,'bpm'))+stat('平均功率',metric(a.power,'W')))}
 else if(state.sub==='路线装备'){html+=routeDetail(a)}
 else html+=curveData?'<div class="mobile-run-curve">'+curveControls()+'</div>':p('正在读取曲线…');
 }
 v.innerHTML=html+(a.sport==='running'?button('跑后分享','run-poster'):'')+button('查看 / 修改训练后反馈','feedback');
 const chart=v.querySelector('.mobile-run-curve');
 if(chart)mountCurve(chart,curveData,curveStages(a.laps||[],a.distance,a.name),a.curveSettings??={});

}
function directory(){
 return heading('我的')+Object.entries(topicGroups).map(([group,links])=>section(group)+'<div class="panel">'+Object.entries(links).map(([name,k])=>'<button class="row" data-action="topic:'+k+'"><b>'+name+'</b><em>›</em></button>').join('')+'</div>').join('')+'<a href="/desktop">电脑版</a> '+button('退出登录','logout');
}
let abilityMetric='pace', abilityScope='recent';
const paceLabel=seconds=>Math.floor(seconds/60)+':'+String(Math.round(seconds)%60).padStart(2,'0');
function thresholdBounds(day){
 if(abilityScope==='cycle')return cycleBounds();
 if(abilityScope==='recent')return [offsetDate(day,-27),day];
 const month=new Date(day.slice(0,7)+'-01T12:00:00Z');
 month.setUTCMonth(month.getUTCMonth()-(abilityScope==='six'?5:11));
 return [month.toISOString().slice(0,10),day];
}
function thresholdChart(records,field){
 const pace=abilityMetric==='pace',key=pace?'pace_seconds_km':'hr_bpm';
 const [start,end]=thresholdBounds(data.day);
 const points=records.filter(r=>r.date>=start&&r.date<=end&&Number.isFinite(r[key])&&r[key]>0);
 const band=pace&&field&&field.date>=start&&field.date<=end?field:null;
 const values=points.map(r=>r[key]);
 if(band)values.push(band.low,band.high);
 const tabs='<div class="tabs">'+button('阈值配速','threshold:pace',pace)+button('阈值心率','threshold:hr',!pace)+'</div>';
 const scopes={recent:'最近4周',six:'最近6个月',year:'最近1年',cycle:'训练周期'};
 const menu=trainingFilter('时间范围','threshold-scope',Object.entries(scopes),abilityScope);
 const title=pace?'阈值配速参考趋势':'阈值心率参考趋势';
 const format=v=>pace?paceLabel(v):String(v);
 const x=d=>42+258*(Date.parse(d)-Date.parse(start))/(Date.parse(end)-Date.parse(start));
 const low=Math.min(...values)-2,high=Math.max(...values)+2;
 const y=v=>24+72*(pace?v-low:high-v)/(high-low);
 let plot='';
 if(values.length){
   const dots=points.map((r,i)=>{
     const label=r.date+' · 设备估计 '+format(r[key])+(pace?' /km':' bpm');
     const cx=x(r.date),cy=y(r[key]);
     return '<g data-point="'+esc(label)+'"><circle cx="'+cx+'" cy="'+cy+'" r="10" fill="transparent"/><circle cx="'+cx+'" cy="'+cy+'" r="3.5" fill="#318e82"/><title>'+esc(label)+'</title></g>'+(i===points.length-1?'<text x="'+cx+'" y="'+(cy-8)+'" text-anchor="'+(cx>260?'end':'start')+'">'+format(r[key])+'</text>':'');
   }).join('');
   const cx=band?x(band.date):0;
   const range=band?'<g data-point="'+band.date+' · 实跑推定 '+paceLabel(band.low)+'–'+paceLabel(band.high)+' /km"><rect x="'+(cx-10)+'" y="'+(y(band.low)-6)+'" width="20" height="'+(y(band.high)-y(band.low)+12)+'" fill="transparent"/><path stroke="#80273e" stroke-width="3" d="M'+cx+' '+y(band.low)+' V'+y(band.high)+' M'+(cx-5)+' '+y(band.low)+'h10 M'+(cx-5)+' '+y(band.high)+'h10"/></g>':'';
   plot='<svg viewBox="0 0 316 124" width="100%" role="img" aria-label="'+title+'"><text x="2" y="27">'+format(pace?low:high)+'</text><text x="2" y="98">'+format(pace?high:low)+'</text>'+dots+range+'<text x="42" y="118">'+start.slice(5)+'</text><text x="300" y="118" text-anchor="end">'+end.slice(5)+'</text></svg>';
 }else plot=p('所选范围暂无有效记录。');
 const entries=points.map(r=>[r.date,'佳明设备估计 · '+format(r[key])+(pace?' /km':' bpm')]);
 if(band)entries.push([band.date,'实跑推定 · '+paceLabel(band.low)+'–'+paceLabel(band.high)+' /km']);
 entries.sort((a,b)=>b[0].localeCompare(a[0]));
 return '<article class="threshold-plot ability-special"><div class="spec-filters">'+menu+'</div>'+tabs+'<div class="spec-chart"><b>'+title+'</b><small>● 设备估计　'+(pace?'↕ 实跑推定区间 · 分/km':'实跑心率待验证 · bpm')+'</small>'+plot+'<small id="threshold-point" aria-live="polite">'+start+' — '+end+' · 设备 '+points.length+' 次更新'+(band?' · 实跑推定 1 次':'')+'</small></div>'+specialtyDetails('阈值明细',entries)+'</article>';
}
function performanceSections(panel){
 const scene=r=>r.raw.activityType?.typeKey==='treadmill_running'||/跑步机/.test(r.name||'')?'跑步机':classifyRun(r).tags.includes('越野跑')?'越野':'户外';
 const outdoor=panel.recent.filter(r=>scene(r)==='户外');
 const valid=outdoor.filter(r=>r.distance_km>0&&r.timer_seconds>0);
 const pace=r=>r.timer_seconds/r.distance_km;
 const easy=valid.filter(r=>executionType(r)==='轻松跑');
 const long=outdoor.filter(r=>r.timer_seconds>=4500);
 const latest=(label,r)=>card(label,r?p(kmText(r.distance_km)+' · '+secsText(r.timer_seconds))+p(paceLabel(Math.round(pace(r)))+' /km · '+metric(r.average_hr,'bpm'))+'<small>'+r.date+'</small>':p('暂无记录'));
 return '<details class="recent-performance"><summary>近期实跑表现 · 最近4周</summary><div class="spec-pair">'+latest('近期轻松跑',easy[0])+latest('近期长跑',long.find(r=>r.distance_km>0))+'</div></details>';

}
function abilityView(){
 if(!topicRows)return heading('跑步能力')+p('正在读取跑步能力…');
 const {rows,thresholds,field}=topicRows;
 const records=thresholds.filter(r=>r.date<=data.day).sort((a,b)=>a.date.localeCompare(b.date));
 const latest=records.at(-1), practical=field&&field.date<=data.day?field:null;
 const vo2=rows.find(row=>row[1]==='最大摄氧量 · 周汇总');
 const tiles='<div class="threshold-pair">'+card('实跑推定',p(practical?paceLabel(practical.low)+'–'+paceLabel(practical.high)+' /km':'—')+p('心率待验证')+'<small>'+esc(practical?.date)+' · 训练参考</small>')+card('佳明设备估计',p(latest?.pace_seconds_km?paceLabel(latest.pace_seconds_km)+' /km':'—')+p(latest?.hr_bpm?latest.hr_bpm+' bpm':'—')+'<small>'+esc(latest?.date)+' · 设备估计</small>')+'</div>';
 return heading('跑步能力')+card('最大摄氧量 · 周汇总',vo2?p(vo2[2])+'<small>'+esc(vo2[0])+'</small>':p('暂无记录'))+tiles+performanceSections(topicRows)+specializedView(topicRows,thresholdChart(records,practical))+'<article><details><summary>设备历史记录</summary>'+rows.map(row=>p(row.filter(Boolean).join(' · '))).join('')+'</details></article>';
}

v.addEventListener('click',event=>{
 const point=event.target.closest('[data-point]');
 if(point)q('#threshold-point').textContent=point.dataset.point;
});
function periodicReviewBody(row){
 const detail=row[5], review=detail.review, month=row[1]==='月';
 const section=(title,html)=>html?'<section><h3>'+esc(title)+'</h3>'+html+'</section>':'';
 const paragraph=value=>typeof value==='string'&&value.trim()?p(value):'';
 const fold=(title,html)=>html?'<details class="period-evidence"><summary>'+esc(title)+'</summary>'+html+'</details>':'';
 const entries=(items,render)=>(items||[]).map(render).join('');
 const findings=items=>entries(items,item=>'<div class="period-point"><b>'+esc(item.name||item.title)+'</b>'+paragraph(item.status)+paragraph(item.meaning)+fold('查看依据',paragraph(item.evidence))+'</div>');
 const goal=review.goal||{};
 const actions=entries(review.actions,item=>'<div class="period-point"><b>'+esc(item.when)+'</b>'+paragraph(item.action)+(item.check?paragraph('验收条件 · '+item.check):'')+'</div>')||entries(detail.next_actions,paragraph);
 const evidence=Object.entries(detail.notes).map(([label,text])=>section(label,paragraph(text))).join('');
 const limits=[...new Set([review.limits,...detail.limitations].filter(v=>typeof v==='string'))];
 const followup=review.followup_recovery;
 return '<div class="review-copy period-report">'+
   section(month?'本月结论':'本周结论',paragraph(row[4]))+
   '<small>'+esc(row[3])+(detail.through?' · 数据截至 '+esc(detail.through):'')+(detail.reviewed?' · 复盘于 '+esc(detail.reviewed):'')+'</small>'+
   section('能力变化',findings(review.abilities))+
   section('做得好',findings(review.strengths))+section('不足与影响',findings(review.gaps))+
   section('目标评估',paragraph(goal.decision)+paragraph(goal.reason)+paragraph(goal.trigger))+
   section('下一阶段',paragraph(review.next_stage))+
   section('改善与验证',actions)+
     (detail.loadReports||[]).map(x=>fold('本周负荷分析',paragraph(x.title)+paragraph(x.assessment)+paragraph(x.recommendation))).join('')+
   (followup?section('后续恢复 · '+followup.date,paragraph(followup.summary)):'')+
   fold('统计依据与说明',evidence+section('判断边界',entries(limits,paragraph))+paragraph(review.followup))+'</div>';
}


let chosenStageDates=null;
function stageDateForm(){
 const dates=chosenStageDates||{start:offsetDate(data.day,-6),end:data.day};
 const input=(label,name,value)=>'<label>'+label+'<input required type="date" name="'+name+'" value="'+esc(value)+'" max="'+esc(data.day)+'"></label>';
 return '<form class="stage-date-form"><div>'+input('开始日期','start',dates.start)+input('结束日期','end',dates.end)+'</div><button type="submit">查看所选时段</button></form>';
}
v.addEventListener('submit',async event=>{
 const form=event.target;
 if(!form.matches('.stage-date-form'))return;
 event.preventDefault();
 const {start,end}=form.elements;
 if(start.value>end.value){end.setCustomValidity('结束日期须等于或晚于开始日期');end.reportValidity();end.setCustomValidity('');return}
 chosenStageDates={start:start.value,end:end.value};
 try{await openTopic('阶段_'+start.value+'_'+end.value);window.scrollTo(0,0)}
 catch(error){msg.textContent=error.message}
});
function journalDate(date){
 if(!/^\d{4}-\d{2}-\d{2}$/.test(date))return date||'日期待核';
 return Number(date.slice(5,7))+' 月 '+Number(date.slice(8))+' 日　周'+'日一二三四五六'[new Date(date+'T00:00:00Z').getUTCDay()];
}
function journalRunName(run){
 const name=(run.name||'').replace(/^.*?\s-\s/,'').replace(/^\d{1,2}\/\d{1,2}\s*/,'').trim();
 if(/长跑/.test(name))return (run.route||'').split('·')[0].trim()+'长跑';
 return name.replace(/(?:\d+(?:\.\d+)?\s*(?:公里|km))$/i,'').trim()||'跑步';
}
function journalRunLead(text,verdict,halves,name){
 if(halves&&name.includes('长跑')&&!verdict){
   const [a,b]=halves, pace=b.pace-a.pace;
   const change=pace?'每公里'+(pace<0?'快 ':'慢 ')+Math.abs(pace)+' 秒':'配速持平';
   const hr=Number.isFinite(a.hr)&&Number.isFinite(b.hr)?b.hr-a.hr:null;
   return '后半程'+change+(hr===null?'':hr===0?'，均心持平':'，均心'+(hr>0?'高 ':'低 ')+Math.abs(hr)+' 次/分')+'。';
 }
 return reviewLead(text,verdict);
}
function reviewList(rows){
 const types=['全部','单次','专项','周','月','阶段'];
 const names={日评:'每日简评',单次:'单次复盘',专项:'专项分析',周:'周复盘',月:'月复盘',阶段:'阶段复盘'};
 const renderEntries=selected=>{const byDay=new Map();
 for(const r of selected){
   if(state.report!=='全部'&&r[1]!==state.report)continue;
   if(!byDay.has(r[0]))byDay.set(r[0],[]);
   byDay.get(r[0]).push(r);
 }
 return [...byDay].map(([day,items])=>'<section class="review-day"><h2><time>'+esc(journalDate(day))+'</time></h2><div>'+items.map(r=>{
   const stage=r[1]==='阶段'&&Number.isInteger(r[5]);
   const name=r[2]||names[r[1]];
   const title='<span class="review-subject">'+(state.report==='全部'&&name!==names[r[1]]?'<small>'+esc(names[r[1]]||r[1])+'</small>':'')+'<strong>'+esc(name)+'</strong></span>';
   if(stage)return '<button class="review-link" data-action="topic:阶段_'+r[5]+'">'+title+'<span aria-hidden="true">›</span></button>';
   if(['月','周'].includes(r[1])&&r[5]?.review){
     return '<details class="review-item"><summary>'+title+'</summary>'+periodicReviewBody(r)+'</details>';
   }
   if(r[1]==='单次'){
     const info=r[5]||{}, runName=info.run?journalRunName(info):name;
     const heading=runName+(info.run&&Number.isFinite(info.km)?' · '+kmText(info.km):'');
     const halves=reviewHalfStats(info.laps||[],info.km),lead=journalRunLead(r[3],info.verdict,halves,runName);
     const full=(r[3]?p(r[3]):'')+(r[4]?'<h3>后续建议</h3>'+p(r[4]):'');
     return '<details class="review-item single-review"><summary><span class="review-subject"><strong>'+esc(heading)+'</strong>'+
       (lead?'<span class="review-preview">'+esc(lead)+'</span>':'')+'</span></summary><div class="review-copy">'+
       workReview({...info,date:r[0]})+reviewHalfTable(info.laps||[],info.km,halves)+(info.run?button('逐公里分段与曲线 ›','stage-run:'+info.run):'')+
       (full?'<details class="review-full"><summary>完整教练判断</summary>'+full+'</details>':'')+'</div></details>';
   }
   const body=['周','月'].includes(r[1])&&!r[5]?.loadAnalysis?['统计周期','复盘结论']:['教练判断','后续建议'];
   return '<details class="review-item"><summary>'+title+'</summary><div class="review-copy">'+(r[5]?.run?workReview({...r[5],date:r[0]}):'')+r.slice(3,5).map((v,i)=>v?'<h3>'+body[i]+'</h3>'+p(v):'').join('')+'</div></details>';
 }).join('')+'</div></section>').join('');
 };
 const focused=['全部','专项'].includes(state.report),topics=focused?journalFocusTopics(focusDayAt(),data?.goals?.focus_topics):[],specials=rows.filter(r=>r[1]==='专项');
 const attached=t=>specials.filter(r=>(r[5]?.focusKey===t.key||focusOwnsReport(t,r[2],r[0])));
 const other=specials.filter(r=>!topics.some(t=>(r[5]?.focusKey===t.key||focusOwnsReport(t,r[2],r[0]))));
 const card=t=>'<article class="focus-mobile"><span class="focus-tag">'+(t.archived?'已归档':'当前专项')+'</span>'+focusContent(t,renderEntries(attached(t)),data?.goals)+'</article>';
 const closed=topics.filter(t=>t.archived),n=closed.length;
 const entries=topics.filter(t=>!t.archived).map(card).join('')+renderEntries(focused?rows.filter(r=>r[1]!=='专项'||other.includes(r)):rows)+(focused&&n?'<details class="special-history"><summary>历史专项 · '+n+'</summary>'+closed.map(card).join('')+'</details>':'');
 return '<div class="review-index">' +button('‹ 返回','topicback')+heading('教练复盘')+'<div class="review-filter" aria-label="复盘类型">'+types.map(t=>'<button type="button" data-action="report:'+t+'" aria-pressed="'+(state.report===t)+'">'+t+'</button>').join('')+'</div>'+(state.report==='阶段'?stageDateForm():'')+(entries||p('暂无这类复盘。'))+'</div>';
}

function topicView(){
 if(state.topic==='能力')return button('‹ 返回','topicback')+abilityView();
 if(!topicRows)return p('正在读取档案…');
 if(state.topic?.startsWith('阶段_'))return stageReviewView(topicRows);
 if(state.topic==='年度')return button('‹ 返回','topicback')+annualView(topicRows);
 if(libraryViews[state.topic])return button('‹ 返回','topicback')+libraryViews[state.topic](topicRows);
 if(state.topic==='报告')return reviewList(topicRows);
 const label=Object.entries(Object.assign({},...Object.values(topicGroups))).find(([,val])=>val===state.topic)?.[0]||state.topic;
 return button('‹ 返回','topicback')+heading(label)+topicRows.map(r=>'<article><small>'+esc(r[0])+'</small><details><summary>'+esc(r[1])+'</summary>'+r.slice(2).filter(Boolean).map(p).join('')+'</details></article>').join('');
}
async function openTopic(k){
 if(k==='纪录')prType=null;
 if(['running','strength'].includes(k)){state.sport=k;state.selected=null;editing=null;state.page=1;tab='训练';state.topic=null;render();return}
 state.topic=k;topicRows=null;const ticket=++loadNumber;render();
 try{
   const rows=await api('/api/topic/'+encodeURIComponent(k==='能力'?'跑步能力面板':k));
   if(ticket===loadNumber&&state.topic===k){topicRows=rows;render()}
 }catch(error){
   if(ticket===loadNumber&&state.topic===k){
     v.innerHTML=button('‹ 返回',k.startsWith('阶段_')?'topic:报告':'topicback')+p('暂时无法读取，请重试。')+button('重新读取','topic:'+k);
   }
   throw error;
 }
}
let recordReturnScroll=0;
async function openArchiveRun(id){
 recordReturnScroll=window.scrollY;
 routeList=false;routeParent=null;
 if(tab==='我的'){prReturn=prType;tab='训练'}
 state.selected=id;state.sub='分段';curveData=null;selectedRecord=null;render();window.scrollTo(0,0);
 const result=await api('/api/activity/'+id);
 if(state.selected!==id)return;
 selectedRecord=result;render();
}
v.addEventListener('click',async e=>{
 const action=e.target.closest('[data-action]')?.dataset.action;if(!action||busy)return;
 try{
 if(action.startsWith('stage-feedback:')){tab='今天';await openDay(action.slice(15));return}
 if(action==='stage-share'){
   openStagePoster(topicRows);
   return;
 }
 if(action.startsWith('stage-run:')){
   stageRunReturn=state.topic;
   try{await openArchiveRun(Number(action.slice(10)))}
   catch(error){if(stageRunReturn){tab='我的';state.selected=null;stageRunReturn=null;render()}throw error}
   return;
 }
 if(action==='list' && stageRunReturn && !routeParent){
   state.topic=stageRunReturn;stageRunReturn=null;prReturn=null;state.selected=null;editing=null;tab='我的';
   render();window.scrollTo(0,recordReturnScroll);return;
 }
 if(action==='run-poster'){
   const row=indexData?.items.find(item=>item.id===selectedRecord?.id);
   if(selectedRecord?.sport==='running')openRunPoster(selectedRecord,row?.types?.[0]);
   return;
 }
 if(action==='footprint-retry'){footprintLoad?.remove();footprintLoad=null;footprintError=false;training();return}
 if(action.startsWith('yearlink:')){annualYear=action.slice(9);await openTopic('年度');return}
 if(action.startsWith('routeretry:')){routeCache.delete(state.selected);render();return}
 if(action.startsWith('special:')){activeSpecialty=action.slice(8);render();return}
 if(action.startsWith('specretry:')){specCache.delete(action.slice(10));render();return}
 if(action.startsWith('vo2move:')){
   const c=specState['最大摄氧量'],n=Number(action.slice(8)),day=c.anchor||data.day;
   const next=c.range==='最近4周'?offsetDate(day,n*28):offsetDate(monthShift(day,n*(c.range==='最近6个月'?6:12)+1),-1);
   c.anchor=!n||next>data.day?data.day:next;render();return;
 }
 if(action.startsWith('threshold:')){abilityMetric=action.slice(10);render();return}
 if(action==='daily'){await openDay(feedbackToday());return}
 if(action==='dailyback')feedbackDay=null;
 if(action.startsWith('week:')){await switchWeek(action.slice(5));return}
 if(action.startsWith('day:')){
   const day=action.slice(4);
   weekDay=weekDay===day?null:day;
   render();
   v.querySelector('[data-action="day:'+day+'"]')?.focus({preventScroll:true});
   return;
 }
 if(action==='logout'){await api('/logout',{method:'POST'});clearDailyDrafts();sessionStorage.clear();location.reload();return}
 if(action.startsWith('topic:')){await openTopic(action.slice(6));window.scrollTo(0,0);return}
 if(action.startsWith('report:'))state.report=action.slice(7);
 if(action==='topicback'){state.topic=null;tab='我的'}
 if(['running','strength'].includes(action)){state.sport=action;state.page=1}
 if(action==='prev')state.page--;if(action==='next')state.page++;
 if(action.startsWith('record:')){await openArchiveRun(Number(action.slice(7)));return}
 if(action==='list'&&prReturn&&!routeParent){await backToPr();return}
 if(action==='list'&&routeParent){await backToRoute();return}
 if(action==='list'){state.selected=null;editing=null}
 if(action==='feedback')editing=state.selected;
 if(action.startsWith('sub:')){state.sub=action.slice(4);if(state.sub==='曲线'&&!curveData){const id=state.selected;render();const c=await api('/api/curve/'+id);if(id!==state.selected)return;curveData=c}}
 render();window.scrollTo(0,action==='list'?recordReturnScroll:0)
 }catch(error){msg.textContent=error.message}
});
let weekDay=null;
let selectedWeek=null, fetchedWeek=null, weekRequest=0, weekError='';
function offsetDate(date, days){
 const time=new Date(date+'T12:00:00Z');
 time.setUTCDate(time.getUTCDate()+days);
 return time.toISOString().slice(0,10);
}
async function switchWeek(direction,picked){
 const start=selectedWeek||data.week.start;
 const target=direction==='pick'?picked:direction==='current'?data.week.start:direction==='retry'?start:offsetDate(start,direction==='prev'?-7:7);
 const request=++weekRequest;
 selectedWeek=target===data.week.start?null:target;
 weekDay=null;fetchedWeek=null;weekError='';render();
 if(!selectedWeek)return;
 try{
   const loaded=await api('/api/week/'+target);
   if(request!==weekRequest)return;
   fetchedWeek=loaded;
 }catch(error){
   if(request!==weekRequest)return;
   weekError=error.message;
 }
 render();
}
function weekView(d){
 const start=selectedWeek||d.week.start;
 const week=start===d.week.start?d.week:fetchedWeek;
 const dates=Array.from({length:7},(_,i)=>offsetDate(start,i));
 const title=homeHeading(start===d.week.start?'本周训练':'训练日历','week',shortHomeDay(start)+' 至 '+shortHomeDay(dates[6]));
 if(!week)return title+'<div class="panel">'+(weekError?p(weekError)+button('重新读取','week:retry'):p('正在读取这周的训练…'))+'</div>'+button('＋ 记每日反馈','daily');
 const cells=dates.map((date,index)=>{
   const today=date===d.day, selected=date===weekDay;
   const plans=week.weekPlans.filter(plan=>plan.date===date);
   const actual=week.activities.filter(activity=>activity.date===date);
   const marker=actual.length?'已记录':plans.length?'有课表':'';
   return '<button class="cal-day" data-action="day:'+date+'" aria-expanded="'+selected+'"'+(today?' aria-current="date"':'')+' aria-label="'+date+' '+marker+'"><small>周'+'一二三四五六日'[index]+'</small><b>'+Number(date.slice(-2))+'</b><span>'+ (today?'今天':marker)+'</span></button>';
 }).join('');
 let detail='';
 if(dates.includes(weekDay)){
   const plans=week.weekPlans.filter(plan=>plan.date===weekDay);
   const actual=week.activities.filter(activity=>activity.date===weekDay);
   const records=actual.map(activity=>p(sport(activity.sport)+(trainingMinutes(activity)==null?'':' · '+trainingDurationText(activity))+(activity.session_rpe==null?'':' · RPE '+activity.session_rpe))).join('');
   detail='<section class="cal-detail"><b>'+weekDay+'</b><small>训练计划</small>'+(plans.map(plan=>p(plan.name)).join('')||p('暂无归档课表'))+'<small>训练记录</small>'+(records||p(weekDay>d.day?'待执行':'暂无已归档训练'))+'</section>';
 }
 return title+'<div class="panel">'+'<div class="week-calendar">'+cells+'</div>'+detail+'</div>'+button('＋ 记每日反馈','daily')
}
