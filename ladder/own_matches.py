"""Our own automatch's matches, kept for our own rating (10.11.2026, own_rating step 1a): passive storage only.

Nothing here changes a rating, the queue or a room: every call is wrapped (an error is logged and swallowed), the tables are
written and never read by the matchmaking. sid = own_lobby room id (mid) = the node's session id = mm_history 'NM-<sid>'.
Writers: ladder.py _history_add (the players at the start, rating before), mm_ended (menu_t), _end_match (ended), mm_ruined for
NM- lobbies (ruined_t: his game fell while loading), nm/report from own_lobby (every game's report + who never reported).
The columns of step 2 (final, winner_team, result_src, rated...) are filled by the step 2 part at the end (shadow only). Plan: reports/rating_plan/STEP1_DATA_RU.md 3.3.
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


# ---------------------------------------------------------------------------------------------------------------------------
# Step 2 (10.11.2026): the result of a match and "a leave = a loss" + the SHADOW rating own_ratings. Shown to nobody: the ladder's
# tables (matches / ratings), its Glicko over Relic and data/unrated.on are not touched. Plan: reports/rating_plan/PLAN_RU.md
# rules 1-7, STEP1_DATA_RU.md 3.3; the comparison on the history: STEP2_RU.md. Called by match_log_collect.py after its writes.
END_EPS = 5             # s: he left at least this long before the end of the game = he left DURING the game
END_EPS_EST = 15        # s: the same when the end is only estimated (backfill: the time the ladder stored the match)
REPORT_WAIT = 90        # s: own_lobby stores a match this long after the first report when someone's report is missing
EARLY_S = 120           # s from the start: a leave before this = the match did not take place (rated for nobody)
FORGIVE_S = 86400       # ... and the leaver is forgiven his first such leave in this window, every next one is his loss
ALL_GONE_S = 3          # s: everyone gone within this (before any result) = our node / the network, no rating
SHORT_W = 0.5           # weight of the loss of a leaver's teammate whose team then lost short-handed
ROOMS_RATED = False     # launcher rooms: there is no "rated" tick yet (rule 1) -> unrated 'room'
CAL_GAMES = 5           # the first games of a player in a mode+season: calibration (cal_left)
MODES_N = {1: '1v1', 2: '2v2', 3: '3v3'}

MIGRATE = [('own_matches', 'notes', 'TEXT'), ('own_matches', 'resolved', 'INTEGER'),
           ('own_match_players', 'weight', 'REAL'), ('own_match_players', 'early_leave', 'INTEGER'),
           ('own_match_players', 'note', 'TEXT')]
RATINGS_SCHEMA = '''
CREATE TABLE IF NOT EXISTS own_ratings (
  steam TEXT, mode TEXT, season TEXT, rating REAL, rd REAL, vol REAL, games INTEGER, wins INTEGER, losses INTEGER,
  leaves INTEGER, cal_left INTEGER, cons REAL, last INTEGER, PRIMARY KEY (steam, mode, season));
'''


def migrate(c):
    c.executescript(SCHEMA + RATINGS_SCHEMA)
    for t, col, typ in MIGRATE:
        if col not in [r[1] for r in c.execute('PRAGMA table_info(%s)' % t)]:
            c.execute('ALTER TABLE %s ADD COLUMN %s %s' % (t, col, typ))


_LADDER_FN = {}
def ladder_fn():
    """glicko2_update and season_of: the very code of ladder.py (its functions are taken out of its source - importing the ladder
    would start its module-level setup)"""
    if not _LADDER_FN:
        import ast, math, os, time as _t
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ladder.py'), encoding='utf-8').read()
        want = {'Q', 'TAU', '_g', '_E', 'glicko2_update', 'season_of'}
        body = [n for n in ast.parse(src).body
                if (isinstance(n, ast.FunctionDef) and n.name in want) or
                   (isinstance(n, ast.Assign) and any(getattr(t, 'id', None) in want for t in n.targets))]
        ns = {'math': math, 'time': _t}
        exec(compile(ast.Module(body=body, type_ignores=[]), 'ladder.py', 'exec'), ns)
        _LADDER_FN.update(glicko=ns['glicko2_update'], season=ns['season_of'])
    return _LADDER_FN


def _loads(s, d=None):
    try: return json.loads(s) if s else d
    except Exception: return d


def decide(m, ps, early_before=lambda steam: 0):
    """the result of one match. m: {kind, started, end_est (bool), all_gone_s, conflict (bool)}; ps: [{steam, team, rep (1/0/3/-1/None),
    rep_t, leave (s, his effective leave time or None)}] -> {winner_team, result_src, rated, why, notes, players: {steam: (final, weight,
    early, note)}}. Pure: the tests feed it made-up matches."""
    fin = {p['steam']: ['none', 1.0, 0, None] for p in ps}
    r = dict(winner_team=None, result_src=None, rated=0, why=None, notes=[], players=fin)
    teams = {}
    for p in ps: teams.setdefault(p['team'], []).append(p)
    sizes = sorted(len(v) for v in teams.values())
    why_el = None                                        # rule 1: what makes the match unrated whatever happened in it
    if len(teams) != 2 or sizes[0] != sizes[1] or sizes[0] not in MODES_N: why_el = 'not_full_teams'
    elif any(not p['steam'] or str(p['steam']).startswith('pid:') for p in ps): why_el = 'no_steam'
    elif m.get('kind') == 'room' and not ROOMS_RATED: why_el = 'room'
    elif m.get('kind') not in ('mm', 'room'): why_el = 'no_history'      # not known to come from our automatch / a room
    tids = sorted(teams, key=lambda t: (t is None, t))
    def other(t): return tids[1] if t == tids[0] else tids[0]
    def done(why, src=None):
        r['why'] = why_el or why; r['result_src'] = src
        if why_el and why: r['notes'].append(why)
        r['rated'] = 1 if (r['why'] is None and r['winner_team'] is not None) else 0
        return r
    if len(teams) != 2: return done('not_full_teams')
    # the reports: only 1/0 say who won (3 = "ended by a leave, no winner", -1/None = no report)
    real = [p for p in ps if p['rep'] in (0, 1)]
    tv = {t: {p['rep'] for p in real if p['team'] == t} for t in tids}
    if m.get('conflict') or any(len(v) > 1 for v in tv.values()) or (tv[tids[0]] and tv[tids[0]] == tv[tids[1]]):
        return done('reports_disagree', 'check')
    eps = END_EPS_EST if m.get('end_est') else END_EPS
    ts = [p['rep_t'] for p in real if p.get('rep_t')]
    end_t = min(ts) if ts else None
    known = [p for p in ps if p['leave'] is not None]
    gone = sorted(known, key=lambda p: p['leave'])
    # rule 5: everybody dropped at once before any result -> the node / the network
    if len(gone) == len(ps) and gone[-1]['leave'] - gone[0]['leave'] <= ALL_GONE_S and (end_t is None or gone[-1]['leave'] < end_t - eps):
        return done('all_gone', 'node')
    started = m.get('started') or 0
    if real:
        win = next(t for t in tids if tv[t] == {1}) if any(tv[t] == {1} for t in tids) else other(next(t for t in tids if tv[t] == {0}))
        if end_t is None:                                # 1/0 without a time: nobody can be judged a leaver
            leavers = []; r['notes'].append('no_report_time')
        else:
            leavers = [p for p in known if p['leave'] < end_t - eps]
        src = 'reports+node' if leavers else 'reports'
    else:
        # no 1/0 report: the team all of whose players left first lost, if the others stayed longer than ALL_GONE_S
        if not ps or len(known) < len(ps): return done('no_data' if not any(p['rep'] is not None for p in ps) else 'no_winner', None)
        cnt = {t: 0 for t in tids}; lost = t_lost = None
        for p in gone:
            cnt[p['team']] += 1
            if cnt[p['team']] == len(teams[p['team']]): lost, t_lost = p['team'], p['leave']; break
        win = other(lost)
        stay = [p['leave'] for p in teams[win] if p['leave'] > t_lost]
        if not stay or min(stay) - t_lost <= ALL_GONE_S: return done('all_gone', 'node')
        leavers = [p for p in gone if p['leave'] <= t_lost]
        src = 'node'
    if all(p in leavers for p in teams[win]): return done('winners_left', 'check')
    r['winner_team'] = win
    # rule 4, early: a leave before EARLY_S = no match; the leaver loses unless it is his first such in FORGIVE_S
    early = [p for p in leavers if p['leave'] - started < EARLY_S] if started else []
    if early:
        for p in early:
            f = fin[p['steam']]; f[2] = 1
            if early_before(p['steam']) > 0: f[0] = 'loss_leave'; f[3] = 'early_leave'
            else: f[3] = 'early_forgiven'
        return done('early_leave', src)
    nl = {t: sum(1 for p in leavers if p['team'] == t) for t in tids}
    for p in ps:
        f = fin[p['steam']]
        if p in leavers: f[0] = 'loss_leave'; f[3] = ('left_%ds_before_end' % (end_t - p['leave'])) if real else 'left_first'
        elif p['team'] == win: f[0] = 'win'
        else:
            f[0] = 'loss'
            if nl[p['team']] > nl[other(p['team'])]: f[1] = SHORT_W; f[3] = 'short_handed'
    return done(None, src)


def _match_input(c, sid):
    """own_matches + own_match_players rows -> decide()'s m, ps (+ pid by steam)"""
    row = c.execute('SELECT kind, started, reports, node_log, flags FROM own_matches WHERE sid = ?', (sid,)).fetchone()
    if not row: return None, None
    kind, started, reports, node_log, flags = row
    rep = _loads(reports, {}) or {}
    logs = _loads(node_log, []) or []
    if not isinstance(logs, list): logs = [logs]
    best = max(logs, key=lambda x: x.get('ticks') or 0) if logs else {}
    m = dict(kind=kind, started=started, end_est=False, all_gone_s=best.get('all_gone_within_s'), conflict=False)
    cols = 'steam, pid, team, report_result, report_t, leave_t, menu_t, ruined_t'
    pl = [dict(zip(cols.split(', '), x)) for x in c.execute('SELECT %s FROM own_match_players WHERE sid = ?' % cols, (sid,))]
    if rep.get('backfill'):                              # 06-09.11: only the first report + the ladder's outcome per pid, no times
        out = rep.get('outcome') or {}
        try: ct = c.execute('SELECT json_extract(data, "$.completiontime") FROM matches WHERE id = ?', (sid,)).fetchone()
        except Exception: ct = None
        ct = ct[0] if ct else None
        miss = any(_int(v) == -1 for v in out.values())
        for p in pl:
            v = _int(out.get(str(p['pid'])))
            p['report_result'] = v if v != -1 else None
            p['report_t'] = (ct - (REPORT_WAIT if miss else 0)) if (ct and v is not None and v != -1) else None
        m['end_est'] = True
    else:                                                # every game's report: the same player told differently = a conflict
        seen = {}
        for x in (rep.get('reports') or {}).values():
            if not isinstance(x, dict): continue
            try: res = dict(zip([int(q) for q in json.loads(x.get('profile_ids') or '[]')], json.loads(x.get('results') or '[]')))
            except Exception: continue
            for pid, v in res.items():
                if v in (0, 1): seen.setdefault(pid, set()).add(v)
        m['conflict'] = any(len(v) > 1 for v in seen.values())
    ps = []
    for p in pl:
        lv = [t for t in (p['leave_t'], p['menu_t'], p['ruined_t']) if t]
        ps.append(dict(steam=p['steam'], pid=p['pid'], team=p['team'], rep=p['report_result'], rep_t=p['report_t'], leave=min(lv) if lv else None))
    return m, ps


def resolve(sid, c):
    """decide() on the stored data and write it: own_matches winner_team/result_src/rated/why_unrated/notes, players final/weight/early_leave/note"""
    m, ps = _match_input(c, sid)
    if m is None: return None
    def early_before(steam):
        return c.execute('SELECT COUNT(*) FROM own_match_players p JOIN own_matches x ON x.sid = p.sid WHERE p.steam = ? AND p.early_leave = 1 '
                         'AND p.sid != ? AND x.started >= ? AND x.started < ?', (steam, sid, (m['started'] or 0) - FORGIVE_S, m['started'] or 0)).fetchone()[0]
    r = decide(m, ps, early_before)
    c.execute('UPDATE own_matches SET winner_team = ?, result_src = ?, rated = ?, why_unrated = ?, notes = ?, resolved = ? WHERE sid = ?',
              (r['winner_team'], r['result_src'], r['rated'], r['why'], ','.join(r['notes']) or None, int(time.time()), sid))
    for steam, (final, w, early, note) in r['players'].items():
        c.execute('UPDATE own_match_players SET final = ?, weight = ?, early_leave = ?, note = ? WHERE sid = ? AND steam = ?',
                  (final, w, early, note, sid, steam))
    return r


def recompute_own(c, log=print):
    """the shadow rating from scratch: Glicko-2 of the ladder over own_matches rated=1 (+ the leaver's own loss in an 'early_leave'
    match), in the order of the start; one match = one period, against the other team's average (as ladder.recompute); the weight
    w < 1 scales his rating change. -> own_ratings (cons = rating - 2*RD, cal_left = calibration games left)"""
    L = ladder_fn(); g2 = L['glicko']
    R = {}
    def get(steam, mode, season): return R.setdefault((steam, mode, season), [1500.0, 350.0, 0.06, 0, 0, 0, 0, 0])
    ms = c.execute('SELECT sid, started, season, rated, why_unrated, winner_team FROM own_matches WHERE rated = 1 OR why_unrated = "early_leave" '
                   'ORDER BY started, sid').fetchall()
    n = 0
    for sid, started, season, rated, why, win in ms:
        ps = c.execute('SELECT steam, team, final, coalesce(weight, 1) FROM own_match_players WHERE sid = ?', (sid,)).fetchall()
        teams = {}
        for p in ps: teams.setdefault(p[1], []).append(p)
        if len(teams) != 2: continue
        mode = MODES_N.get(len(ps) // 2); season = season or L['season'](started)
        if not mode: continue
        avg = {}
        for t, v in teams.items():
            rs = [get(p[0], mode, season) for p in v]
            avg[t] = (sum(a[0] for a in rs) / len(rs), (sum(a[1] * a[1] for a in rs) / len(rs)) ** 0.5)
        upd = []
        for t, v in teams.items():
            ot = [k for k in teams if k != t][0]
            for steam, _, final, w in v:
                if final not in ('win', 'loss', 'loss_leave') or (not rated and final != 'loss_leave'): continue
                st = get(steam, mode, season); s = 1.0 if final == 'win' else 0.0
                nr, nrd, nv = g2(st[0], st[1], st[2], [(avg[ot][0], avg[ot][1], s)])
                upd.append((st, st[0] + w * (nr - st[0]), nrd, nv, final, started))
        for st, nr, nrd, nv, final, t in upd:
            st[0], st[1], st[2] = nr, nrd, nv
            st[3] += 1; st[4] += final == 'win'; st[5] += final != 'win'; st[6] += final == 'loss_leave'; st[7] = t
        n += 1
    c.execute('DELETE FROM own_ratings')
    for (steam, mode, season), st in R.items():
        if not st[3]: continue
        c.execute('INSERT INTO own_ratings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (steam, mode, season, st[0], st[1], st[2], st[3], st[4], st[5], st[6], max(0, CAL_GAMES - st[3]), st[0] - 2 * st[1], st[7]))
    log('own_matches: shadow rating from %d matches, %d player rows' % (n, sum(1 for v in R.values() if v[3])))
    return n


def step2(db_path, log=print):
    """match_log_collect.py: resolve every own match in the order of the start (the forgiveness of the first early leave depends on
    the earlier ones), then recompute_own. Its own connection; any error -> one log line, nothing raised"""
    try:
        c = sqlite3.connect(db_path, timeout=30)
        try:
            with c:
                migrate(c)
                c.execute('UPDATE own_match_players SET early_leave = NULL')
                sids = [r[0] for r in c.execute('SELECT sid FROM own_matches ORDER BY started, sid')]
                res = {}
                for sid in sids:
                    r = resolve(sid, c); k = (r or {}).get('why') or 'rated'; res[k] = res.get(k, 0) + 1
                log('own_matches: resolved %d: %s' % (len(sids), json.dumps(res, sort_keys=True)))
                recompute_own(c, log)
        finally: c.close()
        return True
    except Exception as e: _log('step2', e); return False


# ---------- step 3: the site (/ladder/ "Elite (test)" tab), read only (10.11.2026) ----------
def _names(c, steams):
    """steam -> his latest name in our matches (own_mp_steam index)"""
    out = {}
    for s in set(steams):
        r = c.execute('SELECT name FROM own_match_players WHERE steam = ? AND coalesce(name, "") != "" ORDER BY sid DESC LIMIT 1', (s,)).fetchone()
        out[s] = r[0] if r else ''
    return out


def site_board(mode, season):
    """/ladder/api/own: the table (cal_left = 0, by cons = rating - 2*RD) and the players still in calibration (no rating shown)"""
    with _db() as c:
        try:
            rows = c.execute('SELECT steam, rating, rd, games, wins, losses, leaves, cal_left, last FROM own_ratings '
                             'WHERE mode = ? AND season = ? ORDER BY cons DESC, games DESC', (mode, season)).fetchall()
            seasons = [r[0] for r in c.execute('SELECT DISTINCT season FROM own_ratings ORDER BY season DESC')]
        except sqlite3.OperationalError: rows, seasons = [], []          # no own_ratings yet (step 2 not run)
        nm = _names(c, [r[0] for r in rows])
    board, cal = [], []
    for steam, rating, rd, games, wins, losses, leaves, cal_left, last in rows:
        p = {'steam': steam, 'name': nm.get(steam) or steam, 'games': games, 'wins': wins,
             'losses': losses - leaves, 'leaves': leaves, 'last': last}
        if cal_left > 0: p['cal_left'] = cal_left; cal.append(p)
        else:
            p.update(rank=len(board) + 1, cons=round(rating - 2 * rd), rating=round(rating), rd=round(rd)); board.append(p)
    cal.sort(key=lambda p: -(p['last'] or 0))
    return {'mode': mode, 'season': season, 'seasons': seasons, 'cal_games': CAL_GAMES, 'board': board, 'calibrating': cal}


def site_player(steam, race_key=lambda rc, modname: None, limit=50):
    """/ladder/api/own/player: his ratings and his latest own matches (teams, his final with the reason)"""
    with _db() as c:
        try:
            rt = c.execute('SELECT mode, season, rating, rd, games, wins, losses, leaves, cal_left, last FROM own_ratings '
                           'WHERE steam = ? ORDER BY season DESC, mode', (steam,)).fetchall()
        except sqlite3.OperationalError: rt = []
        sids = [r[0] for r in c.execute('SELECT sid FROM own_match_players WHERE steam = ? ORDER BY sid DESC LIMIT ?', (steam, limit))]
        ms = []
        for sid in sids:
            m = c.execute('SELECT kind, mode, map, modname, started, ended, winner_team, rated, why_unrated FROM own_matches WHERE sid = ?',
                          (sid,)).fetchone()
            if not m: continue
            ps = c.execute('SELECT steam, name, team, race, final, note, weight FROM own_match_players WHERE sid = ? ORDER BY team, pid',
                           (sid,)).fetchall()
            teams, me = {}, None
            for s, name, team, race, final, note, w in ps:
                p = {'steam': s, 'name': name or s, 'team': team, 'race': race_key(race, m[3]), 'final': final}
                teams.setdefault(team, []).append(p)
                if s == steam: me = {'team': team, 'final': final, 'note': note, 'weight': w}
            ms.append({'sid': sid, 'kind': m[0], 'mode': m[1], 'map': m[2], 'started': m[4], 'ended': m[5], 'winner_team': m[6],
                       'rated': bool(m[7]), 'why': m[8], 'me': me, 'teams': [teams[k] for k in sorted(teams, key=lambda t: (t is None, t))]})
        name = _names(c, [steam]).get(steam) or ''
    ratings = [{'mode': r[0], 'season': r[1], 'games': r[4], 'wins': r[5], 'losses': r[6] - r[7], 'leaves': r[7], 'cal_left': r[8], 'last': r[9],
                **({} if r[8] > 0 else {'cons': round(r[2] - 2 * r[3]), 'rating': round(r[2]), 'rd': round(r[3])})} for r in rt]
    return {'steam': steam, 'name': name, 'ratings': ratings, 'matches': ms}
