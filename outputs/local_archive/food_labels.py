"""Exact barcode lookups and packaging-label OCR for the private food journal."""
import base64
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import subprocess
from threading import BoundedSemaphore, Timer
import unicodedata

ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / 'food-catalog.sqlite3'
OCR_SLOTS = BoundedSemaphore(2)

def barcode_key(code):
    if not re.fullmatch(r'(?:[0-9]{8}|[0-9]{12,14})', code):
        return None
    checksum = sum(int(d)*(3 if i%2 else 1) for i,d in enumerate(reversed(code)))
    return code.zfill(14) if not checksum%10 else None

def catalog_lookup(code):
    key = barcode_key(code)
    if not key:
        return 400, {'error':'条码无效'}
    try:
        with closing(sqlite3.connect(CATALOG.as_uri()+'?mode=ro', uri=True)) as db:
            row = db.execute('SELECT name,spec FROM products WHERE code=?',(key,)).fetchone()
    except sqlite3.Error:
        return 503, {'error':'国内商品库暂时无法读取'}
    return (200,dict(name=row[0],spec=row[1])) if row else (404,{'error':'国内商品库未收录'})

def visual_rows(words):
    """Join words from the same printed row even when the OCR engine groups by column."""
    groups=[]
    for word in sorted(words,key=lambda w: -w['h']):
        top,height=word['y'],max(word['h'],1)
        center=top+height/2
        near=[g for g in groups if g[0]-.12*g[1]<=center<=g[0]+1.12*g[1]]
        if near:
            min(near,key=lambda g:abs(center-g[0]-g[1]/2))[2].append(word)
        else:
            groups.append((top,height,[word]))
    return [' '.join(w['t'] for w in sorted(group,key=lambda w:w['x'])) for _,__,group in sorted(groups,key=lambda g:g[0])]

NAMES = {
    'kcal':r'能量|热量|energy','p':r'蛋白质|protein','c':r'碳水化合物|carbohydrate',
    'f':r'^(?:总)?脂肪|^totalfat|^fat','fiber':r'膳食纤维|dietaryfib(?:er|re)',
    'sodium':r'钠|sodium','sugars':r'^(?:其中[:：-]?)?(?:总糖|糖|sugars?)',
    'calcium':r'钙|calcium','iron':r'铁|iron','vitc':r'维生素c|维他命c|vitaminc',
}
WEIGHT_UNIT = r'毫升|毫克|微克|千克|克|ml|mg|[μµu]g|kg|g'
MASS = {'毫克':.001,'mg':.001,'微克':.000001,'μg':.000001,'ug':.000001,'克':1,'g':1,'千克':1000,'kg':1000}
def parse_label(lines):
    # Two separated digit tokens without a decimal point are ambiguous (e.g. '3 2 g').
    rows=[]
    for line in lines:
        line=unicodedata.normalize('NFKC',line).lower().replace('公克','克').replace('·','.')
        # On labels such as “钠(mg) 58 3%”, remove the separate NRV cell first.
        line=re.sub(r'\s+\d+(?:[.,]\d+)?\s*%\s*$','',line)
        line=re.sub(r'(?<=\d)\s+(?=\d)',' ? ',line)
        rows.append(re.sub(r'\s+','',line))
    text='\n'.join(rows)
    # Multiple nutrition columns cannot be safely mapped to a single set of values.
    bases=set()
    for row in rows:
        for match in re.finditer(r'(?:每(?:一?份)?(?:[\(:约]*)|per(?:serving)?[\(:]*|/)(\d+(?:\.\d+)?)(毫升|ml|克|g)',row):
            size=float(match[1]);unit='ml' if match[2] in ('毫升','ml') else 'g'
            if 0<size<=100000:bases.add((size,unit))
    if not bases and re.search(r'(?:每份|份量|servingsize)',text):
        for match in re.finditer(r'(?:份量|servingsize|每份(?:含量|重量)?)[(:约为]*(\d+(?:\.\d+)?)(毫升|ml|克|g)',text):
            bases.add((float(match[1]),'ml' if match[2] in ('毫升','ml') else 'g'))
    dual=len(bases)>1 or (bool(re.search(r'每100(?:克|g|毫升|ml)',text)) and '每份' in text)
    base,unit=next(iter(bases)) if len(bases)==1 and not dual else (None,None)
    result={'base':base,'unit':unit,'energyUnit':None,'values':{},'lines':lines}
    if dual:
        result['notice']='检测到多个计量列，请对照包装选择一列填写。'
        return result
    uncertain=set()
    for row in rows:
        for key,pattern in NAMES.items():
            label=re.search(pattern,row)
            if not label:continue
            start=row[label.end():]
            if key=='sugars' and re.match(r'醇|原|类',start):continue
            units=r'千焦耳?|千卡|大卡|kcal|kj' if key=='kcal' else WEIGHT_UNIT
            unit_first=re.fullmatch(r'\(('+units+r')\)[:：]?(\d+(?:[.,]\d+)?)',start)
            if unit_first:start=unit_first[2]+unit_first[1]
            amounts=list(re.finditer(r'(?<![\d.%])(\d+(?:[.,]\d+)?)('+units+r')(?![a-z])',start))
            if len(amounts)!=1 or re.search(r'[<>≤≥]|小于|低于|不超过|~|～|\d[-–]\d',start):continue
            m=amounts[0];val=float(m[1].replace(',','.'));u=m[2]
            # An NRV percentage or second nutrient on the same row must not supply this field's value.
            if re.search(r'[?%\-]|[一-龥a-z]{2,}',start[:m.start()].strip(':()')):continue
            if key=='kcal':
                energy='kJ' if u.startswith('千焦') or u=='kj' else 'kcal'
            else:
                if u not in MASS:continue
                val=round(val*MASS[u]*(1000 if key in ('sodium','calcium','iron','vitc') else 1),6)
            if key in uncertain:continue
            if key in result['values'] and (result['values'][key]!=val or (key=='kcal' and result['energyUnit']!=energy)):
                result['values'].pop(key);uncertain.add(key);continue
            result['values'][key]=val
            if key=='kcal':result['energyUnit']=energy
            break
    return result

def valid_photo(data):
    # Only accept bounded JPEGs resized by the food page.
    if not data.startswith(b'\xff\xd8\xff') or not data.endswith(b'\xff\xd9'):return False
    pos=2
    while pos+4<len(data) and data[pos]==255:
        marker=data[pos+1]
        if marker==255:pos+=1;continue
        size=int.from_bytes(data[pos+2:pos+4],'big')
        if size<2 or pos+size+2>len(data):return False
        if marker in (192,193,194):
            return size>=8 and all(0<int.from_bytes(data[n:n+2],'big')<=2400 for n in (pos+5,pos+7))
        if marker==218:return False
        pos+=size+2
    return False

def photo_text(data):
    runtime=ROOT/'food-ocr-runtime'
    args=[str(runtime/'RapidOCR-json.exe'),'--ensureAscii=1','--numThread=2','--maxSideLen=1500',
          '--det=ch_PP-OCRv4_det_infer.onnx','--rec=rec_ch_PP-OCRv4_infer.onnx','--keys=dict_chinese.txt']
    with subprocess.Popen(args,cwd=runtime,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW) as proc:
        timer=Timer(25,proc.kill);timer.daemon=True;timer.start()
        try:
            proc.stdin.write(b'{"image_base64":"'+base64.b64encode(data)+b'"}\n');proc.stdin.flush()
            for line in proc.stdout:
                if not line.startswith(b'{'):continue
                answer=json.loads(line)
                if answer['code']==101:return []
                if answer['code']!=100:raise ValueError('Recognition failed')
                words=[]
                for item in answer['data']:
                    x,y=zip(*item['box'])
                    # An unreadable block keeps its place on this row without supplying a number.
                    words.append(dict(t=item['text'] if item['score']>=.86 else '?',x=min(x),y=min(y),h=max(y)-min(y)))
                return visual_rows(words)
            raise ValueError('Recognition interrupted')
        finally:
            timer.cancel()
            if proc.poll() is None:proc.kill()

def recognize_photo(data):
    if not valid_photo(data):return 400, {'error':'照片格式或尺寸有误，请重新选择照片。'}
    if not OCR_SLOTS.acquire(blocking=False):return 429,{'error':'识别正在使用，请稍后重试。'}
    try:
        result=parse_label(photo_text(data))
        result.pop('lines',None)
        return 200,result
    except (OSError,ValueError,subprocess.SubprocessError):
        return 503,{'error':'识别暂时无法完成，可重试或手动填写。'}
    finally:OCR_SLOTS.release()
