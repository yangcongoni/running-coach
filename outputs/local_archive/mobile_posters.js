function clock(sec){if(sec==null)return '—';const n=Math.round(sec);return (n>=3600?Math.floor(n/3600)+':':'')+(n>=3600?String(Math.floor(n%3600/60)).padStart(2,'0'):Math.floor(n/60))+':'+String(n%60).padStart(2,'0')}
function stageMetrics(stage){
 const fields=new Map(), test=stage.test;
 if(test){
   const label=test.km+' 公里 '+(test.pb?'PB':'测试');
   fields.set('result',[label,clock(test.pb||test.seconds)]);
   fields.set('pace',['测试均配',clock(test.seconds/test.km)+'/km']);
 }
 if(stage.start&&stage.end){
   fields.set('runs',['跑步次数',stage.runs.length+' 次']);
   if(stage.distance!=null)fields.set('km',['累计跑量',stage.distance.toFixed(2)+' km']);
   if(!test && stage.runs.length){
     fields.set('days',['跑步天数',new Set(stage.runs.map(r=>r.date)).size+' 天']);
     const distances=stage.runs.map(r=>r.km).filter(Number.isFinite);
     if(distances.length)fields.set('longest',['最长单次',Math.max(...distances).toFixed(2)+' km']);
   }
 }
 return fields;
}
function stageRange(s){
 if(!s.start||!s.end)return '阶段日期待核';
 const last=s.through&&s.through<s.end?s.through:s.end;
 const end=last.slice(0,4)===s.start.slice(0,4)?last.slice(5):last;
 return (s.start+'–'+end).replaceAll('-','.'); 
}
const journeyMeasures = {
 score:['睡眠评分','分'], sleep:['睡眠时长','小时'], hr:['静息心率','bpm'], hrv:['单晚 HRV','ms'], readiness:['晨间准备度','分']
};
function journeyReport(stage){
 const end=stage.through && stage.through<stage.end?stage.through:stage.end;
 const rows=(stage.recoveries||[]).filter(r=>r.date>=stage.start&&r.date<=end&&!r.after)
   .map(r=>[r.date,...Object.keys(journeyMeasures).map(k=>Number.isFinite(r[k])?r[k]:null)]).sort((a,b)=>a[0].localeCompare(b[0]));
 const available=Object.keys(journeyMeasures).filter((k,i)=>rows.some(r=>r[i+1]!=null));
 if(!available.length)return '<p>这段时间没有归档的恢复指标。</p>';
 const options=available.map(k=>'<option value="'+k+'">'+journeyMeasures[k][0]+'</option>').join('');
 return '<div class="journey-report" data-first="'+esc(stage.start)+'" data-last="'+esc(end)+'"><label>恢复趋势 <select data-journey-measure>'+options+'</select></label><template>'+esc(JSON.stringify(rows))+'</template><div data-journey-plot>'+journeyPlot(rows,stage.start,end,available[0])+'</div></div>';
}
function journeyPlot(rows,start,end,key){
 const [label,unit]=journeyMeasures[key],index=Object.keys(journeyMeasures).indexOf(key)+1;
 const samples=rows.filter(r=>Number.isFinite(r[index])).map(r=>[r[0],r[index]]);
 if(!samples.length)return '';
 const fmt=v=>key==='sleep'?(v/60).toFixed(1):String(v);
 const ticks=s=>Date.parse(s+'T00:00:00Z')/86400000;
 const day0=ticks(start),span=ticks(end)-day0, values=samples.map(r=>r[1]);
 const low=Math.min(...values),high=Math.max(...values),w=360,h=115;
 const x=date=>span?16+328*(ticks(date)-day0)/span:180;
 const y=v=>high===low?56:93-74*(v-low)/(high-low);
 const points=samples.map(([d,v])=>[x(d).toFixed(2),y(v).toFixed(2)]);
 const commands=points.map(([a,b],i)=>(i&&ticks(samples[i][0])-ticks(samples[i-1][0])===1?'L':'M')+a+' '+b).join(' ');
 const dots=points.map(([a,b],i)=>'<circle cx="'+a+'" cy="'+b+'" r="2.6"><title>'+esc(samples[i][0]+' · '+fmt(values[i])+' '+unit)+'</title></circle>').join('');
 const days=samples.map(([date,v])=>'<li><time>'+esc(date)+'</time><b>'+esc(fmt(v)+' '+unit)+'</b></li>').reverse().join('');
 return '<div class="journey-range"><strong>'+esc(low===high?fmt(low):fmt(low)+'–'+fmt(high))+' <small>'+unit+'</small></strong><span>'+samples.length+' 天有记录</span></div><svg role="img" aria-label="'+label+'趋势" viewBox="0 0 '+w+' '+h+'"><path class="journey-grid" d="M16 19H344 M16 56H344 M16 93H344"/><path class="journey-line" d="'+commands+'"/>'+dots+'</svg><div class="journey-axis"><time>'+esc(start)+'</time>'+(start!==end?'<time>'+esc(end)+'</time>':'')+'</div><details><summary>逐日读数</summary><ul>'+days+'</ul></details>';
}
function journeyStats(s){
 const runs=s.runs||[], cells=[];
 const cell=(name,value,note='')=>cells.push('<div><small>'+esc(name)+'</small><b>'+esc(value)+'</b>'+(note?'<small>'+esc(note)+'</small>':'')+'</div>');
 cell('跑步次数',runs.length+' 次');
 cell('跑步天数',new Set(runs.map(r=>r.date)).size+' 天');
 if(s.distance!=null)cell('累计跑量',s.distance.toFixed(2)+' km');
 const distances=runs.map(r=>r.km).filter(Number.isFinite);
 if(distances.length)cell('最长单次',Math.max(...distances).toFixed(2)+' km');
 for(const [key,title,format] of [['seconds','跑步计时时长',v=>clock(v)],['climb','累计爬升',v=>Math.round(v)+' m']]){
   const vals=runs.map(r=>r[key]).filter(v=>Number.isFinite(v)&&v>=0);
   if(vals.length)cell(title,format(vals.reduce((a,b)=>a+b,0)),vals.length===runs.length?'':'已记录 '+vals.length+'/'+runs.length+' 次');
 }
 if(Array.isArray(s.strength))cell('力量训练',s.strength.length+' 次');
 return '<div class="journey-stats">'+cells.join('')+'</div>';
}
function reviewLead(assessment,verdict){
 if(verdict)return verdict;
 const sentences=String(assessment||'').match(/[^。！？]+[。！？]?/g)||[];
 return sentences.find(s=>/核心任务|符合.*要求|后半程.*稳定|强度控制|达到.*目标|未完成|按计划完成/.test(s))||sentences[0]||'';
}
function goalTimeLabel(value){
 const sec=Math.round(value);
 if(!Number.isFinite(value)||sec<=0)return '';
 return [Math.floor(sec/3600)?Math.floor(sec/3600)+' 小时':'',Math.floor(sec/60)%60?Math.floor(sec/60)%60+' 分':'',sec%60?sec%60+' 秒':''].filter(Boolean).join(' ');
}
function goalSummaryText(text){
 return String(text||'').replace(/半马\s*(\d{1,2}):([0-5]\d)(?![:.\d])/g,(_,h,m)=>'半马 '+goalTimeLabel(Number(h)*3600+Number(m)*60))
   .replace(/的教练主观把握/g,'的教练估计把握');
}
function goalTestClock(value){
 const seconds=Math.round(value);
 return Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0');
}
function goalEvidenceItem(e,tests){
 const original=String(e.text||''), label=[e.date,e.label].filter(Boolean).join(' · ');
 const test=tests?.[e.activity_id];
 if(!test||!String(e.label||'').includes('测试')||!(test.timer_seconds>0&&test.distance_m>0)){
   const cut=original.indexOf('。')+1;
   const more=original.length>130&&cut>0&&cut<original.length;
   return '<div class="goal-evidence-item"><b>'+esc(label)+'</b><p>'+esc(more?original.slice(0,cut):original)+'</p>'+(more?'<details><summary>查看完整记录</summary><p>'+esc(original.slice(cut).trim())+'</p></details>':'')+'</div>';
 }
 const km=test.distance_m/1000, distance=new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(km);
 const laps=Array.isArray(test.laps)?test.laps:[];
 const complete=laps.length===km&&laps.every((r,i)=>r.km===i+1&&Number.isFinite(r.seconds)&&r.seconds>0);
 const halves=km===10&&test.first5_seconds>0&&test.last5_seconds>0;
 const delta=halves?Math.round(Math.abs(test.last5_seconds-test.first5_seconds)):0;
 const metrics=['平均配速 '+goalTestClock(test.timer_seconds/km)+'/km'];
 if(halves)metrics.push(delta?'后半程'+(test.last5_seconds>test.first5_seconds?'慢 ':'快 ')+delta+' 秒':'前后半程用时相同（按秒）');
 if(complete)metrics.push('末公里 '+goalTestClock(laps.at(-1).seconds)+'/km');
 const row=(name,value,unit='')=>'<tr><th scope="row">'+esc(name)+'</th><td>'+esc(goalTestClock(value)+unit)+'</td></tr>';
 const splitRows=(halves?row('前 5 公里',test.first5_seconds)+row('后 5 公里',test.last5_seconds):'')+
    (complete?laps.map(r=>row('第 '+r.km+' 公里',r.seconds)).join(''):'');
 const verdict=halves&&complete&&delta&&test.last5_seconds>test.first5_seconds&&delta/test.first5_seconds<0.02&&laps.at(-1).seconds<laps.at(-2).seconds?'后半程用时稍长，最后一公里再次提速。':'';
 return '<section class="goal-evidence-item goal-test"><div class="goal-test-lead"><span>'+esc(distance)+' 公里测试</span><strong>'+esc(goalTestClock(test.timer_seconds))+'</strong></div>'+
   '<div class="goal-test-metrics">'+metrics.map(s=>'<span>'+esc(s)+'</span>').join('')+'</div>'+
   (verdict?'<p>'+verdict+'</p>':'')+(splitRows?'<details><summary>查看分段</summary><table><thead><tr><th>分段</th><th>用时</th></tr></thead><tbody>'+splitRows+'</tbody></table></details>':'')+
   '<details><summary>原始记录</summary><p>'+esc(original)+'</p></details></section>';
}


function goalDecisionView(g,tests={}){
 const evidence=(g.evidence||[]).filter(e=>e.text);
 const picks=[evidence.find(e=>e.activity_id),evidence.at(-1)].filter((e,i,a)=>e&&a.indexOf(e)===i);
 const node=g.next_review_node||{};
 return '<section class="review-decision">'+(g.summary?'<p class="goal-summary">'+esc(goalSummaryText(g.summary))+'</p>':'')+
   (picks.length?'<details><summary>哪些训练支持这个判断？</summary>'+picks.map(e=>goalEvidenceItem(e,tests)).join('')+'</details>':'')+
   (node.label||g.next_review_action?'<p><b>下一次验证</b>　'+esc([node.date||g.next_review_on,node.label].filter(Boolean).join(' · '))+'</p>'+(g.next_review_action?'<p>'+esc(g.next_review_action)+'</p>':''):'')+'</section>';
}
function reviewHalfStats(laps, distance){
 // Compare complete kilometre splits. A short finishing fragment stays in the detailed record.
 const rows=laps.slice();
 if(rows.at(-1)?.[0]>0&&rows.at(-1)[0]<0.05)rows.pop();
 if(rows.length<2||rows.length%2||rows.some(([km,sec])=>!(km>=0.995&&km<=1.005&&sec>0))||
    !Number.isFinite(distance)||Math.abs(rows.length-distance)>0.06)return null;
 const half=rows.length/2;
 return [rows.slice(0,half),rows.slice(half)].map(part=>{
   const seconds=part.reduce((s,r)=>s+r[1],0),km=part.reduce((s,r)=>s+r[0],0);
   const pace=Math.round(seconds/km);
   const hr=part.every(r=>r[2]>0)?Math.round(part.reduce((s,r)=>s+r[1]*r[2],0)/seconds):'—';
   return {half,pace,hr};
 });
}
function reviewHalfTable(laps,distance,stats=reviewHalfStats(laps,distance)){
 if(!stats)return '';
 const tr=stats.map(({half,pace,hr},i)=>{
   return '<tr><th>'+(i?'后':'前')+half+' 公里</th><td>'+Math.floor(pace/60)+':'+String(pace%60).padStart(2,'0')+'</td><td>'+hr+'</td></tr>';
 }).join('');
 return '<table><thead><tr><th>区段</th><th>均配 /km</th><th>均心（次/分）</th></tr></thead><tbody>'+tr+'</tbody></table>';
}
function recoveryAfterRun(run,day){
 const measured=day?.post, stamp=x=>Date.parse(x?.replace(/(?:Z|[+-]\d\d:\d\d)$/,'')+'+08:00');
 const lag=stamp(measured?.measured_at)-stamp(run.start)-run.elapsed*1000;
 return measured?.input_context==='AFTER_POST_EXERCISE_RESET'&&Number.isFinite(run.elapsed)&&lag>=-60000&&lag<=300000&&Number.isFinite(measured.minutes)?measured:null;
}
function stageRecoveryLink(run,s,feedbackLink){
 const nextDay=new Date(Date.parse(run.date+'T00:00:00Z')+86400000).toISOString().slice(0,10);
 const day=s.recoveries.find(r=>r.date===run.date);
 const morning=s.recoveries.find(r=>r.date===nextDay)||s.followingMorning;
 const r=morning?.date===nextDay?morning:null;
 const next=s.runs.find(x=>x.date>run.date)||s.followingRun;
 const measured=recoveryAfterRun(run,day), post=Boolean(measured);
 const fields=r?[r.sleep!=null?'睡眠 '+Math.floor(r.sleep/60)+'小时'+Math.round(r.sleep%60)+'分':'',r.hrv!=null?'HRV '+r.hrv+' ms':'',r.hr!=null?'静息心率 '+r.hr+' 次/分':'',r.readiness!=null?'准备度 '+r.readiness:''].filter(Boolean):[];
 const feedback=r?.feedback||r?.feeling;
 return '<details class="ws-recovery"><summary>跑后与次晨恢复</summary>'+
   (post?'<p><b>跑后</b>　'+esc(measured.measured_at.slice(11,16))+' 设备预计恢复 '+Math.floor(measured.minutes/60)+'小时'+measured.minutes%60+'分</p>':'')+
   '<p><b>'+esc(nextDay.slice(5))+' 次晨</b>　'+esc(fields.join(' · ')||'暂无归档恢复读数')+'</p>'+
   (feedback?'<p>当日反馈 · '+esc(feedback)+'</p>':feedbackLink(nextDay))+
   (next?'<p><b>'+esc(next.date.slice(5))+' 下次跑步</b>　'+esc([next.km!=null?next.km.toFixed(2)+' km':'',next.hr!=null?'均心 '+next.hr:'',next.rpe!=null?'RPE '+next.rpe:''].filter(Boolean).join(' · '))+'</p>':'')+'</details>';
}

function stageJourney(s,overview){
 const names=['概述','报告','统计'];
 const controls=names.map((name,i)=>'<button type="button" data-journey-tab="'+i+'" aria-pressed="'+(i===0)+'">'+name+'</button>').join('');
 return '<div class="stage-journey"><div class="journey-nav" role="group" aria-label="阶段视图">'+controls+'</div>'+[overview,journeyReport(s),journeyStats(s)].map((panel,i)=>'<section data-journey-panel="'+i+'"'+(i?' hidden':'')+'>'+panel+'</section>').join('')+'</div>';
}
document.addEventListener('click',e=>{
 const tab=e.target.closest('[data-journey-tab]');if(!tab)return;
 const view=tab.closest('.stage-journey');
 view.querySelectorAll('[data-journey-tab]').forEach(b=>b.setAttribute('aria-pressed',String(b===tab)));
 view.querySelectorAll('[data-journey-panel]').forEach(p=>p.hidden=p.dataset.journeyPanel!==tab.dataset.journeyTab);
});
document.addEventListener('change',e=>{
 if(!e.target.matches('[data-journey-measure]'))return;
 const report=e.target.closest('.journey-report');
 const rows=JSON.parse(report.querySelector('template').content.textContent);
 report.querySelector('[data-journey-plot]').innerHTML=journeyPlot(rows,report.dataset.first,report.dataset.last,e.target.value);
});

function openStagePoster(stage){
   const fields=stageMetrics(stage);
   if(fields.size>=2)openPosterEditor({heading:'阶段分享',initial:'track-teal',fields,
     defaults:()=>[...fields.keys()].slice(0,2), titleFor:()=>stage.title,
     caption:stageRange(stage),filename:'阶段-'+stage.start+'-'+stage.end});
}
// Render privately in the browser. The artwork contains no workout values.
function openRunPoster(activity, runType) {
  const records = (activity.poster_records || []).slice().sort((a,b) => (b.km || 0) - (a.km || 0));
  if (records.length > 2) records.splice(1, records.length-1, ...records.slice(1).reverse());
  const trail = runType === '越野跑' || activity.trail;
  const normalTitle = trail ? '越野跑' : runType && runType !== '待分类' ? runType : '跑步';
  const initial = trail ? 'trail-ridge' : records.length || /测试|间歇/.test(activity.name || '') ? 'track-teal' : 'river-walk';
  const fields = new Map();
  function field(key, label, value) { fields.set(key, [label, value]); }
  const km = activity.distance, sec = activity.seconds;
  field('distance', '距离', Number.isFinite(km) ? km.toFixed(2)+' km' : '—');
  field('duration', '用时', clock(sec));
  field('pace', '平均配速', km > 0 && sec > 0 ? clock(sec/km)+'/km' : '—');
  field('climb', '累计爬升', Number.isFinite(activity.climb) ? Math.round(activity.climb)+' m' : '—');
  if (activity.hr > 0) field('heart', '平均心率', Math.round(activity.hr)+' bpm');
  if (activity.power > 0) field('power', '平均功率', Math.round(activity.power)+' W');
  const pbKeys = records.map((record, i) => {
    const key = 'pb-'+i;
    field(key, record.label+' PB', record.seconds == null ? record.distance_km.toFixed(2)+' km' : clock(record.seconds));
    return key;
  });
  function defaults(key) {
    const base = trail || key.startsWith('trail-') ? ['distance','climb','duration','pace'] : ['distance','duration','pace','climb'];
    const available = base.filter(id => fields.get(id)[1] !== '—');
    const best = [...new Set([...pbKeys,...available,...fields.keys()])];
    return best.slice(0, Math.max(3, Math.min(4, pbKeys.length)));
  }
  openPosterEditor({heading:'跑后分享',initial,fields,defaults,caption:'训练手记 · '+activity.date.replaceAll('-','.'),
    filename:activity.date,titleFor:selected=>{
      const pb=pbKeys.find(k=>selected.includes(k));
      return pb?fields.get(pb)[0]:normalTitle;
    }});
}

function openPosterEditor({heading,initial,fields,defaults,titleFor,caption,filename}) {
  const groups = {
    '跑道': [['track-teal','橙青弯道'],['track-midnight','午夜蓝'],['track-gold','墨绿金线']],
    '江岸': [['river-walk','俯视岸线'],['river-steps','江堤版画'],['river-dusk','暮色江面']],
    '越野': [['trail-ridge','山脊'],['trail-meadow','山腰小径'],['trail-cloud','云海山脊'],['trail-scree','碎石下坡'],['trail-night','山口夜跑']]
  };
  let selected = defaults(initial), customized = false;
  const modal = document.createElement('dialog');
  modal.className = 'run-poster';
  modal.setAttribute('aria-labelledby','poster-title');
  modal.innerHTML = '<div class="poster-top"><h2 id="poster-title">'+esc(heading)+'</h2><button type="button" data-close>关闭</button></div>'
    + '<label class="poster-choice">海报模板<select></select></label>'
    + '<label class="poster-photo" hidden>选择本机照片<input type="file" accept="image/*"></label>'
    + '<fieldset class="poster-fields"><legend>展示字段（选 2–4 项）</legend><div></div></fieldset>'
    + '<div class="poster-preview"><img alt="本次跑步的分享海报" hidden></div>'
    + '<p role="status" aria-live="polite"></p><div class="poster-actions"><button type="button" disabled data-save>保存图片</button>'
    + '<button type="button" hidden data-share>系统分享</button><button type="button" hidden data-retry>重新生成</button></div>'
    + '<small>保存后，在微信朋友圈从相册选择图片。</small>';
  const find = selector => modal.querySelector(selector);
  const select = find('select'), img = find('img'), status = find('[role=status]');
  if(heading==='阶段分享'){find('.poster-preview').after(find('.poster-fields'));img.alt='阶段分享海报'}
  const embedded=typeof LOCAL_POSTER_ART!=='undefined';
  const preview=embedded?document.createElement('canvas'):img;
  if(embedded){preview.setAttribute('aria-label',img.alt);preview.hidden=true;img.replaceWith(preview)}
  const save = find('[data-save]'), share = find('[data-share]'), retry = find('[data-retry]');
  for (const [family,templates] of Object.entries(groups)) {
    const group = document.createElement('optgroup');
    group.label = family;
    for (const [key,label] of templates) group.append(new Option(family + ' · ' + label,key));
    select.append(group);
  }
  select.append(new Option('自定义图片 · 从相册选图','photo'));
  const photoRow = find('.poster-photo'), picker = photoRow.querySelector('input');
  const panel = find('.poster-fields div');
  let photoURL = '', photoImage = null;
  function clearPhoto() {
    if (photoURL) URL.revokeObjectURL(photoURL);
    photoURL = ''; photoImage = null;
  }
  for (const [key, [label, value]] of fields) {
    const box = document.createElement('input'), wrap = document.createElement('label');
    box.type = 'checkbox'; box.value = key;
    wrap.append(box, label + (value === '—' ? '（缺数据）' : '')); panel.append(wrap);
  }
  function updateFields() {
    for (const box of panel.querySelectorAll('input')) {
      box.checked = selected.includes(box.value);
      box.disabled = box.checked ? selected.length <= 2 : selected.length >= 4;
    }
  }
  panel.onchange = event => {
    const box = event.target;
    customized = true;
    selected = box.checked ? [...selected, box.value] : selected.filter(k => k !== box.value);
    updateFields(); prepare();
  };
  picker.onchange = () => {
    const picked = picker.files[0];
    if (!picked) return;
    clearPhoto();
    if(embedded)photoImage=picked;
    else{photoURL=URL.createObjectURL(picked);photoImage=new Image();photoImage.src=photoURL}
    picker.value = '';
    prepare();
  };
  select.value = initial;
  updateFields();
  document.body.append(modal);
  modal.showModal();
  let version = 0, url = '', file;
  function release() {
    if (url) URL.revokeObjectURL(url);
    url = ''; file = null;
  }
  modal.addEventListener('close', () => { version++; release(); clearPhoto(); modal.remove(); }, {once:true});
  find('[data-close]').onclick = () => modal.close();
  async function prepare() {
    const ticket = ++version, key = select.value;
    save.disabled = true; share.hidden = true; retry.hidden = true;
    preview.hidden=true;img.removeAttribute('src');release();
    const customPhoto = key === 'photo';
    photoRow.hidden = !customPhoto;
    if (customPhoto && !photoImage) {
      status.textContent = '请选择一张照片，图片仅在本机处理。';
      return;
    }
    status.textContent = '正在生成海报…';
    try {
      let art;
      if(embedded){
        const source=customPhoto?photoImage:new Blob([Uint8Array.from(atob(LOCAL_POSTER_ART[key]),c=>c.charCodeAt(0))],{type:'image/webp'});
        art=await createImageBitmap(source);
      }else{
        art=customPhoto?photoImage:new Image();
        if(!customPhoto)art.src=typeof OFFLINE_POSTER_ART==='undefined'?'/poster-art/'+key+'.webp':OFFLINE_POSTER_ART[key];
        await art.decode();
      }
      let blob;
      try{
        if(version!==ticket)return;
        blob=await paintRunPoster(art,caption,titleFor(selected),selected.map(k=>fields.get(k)),customPhoto);
      }finally{if(embedded)art.close()}
      if (version !== ticket) return;
      url = URL.createObjectURL(blob);
      file = new File([blob], '训练手记-' + filename + '-' + key + '.png', {type:'image/png'});
      if(embedded){
        const bitmap=await createImageBitmap(blob);
        try{
          if(version!==ticket)return;
          preview.width=bitmap.width;preview.height=bitmap.height;
          preview.getContext('2d').drawImage(bitmap,0,0);
        }finally{bitmap.close()}
      }else{img.src=url;await img.decode()}
      if (version !== ticket) return;
      preview.hidden=false; save.disabled=false;
      share.hidden = !(navigator.canShare && navigator.canShare({files:[file]}));
      status.textContent = '';
    } catch {
      if (version !== ticket) return;
      status.textContent = customPhoto ? '这张照片暂时无法生成海报，请换一张 JPG、PNG 或 WebP 图片。' : '海报暂未生成，请检查连接后重试。';
      retry.hidden = customPhoto;
    }
  }
  select.onchange = () => {
    if (!customized) selected = defaults(select.value);
    updateFields(); prepare();
  };
  retry.onclick = prepare;
  save.onclick = () => {
    if (!file) return;
    const link = document.createElement('a');
    link.href = url; link.download = file.name; modal.append(link); link.click(); link.remove();
    status.textContent = '已请求下载 PNG。也可以长按上方海报保存到相册。';
  };
  share.onclick = async () => {
    if (!file) return;
    try { await navigator.share({files:[file]}); }
    catch (err) { if (err.name !== 'AbortError') status.textContent = '可以点「保存图片」，再从朋友圈选择。'; }
  };
  prepare();
}

async function paintRunPoster(art, caption, title, metrics, customPhoto) {
  const canvas = document.createElement('canvas');
  canvas.width = 1080; canvas.height = 1350;
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height, left = 80, right = w-left;
  const columns = metrics.length === 4 ? 2 : metrics.length;
  const rows = Math.ceil(metrics.length / columns);
  const titleY = h - 220 - (rows-1)*86;
  // Extend a narrow strip of the same artwork into the footer without including any baked-in example data.
  const artEnd = titleY - 35;
  if (customPhoto) {
    ctx.fillStyle = '#182024'; ctx.fillRect(0,0,w,h);
    const scale = Math.max(w/art.width,h/art.height);
    const dw = art.width*scale, dh = art.height*scale;
    ctx.drawImage(art,(w-dw)/2,(h-dh)/2,dw,dh);
  } else {
    ctx.drawImage(art,0,0,w,artEnd);
    const strip = Math.max(1,Math.round(art.height*.07));
    ctx.save(); ctx.translate(0,h); ctx.scale(1,-1);
    ctx.drawImage(art,0,art.height-strip,art.width,strip,0,0,w,h-artEnd); ctx.restore();
  }
  const start = customPhoto ? titleY-180 : artEnd-70;
  const shade = ctx.createLinearGradient(0,start,0,h);
  shade.addColorStop(0,'rgba(5,15,20,0)'); shade.addColorStop(.46,customPhoto ? 'rgba(5,15,20,.74)' : 'rgba(5,15,20,.40)'); shade.addColorStop(1,'rgba(5,15,20,.78)');
  ctx.fillStyle = shade; ctx.fillRect(0,start,w,h-start);
  ctx.fillStyle = '#fff3dd';
  const family = 'system-ui, "Microsoft YaHei", sans-serif';
  ctx.font = '600 35px '+family; ctx.fillText(title,left,titleY,490);
  ctx.textAlign = 'right'; ctx.font = '24px '+family;
  ctx.fillText(caption,right,titleY,408);
  ctx.textAlign = 'left'; ctx.fillRect(left,titleY+24,right-left,1.5);
  metrics.forEach(([label,value],i) => {
    const x = left + i%columns*(right-left)/columns, y = titleY+72+Math.floor(i/columns)*86;
    ctx.font = '24px '+family; ctx.fillText(label,x,y,285);
    ctx.font = '600 34px '+family; ctx.fillText(value,x,y+42,285);
  });
  return new Promise((resolve,reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(Error('PNG')), 'image/png'));
}

function workKmText(value){return Number.isFinite(value)?value.toFixed(2)+' km':'—'}
function workClock(sec){return Number.isFinite(sec)&&sec>=0?clock(Math.round(sec)):'—'}
function workReview(a){
 const groups=a.workGroups||[];
 if(!groups.length)return '';
 const phases=[];
 for(const l of a.laps||[]){
   const [sec,kind]=Array.isArray(l)?[l[1],l[3]]:[l.sec,l.kind||l.stage];
   const tag=({WARMUP:'热身',COOLDOWN:'缓和',REST:'休息',RECOVERY:'恢复','休息':'休息','恢复':'恢复','热身':'热身','缓和':'缓和'})[kind]||'工作';
   if(!(sec>0))continue;
   if(phases.at(-1)?.tag===tag)phases.at(-1).sec+=sec;else phases.push({tag,sec});
 }
 const rests=phases.filter(p=>p.tag==='恢复'||p.tag==='休息');
 const recovery=rests.length&&rests.every(p=>Math.round(p.sec)===Math.round(rests[0].sec))?'组间恢复 '+workClock(rests[0].sec):'';
 const uniform=groups[0].sec>0&&groups.every(g=>Math.round(g.sec)===Math.round(groups[0].sec));
 const secs=Math.round(groups[0].sec), repeat=uniform?groups.length+' × '+(secs%60===0?secs/60+' 分钟':workClock(secs)):groups.length+' 组';
 const kind=/阈值|\bT\s*\d/i.test(a.name||'')?'阈值跑':/间歇|interval/i.test(a.name||'')?'间歇跑':'工作段';
const last=groups.at(-1), prior=groups.at(-2);
 const compare=last.sec>0&&last.km>0&&prior&&last.hr>0&&prior.hr>0?
   '最后一组均配 '+workClock(last.sec/last.km)+'/km，'+(Math.round(last.hr)===Math.round(prior.hr)?'平均心率与上一组同为 '+Math.round(last.hr)+' 次/分。':'平均心率 '+Math.round(last.hr)+' 次/分，上一组 '+Math.round(prior.hr)+' 次/分。'):'';
 const labels=[phases[0]?.tag==='热身'?'热身':'',recovery,phases.at(-1)?.tag==='缓和'?'缓和':''].filter(Boolean);
 const rows=groups.map((g,i)=>'<button type="button" class="wk-row wk-group" aria-expanded="false" data-wk-first="'+Number(g.first)+'" data-wk-last="'+Number(g.last)+'" data-sec="'+(g.sec??'')+'" data-km="'+(g.km??'')+'"><strong>第 '+(i+1)+' 组</strong><b>'+workClock(g.sec>0&&g.km>0?g.sec/g.km:null)+'</b><b>'+(g.hr>0?Math.round(g.hr):'—')+'</b><span aria-hidden="true">›</span></button>').join('');
 return '<section class="wk-review" data-work-session="'+Number(a.run||a.id)+'"><div class="wk-hero"><small>'+esc(a.date||'')+'</small><h3>'+repeat+' '+kind+'</h3><div>全程 <b>'+esc(workKmText(a.km??a.distance))+'</b>　计时 <b>'+workClock(a.seconds)+'</b></div>'+
 (phases.length?'<div class="wk-track" aria-hidden="true">'+phases.map(x=>'<i class="'+(x.tag==='工作'?'on':x.tag==='休息'||x.tag==='恢复'?'pause':'')+'" style="flex-grow:'+x.sec+'"></i>').join('')+'</div>':'')+(labels.length?'<small>'+labels.join(' · ')+'</small>':'')+
 '</div><div class="wk-heading"><strong>工作段对照</strong><small>点一组看曲线</small></div><div class="wk-list"><div class="wk-row wk-label"><span>工作段</span><span>均配 /km</span><span>均心 bpm</span><span></span></div>'+rows+'</div>'+(compare?'<div class="wk-verdict"><strong>复盘要点</strong><p>'+compare+'</p></div>':'')+'</section>';
}

const workCurveCache=new Map();
async function workSamples(id){
 if(!workCurveCache.has(id)){
   const request=(typeof desktopWorkSamples==='function'?desktopWorkSamples(id):api('/api/topic/'+encodeURIComponent('工作段曲线_'+id))).catch(e=>{workCurveCache.delete(id);throw e});
   workCurveCache.set(id,request);
   if(workCurveCache.size>6)workCurveCache.delete(workCurveCache.keys().next().value);
 }
 return workCurveCache.get(id);
}
function drawWorkPlot(panel,curves,series){
 const pts=series.points, span=series.span, x=t=>34+t/span*286;
 const keep=(n)=>Number.isFinite(n)&&n>0;
 let base='',guides=[];
 for(const [key,top,step,color,label] of [[1,19,15,'#842f50','配速 · 分/km'],[2,105,5,'#286589','心率 · bpm']]){
   let lo=Infinity,hi=-Infinity;
   for(const g of curves)for(const p of g.points)if(keep(p[key])){lo=Math.min(lo,p[key]);hi=Math.max(hi,p[key])}
   base+='<text x="34" y="'+(top-5)+'" fill="'+color+'">'+label+'</text>';
   if(!pts.some(p=>keep(p[key]))){base+='<text x="34" y="'+(top+26)+'">暂无采样</text>';continue}
   lo=Math.floor(lo/step)*step;hi=Math.max(lo+step,Math.ceil(hi/step)*step);
   const y=v=>top+(key===1?(v-lo)/(hi-lo):(hi-v)/(hi-lo))*47;
   for(const v of [lo,hi])base+='<path stroke="#ddd5cd" stroke-dasharray="3 3" d="M34 '+y(v)+'H320"/><text x="29" text-anchor="end" y="'+(y(v)+3)+'">'+(key===1?workClock(v):v)+'</text>';
   let line='',previous=null;
   for(const p of pts){
     if(!keep(p[key])){previous=null;continue}
     line+=(previous===null||p[0]-previous>2?'M':'L')+x(p[0]).toFixed(1)+' '+y(p[key]).toFixed(1)+' ';
     if(previous===null||p[0]-previous>2)line+='l0.1 0 ';
     previous=p[0];
   }
   base+='<path fill="none" stroke="'+color+'" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" d="'+line+'"/>';
   guides.push({key,top,color,y});
 }
 for(let i=0;i<=3;i++)base+='<text x="'+x(i*span/3)+'" text-anchor="'+(['start','middle','middle','end'][i])+'" y="174">'+workClock(span*i/3)+'</text>';
 const plot=panel.querySelector('svg'),read=panel.querySelector('.wk-read');
 plot.innerHTML=base+'<g class="wk-mark"></g>';
 const marker=plot.querySelector('.wk-mark');
 let current=0;
 function select(i){
   current=Math.min(pts.length-1,Math.max(0,i));const p=pts[current];
   marker.innerHTML=guides.map(({key,top,color,y})=>'<path stroke="#9b8387" stroke-dasharray="2 3" d="M'+x(p[0])+' '+top+'v47"/>'+(keep(p[key])?'<circle cx="'+x(p[0])+'" cy="'+y(p[key])+'" r="3" fill="'+color+'" stroke="white"/>':'')).join('');
   read.innerHTML='<span>组内 '+workClock(p[0])+'</span><b>'+(keep(p[1])?workClock(p[1])+'/km':'—')+'</b><b>'+(keep(p[2])?Math.round(p[2])+' bpm':'—')+'</b>';
 }
 function nearest(time){let l=0,r=pts.length-1;while(l<r){const m=(l+r)>>1;if(pts[m][0]<time)l=m+1;else r=m}return l&&time-pts[l-1][0]<=pts[l][0]-time?l-1:l}
 select(nearest(span/2));
 plot.onpointermove=plot.onpointerdown=e=>{const b=plot.getBoundingClientRect();select(nearest(((e.clientX-b.left)*328/b.width-34)*span/286))};
 plot.onkeydown=e=>{if(!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();select(current+(e.key==='ArrowRight'?1:-1))};
}
document.addEventListener('click',async event=>{
 const button=event.target.closest('.wk-group');if(!button)return;
 const section=button.closest('.wk-review'),opening=button.getAttribute('aria-expanded')==='false';
 section.querySelector('.wk-panel')?.remove();
 for(const b of section.querySelectorAll('.wk-group'))b.setAttribute('aria-expanded','false');
 if(!opening)return;
 button.setAttribute('aria-expanded','true');
 const panel=document.createElement('div');panel.className='wk-panel';panel.textContent='正在读取本组采样…';button.after(panel);
 try{
   const curves=await workSamples(section.dataset.workSession);
   if(!panel.isConnected)return;
   const group=curves.find(c=>c.first===Number(button.dataset.wkFirst)&&c.last===Number(button.dataset.wkLast));
   if(!group?.points?.some(p=>p[1]>0||p[2]>0)){panel.textContent='本组暂无可定位的配速或心率采样。';return}
   panel.innerHTML='<div class="wk-heading"><strong>组内曲线</strong><small>'+workClock(Number(button.dataset.sec)||null)+' · '+(button.dataset.km?workKmText(Number(button.dataset.km)):'—')+'</small></div><svg viewBox="0 0 328 185" tabindex="0" role="img" aria-label="组内配速和心率曲线，左右方向键查看采样"></svg><div class="wk-read"></div>';
   drawWorkPlot(panel,curves,group);
 }catch{if(panel.isConnected)panel.textContent='读取失败，收起后再点本组重试。'}
});



// The active question and review dates are shared by the mobile and desktop journals.
function focusDayAt(now=new Date()){
 return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
}
function journalFocusTopics(day=focusDayAt(), topics=[]){
 if(!Array.isArray(topics)) return [];
 return topics.filter(topic=>topic && topic.key && topic.title && topic.date && topic.date<=day)
   .map(topic=>({...topic, archived:Boolean(topic.archived || (topic.end_date && day>topic.end_date))}));
}
function focusOwnsReport(topic,title,date){
 return title===topic.title && date>=topic.date && (!topic.end_date || date<=topic.end_date);
}
function qualifiesFocus(spec){
 return !!spec && ['question','decision','evidence','checkpoint','exit'].every(k=>typeof spec[k]==='string'&&spec[k].trim().length>0);
}
function focusContent(topic,records=''){
 const row=(label,value)=>'<div><dt>'+esc(label)+'</dt><dd>'+esc(value)+'</dd></div>';
 const nodes=Array.isArray(topic.nodes)?topic.nodes.filter(n=>Array.isArray(n)&&n.length===2):[];
 return '<section class="focus-content"><h3>'+esc(topic.title)+'</h3>'+
   (topic.intro?'<dl>'+row('要决定什么',topic.intro)+'</dl>':'')+
   (records?'<h4>已归档的复核</h4>'+records:'')+
   (nodes.length?'<h4>复核节点</h4><dl>'+nodes.map(([label,value])=>row(label,value)).join('')+'</dl>':'')+
   '</section>';
}

// Recovery feedback belongs to the run on the previous day; weeks start on Monday in Beijing.
function pastLegReviewWeek(morning,today=focusDayAt()){
 const monday=new Date(today+'T00:00:00Z');monday.setUTCDate(monday.getUTCDate()-(monday.getUTCDay()+6)%7);
 return Date.parse(morning+'T00:00:00Z')-86400000<monday.getTime();
}
