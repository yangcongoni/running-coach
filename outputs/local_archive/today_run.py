"""Beijing-day homepage projection, scoped to individual running sessions."""
import json
import re
from datetime import datetime, timedelta, timezone

from mobile_archive import work_groups


def today_runs(conn, day=None):
    day = day or datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    rows = conn.execute("""
        SELECT s.id,r.distance_km km,r.timer_seconds seconds,r.average_hr hr,
               json_extract(r.details_json,'$.averageRunningCadenceInStepsPerMinute') cadence,
               json_extract(r.details_json,'$.activityName') name,
               json_extract(r.details_json,'$.classification_override.type') category,
               coalesce(json_extract(r.details_json,'$.startTimeLocal'),
                        json_extract(r.details_json,'$.api_list_summary.startTimeLocal')) start
        FROM sessions s JOIN running_details r ON r.session_id=s.id
        WHERE s.date=? AND s.sport='running' ORDER BY start DESC,s.id DESC
    """, (day,))
    feedback = None
    items = []
    for row in rows:
        run = dict(row)
        name = re.sub(r'^(?:.*?\s-\s)?(?:\d{1,2}/\d{1,2}\s*)?', '', run['name'] or '').strip()
        run['label'] = run.pop('category') or ('轻松跑' if '轻松跑' in name else name) or '跑步'
        for review in conn.execute("""SELECT id,assessment,recommendation,evidence_json FROM analyses
                WHERE session_id=? ORDER BY id DESC""", (run['id'],)):
            evidence = json.loads(review['evidence_json'] or '{}')
            if (evidence.get('report_type') not in (None, '', 'activity_review', 'session_review')
                    or evidence.get('journal_special_deleted')
                    or (evidence.get('correction') or {}).get('original_assessment_superseded')):
                continue
            sentences = re.findall(r'[^。！？\n]+[。！？]?', review['assessment'] or '')
            lead = next((s for s in sentences if re.search(r'核心任务|符合.*要求|后半程.*稳定|强度控制|达到.*目标|未完成|按计划完成', s)), '')
            run.update(review_id=review['id'],
                       verdict=(evidence.get('coach_review') or {}).get('verdict') or lead or ''.join(sentences[:2]),
                       next_action=review['recommendation'])
            break
        if feedback is None:
            entry = conn.execute("SELECT value_json FROM metadata WHERE key='training_session_feedback'").fetchone()
            feedback = json.loads(entry[0]) if entry else {}
        fields = (feedback.get(str(run['id'])) or {}).get('fields') or {}
        run['feedback'] = fields.get('pain') or fields.get('note')
        laps = []
        for number, raw in conn.execute('SELECT lap_number,details_json FROM running_laps WHERE session_id=? ORDER BY lap_number,id', (run['id'],)):
            lap = json.loads(raw or '{}')
            laps.append(dict(number=number, kind=(lap.get('api_raw') or {}).get('intensityType'),
                             stage=lap.get('step_type'), km=lap.get('distance_km'),
                             sec=lap.get('time_seconds'), hr=lap.get('average_hr')))
        run['groups'] = work_groups(laps)
        items.append(run)
    return {'day': day, 'items': items}
