"""Our own automatch's matches, kept for our own rating (10.11.2026, own_rating step 1a): passive storage only.

Nothing here changes a rating, the queue or a room: every call is wrapped (an error is logged and swallowed), the tables are
written and never read by the matchmaking. sid = own_lobby room id (mid) = the node's session id = mm_history 'NM-<sid>'.
Writers: ladder.py _history_add (the players at the start, rating before), mm_ended (menu_t), _end_match (ended), mm_ruined for
NM- lobbies (ruined_t: his game fell while loading), nm/report from own_lobby (every game's report + who never reported).
The columns of step 2 (final, winner_team, result_src, rated...) are filled by the step 2 part at the end (shadow only). Plan: reports/rating_plan/STEP1_DATA_RU.md 3.3.
"""
import json, os, re, sqlite3, time, traceback

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
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')   # ladder.py sets its own in setup()


# 17.11.2026 (SirItos: "the ladder API gives the hours"): ladder.py sets HOURS = steam -> Retribution's hours in Steam or None (the
# stats service's lobby line, the same as c/me's hours_played); the site's answers carry them as hours_played (null = not known)
HOURS = None


def hours_of(steam):
    try: h = HOURS(str(steam)) if HOURS else None
    except Exception: h = None
    return h if isinstance(h, (int, float)) and not isinstance(h, bool) else None


def _log(what, e):
    print('own_matches: %s failed: %r %s' % (what, e, traceback.format_exc(limit=2).replace('\n', ' | ')), flush=True)


def setup(db_fn, lock, season_fn, data_dir=None):
    """db_fn() -> sqlite3 connection, lock = the ladder's write lock, season_fn(start) -> '2026-Q4', data_dir = where own_season.json is"""
    global _db, _lock, _season, DATA_DIR
    _db, _lock, _season = db_fn, lock, season_fn
    if data_dir: DATA_DIR = data_dir
    try:
        with _db() as c: migrate(c)          # 17.11.2026: the columns too (own_c / own_d of the player page) - not only at the next step2
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


ELITE_MOD = 'Elite'                 # own_matches.modname as Relic's room params have it: 'Elite' / 'DOW2' (vanilla)
def mod_of(x):
    """a game / mod name -> 'Elite' / 'DOW2' / None (unknown). Takes the ladder's game ('elite-3.2.1', 'elite', 'vanilla') and the
    room's modname ('Elite', 'DOW2', ''): the same form in own_matches.modname whichever wrote it (17.11.2026)"""
    x = str(x or '').strip().lower()
    if not x: return None
    if x.startswith('elite'): return ELITE_MOD
    if x in ('vanilla', 'dow2'): return 'DOW2'
    return None


def _game_of(m):
    """the match's game: m['game'] (ladder _history_add) or the pool's game part ('group|game[|nm|key]', 'lroom:<id>|group|game...')"""
    g = mod_of(m.get('game'))
    if g: return g
    parts = str(m.get('pool') or '').split('|')
    if parts and parts[0].startswith('lroom'): parts = parts[1:]
    return mod_of(parts[1]) if len(parts) > 1 else None


def on_start(m, players):
    """_history_add: the match started (players = the mm_history rows: steam, pid, name, team, rating, race, hero)"""
    try:
        sid = sid_of(m.get('lobby')); players = list(players or [])
        if sid is None: return
        now = int(time.time()); started = int(m.get('started') or now)
        with _lock, _db() as c:
            c.execute('INSERT OR IGNORE INTO own_matches (sid, lobby, kind, mode, map, modname, season, node, started, flags, updated) '
                      'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                      (sid, m['lobby'], 'room' if m.get('lroom') else 'mm', m.get('mode'), m.get('map'), _game_of(m),   # 17.11: was m.get('game'), never set since 10.11
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
EARLY_S = 120           # s from the start: a leave before this = the match did not take place (rated for nobody); PRE_EARLY_S in a preseason
FORGIVE_S = 86400       # ... and the leaver is forgiven his first such leave in this window, every next one is his loss
ALL_GONE_S = 3          # s: everyone gone within this (before any result) = our node / the network, no rating
SHORT_W = 0.5           # weight of the loss of a leaver's teammate whose team then lost short-handed
ROOMS_RATED = False     # launcher rooms: there is no "rated" tick yet (rule 1) -> unrated 'room'
CAL_GAMES = 5           # the first games of a player in a mode+season: calibration (cal_left)
MODES_N = {1: '1v1', 2: '2v2', 3: '3v3'}
SHORT_MATCH_S = 240     # s from the start: a match over before this (a surrender or a leave - nothing else ends a game so fast) is
                        # unrated for all; a leaver in it still gets his loss (17.11.2026, anti-abuse 3a; EARLY_S keeps its own rule)
REPEAT_N = 3            # 1v1: the same pair's rated matches in REPEAT_S before this one - from the (REPEAT_N+1)-th on ...
REPEAT_S = 86400
REPEAT_W = 0.25         # ... both players' rating change is scaled by this (anti-abuse 3b, 17.11.2026)
UNELIGIBLE = ('not_full_teams', 'no_steam', 'room', 'no_history', 'not_elite', 'peer_order')   # rule 1: a manual winner does not make these rated
SEASON_FILE = 'own_season.json'   # <data>/own_season.json {"label": "2026-pre", "start": <unix ts>, "info": "https://..." (optional)}: the (pre)season of the own rating
# 17.11.2026 (SirItos: «ливы в первые 2-3 минуты - игра не в рейтинг»): with own_season.json the early-leave window and the short-match
# threshold are both 3 min, and only Elite matches are rated (a vanilla automatch match stays stored, unrated 'not_elite').
# Without the file: EARLY_S / SHORT_MATCH_S and every mod, as before.
PRE_EARLY_S = 180
PRE_SHORT_S = 180

MIGRATE = [('own_matches', 'notes', 'TEXT'), ('own_matches', 'resolved', 'INTEGER'),
           ('own_match_players', 'weight', 'REAL'), ('own_match_players', 'early_leave', 'INTEGER'),
           ('own_match_players', 'note', 'TEXT'),
           # 17.11.2026 (the player page /ladder/player/<steam>): what this match did to the number of the table (recompute_own) -
           # own_c = his conservative rating (rating - 2*RD) after it, NULL while he still calibrates; own_d = its change, only when he
           # was out of calibration before it too (the hidden rating never leaks); own_n = his games in the mode/season after it
           ('own_match_players', 'own_c', 'REAL'), ('own_match_players', 'own_d', 'REAL'), ('own_match_players', 'own_n', 'INTEGER')]
RATINGS_SCHEMA = '''
CREATE TABLE IF NOT EXISTS own_ratings (
  steam TEXT, mode TEXT, season TEXT, rating REAL, rd REAL, vol REAL, games INTEGER, wins INTEGER, losses INTEGER,
  leaves INTEGER, cal_left INTEGER, cons REAL, last INTEGER, PRIMARY KEY (steam, mode, season));
CREATE TABLE IF NOT EXISTS own_overrides (
  id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER, action TEXT, team INTEGER, note TEXT, ts INTEGER);
CREATE INDEX IF NOT EXISTS own_overrides_mid ON own_overrides (match_id, id);
CREATE TABLE IF NOT EXISTS own_ratings_prev (
  steam TEXT, mode TEXT, season TEXT, rating REAL, rd REAL, vol REAL, games INTEGER, wins INTEGER, losses INTEGER,
  leaves INTEGER, cal_left INTEGER, cons REAL, last INTEGER, PRIMARY KEY (steam, mode, season));
'''
# own_ratings_prev (17.11.2026, SirItos: "in the profile the stats of the last test - the previous season"): with own_season.json the
# matches before its start, by the old rules (no preseason cutoffs, their quarter season) - the player page's "Previous season".
# Kept apart from own_ratings: the queue, the launcher (/own/all) and the table read only the preseason there


def migrate(c):
    c.executescript(SCHEMA + RATINGS_SCHEMA)       # own_overrides: the manual decisions (own_admin.py), a log - rows are never deleted
    for t, col, typ in MIGRATE:
        if col not in [r[1] for r in c.execute('PRAGMA table_info(%s)' % t)]:
            c.execute('ALTER TABLE %s ADD COLUMN %s %s' % (t, col, typ))


def season_cfg(data_dir=None, log=print):
    """<data>/own_season.json -> {'label', 'start'[, 'info', 'maps']} or None (no file = no preseason: every match, the quarter season as before).
    A broken file is logged and treated as no file."""
    fn = os.path.join(data_dir or DATA_DIR, SEASON_FILE)
    try:
        with open(fn, encoding='utf-8') as f: d = json.load(f)
    except FileNotFoundError: return None
    except Exception as e: log('own_matches: %s unreadable: %r' % (fn, e)); return None
    label, start = d.get('label') if isinstance(d, dict) else None, d.get('start') if isinstance(d, dict) else None
    if not (isinstance(label, str) and re.fullmatch(r'[\w.-]{1,9}', label) and isinstance(start, (int, float)) and not isinstance(start, bool)):
        log('own_matches: %s: want {"label": "<=9 chars", "start": <unix ts>}, got %r' % (fn, d)); return None
    out = {'label': label, 'start': int(start)}
    info = d.get('info')                         # 17.11.2026, launcher 1.6.20: the page about the (pre)season, its (i) in the profile
    if isinstance(info, str) and re.fullmatch(r'https://[^\s"<>]{1,300}', info): out['info'] = info
    elif info is not None: log('own_matches: %s: "info" must be an https:// address, got %r' % (fn, info))
    # 18.11.2026 (SirItos): the season's map pool of the Elite automatch, "maps": {"1v1": [keys], "2v2": [...], "3v3": [...]} - while
    # a mode has one, the server picks one of exactly these at random (no player bans); the site's "Season maps" shows them. The keys
    # are checked against the map catalog by ladder.py (_season_pool); a missing "maps" or mode = the old rules
    maps = d.get('maps')
    if isinstance(maps, dict):
        pool = {m: list(dict.fromkeys(k for k in v if isinstance(k, str) and re.fullmatch(r'[\w.-]{1,64}', k)))[:20]
                for m, v in maps.items() if m in MODES_ALL and isinstance(v, list)}
        if any(pool.values()): out['maps'] = {m: v for m, v in pool.items() if v}
    elif maps is not None: log('own_matches: %s: "maps" must be {"1v1": [map keys], ...}, got %r' % (fn, maps))
    return out


def default_season(data_dir=None):
    """the API's default season of the own rating: the preseason's label when own_season.json exists, else None (the caller's quarter)"""
    cfg = season_cfg(data_dir)
    return cfg['label'] if cfg else None


def override_of(c, sid):
    """the latest manual decision for a match: {'action': 'void'|'winner', 'team', 'note'} or None ('clear' = back to the rules)"""
    try: row = c.execute('SELECT action, team, note FROM own_overrides WHERE match_id = ? ORDER BY id DESC LIMIT 1', (sid,)).fetchone()
    except sqlite3.OperationalError: return None      # no table yet
    if not row or row[0] not in ('void', 'winner'): return None
    return {'action': row[0], 'team': row[1], 'note': row[2]}


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


def decide(m, ps, early_before=lambda steam: 0, pair_before=lambda a, b: 0):
    """the result of one match. m: {kind, started, end_est (bool), all_gone_s, conflict (bool), override (None or {action: 'void'|'winner',
    team}), and in a preseason early_s / short_s (s) + elite_only with mod ('Elite' / 'DOW2' / None)}; ps: [{steam, team, rep (1/0/3/-1/None), rep_t, leave (s, his effective leave time or None)}]; pair_before(a, b) = the 1v1
    pair's rated matches in REPEAT_S before this one -> {winner_team, result_src, rated, why, notes, players: {steam: (final, weight,
    early, note)}}. Pure: the tests feed it made-up matches. Order: the rules, then the manual decision, then the repeat-pair weight."""
    r = _decide_rules(m, ps, early_before)
    if m.get('override'): _apply_override(r, ps, m['override'])
    if r['rated'] and r['why'] is None and len(ps) == 2:          # anti-abuse 3b: the same 1v1 pair again and again in a day
        n = pair_before(ps[0]['steam'], ps[1]['steam'])
        if n >= REPEAT_N:
            r['notes'].append('repeat_pair_%d' % (n + 1))
            for f in r['players'].values():
                f[1] *= REPEAT_W; f[3] = 'repeat_pair' if not f[3] else f[3] + ',repeat_pair'
    return r


def _apply_override(r, ps, ov):
    """a manual decision (own_admin.py) on top of decide()'s rules: 'void' = unrated for all (finals kept for the history, an early
    leave in it not counted); 'winner' = that team won, rated unless rule 1 says no (a leaver of the losing team keeps loss_leave)"""
    teams = {p['team'] for p in ps}
    if ov.get('action') == 'void':
        r.update(why='void', rated=0, result_src='manual'); r['notes'].append('manual_void')
        for f in r['players'].values(): f[2] = 0
    elif ov.get('action') == 'winner':
        w = ov.get('team')
        if len(teams) != 2 or w not in teams: r['notes'].append('manual_bad_team'); return
        why = r['why'] if r['why'] in UNELIGIBLE else None
        r.update(winner_team=w, result_src='manual', why=why, rated=0 if why else 1); r['notes'].append('manual_winner')
        for p in ps:
            f = r['players'][p['steam']]
            if p['team'] == w: f[:] = ['win', 1.0, 0, 'manual_winner']
            elif f[0] != 'loss_leave': f[:] = ['loss', 1.0, 0, 'manual_winner']


def _decide_rules(m, ps, early_before):
    """decide() without the manual decision and the repeat-pair weight: rules 1, 4, 5 + the short match (3a)"""
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
    elif m.get('elite_only') and m.get('mod') != ELITE_MOD: why_el = 'not_elite'   # preseason: the Elite table only (vanilla kept, unrated)
    # 20.11.2026 (SirItos 19.11, m19 / m20): the game server numbered two guests otherwise than the host's game did (battle_relay
    # match_log "swapped") - each played the other's army, the results are on the wrong people: never rated.
    # 20.11.2026 (SirItos: "don't mark it yet - we aim for no swaps at all"): only with data/own_peer_order_unrate present;
    # otherwise the match is rated as usual and the swap stays in the node's log / the match's notes
    elif m.get('peer_order') and os.path.exists(os.path.join(DATA_DIR, 'own_peer_order_unrate')): why_el = 'peer_order'
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
        src = 'node'; end_t = t_lost                     # the game ended for the team that left
    if all(p in leavers for p in teams[win]): return done('winners_left', 'check')
    r['winner_team'] = win
    # rule 4, early: a leave before EARLY_S = no match; the leaver loses unless it is his first such in FORGIVE_S
    early = [p for p in leavers if p['leave'] - started < m.get('early_s', EARLY_S)] if started else []
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
    # anti-abuse 3a: over before SHORT_MATCH_S = a surrender or a leave: unrated (the finals stay for the history; a leaver's loss_leave
    # still counts in recompute_own, as after an early leave)
    if started and end_t is not None and end_t - started < m.get('short_s', SHORT_MATCH_S):
        r['notes'].append('short_%ds' % (end_t - started))
        return done('short_match', src)
    return done(None, src)


def _match_input(c, sid):
    """own_matches + own_match_players rows -> decide()'s m, ps (+ pid by steam)"""
    row = c.execute('SELECT kind, started, reports, node_log, flags, modname FROM own_matches WHERE sid = ?', (sid,)).fetchone()
    if not row: return None, None
    kind, started, reports, node_log, flags, modname = row
    rep = _loads(reports, {}) or {}
    logs = _loads(node_log, []) or []
    if not isinstance(logs, list): logs = [logs]
    best = max(logs, key=lambda x: x.get('ticks') or 0) if logs else {}
    m = dict(kind=kind, started=started, end_est=False, all_gone_s=best.get('all_gone_within_s'), conflict=False, mod=mod_of(modname),
             peer_order=any(isinstance(x, dict) and x.get('swapped') for x in logs))
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


def resolve(sid, c, cfg=None):
    """decide() on the stored data and write it: own_matches winner_team/result_src/rated/why_unrated/notes, players final/weight/early_leave/note.
    The manual decision from own_overrides; cfg = season_cfg(): the repeat-pair count looks only at the preseason's matches"""
    m, ps = _match_input(c, sid)
    if m is None: return None
    m['override'] = override_of(c, sid)
    if cfg: m.update(early_s=PRE_EARLY_S, short_s=PRE_SHORT_S, elite_only=True)
    st = m['started'] or 0
    def early_before(steam):
        return c.execute('SELECT COUNT(*) FROM own_match_players p JOIN own_matches x ON x.sid = p.sid WHERE p.steam = ? AND p.early_leave = 1 '
                         'AND p.sid != ? AND x.started >= ? AND x.started < ?', (steam, sid, st - FORGIVE_S, st)).fetchone()[0]
    def pair_before(a, b):                               # the earlier rated 1v1 matches of exactly these two (resolved before this one)
        return c.execute('SELECT COUNT(*) FROM own_matches x WHERE x.rated = 1 AND x.sid != ? AND x.started >= ? AND '
                         '(x.started < ? OR (x.started = ? AND x.sid < ?)) AND '
                         '(SELECT COUNT(*) FROM own_match_players p WHERE p.sid = x.sid) = 2 AND '
                         '(SELECT COUNT(*) FROM own_match_players p WHERE p.sid = x.sid AND p.steam IN (?, ?)) = 2',
                         (sid, max(st - REPEAT_S, cfg['start'] if cfg else 0), st, st, sid, a, b)).fetchone()[0]
    r = decide(m, ps, early_before, pair_before)
    c.execute('UPDATE own_matches SET winner_team = ?, result_src = ?, rated = ?, why_unrated = ?, notes = ?, resolved = ? WHERE sid = ?',
              (r['winner_team'], r['result_src'], r['rated'], r['why'], ','.join(r['notes']) or None, int(time.time()), sid))
    for steam, (final, w, early, note) in r['players'].items():
        c.execute('UPDATE own_match_players SET final = ?, weight = ?, early_leave = ?, note = ? WHERE sid = ? AND steam = ?',
                  (final, w, early, note, sid, steam))
    return r


def shown(prev, cons, final):
    """20.11.2026 (SirItos, variant B): the DISPLAYED rating - the table, the launcher, the player page and its match list - never goes
    up after a loss nor down after a win. Glicko (mean, RD) stays as it is (the queue uses the mean); the displayed number is the
    conservative rating (mean - 2*RD) made monotonic by the result: the first = the conservative at the end of calibration, after a
    win max(previous, conservative), after a loss / a leave min(previous, conservative) (0 where the real number moved the other way)"""
    if prev is None: return cons
    return max(prev, cons) if final == 'win' else min(prev, cons)


def recompute_own(c, log=print, cfg=None):
    """the shadow rating from scratch: Glicko-2 of the ladder over own_matches rated=1 (+ the leaver's own loss in an 'early_leave' /
    'short_match' match), in the order of the start; one match = one period, against the other team's average (as ladder.recompute);
    the weight w < 1 scales his rating change. -> own_ratings (cons = the DISPLAYED rating, see shown(); cal_left = calibration games
    left); own_match_players own_c / own_d = the displayed rating after the match and its change.
    cfg = season_cfg() (the preseason): only the matches started at/after cfg['start'], all under cfg['label']; None = every match,
    its own quarter season (as before 17.11.2026). With cfg the matches before its start go to own_ratings_prev (the previous season:
    the old test, its quarter season, as it was before the preseason) - the player page shows them apart"""
    L = ladder_fn(); g2 = L['glicko']
    R, P = {}, {}
    ms = c.execute('SELECT sid, started, season, rated, why_unrated, winner_team FROM own_matches '
                   'WHERE (rated = 1 OR why_unrated IN (?, ?)) '
                   'ORDER BY started, sid', ('early_leave', 'short_match')).fetchall()
    n, marks, D = 0, [], R
    def get(steam, mode, season): return D.setdefault((steam, mode, season), [1500.0, 350.0, 0.06, 0, 0, 0, 0, 0, None])
    for sid, started, season, rated, why, win in ms:
        prev = bool(cfg) and (started or 0) < cfg['start']
        D = P if prev else R
        if cfg and not prev: season = cfg['label']
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
                upd.append((st, st[0] + w * (nr - st[0]), nrd, nv, final, started, steam))
        for st, nr, nrd, nv, final, t, steam in upd:
            before = st[8]
            st[0], st[1], st[2] = nr, nrd, nv
            st[3] += 1; st[4] += final == 'win'; st[5] += final != 'win'; st[6] += final == 'loss_leave'; st[7] = t
            st[8] = shown(st[8], st[0] - 2 * st[1], final) if st[3] >= CAL_GAMES else None
            after = st[8]
            marks.append((after, after - before if after is not None and before is not None else None, st[3], sid, steam))
        n += not prev
    c.execute('UPDATE own_match_players SET own_c = NULL, own_d = NULL, own_n = NULL WHERE own_n IS NOT NULL')
    c.executemany('UPDATE own_match_players SET own_c = ?, own_d = ?, own_n = ? WHERE sid = ? AND steam = ?', marks)
    for tbl, D in (('own_ratings', R), ('own_ratings_prev', P)):
        c.execute('DELETE FROM ' + tbl)
        for (steam, mode, season), st in D.items():
            if not st[3]: continue
            c.execute('INSERT INTO %s VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)' % tbl,
                      (steam, mode, season, st[0], st[1], st[2], st[3], st[4], st[5], st[6], max(0, CAL_GAMES - st[3]),
                       st[8] if st[8] is not None else st[0] - 2 * st[1], st[7]))
    log('own_matches: shadow rating from %d matches, %d player rows%s' % (n, sum(1 for v in R.values() if v[3]),
                                                                     ' (season %s from %d)' % (cfg['label'], cfg['start']) if cfg else ''))
    return n


def fill_mods(c):
    """own_matches.modname where on_start wrote none (10-17.11.2026: it took a missing m['game']): the room's modname that own_lobby
    stored with the match (matches.data, the same id). -> rows filled"""
    try:
        rows = c.execute('SELECT o.sid, json_extract(x.data, "$.modname") FROM own_matches o JOIN matches x ON x.id = o.sid '
                         'WHERE coalesce(o.modname, "") = ""').fetchall()
    except sqlite3.OperationalError: return 0          # no matches table (a test DB)
    n = 0
    for sid, mn in rows:
        if mod_of(mn): c.execute('UPDATE own_matches SET modname = ? WHERE sid = ?', (mod_of(mn), sid)); n += 1
    return n


def step2(db_path, log=print, cfg='file'):
    """match_log_collect.py: resolve every own match in the order of the start (the forgiveness of the first early leave and the
    repeat-pair count depend on the earlier ones), then recompute_own. cfg: 'file' = own_season.json next to the DB (none = as before),
    or a dict / None given by a test. Its own connection; any error -> one log line, nothing raised"""
    try:
        if cfg == 'file': cfg = season_cfg(os.path.dirname(os.path.abspath(db_path)), log)
        c = sqlite3.connect(db_path, timeout=30)
        try:
            with c:
                migrate(c)
                fill_mods(c)
                c.execute('UPDATE own_match_players SET early_leave = NULL')
                sids = c.execute('SELECT sid, coalesce(started, 0) FROM own_matches ORDER BY started, sid').fetchall()
                res = {}
                for sid, st in sids:      # 17.11.2026: a match before the preseason = the old test - its old rules (the previous season)
                    r = resolve(sid, c, cfg if cfg and st >= cfg['start'] else None); k = (r or {}).get('why') or 'rated'; res[k] = res.get(k, 0) + 1
                log('own_matches: resolved %d: %s' % (len(sids), json.dumps(res, sort_keys=True)))
                recompute_own(c, log, cfg)
        finally: c.close()
        return True
    except Exception as e: _log('step2', e); return False


# ---------- step 3: the site (/ladder/ "Elite (test)" tab, "Elite - preseason" with own_season.json), read only (10.11.2026) ----------
def site_season():
    """/ladder/api/own/season: the page's texts follow it (preseason or the old test)"""
    cfg = season_cfg()
    return {'preseason': bool(cfg), 'label': cfg['label'] if cfg else None, 'start': cfg['start'] if cfg else None, 'info': (cfg or {}).get('info')}


def _names(c, steams):
    """steam -> his latest name in our matches (own_mp_steam index)"""
    out = {}
    for s in set(steams):
        r = c.execute('SELECT name FROM own_match_players WHERE steam = ? AND coalesce(name, "") != "" ORDER BY sid DESC LIMIT 1', (s,)).fetchone()
        out[s] = r[0] if r else ''
    return out


def _roster(c, start, mode=None, steam=None):
    """17.11.2026 (SirItos: "do not wipe the table"): the players of the test before the preseason - a rated Elite match before its
    start - stay in the preseason's table, in calibration 0/5 until they play (18.11: in every mode's table). -> {(steam, mode)}"""
    q = ('SELECT DISTINCT p.steam, m.mode FROM own_match_players p JOIN own_matches m ON m.sid = p.sid '
         'WHERE m.rated = 1 AND m.modname = ? AND coalesce(m.started, 0) < ? AND coalesce(p.steam, "") != ""')
    a = [ELITE_MOD, start]
    if mode: q += ' AND m.mode = ?'; a.append(mode)
    if steam: q += ' AND p.steam = ?'; a.append(steam)
    try: return {(str(r[0]), r[1]) for r in c.execute(q, a)}
    except sqlite3.OperationalError: return set()


def site_board(mode, season):
    """/ladder/api/own: the table (cal_left = 0, by cons = rating - 2*RD) and the players still in calibration (no rating shown)"""
    with _db() as c:
        try:
            rows = c.execute('SELECT steam, rating, rd, games, wins, losses, leaves, cal_left, last, cons FROM own_ratings '
                             'WHERE mode = ? AND season = ? ORDER BY cons DESC, games DESC', (mode, season)).fetchall()
            seasons = [r[0] for r in c.execute('SELECT DISTINCT season FROM own_ratings ORDER BY season DESC')]
        except sqlite3.OperationalError: rows, seasons = [], []          # no own_ratings yet (step 2 not run)
        cfg = season_cfg()
        have = {str(r[0]) for r in rows}
        # 18.11.2026 (SirItos: "0/5 everywhere, the same"): a roster player is in EVERY mode's table (calibration 0/5), not only in the
        # modes he played in the test; a mode where he already has an entry shows that entry
        extra = sorted({s for s, _ in _roster(c, cfg['start'])} - have) if cfg and season == cfg['label'] else []
        nm = _names(c, [r[0] for r in rows] + extra)
    board, cal = [], []
    for steam, rating, rd, games, wins, losses, leaves, cal_left, last, cons in rows:
        p = {'steam': steam, 'name': nm.get(steam) or steam, 'games': games, 'wins': wins,
             'losses': losses - leaves, 'leaves': leaves, 'last': last, 'hours_played': hours_of(steam)}
        if cal_left > 0: p['cal_left'] = cal_left; cal.append(p)
        else:
            p.update(rank=len(board) + 1, cons=round(cons), rating=round(rating), rd=round(rd)); board.append(p)   # cons = the displayed (shown())
    for steam in extra:                  # the test's players with no preseason game yet: calibration 0/5 (the table is not wiped)
        cal.append({'steam': steam, 'name': nm.get(steam) or steam, 'games': 0, 'wins': 0, 'losses': 0, 'leaves': 0, 'last': None,
                    'hours_played': hours_of(steam), 'cal_left': CAL_GAMES})
    cal.sort(key=lambda p: -(p['last'] or 0))
    # 17.11.2026 (SirItos): one table - the rated players by the shown rating, then those in calibration by name ("калибровка k/5");
    # the /ladder/rating/ page reads 'rows', the old tab 'board' + 'calibrating' (unchanged)
    rows = [dict(p, calibrating=False, cal_played=CAL_GAMES, cal_needed=CAL_GAMES) for p in board]
    rows += [dict(p, calibrating=True, cal_played=p['games'], cal_needed=CAL_GAMES, rank=None)
             for p in sorted(cal, key=lambda p: (str(p['name']).casefold(), p['steam']))]
    return {'mode': mode, 'season': season, 'seasons': seasons, 'cal_games': CAL_GAMES, 'board': board, 'calibrating': cal,
            'rows': rows, 'preseason': bool(cfg), 'mod': ELITE_MOD}


def site_all(season):
    """/ladder/api/own/all (launcher 1.6.20, 17.11.2026): the whole table of a season in one answer - every player, every mode -
    for the launcher, which shows the Elite rating of any player it lists (Online, the lobbies, the tips) without asking per player.
    players: {steam: {mode: {c, g, w, l, lv, cal, rank}, hours_played}} - c = the number of the site's table (cons = rating - 2*RD, absent while
    calibrating), rank = the place among the calibrated of that mode (the site's order: cons, then games), cal = calibration games left;
    the losses without the leaves, as site_board"""
    with _db() as c:
        try:
            rows = c.execute('SELECT steam, mode, rating, rd, games, wins, losses, leaves, cal_left, cons FROM own_ratings '
                             'WHERE season = ? ORDER BY mode, cons DESC, games DESC', (season,)).fetchall()
        except sqlite3.OperationalError: rows = []          # no own_ratings yet (step 2 not run)
    players, place = {}, {}
    for steam, mode, rating, rd, games, wins, losses, leaves, cal_left, cons in rows:
        p = {'g': games, 'w': wins, 'l': losses - leaves, 'lv': leaves, 'cal': cal_left}
        if cal_left <= 0:
            place[mode] = place.get(mode, 0) + 1
            p.update(c=round(cons), rank=place[mode])
        players.setdefault(steam, {'hours_played': hours_of(steam)})[mode] = p   # 17.11.2026: + his hours (null = not known)
    return {'season': season, 'cal_games': CAL_GAMES, 'players': players}


def site_player(steam, race_key=lambda rc, modname: None, limit=50):
    """/ladder/api/own/player: his ratings and his latest own matches (teams, his final with the reason); in a preseason
    (own_season.json) only the matches from its start - the earlier ones are in no rating"""
    cfg = season_cfg()
    with _db() as c:
        try:
            rt = c.execute('SELECT mode, season, rating, rd, games, wins, losses, leaves, cal_left, last, cons FROM own_ratings '
                           'WHERE steam = ? ORDER BY season DESC, mode', (steam,)).fetchall()
        except sqlite3.OperationalError: rt = []
        sids = [r[0] for r in c.execute('SELECT p.sid FROM own_match_players p JOIN own_matches m ON m.sid = p.sid '
                                        'WHERE p.steam = ? AND coalesce(m.started, 0) >= ? ORDER BY p.sid DESC LIMIT ?',
                                        (steam, cfg['start'] if cfg else -1, limit))]
        ms = []
        for sid in sids:
            m = c.execute('SELECT kind, mode, map, modname, started, ended, winner_team, rated, why_unrated FROM own_matches WHERE sid = ?',
                          (sid,)).fetchone()
            if not m: continue
            ps = c.execute('SELECT steam, name, team, race, final, note, weight, own_c, own_d, own_n FROM own_match_players '
                           'WHERE sid = ? ORDER BY team, pid', (sid,)).fetchall()
            teams, me = {}, None
            for s, name, team, race, final, note, w, oc, od, on in ps:
                p = {'steam': s, 'name': name or s, 'team': team, 'race': race_key(race, m[3]), 'final': final}
                teams.setdefault(team, []).append(p)
                if s == steam:   # 17.11.2026: + the table's number after this match and its change (None in calibration), games after it
                    me = {'team': team, 'final': final, 'note': note, 'weight': w,
                          'c': None if oc is None else round(oc), 'd': None if od is None else round(od), 'n': on}
            ms.append({'sid': sid, 'kind': m[0], 'mode': m[1], 'map': m[2], 'started': m[4], 'ended': m[5], 'winner_team': m[6],
                       'rated': bool(m[7]), 'why': m[8], 'me': me, 'teams': [teams[k] for k in sorted(teams, key=lambda t: (t is None, t))]})
        name = _names(c, [steam]).get(steam) or ''
        ranks = {}                 # 17.11.2026: his place in each calibrated mode (the board's order: cons, then games)
        for r in rt:
            if r[8] <= 0:
                ranks[(r[0], r[1])] = _rank(c, 'own_ratings', r)
        prev, cal_modes = None, []
        if cfg:     # 17.11.2026 (SirItos): the previous season (the test before the preseason) and the modes he is in the roster of
            cal_modes = sorted(m for _, m in _roster(c, cfg['start'], steam=steam) if m in MODES_ALL)
            try:
                ps = c.execute('SELECT MAX(season) FROM own_ratings_prev').fetchone()[0]
                pr = c.execute('SELECT mode, season, rating, rd, games, wins, losses, leaves, cal_left, last, cons FROM own_ratings_prev '
                               'WHERE steam = ? AND season = ? ORDER BY mode', (steam, ps)).fetchall() if ps else []
            except sqlite3.OperationalError: ps, pr = None, []
            if pr: prev = {'season': ps, 'ratings': [_rating_row(r, _rank(c, 'own_ratings_prev', r) if r[8] <= 0 else None) for r in pr]}
    ratings = [_rating_row(r, ranks.get((r[0], r[1]))) for r in rt]
    return {'steam': steam, 'name': name, 'ratings': ratings, 'matches': ms, 'hours_played': hours_of(steam), 'prev': prev, 'cal_modes': cal_modes}


def _rank(c, tbl, r):
    """the place of a calibrated row (mode, season, rating, rd, games, ...) in its table: the board's order, cons then games"""
    return 1 + c.execute('SELECT COUNT(*) FROM %s WHERE mode = ? AND season = ? AND cal_left <= 0 AND '
                         '(cons > ? OR (cons = ? AND games > ?))' % tbl, (r[0], r[1], r[10], r[10], r[4])).fetchone()[0]


def _rating_row(r, rank):
    return {'mode': r[0], 'season': r[1], 'games': r[4], 'wins': r[5], 'losses': r[6] - r[7], 'leaves': r[7], 'cal_left': r[8], 'last': r[9],
            **({} if r[8] > 0 else {'cons': round(r[10]), 'rating': round(r[2]), 'rd': round(r[3]), 'rank': rank})}


# ---------- 17.11.2026: the own rating for the matchmaking and the launcher (read only) ----------
# A copy of own_ratings of one season in memory, read again at most every CACHE_S (the collector rewrites the table every 5 min):
# the queue (every join) and the launcher's Online block (every second for the stream) never query the DB for it.
CACHE_S = 60
_CACHE = {'t': 0, 'season': None, 'rows': {}}
MODES_ALL = ('1v1', '2v2', '3v3')


def _season_rows(season):
    """{steam: {mode: (rating, rd, games, wins, losses, leaves, cal_left)}} of a season, cached CACHE_S"""
    now = time.time()
    if _CACHE['season'] == season and now - _CACHE['t'] < CACHE_S: return _CACHE['rows']
    rows = {}
    try:
        with _db() as c:
            for steam, mode, r, rd, g, w, l, lv, cl, cn in c.execute('SELECT steam, mode, rating, rd, games, wins, losses, leaves, cal_left, '
                                                                       'cons FROM own_ratings WHERE season = ?', (season,)):
                rows.setdefault(str(steam), {})[mode] = (r, rd, g, w, l, lv, cl, cn)
    except Exception as e:
        if not isinstance(e, sqlite3.OperationalError): _log('own cache', e)
        rows = _CACHE['rows'] if _CACHE['season'] == season else {}
    _CACHE.update(t=now, season=season, rows=rows)
    return rows


def api_season(quarter=None):
    """the season the launcher and the queue use: the preseason's label, else the given quarter (ladder current_season())"""
    cfg = season_cfg()
    return (cfg['label'] if cfg else quarter), bool(cfg)


def own_mode(row):
    """one mode of a player for the API (docs/OWN_RATING_API.md): the rating is hidden (None) while he calibrates"""
    if not row:
        return {'rating': None, 'rd': None, 'conservative': None, 'games': 0, 'wins': 0, 'losses': 0, 'leaves': 0,
                'calibrating': True, 'cal_played': 0, 'cal_needed': CAL_GAMES}
    r, rd, g, w, l, lv, cl = row[:7]
    cn = row[7] if len(row) > 7 and row[7] is not None else r - 2 * rd      # 20.11.2026: the displayed rating (shown())
    cal = cl > 0
    return {'rating': None if cal else round(r), 'rd': None if cal else round(rd), 'conservative': None if cal else round(cn),
            'games': g, 'wins': w, 'losses': l - lv, 'leaves': lv, 'calibrating': cal, 'cal_played': min(g, CAL_GAMES), 'cal_needed': CAL_GAMES}


def player_own(steam, quarter=None):
    """the launcher's own object: {season, preseason, mod, modes: {1v1/2v2/3v3: own_mode}}"""
    season, pre = api_season(quarter)
    rows = _season_rows(season).get(str(steam), {}) if season else {}
    return {'season': season, 'preseason': pre, 'mod': ELITE_MOD, 'modes': {m: own_mode(rows.get(m)) for m in MODES_ALL}}


def card_own(steam, quarter=None):
    """the Online block (users.card): only the modes he has played, {mode: {rating (conservative or None), calibrating, cal_played}}"""
    season, _ = api_season(quarter)
    rows = _season_rows(season).get(str(steam), {}) if season else {}
    out = {}
    for m in MODES_ALL:
        if m in rows:
            x = own_mode(rows[m]); out[m] = {'rating': x['conservative'], 'calibrating': x['calibrating'], 'cal_played': x['cal_played']}
    return out


# the matchmaking by the own rating (ladder._own_mm / _own_window), only with own_season.json and only for Elite:
MM_NEW = (1500.0, 350.0)      # a player with no game in the season (Glicko's start)
MM_WIN_BASE = 150             # the window of rating spread in a match: this ...
MM_WIN_PER_MIN = 50           # ... + this per minute the longest waiting of them has waited ...
MM_WIN_FREE_S = 360           # ... and none after this: nobody waits more than 6 min because of the rating
MM_WIN_RD = 100               # an uncertain player (RD over this - in calibration, after a long break) widens it by the excess


def mm_rating(steam, mode):
    """-> (rating, rd, games, rsrc) for the queue: a rated player his Glicko mean (not rating-2RD: the match must be even, the
    conservative number only orders the table), a player in calibration 1500 with his RD (his hidden rating must not reach the
    lobby or the queue's list), a new one 1500/350"""
    season, _ = api_season()
    row = _season_rows(season).get(str(steam), {}).get(mode) if season else None
    if not row: return MM_NEW[0], MM_NEW[1], 0, 'own_new'
    r, rd, g = row[0], row[1], row[2]
    if row[6] > 0: return MM_NEW[0], rd, g, 'own_cal'
    return r, rd, g, 'own'


def mm_window(wait_s, rd_max=0.0):
    """the largest rating spread allowed in a match whose longest waiting player has waited wait_s; None = any"""
    if wait_s >= MM_WIN_FREE_S: return None
    return MM_WIN_BASE + MM_WIN_PER_MIN * max(0.0, wait_s) / 60.0 + max(0.0, (rd_max or 0) - MM_WIN_RD)
