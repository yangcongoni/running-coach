from pathlib import Path
from functools import lru_cache
from hashlib import sha256

from urllib.parse import parse_qs, urlsplit
import sqlite3
import food_overview

ROOT=Path(__file__).resolve().parent/'food_ui'
FILES=frozenset(['activity.js', 'app.js', 'archive-reader.js', 'assets/breakfast.jpg', 'assets/dinner.jpg', 'assets/hero.jpg', 'assets/overview-meal.webp', 'assets/lunch.jpg', 'backup.js', 'barcode.js', 'batch.js', 'coach-entry.js', 'coaching.js', 'engine.js', 'events.js', 'foods.js', 'imports.js', 'index.html', 'meals.js', 'pages.js', 'settings.js', 'style.css', 'training-archive.js', 'trends.js', 'vendor/ZXing-LICENSE.txt', 'vendor/zxing-0.21.3.min.js', 'vision-frame.html', 'vision.js'])
TYPES={'.js':'application/javascript', '.css':'text/css', '.html':'text/html; charset=utf-8',
       '.jpg':'image/jpeg', '.webp':'image/webp', '.txt':'text/plain; charset=utf-8'}
APP_POLICY=("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; media-src 'self' blob:; worker-src 'self'; "
            "connect-src 'self' https: data: blob:; frame-src 'self'; form-action 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; object-src 'none'")
# Remote ML code runs in an opaque origin without access to authenticated pages or storage.
MODEL_POLICY=("sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline' 'wasm-unsafe-eval' "
              "https://cdn.jsdelivr.net blob:; worker-src blob: https://cdn.jsdelivr.net; "
              "connect-src https://cdn.jsdelivr.net https://huggingface.co https://*.huggingface.co "
              "https://*.hf.co https://tessdata.projectnaptha.com https://*.projectnaptha.com data: blob:; "
              "img-src data: blob:; frame-ancestors 'self'; base-uri 'none'; form-action 'none'")

BUNDLES={
 'core.js':('coach-entry.js','foods.js','engine.js','imports.js','app.js','meals.js','demand-core.js','coaching.js','overview.js','events.js'),
 'report-tools.js':('pages.js','settings.js','trends.js'),
 'activity-tools.js':('activity.js','training-archive.js','vision.js'),
 'meal-tools.js':('batch.js','meal-text.js'),
 'backup-tools.js':('backup.js',),
 'scan-tools.js':('barcode.js',),
}
THUMBS={'assets/'+name+'-thumb.jpg' for name in ('hero','breakfast','lunch','dinner')}

@lru_cache(maxsize=48)
def resource(names,versions):
    data=b'\n;\n'.join((ROOT/name).read_bytes() for name in names)
    return data,'W/"'+sha256(data).hexdigest()[:24]+'"'

def serve(handler,path):
    if path=='/food':
        handler.send_response(303)
        handler.send_header('Location','/food/')
        handler.send_header('Cache-Control','no-store')
        handler.send_header('Content-Length','0')
        handler.end_headers()
        return
    name=path[len('/food/'):] or 'index.html'
    if not handler.authed():
        if name=='index.html':
            return handler.login_page('/food/')
        return handler.reply(401,{'error':'请先登录'})
    if name=='overview-activities':
        try:
            query=parse_qs(urlsplit(handler.path).query)
            return handler.reply(200,food_overview.read_activity_period(query.get('start',[''])[0],query.get('end',[''])[0]))
        except (ValueError,OverflowError):return handler.reply(400,{'error':'日期范围无效'})
        except (sqlite3.Error,OSError):return handler.reply(503,{'error':'跑步档案暂不可用'})
    if name=='overview-day':
        try:
            key=parse_qs(urlsplit(handler.path).query).get('date',[''])[0]
            return handler.reply(200,food_overview.read_day(key))
        except (ValueError, OverflowError):
            return handler.reply(400,{'error':'日期无效'})
        except (sqlite3.Error,OSError):
            return handler.reply(503,{'error':'跑步档案暂不可用'})
    if name not in FILES and name not in BUNDLES and name not in THUMBS:
        return handler.reply(404,{})
    try:
        names=BUNDLES.get(name,(name,))
        versions=tuple((ROOT/f).stat().st_mtime_ns for f in names)
        data,etag=resource(names,versions)
    except OSError:
        return handler.reply(503,{'error':'食衡文件暂不可用'})
    can_cache=name not in ('index.html','vision-frame.html')
    if can_cache and handler.headers.get('If-None-Match')==etag:
        return handler.reply(304,b'',TYPES[Path(name).suffix],etag=etag)
    return handler.reply(200,data,TYPES[Path(name).suffix],etag=etag if can_cache else None,
                         policy=MODEL_POLICY if name=='vision-frame.html' else APP_POLICY)
