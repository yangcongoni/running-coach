"""Machine-specific settings, stored beside the server outside version control."""
import base64
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
SETTINGS_FILE = ROOT / "archive.local.json"

def settings():
    return json.loads(SETTINGS_FILE.read_text(encoding="utf-8")) if SETTINGS_FILE.exists() else {}

def origin(setting, default):
    value = settings().get(setting, default).rstrip("/")
    url = urlsplit(value)
    if (not url.hostname or url.username is not None or url.password is not None
            or url.path or url.query or url.fragment or url.port == 0
            or not (url.scheme == "https" or
                    url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1"})):
        raise ValueError("Invalid origin in " + setting)
    return value

def stage_template(page, standalone=False):
    # The local server can serve the HTML file directly. Keep its artwork usable under a self-only image policy.
    for kind, filename in [('script','today_run.js'),('style','today_run.css')]:
        start = '/* today-run-' + kind + ':start */'
        end = '/* today-run-' + kind + ':end */'
        if start in page:
            before, block = page.split(start, 1)
            _, after = block.split(end, 1)
            page = before + start + '\n' + (ROOT / filename).read_text(encoding='utf-8-sig').strip() + '\n' + end + after
    if '/* stage-editor:start */' not in page:
        return page
    editor = (ROOT / 'mobile_posters.js').read_text(encoding='utf-8')
    styles = (ROOT / 'mobile.html').read_text(encoding='utf-8').split('/* poster-style:start */',1)[1].split('/* poster-style:end */',1)[0]
    if standalone:
        artwork = {p.stem:base64.b64encode(p.read_bytes()).decode('ascii') for p in sorted((ROOT/'poster-art').glob('*.webp'))}
        editor = "const LOCAL_POSTER_ART="+json.dumps(artwork,separators=(',',':'))+";\n"+editor
    for name,content in [('stage-editor',editor),('stage-style',styles)]:
        start='/* '+name+':start */'
        end='/* '+name+':end */'
        before,region=page.split(start,1)
        _,after=region.split(end,1)
        page=before+start+'\n'+content+'\n'+end+after
    return page


def refresh_local_stage_template():
    path=ROOT/'index.html'
    if not path.is_file():
        return
    original=path.read_text(encoding='utf-8')
    built=stage_template(original,standalone=True)
    if original==built:
        return
    with tempfile.NamedTemporaryFile(dir=ROOT,delete=False) as temp:
        temp.write(built.encode('utf-8'))
    try:
        if path.read_text(encoding='utf-8')!=original:
            raise RuntimeError('网页模板已变化，请重新发布。')
        os.replace(temp.name,path)
    finally:
        Path(temp.name).unlink(missing_ok=True)


def desktop_template():
    personal = ROOT / "index.html"
    if personal.is_file():
        page = personal.read_text(encoding="utf-8")
        return stage_template(page)
    page = (ROOT / "archive.html").read_text(encoding="utf-8")
    for name, filename in (("run-period", "run_period.js"),
                           ("run-period-style", "run_period.css"),
                           ("footprint-shared", "footprint.js")):
        page = page.replace("/* include:" + name + " */", (ROOT / filename).read_text(encoding="utf-8"))
    return page
