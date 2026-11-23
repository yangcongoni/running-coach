"""Estimates from archived sets. Reported session minutes always take precedence."""
import re
from collections import defaultdict


def estimate_seconds(sets):
    if not sets:
        return None
    rounds = set()
    active = 0
    for row in sets:
        reps = row['reps']
        if reps is None:
            seconds = re.search(r'(?:持续|保持)\s*(\d+)\s*秒', row.get('notes') or '')
            if not seconds:
                return None
            active += int(seconds[1])
        elif reps > 0:
            active += reps * 3
        else:
            return None
        if row['set_number'] is None:
            return None
        # Paired sides with the same exercise and set number are one round.
        rounds.add((row['exercise'], row['set_kind'], row['set_number']))
    return active + 120 * (len(rounds) - 1)


def enrich_sessions(sessions, sets):
    by_session = defaultdict(list)
    for row in sets:
        by_session[row['session_id']].append(dict(row))
    for session in sessions:
        if session['sport'] == 'strength' and session['duration_minutes'] is None:
            session['strength_duration_estimate_seconds'] = estimate_seconds(by_session[session['id']])


def enrich_mobile(conn, sessions):
    if not any(s['sport'] == 'strength' and s['duration_minutes'] is None for s in sessions):
        return
    sets = conn.execute('SELECT session_id, exercise, set_number, set_kind, reps, notes FROM strength_sets')
    enrich_sessions(sessions, sets)
