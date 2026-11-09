"""Session-bound user supplements. Device records and coach verdicts stay separate."""
import datetime, json, math, sqlite3, uuid
from pathlib import Path

TEXT_FIELDS = {'pain', 'talk', 'shoes', 'route', 'terrain', 'pause', 'cooldown', 'strength_details', 'note'}

def submit_feedback(db, data):
    if not isinstance(data, dict): raise ValueError('提交格式错误')
    sid, expected, rid = data.get('session_id'), data.get('expected_revision'), data.get('request_id')
    if type(sid) is not int or type(expected) is not int or expected < 0: raise ValueError('训练或版本编号无效')
    try: uuid.UUID(rid)
    except (ValueError, TypeError, AttributeError): raise ValueError('请求编号无效')
    fields = data.get('fields')
    if not isinstance(fields, dict) or set(fields) - (TEXT_FIELDS | {'rpe', 'rpe_range'}): raise ValueError('反馈字段无效')
    clean = {}
    for key in TEXT_FIELDS:
        value = fields.get(key, '')
        if not isinstance(value, str) or len(value) > 4000: raise ValueError('反馈文字过长或格式错误')
        clean[key] = value.strip()
    value = fields.get('rpe')
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 10):
        raise ValueError('RPE应为0至10，未反馈请留空')
    clean['rpe'] = value
    span = fields.get('rpe_range')
    if span is not None:
        if value is not None or not isinstance(span, list) or len(span) != 2 or any(type(x) not in (int,float) or not math.isfinite(x) or not 0 <= x <= 10 for x in span) or span[0] > span[1]:
            raise ValueError('RPE范围应为0至10内的递增范围，如7–8；不取中点')
    clean['rpe_range'] = span
    if value is None and span is None and not any(clean[k] for k in TEXT_FIELDS): raise ValueError('请至少填写一项反馈')
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    db = Path(db)
    with sqlite3.connect(db, timeout=30) as c:
        c.row_factory = sqlite3.Row
        # A separate read connection creates a consistent pre-write backup.
        # BEGIN IMMEDIATE serializes feedback revisions across devices.
        c.execute('BEGIN IMMEDIATE')
        session = c.execute('select id,date,sport from sessions where id=?', (sid,)).fetchone()
        if not session or session['sport'] not in ('running', 'strength'): raise ValueError('找不到对应的跑步或力量训练')
        if session['date'] > now.date().isoformat(): raise ValueError('不能记录未来训练的完成反馈')
        key = 'training_session_feedback'
        row = c.execute('select value_json from metadata where key=?', (key,)).fetchone()
        all_records = json.loads(row[0]) if row else {}
        old = all_records.get(str(sid))
        history = [*(old or {}).get('history', []), *([old] if old else [])]
        for entry in history:
            if entry.get('request_id') == rid:
                if entry['fields'] != clean: raise ValueError('请求编号已使用，但内容不同')
                return {'ok': True, 'record': old, 'replayed': True}
        if (old or {}).get('revision', 0) != expected: raise RuntimeError('其他设备已更新此条反馈，请重新打开后补充；当前文字仍保留')
        folder = db.parent / 'backups' / 'training_feedback'
        folder.mkdir(parents=True, exist_ok=True)
        backup = folder / (now.strftime('%Y%m%d_%H%M%S_%f') + '.sqlite3')
        with sqlite3.connect(db) as origin, sqlite3.connect(backup) as target: origin.backup(target)
        stamp = now.isoformat(timespec='seconds')
        source = c.execute('insert into sources(source_key,kind,reference,note) values(?,?,?,?)',
            ('session-feedback:' + rid, 'user_feedback', 'local-web:session:' + str(sid), session['date'] + '训练后反馈；用户填写，未自动生成教练结论')).lastrowid
        record = {'session_id': sid, 'date': session['date'], 'sport': session['sport'], 'fields': clean,
                  'revision': expected + 1, 'request_id': rid, 'source_id': source, 'updated_at': stamp,
                  'status': '待教练复核', 'history': [dict(x, history=[]) for x in history]}
        all_records[str(sid)] = record
        c.execute('insert or replace into metadata(key,value_json) values(?,?)', (key, json.dumps(all_records, ensure_ascii=False)))
        c.execute('insert into revisions(created_at,entity,entity_key,previous_json,replacement_json,reason) values(?,?,?,?,?,?)',
                  (stamp, key, str(sid), json.dumps(old, ensure_ascii=False), json.dumps(record, ensure_ascii=False), '训练后用户反馈；保留设备值、原始反馈及教练判定'))
    return {'ok': True, 'record': record, 'replayed': False}
