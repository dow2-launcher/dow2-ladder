"""Our own automatch's matches, kept for our own rating (10.11.2026, own_rating step 1a): passive storage only.

Nothing here changes a rating, the queue or a room: every call is wrapped (an error is logged and swallowed), the tables are
written and never read by the matchmaking. sid = own_lobby room id (mid) = the node's session id = mm_history 'NM-<sid>'.
Writers: ladder.py _history_add (the players at the start, rating before), mm_ended (menu_t), _end_match (ended), mm_ruined for
NM- lobbies (ruined_t: his game fell while loading), nm/report from own_lobby (every game's report + who never reported).
The columns of step 2 (final, winner_team, result_src, rated...) stay empty here. Plan: reports/rating_plan/STEP1_DATA_RU.md 3.3.
"""
import json, sqlite3, time, traceback

SCHEMA = '''
CREATE TABLE IF NOT EXISTS own_matches (
  sid INTEGER PRIMARY KEY, lobby TEXT, kind TEXT, mode TEXT, map TEXT, modname TEXT, season TEXT, node TEXT,
  started INTEGER, game_over_t INTEGER, game_over_tick INTEGER, ended INTEGER, ticks INTEGER,
  winner_team INTEGER, result_src TEXT, rated INTEGER DEFAULT 0, why_unrated TEXT,
  reports TEXT, node_log TEXT, flags TEXT, updated INTEGER);
CREATE TABLE IF NOT EXISTS own_match_players (
  sid INTEGER, steam TEXT, pid INTEGER, name TEXT, team INTEGER, race INTEGER, hero INTEGER, rating_before REAL,
  report_result INTEGER, report_t INTEGER, join_t INTEGER, leave_t INTEGER, leave_tick INTEGER, leave_reason TEXT,
  rejoins INTEGER, max_solo_ms INTEGER, menu_t INTEGER, ruined_t INTEGER, final TEXT,
  PRIMARY KEY (sid, steam));
CREATE INDEX IF NOT EXISTS own_mp_steam ON own_match_players (steam, sid);
'''
MENU_WINDOW = 6 * 3600          # mm/ended after a match: his latest own match started within this

_db = _lock = _season = None


def _log(what, e):
    print('own_matches: %s failed: %r %s' % (what, e, traceback.format_exc(limit=2).replace('\n', ' | ')), flush=True)


def setup(db_fn, lock, season_fn):
    """db_fn() -> sqlite3 connection, lock = the ladder's write lock, season_fn(start) -> '2026-Q4'"""
    global _db, _lock, _season
    _db, _lock, _season = db_fn, lock, season_fn
    try:
        with _db() as c: c.executescript(SCHEMA)
    except Exception as e: _log('setup', e)


def sid_of(lobby):
    lobby = str(lobby or '')
    return int(lobby[3:]) if lobby.startswith('NM-') and lobby[3:].isdigit() else None


def _int(x):
    try: return int(x)
    except Exception: return None


def _node(m):
    r = m.get('relay_used') or m.get('relay')
    if not r: return None
    return r if isinstance(r, str) else json.dumps(r)


def on_start(m, players):
    """_history_add: the match started (players = the mm_history rows: steam, pid, name, team, rating, race, hero)"""
    try:
        sid = sid_of(m.get('lobby')); players = list(players or [])
        if sid is None: return
        now = int(time.time()); started = int(m.get('started') or now)
        with _lock, _db() as c:
            c.execute('INSERT OR IGNORE INTO own_matches (sid, lobby, kind, mode, map, modname, season, node, started, flags, updated) '
                      'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                      (sid, m['lobby'], 'room' if m.get('lroom') else 'mm', m.get('mode'), m.get('map'), m.get('game'),
                       _season(started), _node(m), started, None, now))
            for p in players:
                race = p.get('race'); race = race if isinstance(race, int) else None     # the ladder's names; the game's id comes with the reports
                c.execute('INSERT OR IGNORE INTO own_match_players (sid, steam, pid, name, team, race, hero, rating_before) VALUES (?,?,?,?,?,?,?,?)',
                          (sid, str(p.get('steam')), _int(p.get('pid')), p.get('name'), _int(p.get('team')), race, _int(p.get('hero')),
                           p.get('rating')))
    except Exception as e: _log('on_start %s' % m.get('lobby'), e)


def on_ended(steam, lobby=None, now=None):
    """mm/ended: he is back in the menu - menu_t of his match (the one in memory, else his latest own match without menu_t)"""
    try:
        now = int(now or time.time()); steam = str(steam); sid = sid_of(lobby)
        with _lock, _db() as c:
            if sid is None:
                row = c.execute('SELECT p.sid FROM own_match_players p JOIN own_matches m ON m.sid = p.sid WHERE p.steam = ? AND m.started > ? '
                                'ORDER BY m.started DESC LIMIT 1', (steam, now - MENU_WINDOW)).fetchone()
                sid = row[0] if row else None
            if sid is None: return
            c.execute('UPDATE own_match_players SET menu_t = ? WHERE sid = ? AND steam = ? AND menu_t IS NULL', (now, sid, steam))
            c.execute('UPDATE own_matches SET ended = coalesce(ended, ?), updated = ? WHERE sid = ?', (now, now, sid))
    except Exception as e: _log('on_ended %s' % steam, e)


def on_match_over(lobby, now=None):
    """_end_match: the ladder thinks the match is over (all back / silent / lroom)"""
    try:
        sid = sid_of(lobby)
        if sid is None: return
        now = int(now or time.time())
        with _lock, _db() as c: c.execute('UPDATE own_matches SET ended = coalesce(ended, ?), updated = ? WHERE sid = ?', (now, now, sid))
    except Exception as e: _log('on_match_over %s' % lobby, e)


def on_ruined(steam, lobby):
    """mm/ruined for an NM- lobby: his game fell while the match was loading. True when his row was marked"""
    try:
        sid = sid_of(lobby)
        if sid is None: return False
        now = int(time.time())
        with _lock, _db() as c:
            n = c.execute('UPDATE own_match_players SET ruined_t = coalesce(ruined_t, ?) WHERE sid = ? AND steam = ?', (now, sid, str(steam))).rowcount
            if n: c.execute('UPDATE own_matches SET updated = ? WHERE sid = ?', (now, sid))
        return bool(n)
    except Exception as e: _log('on_ruined %s %s' % (steam, lobby), e); return False


def on_reports(d):
    """nm/report from own_lobby: {room, relay, reports: {pid: {profile_ids, results, race_ids, teamIDs, counters, _t}},
    missing: [pid], first_t, stored_t, members: {pid: {team, race}}}. Each player's report_result = what HIS game said of him."""
    try:
        sid = _int(d.get('room'))
        if sid is None: return {'ok': False, 'error': 'room'}
        reps = d.get('reports') if isinstance(d.get('reports'), dict) else {}
        now = int(time.time())
        raw = json.dumps({'reports': reps, 'missing': d.get('missing') or [], 'first_t': d.get('first_t'), 'stored_t': d.get('stored_t'),
                          'relay': d.get('relay'), 'members': d.get('members')}, separators=(',', ':'))
        relay = d.get('relay'); relay = relay[0] if isinstance(relay, list) and relay else relay
        with _lock, _db() as c:
            c.execute('INSERT OR IGNORE INTO own_matches (sid, lobby, kind, started, flags, updated) VALUES (?,?,?,?,?,?)',
                      (sid, 'NM-%d' % sid, None, _int(d.get('started')), 'no_start_row', now))
            c.execute('UPDATE own_matches SET reports = ?, node = coalesce(node, ?), updated = ? WHERE sid = ?',
                      (raw, relay if isinstance(relay, str) else None, now, sid))
            for pid, x in reps.items():
                pid = _int(pid)
                if pid is None or not isinstance(x, dict): continue
                try: ids = [int(q) for q in json.loads(x.get('profile_ids') or '[]')]
                except Exception: ids = []
                try: res = dict(zip(ids, json.loads(x.get('results') or '[]')))
                except Exception: res = {}
                try: rc = dict(zip(ids, json.loads(x.get('race_ids') or '[]')))
                except Exception: rc = {}
                race = _int(rc.get(pid)); race = race if race is not None and 0 <= race < 16 else None   # the race he PLAYED (his game's id)
                c.execute('UPDATE own_match_players SET report_result = ?, report_t = ?, race = coalesce(?, race) WHERE sid = ? AND pid = ?',
                          (_int(res.get(pid)), _int(x.get('_t')), race, sid, pid))
        return {'ok': True}
    except Exception as e: _log('on_reports %s' % d.get('room'), e); return {'ok': False}


def leave_reason(x):
    """the node's reasons in one word: how his connection ended (fin/reset/idle/replaced/error/closed), what the node then did
    (grace_over: not back in time / vote_drop: the others voted him out), how the UDP gateway saw it (gw:peer / gw:dead / ...)"""
    parts = [x.get('conn_reason'), x.get('reason')] if x.get('conn_reason') else [x.get('reason')]
    if x.get('gw_reason'): parts.append('gw:%s' % x['gw_reason'])
    return '/'.join(str(p) for p in parts if p) or None


def on_node_log(ml, ip):
    """match_log_collect.py (rts, own rating step 1b): a node's "match_log" of session sid -> own_matches.node_log (a JSON list,
    one entry per node + session end: a second run replaces it, never adds) and the players' join/leave fields from the entry
    with the most ticks. Only a session of one of OUR matches (a row exists) whose time fits the match. -> 'ok' / why not"""
    try:
        sid = _int(ml.get('sid'))
        if sid is None: return 'no_sid'
        with _lock, _db() as c:
            row = c.execute('SELECT started, ended, node_log FROM own_matches WHERE sid = ?', (sid,)).fetchone()
            if not row: return 'not_ours'
            started, ended = row[0] or 0, row[1] or row[0] or 0
            if started and not (ml.get('t_end', 0) >= started - 120 and ml.get('started', 0) <= ended + 600): return 'time'
            try: logs = json.loads(row[2]) if row[2] else []
            except Exception: logs = []
            if not isinstance(logs, list): logs = [logs]
            e = dict(ml, ip=ip); e.pop('ev', None)
            logs = [x for x in logs if not (x.get('ip') == ip and x.get('t_end') == e.get('t_end'))] + [e]
            logs.sort(key=lambda x: x.get('t_end') or 0)
            best = max(logs, key=lambda x: x.get('ticks') or 0)
            now = int(time.time())
            c.execute('UPDATE own_matches SET node_log = ?, node = coalesce(node, ?), ticks = coalesce(?, ticks), updated = ? WHERE sid = ?',
                      (json.dumps(logs, separators=(',', ':')), best.get('ip'), _int(best.get('ticks')), now, sid))
            for p in best.get('players') or []:
                if not p.get('steam'): continue
                c.execute('UPDATE own_match_players SET join_t = ?, leave_t = ?, leave_tick = ?, leave_reason = ?, rejoins = ?, max_solo_ms = ? '
                          'WHERE sid = ? AND steam = ?',
                          (_int(p.get('join_t')), _int(p.get('leave_t')), _int(p.get('leave_tick')), leave_reason(p), _int(p.get('rejoins')),
                           _int(p.get('max_solo_ms')), sid, str(p['steam'])))
        return 'ok'
    except Exception as e: _log('on_node_log %s' % ml.get('sid'), e); return 'error'


def backfill(c, log=print):
    """the own matches stored before 10.11.2026: mm_history NM- rows + matches source=ownlobby; no per-player reports existed then
    (own_lobby kept only the first), so report_result/report_t stay NULL and the first report goes to reports as it was"""
    c.executescript(SCHEMA)
    hist = {sid_of(r[0]): r for r in c.execute('SELECT lobby, mode, map, started, ended, players, result, kind FROM mm_history WHERE lobby LIKE "NM-%"')}
    mt = {r[0]: r for r in c.execute('SELECT id, start, mode, season, data FROM matches WHERE json_extract(data, "$.source") = "ownlobby"')}
    now = int(time.time()); n = 0
    for sid in sorted(set(hist) | set(mt)):
        if sid is None: continue
        h = hist.get(sid); x = mt.get(sid)
        data = json.loads(x[4]) if x else {}
        res = json.loads(h[6]) if h and h[6] else {}
        started = (h[3] if h else None) or (x[1] if x else None)
        ended = (h[4] if h else None) or data.get('completiontime')
        out = {pm['profile_id']: pm.get('outcome') for pm in data.get('matchhistorymember') or []}
        raw = json.dumps({'backfill': True, 'first_report': data.get('report'), 'outcome': out}, separators=(',', ':')) if data else None
        c.execute('INSERT OR IGNORE INTO own_matches (sid, lobby, kind, mode, map, modname, season, started, ended, reports, flags, updated) '
                  'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                  (sid, 'NM-%d' % sid, ('room' if h[7] == 'room' else 'mm') if h else None, h[1] if h else None,
                   (h[2] if h else None) or data.get('mapname'), data.get('modname'), _season(started) if started else None,
                   started, ended, raw, 'backfill' + ('' if h else ',no_history'), now))
        pl = json.loads(h[5]) if h else []
        races = {p.get('pid'): p.get('race') for p in res.get('players') or []}
        if not pl:   # no ladder row: the lobby's members, steam from profiles
            for pm in data.get('matchhistorymember') or []:
                st = c.execute('SELECT steam FROM profiles WHERE profile_id = ?', (pm['profile_id'],)).fetchone()
                pl.append({'steam': (st[0] if st else None) or 'pid:%d' % pm['profile_id'], 'pid': pm['profile_id'], 'team': pm.get('teamid'),
                           'race': pm.get('race_id')})
        for p in pl:
            race = races.get(p.get('pid'), p.get('race')); race = race if isinstance(race, int) else None
            c.execute('INSERT OR IGNORE INTO own_match_players (sid, steam, pid, name, team, race, hero, rating_before) VALUES (?,?,?,?,?,?,?,?)',
                      (sid, str(p.get('steam')), _int(p.get('pid')), p.get('name'), _int(p.get('team')), race, _int(p.get('hero')), p.get('rating')))
        n += 1
    log('own_matches backfill: %d matches' % n)
    return n
