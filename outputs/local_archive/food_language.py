"""Parse food descriptions on the same computer as the diary. No external HTTP routes."""
import base64
import json
import math
import re
import os
from pathlib import Path
import subprocess
import threading
import time
import urllib.error
import urllib.request

DIRECTORY = Path(os.environ['LOCALAPPDATA']) / 'RunningCoach' / 'meal-model'
BASE = 'http://127.0.0.1:18876'
MODEL = 'shiheng-qwen25-3b'
KINDS = ['早餐','午餐','晚餐','加餐']
UNITS = ['克','毫升','块','个','份','碗','杯','罐','瓶','片','只','根','盒','袋','勺','未说明']
SLOT = threading.BoundedSemaphore(1)
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def record(properties):
    return dict(type='object',properties=properties,required=list(properties),additionalProperties=False)

ITEM = record({'quote':{'type':'string'},'name': {'type':'string'},'amount':{'type':'number'},'unit':{'enum':UNITS},
               'approx':{'type':'boolean'}})
MEAL = record({'note':{'type':'string'},'kind':{'enum':KINDS},'skipped':{'type':'boolean'},'items':{'type':'array','items':ITEM}})
SCHEMA = record({'meals':{'type':'array','items':MEAL}})

PROMPT = """你是中文饮食日记的信息抽取器。阅读整段原文，理解指代、否定、修正及实际食用量后输出 JSON。
note逐字摘取属于本餐的原文。早餐、午餐、晚餐、加餐是不同的餐次，有几个就分别生成几个对象。先读完整段，尤其不要跳过开头几餐。例如“早餐牛奶，午餐米饭，晚餐没吃”依次生成早餐牛奶、午餐米饭、晚餐跳过三个对象。只记录用户实际吃喝的食物。没喝、留在锅底、为别人点、明天打算吃的都不要列入。按餐次分组，未说餐次用界面所选餐次。明确说没吃整餐才写 skipped=true。不要编造食品、重量、部位或营养数值。
quote 必须逐字摘取原文里只对应这一项食物及其数量的最短连续片段；不要把整餐或相邻食物复制进同一项。name 是用户所指食物的简明名称；尽量保留商品名、菜名。‘鸡肉’不可细化成鸡胸肉。汤水与明确吃掉的肉块分开，容量属于汤，块数属于肉。一碗又说明毫升，以毫升优先。同一食物仅列一次。
amount 是实际吃下的数量，只计算一次比例。半份干锅写0.5份，两份吃一半写1份，整碗200克吃一半写100克。没有数量时用0和未说明，切勿推测一个重量。公斤换克，升换毫升。保留块、个等计数，不得自行换成克。approx只在原文里明确说“大概、约、左右”等才为true。"""

def request_json(path,data=None,timeout=5,base=BASE):
    payload=json.dumps(data,ensure_ascii=False,allow_nan=False).encode() if data is not None else None
    req=urllib.request.Request(base+path,data=payload,headers={'Content-Type':'application/json'})
    with HTTP.open(req,timeout=timeout) as response:
        return json.load(response)

def ensure_model(base=BASE, model=MODEL, weights_name='qwen2.5-3b.gguf', projector=None):
    try:
        models=request_json('/v1/models',timeout=2,base=base)['data']
    except urllib.error.URLError:
        models=None
    if models is not None:
        if not any(m.get('id')==model for m in models):
            raise RuntimeError('本机模型端口正在被其他程序使用。')
        return
    exe=DIRECTORY/'runtime'/'llama-server.exe'
    weights=DIRECTORY/weights_name
    if not exe.is_file() or not weights.is_file():
        raise RuntimeError('未找到本机语言模型文件。')
    args=[str(exe),'-m',weights.name,'--alias',model,'--host','127.0.0.1','--port',base.rsplit(':',1)[1],
          '-c','8192','-t','8','-np','1','--no-webui','--log-disable']
    if projector:
        if not (DIRECTORY/projector).is_file():raise RuntimeError('未找到视觉模型的图像编码器。')
        args.extend(['--mmproj',projector])
    proc=subprocess.Popen(args,cwd=DIRECTORY,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(100):
        try:
            if any(m.get('id')==model for m in request_json('/v1/models',timeout=1,base=base)['data']):return
        except (OSError,ValueError,KeyError):pass
        if proc.poll() is not None:break
        time.sleep(.4)
    if proc.poll() is None:proc.terminate()
    raise RuntimeError('本机模型未能启动。')

def food_quote(text, item, items):
    name=item['name'].strip()
    quote=item.get('quote')
    clauses=[s.strip() for s in re.split(r'[，,；;、。！？\n]',text) if s.strip()]
    def simple(span):
        if name not in span:return False
        other=span.replace(name,'',1)
        other=re.sub(r'今天|今日|早餐|午餐|晚餐|加餐|吃了|喝了|我|一共|大概|大约|约|左右|毫升|公斤|千克|克|千卡|升|ml|kg|g|[0-9.一二两三四五六七八九十百半份个块片包袋杯瓶罐碗只勺根盒\s]','',other,flags=re.I)
        return not other and not any(x is not item and x.get('name')!=name and x.get('name') in span for x in items)
    for span in clauses:
        if simple(span):return span
    if isinstance(quote,str) and quote and quote in text and simple(quote):return quote
    return name if name in text else ''

def interpret(data):
    if not isinstance(data,dict):raise ValueError('缺少餐食描述')
    text=data.get('text')
    if not isinstance(text,str) or not 0<len(text.strip())<=1800 or data.get('kind') not in KINDS:
        raise ValueError('餐次或文字长度无效')
    if not SLOT.acquire(timeout=3):return 429,{'error':'本机正在理解另一段记录，请稍后再试。'}
    try:
        ensure_model()
        payload={'model':MODEL,'temperature':0,'seed':1,'max_tokens':2200,
                 'messages':[{'role':'system','content':PROMPT},{'role':'user','content':'以下是整段原文，按出现顺序逐餐提取，每一餐都要保留。只有原文完全没有说是哪餐时才使用'+data['kind']+'。\n'+text}],
                 'response_format':{'type':'json_schema','json_schema':{'name':'meal_diary','strict':True,'schema':SCHEMA}}}
        choice=request_json('/v1/chat/completions',payload,timeout=120)['choices'][0]
        if choice.get('finish_reason')!='stop':raise ValueError('incomplete')
        meals=json.loads(choice['message']['content'])['meals']
        if not isinstance(meals,list) or len(meals)>12:raise ValueError('invalid meals')
        for meal in meals:
            if not isinstance(meal['note'],str) or len(meal['note'])>1800 or meal['kind'] not in KINDS or type(meal['skipped']) is not bool or not isinstance(meal['items'],list) or len(meal['items'])>80:raise ValueError('invalid meal')
            for item in meal['items']:
                if not isinstance(item['name'],str) or not 0<len(item['name'].strip())<=80 or item['unit'] not in UNITS:raise ValueError('invalid food')
                item['quote']=food_quote(text,item,meal['items'])
                amount=item['amount']
                if type(amount) not in (float,int) or not math.isfinite(amount) or not 0<=amount<=100000 or type(item['approx']) is not bool:raise ValueError('invalid amount')
        return 200,{'meals':meals}
    except RuntimeError as err:return 503,{'error':str(err)}
    except (ValueError,KeyError,TypeError,IndexError,OSError):return 503,{'error':'本机模型未能完整读取这段描述，可重试或手动添加食物。'}
    finally:SLOT.release()


VISION_BASE='http://127.0.0.1:18877'
VISION_MODEL='shiheng-meal-vision'
VISION_SLOT=threading.BoundedSemaphore(1)

def recognize_photo(image):
    if not 0<len(image)<=2_500_000 or not image.startswith(bytes.fromhex('ffd8ff')):
        return 400,{'error':'请选择可读取的餐食照片。'}
    if not VISION_SLOT.acquire(timeout=2):
        return 429,{'error':'食衡电脑正在识别另一张照片，请稍后再试。'}
    try:
        ensure_model(VISION_BASE,VISION_MODEL,'Qwen2-VL-2B-Instruct-Q4_K_M.gguf','mmproj-Qwen2-VL-2B-Instruct-Q8_0.gguf')
        prompt='这是用户的一餐。请仔细看整张照片，包括盘碗和饮料罐。用简体中文列出能看见的菜品、主食和饮料，每种食品只列一次。不要列餐具或背景物件。混合菜列一道菜，肉类部位看不清可称肉菜。不要推测重量、吃了多少、油量或被遮住的原料。'
        url='data:image/jpeg;base64,'+base64.b64encode(image).decode('ascii')
        schema=record({'foods':dict(type='array',items=record({'name':{'type':'string'}}))})
        payload=dict(model=VISION_MODEL,temperature=0,seed=1,max_tokens=250,
            messages=[dict(role='user',content=[dict(type='image_url',image_url={'url':url}),dict(type='text',text=prompt)])],
            response_format={'type':'json_schema','json_schema':{'name':'photo_foods','strict':True,'schema':schema}})
        choice=request_json('/v1/chat/completions',payload,timeout=120,base=VISION_BASE)['choices'][0]
        if choice.get('finish_reason')!='stop':raise ValueError()
        foods=json.loads(choice['message']['content'])['foods']
        if not isinstance(foods,list):raise ValueError()
        names=dict.fromkeys(f['name'].strip() for f in foods if isinstance(f,dict) and isinstance(f.get('name'),str) and 0<len(f['name'].strip())<=60)
        return 200,{'foods':[{'name':name} for name in list(names)[:20]]}
    except RuntimeError as e:return 503,{'error':str(e)}
    except (OSError,KeyError,ValueError,TypeError,IndexError):
        return 503,{'error':'食衡电脑暂时未能读出这张照片，可以重试或写下菜名。'}
    finally:VISION_SLOT.release()
