"""Adapt compatible live templates without writing to index.html or affecting exports."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parent
MAP=r'^const footprintRegions=(\[.*\]);[ \t]*$'

def geometry(page):
    return re.search(MAP,page,re.M)

def enhance(page):
    script=(ROOT/'desk_demand.js').read_text(encoding='utf8')
    changes=[
        ("const response=await fetch('/api/running/'+encodeURIComponent(r.id)+'/raw');", "const response=await fetch(D._desk_lite?'/api/desk-v3/curve/'+encodeURIComponent(r.id):'/api/running/'+encodeURIComponent(r.id)+'/raw');"),
        ("const today=stageDateLimit(),first=rows.map(r=>r.date).sort()[0]||today;", "const today=stageDateLimit(),first=D.careerDays?.[0]?.[0]||rows.map(r=>r.date).sort()[0]||today;"),
        ("const last=rows.map(r=>r.date).sort().at(-1)||today;", "const last=D.careerDays?.at(-1)?.[0]||rows.map(r=>r.date).sort().at(-1)||today;"),
        ("    $('#career-stats').innerHTML=", "    let count=filtered.length;if(D.careerDays){km=sec=pairedKm=pairedSec=count=0;for(const [day,n,k,t,pk,pt] of D.careerDays){if(valid&&day>=from&&day<=to){count+=n;km+=k;sec+=t;pairedKm+=pk;pairedSec+=pt}}}\n    $('#career-stats').innerHTML="),
        ("metricCell('跑步次数',valid?filtered.length:", "metricCell('跑步次数',valid?count:"),
        ('async function load(){',script+'\nasync function load(){'),
        ('try{result=await fetchArchive(controller.signal,bytes=>{','try{result=await deskInitial(controller.signal,bytes=>{'),
        ('function navigate(p){','function navigate(p){if(deskGuard(p))return;'),
        ('function renderSelectedPage(){','function renderSelectedPage(){if(deskPaged())return;'),
        ("function runDetails(r,entry='data'){if(!r)return;", "function runDetails(r,entry='data'){if(!r)return;if(D._desk_lite&&!r._deskReady){deskRun(r,entry);return}"),
        ('${runLapSection(r,laps)}</section>', "${D._desk_lite?'':runLapSection(r,laps)}</section>"),
        ("if(i===2){const c=$('#run-pane-2", "if(i===1&&D._desk_lite)deskLaps(r);if(i===2){const c=$('#run-pane-2"),

        ("if(!activity&&D._page_projection){", "if(!activity&&D._desk_lite){deskRun({id:run.id},'review');return}if(!activity&&D._page_projection){"),
    ]
    line=geometry(page)
    if not line or any(page.count(old)!=1 for old,_ in changes):return page
    page=page[:line.start()]+'let footprintRegions=[];'+page[line.end():]
    for old,new in changes:page=page.replace(old,new,1)
    return page

