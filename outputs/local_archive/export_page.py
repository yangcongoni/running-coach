"""Publish the live archive's full snapshot and mobile reading snapshot together.

The source database is read-only.  The full HTML and JSON remain lossless exports;
the mobile snapshot only omits duplicate/raw transport and audit payloads.
"""
from pathlib import Path
from archive_config import desktop_template
import base64
import copy
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent
TABLES = ['metadata', 'sources', 'strength_baselines', 'planned_sessions',
          'sessions', 'running_details', 'running_laps', 'strength_sets',
          'daily_recovery', 'analyses', 'revisions', 'periodic_reviews',
          'stretching_records', 'daily_submissions', 'daily_submission_history']
FULL_HTML = '训练档案.html'
LIGHT_HTML = '训练档案_手机轻量版.html'
FULL_ZIP = 'running-archive-offline-20261025.zip'
LIGHT_ZIP = 'running-archive-light.zip'


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def js_json(value):
    return dumps(value).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')


def compact_history(value):
    """Do not carry recursively nested old plans inside every plan revision."""
    if isinstance(value, dict):
        return {key: compact_history(item) for key, item in value.items()
                if key not in ('execution_plan_history', 'revisions')}
    if isinstance(value, list):
        return [compact_history(item) for item in value]
    return value


def light_data(data):
    result = copy.deepcopy(data)
    # API transport observations are retained in the full export/database, not duplicated on mobile.
    result['metadata'] = [row for row in result['metadata'] if not row['key'].startswith('garmin_api_')]
    # The renderer reads running_details, not this second copy of the same raw run.
    for row in result['sessions']:
        if row['sport'] == 'running':
            original = json.loads(row['raw_json'] or '{}')
            row['raw_json'] = dumps({k: original[k] for k in ('user_followup','user_followups','user_report','original_user_text') if k in original})
    run_dates={r['id']:r['date'] for r in result['sessions'] if r['sport']=='running'}
    recent_from=(datetime.fromisoformat(max(run_dates.values()))-timedelta(days=28)).date().isoformat() if run_dates else ''
    for row in result['running_details']:
        raw = json.loads(row['details_json'])
        for key in ('userRoles', 'ownerProfileImageUrlSmall', 'ownerProfileImageUrlMedium',
                    'ownerProfileImageUrlLarge'):
            raw.pop(key, None)
        if 'splitSummaries' in raw:
            raw['splitSummaries'] = [
                {key: value for key, value in split.items() if key in ('splitType', 'noOfSplits')}
                for split in raw['splitSummaries']]
        curve=raw.get('archived_curve')
        if curve and len(curve.get('points',[]))>600:
            points=curve['points'];indices={0,len(points)-1};buckets=100 if run_dates.get(row.get('session_id'),'')>=recent_from else 24; width=max(1,(len(points)+buckets-1)//buckets)
            for start in range(0,len(points),width):
                stop=min(len(points),start+width);indices.add(start)
                for col in range(2,len(curve['columns'])):
                    valid=[i for i in range(start,stop) if points[i][col] is not None]
                    if valid:indices.update([min(valid,key=lambda i:points[i][col]),max(valid,key=lambda i:points[i][col])])
            for i in range(1,len(points)):
                if any((points[i][j] is None)!=(points[i-1][j] is None) for j in range(2,len(curve['columns']))):indices.update([i-1,i])
            curve['points']=[points[i] for i in sorted(indices)]
            curve['display_sampling']='bucket_extrema_'+str(buckets)+'; full original retained in complete archive'
        row['details_json'] = dumps(raw)
    for row in result['revisions']:
        for column in ('previous_json', 'replacement_json'):
            if not re.search('plan|计划', row['entity'] or ''):
                row[column] = None
            elif row[column]:
                try:
                    value = json.loads(row[column])
                    if isinstance(value, dict) and isinstance(value.get('prescription_json'), str):
                        value['prescription_json'] = dumps(compact_history(json.loads(value['prescription_json'])))
                    row[column] = dumps(compact_history(value))
                except (ValueError, TypeError):
                    pass  # An uncommon old format is safer to retain than discard.
    result['_page_projection'] = False  # A single file must never request the local API.
    result['_offline_light'] = True
    result['_release']['mode'] = 'light'
    result['_release']['limitations'] = (
        '手机轻量版保留训练、计划、分圈、恢复、教练分析和知识库；'
        '不含数据库备份及部分重复原始字段、完整修改前后数据。完整审计请用完整版。')
    return result


def data_date(data):
    dates = []
    for table in ('sessions', 'daily_recovery', 'stretching_records', 'daily_submissions'):
        for row in data[table]:
            date = row.get('date')
            if isinstance(date, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
                dates.append(date)
    return max(dates) if dates else None


def make_html(template, data, backup, mode):
    html = template
    assets = {name: 'data:image/png;base64,' + base64.b64encode((ROOT / 'assets' / name).read_bytes()).decode('ascii')
              for name in (('strength-anatomy-v2.png', 'strength-anatomy-back.png') if 'strength-anatomy-' in template else ()) + tuple(sorted(p.name for p in (ROOT / 'assets').glob('race-map-*.png')))}
    # Assets appear once in the bundle, independently of the number of rendered body maps.
    html = html.replace('/assets/${asset}', '${OFFLINE_ASSETS[asset]}')
    for name in assets:
        html = html.replace('/assets/' + name, '${OFFLINE_ASSETS[' + json.dumps(name) + ']}')
    extra = 'const OFFLINE_ASSETS=' + js_json(assets) + ';\n'
    extra += 'const ARCHIVE_DATA=' + js_json(data) + ';\n'
    extra += """
function download(blob,name){const u=URL.createObjectURL(blob),a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),3000)}
"""
    if mode == 'full':
        extra += """
document.addEventListener('click',e=>{let a=e.target.closest('a');if(!a)return;if(a.getAttribute('href')==='/export.json'){e.preventDefault();download(new Blob([JSON.stringify(D,null,2)],{type:'application/json'}),'training-archive.json')}else if(a.getAttribute('href')==='/backup.sqlite3'){e.preventDefault();const bytes=Uint8Array.from(atob(BACKUP_DATA),c=>c.charCodeAt(0));download(new Blob([bytes],{type:'application/vnd.sqlite3'}),'training-backup.sqlite3')}});
""".replace('BACKUP_DATA', json.dumps(backup))
    else:
        extra += """
document.addEventListener('click',e=>{let a=e.target.closest('a');if(!a)return;if(a.getAttribute('href')==='/export.json'){e.preventDefault();download(new Blob([JSON.stringify(D,null,2)],{type:'application/json'}),'training-archive-reading-data.json')}else if(a.getAttribute('href')==='/backup.sqlite3'){e.preventDefault();alert('手机轻量版不包含数据库备份。请在完整版或在线网页下载完整备份。')}});
"""
        html = html.replace('<summary>查看原始数据</summary>', '<summary>查看查阅数据摘录</summary>')
        html = html.replace("D._page_projection?'展开后读取完整原始记录…':esc(JSON.stringify(r.raw,null,2))", "'轻量版仅含查阅字段；完整原始记录请用完整版。\\n'+esc(JSON.stringify(r.raw,null,2))")
        html = html.replace('<summary>修改历史</summary>', '<summary>修改历史摘要</summary><p class="scope-note">保留修改时间和原因；部分完整修改前后数据仅在完整版中提供。</p>')
        html = html.replace('导出完整 JSON', '导出查阅数据 JSON').replace('导出JSON', '导出查阅数据')
        html = re.sub(r'<a class="button" href="/backup.sqlite3">.*?</a>', '<span class="scope-note">完整备份请用完整版</span>', html)
    # Retain the existing entry point contract so render wrappers continue to work.
    extra += "function load(){D=ARCHIVE_DATA;navigate(page);if(typeof renderArchiveRelease==='function')renderArchiveRelease()}load();"
    start = html.index('async function load(){')
    end = html.rindex('load();') + len('load();')
    html = html[:start] + extra + html[end:]
    html = html.replace('仅本机可访问；不会自动连接佳明或跨设备同步。', '离线快照；不会自动连接佳明。数据变化后请重新下载最新版本。')
    html = html.replace('重新读取数据', '重新显示当前快照').replace('再刷新页面', '再下载最新快照')
    html = html.replace('通过已配置的私人远程连接访问；网页不自动连接佳明。', '离线文件不会自动同步；数据变化后请下载新版。')
    html = html.replace('日常反馈可在聊天中提供，也可在跑步或力量档案的“训练后反馈”中补充。', '训练后反馈可生成文字，复制到聊天后归档；离线填写不会自动保存到数据库。')
    return html


def write_text_chunks(path, text):
    with path.open('w', encoding='utf-8', newline='') as stream:
        for start in range(0, len(text), 1024 * 1024):
            stream.write(text[start:start + 1024 * 1024])


def stream_hash(stream):
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(block)
    return digest.hexdigest()


def file_hash(path):
    with path.open('rb') as stream:
        return stream_hash(stream)


def json_chunks(data):
    encoder = json.JSONEncoder(ensure_ascii=False, separators=(',', ':'))
    for token in encoder.iterencode(data):
        for start in range(0, len(token), 1024 * 1024):
            yield token[start:start + 1024 * 1024]


def write_snapshot(path, template, data, backup, mode):
    # Format only the small template before inserting raw data and backup bytes.
    shell = make_html(template, '__DATA_SLOT__', '__BACKUP_SLOT__', mode)
    before, after = shell.split('"__DATA_SLOT__"')
    with path.open('w', encoding='utf-8', newline='') as stream:
        stream.write(before)
        for chunk in json_chunks(data):
            stream.write(chunk.replace('<', r'\u003c').replace('>', r'\u003e').replace('&', r'\u0026'))
        if mode == 'full':
            prefix, after = after.split('__BACKUP_SLOT__')
            stream.write(prefix)
            for start in range(0, len(backup), 1024 * 1024):
                stream.write(backup[start:start + 1024 * 1024])
        stream.write(after)


def publish():
    with sqlite3.connect(f'file:{(OUT / "训练日志.sqlite3").as_posix()}?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        data = {table: [dict(row) for row in conn.execute('SELECT * FROM ' + table)] for table in TABLES}
        with sqlite3.connect(':memory:') as target:
            conn.backup(target)
            backup = base64.b64encode(target.serialize()).decode('ascii')
    template = desktop_template()
    now = datetime.now(timezone(timedelta(hours=8)))
    hasher = hashlib.sha256(template.encode('utf-8'))
    for chunk in json_chunks(data):
        hasher.update(chunk.encode('utf-8'))
    digest = hasher.hexdigest()[:10]
    release = {'release_id': now.strftime('%Y%m%d-%H%M%S') + '-' + digest,
               'generated_at': now.isoformat(timespec='seconds'), 'data_through': data_date(data),
               'snapshot_date': now.date().isoformat(), 'mode': 'full',
               'limitations': '离线快照仅反映生成时已归档内容；生成时间不是佳明同步时间。'}
    data['_release'] = release
    lite = light_data(data)
    # Every visible activity/set/lap/recovery/analysis remains present at original precision.
    for table in ('strength_sets', 'running_laps', 'daily_recovery', 'analyses', 'periodic_reviews',
                  'sources', 'planned_sessions', 'stretching_records', 'daily_submissions'):
        assert data[table] == lite[table], table
    assert [row for row in data['metadata'] if not row['key'].startswith('garmin_api_')] == lite['metadata']
    assert len(data['sessions']) == len(lite['sessions'])
    assert len(data['running_details']) == len(lite['running_details'])
    # Stage all artifacts before replacing published files; manifest goes last.
    with tempfile.TemporaryDirectory(prefix='.archive-publish-', dir=OUT) as staging:
        stage = Path(staging)
        write_snapshot(stage / FULL_HTML, template, data, backup, 'full')
        del backup
        write_snapshot(stage / LIGHT_HTML, template, lite, None, 'light')
        with (stage / '训练档案_可导出数据.json').open('w', encoding='utf-8', newline='') as stream:
            stream.writelines(json_chunks(data))
        for zipname, htmlname, entry in ((FULL_ZIP, FULL_HTML, 'running-archive.html'),
                                         (LIGHT_ZIP, LIGHT_HTML, 'running-archive-light.html')):
            with zipfile.ZipFile(stage / zipname, 'w', zipfile.ZIP_DEFLATED) as z:
                z.write(stage / htmlname, entry)
            with zipfile.ZipFile(stage / zipname) as z:
                with z.open(entry) as member:
                    assert stream_hash(member) == file_hash(stage / htmlname)
        for name in (FULL_HTML, LIGHT_HTML, '训练档案_可导出数据.json', FULL_ZIP, LIGHT_ZIP):
            os.replace(stage / name, OUT / name)
        release['artifacts'] = {name: {'bytes': (OUT / name).stat().st_size,
                                      'sha256': file_hash(OUT / name)}
                                for name in (FULL_HTML, LIGHT_HTML, '训练档案_可导出数据.json', FULL_ZIP, LIGHT_ZIP)}
        (stage / 'archive_release.json').write_text(dumps(release), encoding='utf-8')
        os.replace(stage / 'archive_release.json', ROOT / 'archive_release.json')
    print('Published ' + release['release_id'] + ': full HTML/JSON/ZIP and mobile HTML/ZIP verified.')
    print('HTML bytes: full=' + str((OUT / FULL_HTML).stat().st_size) + ', mobile=' + str((OUT / LIGHT_HTML).stat().st_size))


if __name__ == '__main__':
    publish()
