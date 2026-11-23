let feedbackDay=null, dayRecord=null;
const draftPrefix='running-coach:daily:v1:';
function readDailyDraft(day){
  try{return JSON.parse(localStorage.getItem(draftPrefix+day))}catch{return null}
}
function feedbackToday(){return new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'})}
function dayUnavailable(day,offline){
 v.innerHTML=button('‹ 今天','dailyback')+heading('每日反馈')+'<label>反馈归属日期<input id="dayDate" type="date" value="'+esc(day)+'" max="'+esc(feedbackToday())+'"></label>'+p(offline?'这一天没有离线草稿。可选其他日期继续草稿，或联网后填写。':'未能读取这一天的反馈。')+(offline?'':'<button id="retryDay" type="button">重新读取</button>');
 q('#dayDate').onchange=e=>{if(e.target.value&&e.target.validity.valid)openDay(e.target.value)};
 if(!offline)q('#retryDay').onclick=()=>openDay(day);
}
function clearDailyDrafts(){
  for(const key of Object.keys(localStorage))if(key.startsWith(draftPrefix))localStorage.removeItem(key);
}
async function openDay(day){
  msg.textContent='';
  feedbackDay=day;
  const draft=readDailyDraft(day);
  if(draft?.record){dayRecord=draft.record;render();return}
  dayRecord=null;
  if(q('#offline-shell')){dayUnavailable(day,true);return}
  render();
  try{
    const record=await api('/api/day/'+day);
    if(feedbackDay===day){dayRecord=record;render()}
  }catch(error){
    if(feedbackDay!==day)return;
    dayUnavailable(day,false);
    msg.textContent=error.message;
  }
}
// Keep the daily strength entry readable in the desktop journal and review exports.
const strengthLabels=['动作','重量','组数','次数/时长','RIR'];
function unpackStrength(text){
 const entries=[],notes=[];
 for(const line of (text||'').split('\n')){
   const parts=line.split('\t');
   if(parts.length===strengthLabels.length && parts.every((part,i)=>part.startsWith(strengthLabels[i]+'：'))){
     entries.push(parts.map((part,i)=>{const value=part.slice(strengthLabels[i].length+1);return value==='—'?'':value}));
   }else notes.push(line);
 }
 return {entries,notes:notes.join('\n')};
}
const weightBases=['每只','每侧','总重量','自重'];
function splitStrengthWeight(text){
 if(text==='自重')return {basis:'自重',amount:''};
 const match=text.match(/^(每只|每侧|总重量|总负重|总重)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(?:kg|公斤|千克)?$/i) || text.match(/^(每只|每侧|总重量)\s+(.+)$/);
 return match?{basis:match[1].startsWith('总')?'总重量':match[1],amount:match[2]}:{basis:'',amount:text};
}
function packStrengthWeight(row,amount){
 const select=row.querySelector('[data-weight-basis]'),basis=select.value;
 if(basis==='自重')return '自重';
 const original=row.dataset.originalWeight;
 const prior=splitStrengthWeight(original);
 if(amount===prior.amount && basis===prior.basis)return original;
 const input=row.querySelector('[data-actual]');
 if(!amount && basis){input.focus();throw Error('请填入所选口径对应的重量。')}
 if(!amount)return '';
 if(amount==='自重'){
   if(basis){select.focus();throw Error('自重动作请选择“自重”。')}
   return amount;
 }
 const parsed=splitStrengthWeight(amount);
 if(parsed.basis && basis && parsed.basis!==basis){
   select.focus();throw Error('填写的重量与所选口径不同，请核对。');
 }
 const kind=basis||parsed.basis;
 if(!kind && /\d/.test(amount)){select.focus();throw Error('请为这个重量选择每只、每侧或总重量。')}
 const numeric=parsed.amount.match(/^(\d+(?:\.\d+)?)\s*(?:kg|千克|公斤)?$/i);
 return [kind,numeric?numeric[1]+' kg':parsed.amount].filter(Boolean).join(' ');
}
function strengthEditor(host,plans,previous,onEdit,draft){
 const {entries,notes}=unpackStrength(previous);
 const planDetails=plans.map(plan=>'<details><summary>'+esc(plan.title||'当日课表')+'</summary>'+p(plan.details)+'</details>').join('');
 host.innerHTML='<h2>力量训练</h2>'+planDetails+'<div class="strength-rows"></div><p><small>锻炼时长（估算） <output data-duration>—</output></small></p><button type="button" class="strength-add">＋ 手动添加动作</button>';
 const list=host.querySelector('.strength-rows');
 function add(plan,values=['','','','','']){
   const row=document.createElement('div');row.className='strength-row';
   const name=plan?.name||values[0];
   const title=plan?'<strong>'+esc(name)+'</strong><small>计划 '+esc(plan.dose)+'</small>':'<label>动作名称<input data-name maxlength="100" value="'+esc(name)+'"></label><button type="button" class="strength-remove">移除</button>';
   const weight=splitStrengthWeight(values[1]);
   row.dataset.originalWeight=values[1];
   const basisField='<label>重量口径<select data-weight-basis aria-label="重量口径"><option value="">请选择</option>'+weightBases.map(b=>'<option'+(b===weight.basis?' selected':'')+'>'+b+'</option>').join('')+'</select></label>';
   row.innerHTML='<div class="strength-title">'+title+'</div><div class="strength-fields">'+
     ['重量（kg）','组数','次数 / 秒','RIR'].map((label,i)=>{
       const attrs=['type="text" maxlength="48" placeholder="公斤数"','type="number" inputmode="numeric" min="1" step="1"','type="text" maxlength="48" placeholder="如 8 次"','type="number" inputmode="decimal" min="0" max="10" step="any"'][i];
       return '<label>'+label+'<input data-actual '+attrs+' value="'+esc(i===0?weight.amount:values[i+1])+'"></label>'+(i===0?basisField:'');
     }).join('')+'</div>';
   const basis=row.querySelector('[data-weight-basis]'), kilograms=row.querySelector('[data-actual]');
   function updateWeightInput(){
     kilograms.disabled=basis.value==='自重';
     if(kilograms.disabled)kilograms.value='';
     kilograms.placeholder=kilograms.disabled?'无需填写':'公斤数';
   }
   updateWeightInput();
   basis.onchange=()=>{updateWeightInput();onEdit()};
   if(plan){row.dataset.plannedName=name;row.dataset.dose=plan.dose}
   list.append(row);
   const remove=row.querySelector('.strength-remove');
   if(remove)remove.onclick=()=>{row.remove();onEdit()};
   return row;
 }
 if(draft){
   for(const item of draft.rows){
     const row=add(item.plan,item.values);
     row.querySelector('[data-weight-basis]').value=item.basis;
     const inputs=row.querySelectorAll('[data-actual]');
     inputs.forEach((input,i)=>input.value=item.inputs[i]);
     inputs[0].disabled=item.basis==='自重';
     inputs[0].placeholder=inputs[0].disabled?'无需填写':'公斤数';
   }
 }else for(const plan of plans.flatMap(p=>p.items)){
   const index=entries.findIndex(e=>e[0]===plan.name);
   add(plan,index<0?undefined:entries.splice(index,1)[0]);
 }
 if(!draft)for(const entry of entries)add(null,entry);
 if(notes||draft?.notes){
   const label=document.createElement('label');label.textContent='已有力量记录';
   const textarea=document.createElement('textarea');textarea.dataset.strengthNotes='';textarea.value=draft?.notes??notes;label.append(textarea);host.append(label);
 }
 host.querySelector('.strength-add').onclick=()=>{add(null).querySelector('[data-name]').focus();onEdit()};
 function snapshot(){
   const rows=Array.from(list.children,row=>{
     const plan=row.dataset.plannedName?{name:row.dataset.plannedName,dose:row.dataset.dose}:null;
     return {plan,values:[row.querySelector('[data-name]')?.value||'',row.dataset.originalWeight,'','',''],
       inputs:Array.from(row.querySelectorAll('[data-actual]'),input=>input.value),basis:row.querySelector('[data-weight-basis]').value};
   });
   return {rows,notes:host.querySelector('[data-strength-notes]')?.value||''};
 }
 function collect(){
   const lines=[];
   const originalNotes=host.querySelector('[data-strength-notes]')?.value;
   if(originalNotes)lines.push(originalNotes);
   for(const row of list.children){
     const input=row.querySelector('[data-name]');
     const name=row.dataset.plannedName||input?.value.trim();
     const actual=[...row.querySelectorAll('[data-actual]')].map(el=>el.value.trim());
     actual[0]=packStrengthWeight(row,actual[0]);
     if(!actual.some(Boolean)){
       if(input?.value.trim()){input.focus();throw Error('请为手动添加的动作填写至少一项实绩。')}
       continue;
     }
     if(!name){input.focus();throw Error('请填写动作名称。')}
     const values=[name,...actual];
     lines.push(strengthLabels.map((label,i)=>label+'：'+(values[i].replace(/\t/g,' ')||'—')).join('\t'));
   }
   const text=lines.join('\n');
   if(text.length>6000)throw Error('当天力量反馈超过 6000 字，请缩短后保存。');
   return text;
 }
 function refreshDuration(){
   let seconds=0,rounds=0;
   const output=host.querySelector('[data-duration]');
   output.title='每次动态动作按3秒，静态动作按填写的秒数。左右连续做完算一组，组间和动作间按2分钟。';
   if(host.querySelector('[data-strength-notes]')?.value.trim()){output.textContent='—';return}
   for(const row of list.children){
     const [weight,sets,dose,rir]=[...row.querySelectorAll('[data-actual]')].map(input=>input.value.trim());
     if(!sets&&!dose&&!weight&&!rir&&!row.querySelector('[data-weight-basis]').value)continue;
     const name=row.dataset.plannedName||row.querySelector('[data-name]')?.value||'';
     const count=Number(sets),match=dose.match(/^(每侧|每边|单侧)?\s*(\d+)\s*(次|秒|步)?$/);
     if(!name||!Number.isSafeInteger(count)||count<=0||!match||Number(match[2])<=0){output.textContent='—';return}
     const sides=match[1]||/每侧|每边/.test(name)?2:1;
     const held=match[3]==='秒'||(!match[3]&&(/秒/.test(row.dataset.dose||'')||/平板/.test(name)));
     rounds+=count;
     seconds+=count*sides*Number(match[2])*(held?1:3);
   }
   output.textContent=rounds?'约 '+Math.round((seconds+(rounds-1)*120)/60)+' 分钟':'—';
 }
 refreshDuration();
 return {snapshot,collect,refreshDuration};
}

function dailyView(){
 if(!dayRecord){v.innerHTML=p('正在读取每日反馈…');return}
 const fields=dayRecord.fields;v.innerHTML=button('‹ 今天','dailyback')+heading('每日反馈')+'<form id="daily"><label>反馈归属日期<input type="date" id="dayDate" value="'+esc(feedbackDay)+'" max="'+esc(feedbackToday())+'"></label><label>当天体感<textarea id="feeling"></textarea></label><label>拉伸记录<textarea id="stretch"></textarea></label><div class="tabs"><button type="button" id="noStretch">没做拉伸</button></div><section class="daily-strength" aria-label="力量训练"></section><button type="submit" class="primary">保存这一天的反馈</button><p id="dailyStatus" role="status" aria-live="polite"></p></form>';
 const draft=readDailyDraft(feedbackDay);
 q('#feeling').value=draft?.overall??fields.overall??'';
 q('#stretch').value=draft?.stretching??fields.stretching??'';
 q('#dayDate').onchange=e=>{if(e.target.value&&e.target.validity.valid)openDay(e.target.value).catch(err=>msg.textContent=err.message)};
 const form=q('#daily'), save=form.querySelector('[type=submit]'), notice=q('#dailyStatus');
 const submitted=feedbackDay;
 let pending=draft?.pending||null, saved=false;
 const editor=strengthEditor(form.querySelector('.daily-strength'),dayRecord.strengthPlans||[],fields.strength,edited,draft?.strength);
 const draftKey=draftPrefix+submitted;
 function persist(){
   const entry={record:dayRecord,updated:Date.now(),overall:q('#feeling').value,stretching:q('#stretch').value,
     strength:editor.snapshot(),pending};
   try{localStorage.setItem(draftKey,JSON.stringify(entry));return true}
   catch{return false}
 }
 function edited(){
   editor.refreshDuration();
   if(saved){saved=false;save.disabled=false;save.textContent='保存这一天的反馈'}
   notice.textContent=persist()?'草稿已存到本机':'浏览器无法保存本机草稿，请保留此页面。';
 }
 if(draft)notice.textContent='已恢复 '+submitted+' 的本机草稿。';
 form.oninput=e=>{if(e.target.id!=='dayDate')edited()};
 q('#noStretch').onclick=()=>{q('#stretch').value='未做拉伸';edited()};
 form.onsubmit=async event=>{
   event.preventDefault();
   if(busy||saved)return;
   const fields={...dayRecord.fields,overall:q('#feeling').value,stretching:q('#stretch').value};
   try{fields.strength=editor.collect()}catch(err){notice.textContent=err.message;return}
   if(!Object.values(fields).some(value=>String(value??'').trim())){
     notice.textContent='请至少填写一项反馈。';q('#feeling').focus();return;
   }
   const payload={date:submitted,expected_revision:dayRecord.revision,fields};
   const controls=[...form.elements].filter(control=>!control.disabled);
   busy=true;controls.forEach(control=>control.disabled=true);
   save.textContent='正在保存…';notice.textContent='正在写入训练手记…';
   try{
     const signature=JSON.stringify(payload);
     if(pending?.signature!==signature)pending={signature,id:crypto.randomUUID()};
     persist();
     const result=await api('/api/day-feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...payload,request_id:pending.id})});
     // A second tab may already have edited this date. Only clear the acknowledged draft.
     if(readDailyDraft(submitted)?.pending?.id===pending.id){
       const latest=readDailyDraft(submitted);
       if(latest.overall===q('#feeling').value && latest.stretching===q('#stretch').value &&
          JSON.stringify(latest.strength)===JSON.stringify(editor.snapshot()))localStorage.removeItem(draftKey);
     }
     pending=null;
     saved=true;
     if(result.current_revision>result.revision){
       const fresh=await api('/api/day/'+submitted);
       if(feedbackDay===submitted){dayRecord=fresh;render()}
       msg.textContent='此前提交已确认，此日期后来有更新。';
     }else{
       dayRecord={...dayRecord,revision:result.revision,fields};
       notice.textContent=submitted+' 的反馈已保存，待教练复核。';
     }
   }catch(error){
     notice.textContent=error.message;
     if(error.status===409){
       const reload=document.createElement('button');
       reload.type='button';reload.textContent='查看最新记录';
       reload.onclick=async()=>{
         try{
           const fresh=await api('/api/day/'+submitted);
           const summary=[fresh.fields.overall,fresh.fields.stretching,fresh.fields.strength].filter(Boolean).join('\\n');
           if(confirm('服务器最新记录\\n'+summary+'\\n\\n放弃本机这一天的草稿并载入此记录？')){
             localStorage.removeItem(draftKey);dayRecord=fresh;render();
           }
         }catch(err){notice.textContent=err.message}
       };
       notice.append(' ',reload);
     }
   }
   finally{
     busy=false;controls.forEach(control=>control.disabled=false);save.disabled=saved;
     save.textContent=saved?'已保存':'保存这一天的反馈';
   }
 };
}

