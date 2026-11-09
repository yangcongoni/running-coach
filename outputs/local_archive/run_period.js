// Shared archive charts for desktop, mobile and offline pages.
const curveLabels = {pace:['配速','分/km'],hr:['心率','bpm'],pc:['跑中表现状况',''],elevation:['海拔','m'],cadence:['步频','步/分'],power:['功率','W'],stride:['步幅','m'],gct:['触地时间','ms'],oscillation:['垂直振幅','cm'],ratio:['垂直比','%']};

function curveControls() {
  const checks = Object.entries(curveLabels).map(([key,[name]]) =>
    '<label><input type="checkbox" data-phys-metric value="'+key+'">'+name+'</label>').join('');
  return '<div class="phys-controls"><fieldset class="phys-multiselect"><legend>纵轴指标 · 可多选</legend>'+checks+'</fieldset>'+
    '<div class="phys-axis-control"><span>横轴</span><div role="group" aria-label="曲线横轴"><button type="button" data-phys-axis="time">时间</button><button type="button" data-phys-axis="distance">距离</button></div></div></div>'+
    '<div class="curve-stages" data-curve-stages></div><div data-phys-plot></div>';
}

// Distances are measured from the activity start. Missing or partial lap coverage cannot anchor a highlight.
function curveStages(laps, totalKm, title) {
  let end=0;
  const stages=[];
  const groups=[];
  for (const [index,lap] of laps.entries()) {
    if (Number(lap.number)!==index+1 || !(lap.km>0)) return [];
    const start=end;
    end+=lap.km*1000;
    const label=String(lap.stage||'').trim();
    let kind='';
    if (/^(热身|暖身|warm[ _-]?up)(?:$|[（(])/i.test(label)) kind='热身';
    else if (/^(冷身|缓和|cool[ _-]?down)(?:$|[（(])/i.test(label)) kind='冷身';
    else if (/^(跑步|工作段?|主段|主训练|间歇|RUN|ACTIVE|INTERVAL_ACTIVE)(?:$|[（(])/i.test(label)) kind='工作段';
    else if (/^(恢复|休息|RECOVERY|REST)(?:$|[（(])/i.test(label)) kind='恢复';
    const previous=groups.at(-1);
    if (previous && previous.kind===kind) {
      previous.end=end;
      previous.seconds=previous.seconds!=null && lap.sec>0 ? previous.seconds+lap.sec : null;
    } else groups.push({kind,start,end,seconds:lap.sec>0?lap.sec:null});
  }
  if (!(totalKm>0) || Math.abs(end-totalKm*1000)>Math.max(50,totalKm*5)) return [];
  const workCount=groups.filter(g=>g.kind==='工作段').length;
  for (const [index,g] of groups.entries()) {
    if (!g.kind || (g.kind==='热身' && index!==0) || (g.kind==='冷身' && index!==groups.length-1)) continue;
    const peers=groups.filter(x=>x.kind===g.kind);
    const titleText=g.kind==='工作段' && workCount===1 && /测试/.test(title||'')?'测试主段':g.kind;
    stages.push({...g,name:titleText+(peers.length>1?' '+(peers.indexOf(g)+1):'')});
  }
  return stages;
}

let curveClipSequence=0;
function mountCurve(el,c,stages,settings={}) {
  if (!c?.points?.length) {el.querySelector('[data-phys-plot]').textContent='暂无归档曲线';return}
  const distanceIndex=c.columns.indexOf('distance'), hasDistance=c.points.some(p=>Number.isFinite(p[distanceIndex]));
  const options=hasDistance?stages:[];
  settings.axis??=c.columns.includes('time')?'time':'distance';
  settings.keys??=['pace','hr'];
  settings.selected??=options.findIndex(g=>g.name==='测试主段');
  const buttons=el.querySelector('[data-curve-stages]');
  const clipId='run-stage-'+(++curveClipSequence);
  function draw(){
    const stage=options[settings.selected];
    el.querySelectorAll('[data-phys-metric]').forEach(b=>{b.checked=settings.keys.includes(b.value)});
    el.querySelectorAll('[data-phys-axis]').forEach(b=>{b.setAttribute('aria-pressed',String(settings.axis===b.dataset.physAxis))});
    if(options.length){
      const sec=stage?.seconds==null?'':' · '+Math.floor(Math.round(stage.seconds)/60)+':'+String(Math.round(stage.seconds)%60).padStart(2,'0');
      const km=m=>Number((m/1000).toFixed(2));
      const text=stage?km(stage.start)+'–'+km(stage.end)+' km'+sec:'';
      buttons.innerHTML='<span>分段</span>'+['全程',...options.map(g=>g.name)].map((name,i)=>'<button type="button" data-phase="'+(i-1)+'" aria-pressed="'+(settings.selected===i-1)+'">'+name+'</button>').join('')+'<small>'+text+'</small>';
    }
    drawPhysOverlay(el,c,settings.keys,settings.axis,curveLabels,settings,stage,clipId);
  }
  el.onchange=e=>{if(e.target.matches('[data-phys-metric]')){
    settings.keys=[...el.querySelectorAll('[data-phys-metric]:checked')].map(b=>b.value);draw();
  }};
  el.onclick=e=>{
    const b=e.target.closest('[data-phase],[data-phys-axis]');if(!b)return;
    if(b.hasAttribute('data-phase')){
      settings.selected=Number(b.dataset.phase);
      const next=options[settings.selected],d=settings.sample?.[distanceIndex];
      if(next && !(d>=next.start && d<=next.end))settings.sample=null;
    }
    else settings.axis=b.dataset.physAxis;
    draw();
    if(b.hasAttribute('data-phase'))buttons.querySelector('[data-phase="'+settings.selected+'"]').focus({preventScroll:true});
  };
  draw();
}
const physColors={pace:'#812b40',hr:'#2878b5',pc:'#9156b0',elevation:'#408551',cadence:'#bc721e',power:'#ca5268',stride:'#008a90',gct:'#786341',oscillation:'#5869b7',ratio:'#707579'};
function drawPhysOverlay(el,c,keys,axis,labels,settings,stage,clipId){
 const host=el.querySelector('[data-phys-plot]'),xi=c.columns.indexOf(axis),ti=c.columns.indexOf('time');
 el.querySelectorAll('[data-phys-metric]').forEach(input=>{input.style.accentColor=physColors[input.value];input.closest('label').style.setProperty('--metric-color',physColors[input.value])});
 if(!keys.length){host.innerHTML='<p class="scope-note">请选择至少一个纵轴指标。</p>';return}
 const validX=c.points.filter(p=>Number.isFinite(p[xi]));if(!validX.length){host.innerHTML='<p class="scope-note">该横轴暂无有效采样。</p>';return}
 const series=keys.map(k=>{const yi=c.columns.indexOf(k==='pace'?'speed':k),points=c.points.map(p=>({x:p[xi],time:p[ti],y:k==='pace'?(p[yi]>0?1000/p[yi]/60:null):p[yi]})),ys=points.filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)).map(p=>p.y);if(!ys.length)return {k,points,missing:true};let lo=Math.min(...ys),hi=Math.max(...ys),pad=(hi-lo)*.05||Math.max(Math.abs(hi)*.05,1);return {k,points,lo:lo-pad,hi:hi+pad,min:lo,max:hi}}),good=series.filter(s=>!s.missing);
 if(!good.length){host.innerHTML='<p class="scope-note">所选指标均无有效采样，不补零。</p>';return}
 const W=Math.max(280,host.clientWidth||760),H=240,L=52,R=good.length>1?52:18,T=20,B=44,xmin=Math.min(...validX.map(p=>p[xi])),xmax=Math.max(...validX.map(p=>p[xi])),X=x=>L+(x-xmin)/(xmax-xmin||1)*(W-L-R),Y=(v,s)=>T+(s.k==='pace'?(v-s.lo)/(s.hi-s.lo):(s.hi-v)/(s.hi-s.lo))*(H-T-B),format=(v,k)=>k==='pace'?Math.floor(Math.round(v*60)/60)+':'+String(Math.round(v*60)%60).padStart(2,'0'):Number(v.toFixed(k==='pc'?0:1)).toString(),xf=x=>axis==='distance'?(x/1000).toFixed(2)+' km':Math.floor(x/60)+':'+String(Math.floor(x%60)).padStart(2,'0');
 const di=c.columns.indexOf('distance');
 const locate=d=>{
   if(axis==='distance')return d;
   let last=null;
   for(const p of validX){
     if(!Number.isFinite(p[di]))continue;
     if(p[di]>=d){
       if(!last||p[di]===last[di])return p[xi];
       return last[xi]+(p[xi]-last[xi])*(d-last[di])/(p[di]-last[di]);
     }
     last=p;
   }
   return xmax;
 };
 let svg=`<svg class="phys-overlay-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="所选跑步指标叠加曲线，各用独立刻度">`;
 for(let j=0;j<5;j++){let yy=T+j*(H-T-B)/4;svg+=``;good.slice(0,2).forEach((s,i)=>{let v=s.k==='pace'?s.lo+j*(s.hi-s.lo)/4:s.hi-j*(s.hi-s.lo)/4;svg+=`<text x="${i?W-R+7:L-7}" y="${yy+4}" text-anchor="${i?'start':'end'}" fill="${physColors[s.k]}" font-size="11">${format(v,s.k)}</text>`})}
 if(stage){
   const left=X(Math.max(xmin,locate(stage.start))),right=X(Math.min(xmax,locate(stage.end)));
   const box=`x="${left}" y="${T}" width="${Math.max(0,right-left)}" height="${H-T-B}"`;
   svg+=`<defs><clipPath id="${clipId}"><rect ${box}/></clipPath></defs><rect data-stage-band ${box} fill="#f4e9ed"/>`;
 }
 good.forEach(s=>{let path='',prev=null;const steps=s.points.slice(1).map((p,i)=>p.time-s.points[i].time).filter(v=>v>0).sort((a,b)=>a-b),gap=Math.max(10,(steps[Math.floor(steps.length/2)]||1)*3);s.points.forEach(p=>{if(!Number.isFinite(p.x)||!Number.isFinite(p.y)){prev=null;return}path+=(prev&&p.time-prev.time<=gap&&p.x>=prev.x?'L':'M')+X(p.x).toFixed(2)+','+Y(p.y,s).toFixed(2)+' ';prev=p});svg+=`<path data-overlay-series="${s.k}" d="${path}" fill="none" stroke="${physColors[s.k]}" stroke-width="1.7" opacity="${stage?0.30:1}"/>`;if(stage)svg+=`<path d="${path}" clip-path="url(#${clipId})" fill="none" stroke="${physColors[s.k]}" stroke-width="2"/>`});
 for(let j=0;j<3;j++){const x=xmin+j*(xmax-xmin)/2;svg+=`<text x="${X(x)}" y="${H-20}" text-anchor="${j===0?'start':j===2?'end':'middle'}" fill="#776e70" font-size="11">${xf(x)}</text>`}
 svg+=`<line data-crosshair x1="0" x2="0" y1="${T}" y2="${H-B}" stroke="#8a8183" stroke-dasharray="3 3" visibility="hidden"/><rect data-plot-hit x="${L}" y="${T}" width="${W-L-R}" height="${H-T-B}" fill="transparent"/></svg>`;
 host.innerHTML=`<div class="phys-overlay-legend">${series.map(s=>`<span><i style="background:${physColors[s.k]}"></i><b>${esc(labels[s.k][0])}</b> <small>${s.missing?'无数据':(good.indexOf(s)===0?'左轴 ':good.indexOf(s)===1?'右轴 ':'独立刻度 ')+format(s.lo,s.k)+'–'+format(s.hi,s.k)+' '+esc(labels[s.k][1])}</small></span>`).join('')}</div>${svg}<div class="phys-overlay-values" aria-live="polite">点选图表查看各指标采样值</div>`;
 const svgEl=host.querySelector('svg'),hit=host.querySelector('[data-plot-hit]'),cross=host.querySelector('[data-crosshair]');
 const inspect=e=>{const box=svgEl.getBoundingClientRect(),px=Math.max(L,Math.min(W-R,(e.clientX-box.left)*W/box.width)),x=xmin+(px-L)/(W-L-R)*(xmax-xmin);let nearest=validX[0];for(const p of validX)if(Math.abs(p[xi]-x)<Math.abs(nearest[xi]-x))nearest=p;show(nearest)};
 const show=nearest=>{settings.sample=nearest;const at=X(nearest[xi]);cross.setAttribute('x1',at);cross.setAttribute('x2',at);cross.setAttribute('visibility','visible');host.querySelector('.phys-overlay-values').innerHTML=`<b>${esc(xf(nearest[xi]))}</b>`+series.map(s=>{const yi=c.columns.indexOf(s.k==='pace'?'speed':s.k),v=s.k==='pace'?(nearest[yi]>0?1000/nearest[yi]/60:null):nearest[yi];return `<span><i style="background:${physColors[s.k]}"></i>${esc(labels[s.k][0])} <b>${Number.isFinite(v)?format(v,s.k)+' '+esc(labels[s.k][1]):'缺失'}</b></span>`}).join('')};hit.onpointermove=inspect;hit.onclick=inspect;
 let sample=settings.sample;
 if(!sample || !Number.isFinite(sample[xi])){
   const target=stage?locate((stage.start+stage.end)/2):xmin;
   sample=validX.reduce((a,p)=>Math.abs(p[xi]-target)<Math.abs(a[xi]-target)?p:a);
 }
 show(sample);
}

const RunPeriods = (() => {
  const modes = ['年','月','周','日','全部'];
  const names = {年:'年度汇总',月:'月度汇总',周:'每周汇总',日:'每日汇总',全部:'累计汇总'};
  const form = [
    ['cadence','步频','步/分',0], ['stride','步幅','m',2],
    ['vertical','垂直振幅','cm',1], ['ratio','垂直振幅比','%',1], ['contact','触地时间','ms',0]
  ];
  const state = {mode:'年', focus:null, history:[], limit:4, scope:''};
  const shift = (date,days) => {
    const d = new Date(date+'T12:00:00Z');
    d.setUTCDate(d.getUTCDate()+days);
    return d.toISOString().slice(0,10);
  };
  function key(date,unit) {
    if(unit==='周') return shift(date,-((new Date(date+'T12:00:00Z').getUTCDay()+6)%7));
    return unit==='年'?date.slice(0,4):unit==='月'?date.slice(0,7):unit==='日'?date:'全部';
  }
  function groups(rows,unit) {
    const out = new Map();
    for(const r of rows) {
      const k=key(r.date,unit);
      if(!out.has(k)) out.set(k,[]);
      out.get(k).push(r);
    }
    return out;
  }
  function scoped(rows,signature) {
    if(state.scope!==signature){state.scope=signature; state.focus=null;state.history=[];state.limit=4}
    return state.focus ? rows.filter(r=>key(r.date,state.focus.unit)===state.focus.key) : rows;
  }
  function distance(rows) {
    const valid=rows.filter(r=>Number.isFinite(r.distance_km)&&r.distance_km>0);
    return valid.length?valid.reduce((n,r)=>n+r.distance_km,0):null;
  }
  const km = value => value==null?'—':value.toLocaleString('zh-CN',{maximumFractionDigits:0});
  function weighted(rows,read) {
    let count=0, seconds=0, sum=0;
    for(const row of rows){const value=read(row);if(Number.isFinite(value)&&value>0&&row.timer_seconds>0){
      seconds+=row.timer_seconds;sum+=row.timer_seconds*value;count++;
    }}
    return {value:seconds?sum/seconds:null,count};
  }
  function figures(rows) {
    const timed=rows.filter(r=>r.timer_seconds>0);
    const seconds=timed.reduce((a,r)=>a+r.timer_seconds,0);
    const paired=timed.filter(r=>r.distance_km>0);
    const pace=paired.length?Math.round(paired.reduce((a,r)=>a+r.timer_seconds,0)/distance(paired)):null;
    const hr=weighted(rows,r=>r.average_hr).value;
    return [['跑步次数',rows.length+' 次'],['计时时长',seconds?Math.floor(seconds/3600)+'h '+Math.floor(seconds%3600/60)+'m':'—'],
      ['综合配速 /km',pace==null?'—':Math.floor(pace/60)+':'+String(pace%60).padStart(2,'0')],['平均心率',hr==null?'—':Math.round(hr)+' bpm']];
  }
  function formGrid(rows,read,allHistory) {
    const runs2026 = rows.filter(row => row.date.startsWith('2026-'));
    const allowYearMetrics = allHistory || runs2026.length === rows.length;
    const items = form.map(([key,label,unit,precision]) => {
      const yearMetric = ['vertical', 'ratio', 'contact'].includes(key);
      if (yearMetric && !allowYearMetrics) return '';
      const {value} = weighted(yearMetric ? runs2026 : rows, row => read(row,key));
      if (value === null) return '';
      const caption = yearMetric && allHistory ? label + '（2026）' : label;
      return '<div><small>'+caption+'</small><b>'+value.toFixed(precision)+' <i>'+unit+'</i></b></div>';
    }).join('');
    return items?'<div class="rp-formgrid">'+items+'</div>':'';
  }
  function childUnit(mode,scope) {
    if(mode==='全部') return scope==='cycle'?'周':scope==='all'?'年':'月';
    return mode==='年'?'月':'日';
  }
  function binKeys(k,mode,buckets,child) {
    if(mode==='年')return Array.from({length:12},(_,i)=>k+'-'+String(i+1).padStart(2,'0'));
    if(mode==='月'||mode==='周') {
      const n=mode==='周'?7:new Date(Date.UTC(+k.slice(0,4),+k.slice(5),0)).getUTCDate();
      return Array.from({length:n},(_,i)=>shift(mode==='月'?k+'-01':k,i));
    }
    const dates=[...buckets.keys()].sort();if(!dates.length)return [];
    const bins=[];let date=dates[0];
    while(date<=dates.at(-1)){
      bins.push(date);
      if(child==='周')date=shift(date,7);
      else if(child==='年')date=String(+date+1);
      else date=shift(date+'-01',32).slice(0,7);
    }
    return bins;
  }
  function label(k,unit) {
    if(unit==='年')return k+' 年';
    if(unit==='月')return k.slice(0,4)+' 年 '+Number(k.slice(-2))+' 月';
    if(unit==='周')return k+' 至 '+shift(k,6).slice(5);
    return unit==='全部'?'所选范围':k;
  }
  function bars(k,rows,unit,child,max) {
    const buckets=groups(rows,child),keys=binKeys(k,unit,buckets,child);
    return '<div class="rp-chartlabel">'+child+'跑量 · km</div><div class="rp-bars" style="--slots:'+(unit==='月'?31:Math.max(keys.length,1))+'">'+keys.map((b,i)=>{
      const amount=distance(buckets.get(b)||[]),tick=child==='年'?b:child==='周'?b.slice(5):b.slice(-2);
      const caption=b+' · '+(amount==null?'暂无已归档跑量':km(amount)+' km');
      return '<button class="rp-bar" data-rp-child="'+child+'" data-rp-key="'+b+'" title="'+caption+'" aria-label="'+caption+'" '+(amount==null?'disabled':'')+'><i style="height:'+((amount||0)/max*74)+'%"></i><span>'+((keys.length<16||i%5===0||i===keys.length-1)?tick:'')+'</span></button>';
    }).join('')+'</div>';
  }
  function card(k,rows,opt,child,max) {
    const m=state.mode, drill=m==='年'?'月':m==='月'||m==='周'?'日':'';
    const period=label(k,m),title=drill?'<button class="rp-title" data-rp-unit="'+m+'" data-rp-child="'+drill+'" data-rp-key="'+k+'">'+period+'</button>':'<b class="rp-title">'+period+'</b>';
    const note=key(opt.asOf,m)===k&&m!=='全部'?'截至 '+opt.asOf:({年:'自然年',月:'自然月',周:'周一至周日',日:'已归档跑步',全部:'当前筛选范围'})[m];
    const runs=rows.map(r=>r.distance_km).filter(x=>x>0);
    const elevation=rows.map(opt.climb).filter(x=>Number.isFinite(x)&&x>=0);
    return '<div class="rp-card" data-rp-mode="'+m+'"><div class="rp-cap"><div>'+title+'<small>'+note+'</small></div><strong>'+km(distance(rows))+' <i>km</i></strong></div><div class="rp-metrics">'+figures(rows).filter(([,value])=>value!=='—').map(([l,v])=>'<div><small>'+l+'</small><b>'+v+'</b></div>').join('')+'</div>'+
      formGrid(rows,opt.metric,m==='全部' && opt.scope==='all')+(m==='日'?'<div class="rp-activities">'+rows.map(r=>'<button data-rp-run="'+r.id+'"><span>'+esc(r.raw?.activityName||r.name||'跑步')+'</span><b>'+km(r.distance_km)+' km ›</b></button>').join('')+'</div>':bars(k,rows,m,child,max))+
      '<div class="rp-foot">'+(runs.length?'<span>最远单次 '+km(Math.max(...runs))+' km</span>':'')+(elevation.length?'<span>累计爬升 '+Math.round(elevation.reduce((a,b)=>a+b,0))+' m</span>':'')+'</div></div>';
  }
  function render(rows,opt) {
    const g=groups(rows,state.mode),child=childUnit(state.mode,opt.scope);
    const max=Math.max(1,...[...groups(rows,child).values()].map(rs=>distance(rs)||0));
    const sorted=[...g.keys()].sort().reverse();
    return '<section class="rp"><div class="rp-tabs" aria-label="按时间展示">'+modes.map(m=>'<button data-rp-tab="'+m+'" aria-pressed="'+(m===state.mode)+'">'+m+'</button>').join('')+'</div>'+
      (state.focus?'<button class="rp-back" data-rp-back>‹ 返回上一级 · '+label(state.focus.key,state.focus.unit)+'</button>':'')+
      '<div class="rp-heading"><h3>'+names[state.mode]+'</h3><small>'+g.size+' 个周期</small></div><div class="rp-grid">'+sorted.slice(0,state.limit).map(k=>card(k,g.get(k),opt,child,max)).join('')+'</div>'+
      (!g.size?'<p>当前筛选暂无跑步记录。</p>':'')+(sorted.length>state.limit?'<button data-rp-more>显示更多</button>':'')+'</section>';
  }
  function bind(host,refresh,open) {
    if(!host)return;
    host.onclick=e=>{
      const b=e.target.closest('button');if(!b)return;
      if(b.dataset.rpRun){open(Number(b.dataset.rpRun));return}
      let restoreScroll=null;const drill=!!b.dataset.rpChild;
      if(b.hasAttribute('data-rp-more'))state.limit+=6;
      else if(b.hasAttribute('data-rp-back')){const last=state.history.pop();if(!last)return;state.mode=last.mode;state.focus=last.focus;state.limit=last.limit;restoreScroll=last.scroll}
      else if(b.dataset.rpTab){state.mode=b.dataset.rpTab;state.limit=4;state.history=[];state.focus=null}
      else if(b.dataset.rpChild){state.history.push({mode:state.mode,focus:state.focus,limit:state.limit,scroll:window.scrollY});state.mode=b.dataset.rpChild;state.focus={key:b.dataset.rpKey,unit:b.dataset.rpUnit||state.mode};state.limit=4}
      else return;
      refresh();
      if(restoreScroll!=null)window.scrollTo(0,restoreScroll);
      else if(drill){const next=document.querySelector('.rp');if(next?.getBoundingClientRect().top<0)next.scrollIntoView({block:'start'})}
    };
  }
  return {scoped,render,bind};
})();
