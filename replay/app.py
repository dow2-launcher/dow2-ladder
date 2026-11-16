#!/usr/bin/env python3
"""Страница разбора реплеев DoW2 Retribution / Elite: https://rts.fintebtc.de/replay/
Загрузка .rec (сырые байты из браузера) → make_report.py → страница результатов с постоянной ссылкой.
По кнопке — история матча (Claude по выжимке фактов), с суточным лимитом.
Слушает 127.0.0.1:8215, nginx проксирует /replay/."""
import gzip, hashlib, html, json, os, re, sqlite3, subprocess, sys, threading, time, unicodedata, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
APP = os.path.dirname(os.path.abspath(__file__))            # /srv/replayweb/app — код и парсер, только чтение
ROOT = os.path.dirname(APP); STORE = ROOT + '/data'; QUEUE = ROOT + '/queue'; PORT = int(os.environ.get('PORT', 8215))
STORY_LIMIT = int(os.environ.get('STORY_LIMIT', 20)); story_today = {'day': '', 'n': 0}; running = set()
UPLOADS_PER_HOUR = 20; STORE_MAX = 12 * 1024**3; ip_hits = {}   # с одного адреса 20 загрузок в час; хранилище до 12 ГБ (13.11: пул реплеев лаунчера)
def client_ip(h): return h.headers.get('CF-Connecting-IP') or h.headers.get('X-Real-IP') or h.client_address[0]
def allow_upload(ip):
    now = time.time(); hits = [t for t in ip_hits.get(ip, []) if now - t < 3600]
    if len(hits) >= UPLOADS_PER_HOUR: ip_hits[ip] = hits; return False
    hits.append(now); ip_hits[ip] = hits; return True
def store_size():
    return sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(STORE) for f in fs)
os.makedirs(STORE, exist_ok=True)

# ---------- индекс реплеев: один матч — один реплей ----------
# После матча реплей присылает каждый участник (MMFind из игры). Файлы у всех разные (шапка), но поток команд один и тот же:
# ключ матча = карта + profile_id игроков + первые 200 команд. Храним одну копию — самую длинную (кто вышел раньше, у того обрезана).
sys.path.insert(0, APP); import dow2rec
IDX = STORE + '/index.sqlite'; _ilock = threading.Lock()
def idb():
    c = sqlite3.connect(IDX, timeout=30); c.execute('PRAGMA journal_mode=WAL'); return c
with idb() as c:
    c.executescript('''CREATE TABLE IF NOT EXISTS replays (rid TEXT PRIMARY KEY, mkey TEXT UNIQUE, name TEXT, lobby TEXT, map TEXT,
        players TEXT, ticks INTEGER, recorded TEXT, uploaded INTEGER, size INTEGER, uploads INTEGER DEFAULT 1);
        CREATE INDEX IF NOT EXISTS replays_up ON replays (uploaded DESC); CREATE INDEX IF NOT EXISTS replays_lobby ON replays (lobby);
        CREATE TABLE IF NOT EXISTS aliases (sha TEXT PRIMARY KEY, rid TEXT);''')
    # the replay pool of the launcher (13.11.2026): the game version, who put the replay in, their description, where it came from
    have = {r[1] for r in c.execute('PRAGMA table_info(replays)')}
    for col, typ in (('vhash', 'TEXT'), ('author', 'TEXT'), ('author_steam', 'TEXT'), ('descr', 'TEXT'), ('source', 'TEXT'), ('src_link', 'TEXT'),
                     ('hidden', 'TEXT'), ('views', 'INTEGER DEFAULT 0')):
        if col not in have: c.execute(f'ALTER TABLE replays ADD COLUMN {col} {typ}')
    c.execute('CREATE INDEX IF NOT EXISTS replays_author ON replays (author_steam)')
    # 14.11.2026 (owner): views of the match player (the detailed analysis), one per viewer per day; a viewer = a daily hash of
    # the address, the address itself is not kept
    c.execute('CREATE TABLE IF NOT EXISTS views_seen (rid TEXT, who TEXT, day TEXT, PRIMARY KEY (rid, who, day))')
    hide_backfill = 'hidden' not in have

# The game version a replay was recorded on: bytes 4..7 of the file are a checksum of the game data (one per Elite release,
# one per Tau test build, one for vanilla). The table is elite_versions.json next to this file; a value missing there = a new
# version nobody has named yet ("unknown"). Read again when the file changes, no restart.
VFILE = APP + '/elite_versions.json'; _vers = {'mt': 0, 'map': {}}
def versions():
    try:
        mt = os.path.getmtime(VFILE)
        if mt != _vers['mt']: _vers.update(mt=mt, map=json.load(open(VFILE, encoding='utf-8')))
    except Exception: pass
    return _vers['map']
def vname(vh):
    if not vh: return None
    v = versions().get(vh)
    return v['version'] if v else 'unknown'
def vhash_of(path):
    with open(path, 'rb') as f: b = f.read(8)
    return '%08x' % int.from_bytes(b[4:8], 'little') if len(b) == 8 else None

def rec_meta(path):
    meta, acts = dow2rec.parse(path)
    pl = [{'name': p.get('name'), 'team': p.get('team'), 'race': p.get('race'), 'hero': p.get('hero'), 'pid': p.get('profile_id'),
           'level': p.get('army_level')} for p in meta.get('players', []) if p.get('race')]
    mp = (meta.get('map') or '').replace('/', '\\').split('\\')[-1].lower()
    h = hashlib.sha256((mp + '|' + ','.join(str(x) for x in sorted(p['pid'] or 0 for p in pl))).encode())
    for a in acts[:200]: h.update(a[3])
    return {'map': mp, 'players': pl, 'ticks': meta.get('ticks') or 0, 'recorded': meta.get('recorded'), 'mkey': h.hexdigest()[:32] if acts else None,
            'vhash': vhash_of(path)}
def index_add(rid, meta, name, lobby, size, author=None, author_steam=None, descr=None, source=None, src_link=None):
    with _ilock, idb() as c:
        c.execute('INSERT OR IGNORE INTO replays (rid, mkey, name, lobby, map, players, ticks, recorded, uploaded, size, vhash, author, author_steam, descr, source, src_link)'
                  ' VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (rid, meta['mkey'], name, lobby or None, meta['map'], json.dumps(meta['players'], ensure_ascii=False), meta['ticks'],
                   meta['recorded'], int(time.time()), size, meta.get('vhash'), author, author_steam, descr, source, src_link))
def backfill():
    with idb() as c: known = {r[0] for r in c.execute('SELECT rid FROM replays')}
    for rid in os.listdir(STORE):
        f = f'{STORE}/{rid}/replay.rec'
        if rid in known or not re.fullmatch(r'[0-9a-f]{16}', rid) or not os.path.exists(f): continue
        try:
            meta = rec_meta(f); nm = open(f'{STORE}/{rid}/name.txt').read() if os.path.exists(f'{STORE}/{rid}/name.txt') else 'replay.rec'
            if meta['mkey'] is None: meta['mkey'] = 'file:' + rid
            index_add(rid, meta, nm, None, os.path.getsize(f))
            with _ilock, idb() as c: c.execute('UPDATE replays SET uploaded = ? WHERE rid = ?', (int(os.path.getmtime(f)), rid))
        except Exception: pass
    with idb() as c: nov = [r[0] for r in c.execute('SELECT rid FROM replays WHERE vhash IS NULL')]
    for rid in nov:                       # the versions of the replays stored before the column existed
        try: vh = vhash_of(f'{STORE}/{rid}/replay.rec')
        except OSError: continue
        with _ilock, idb() as c: c.execute('UPDATE replays SET vhash = ? WHERE rid = ?', (vh, rid))
backfill()

# ---------- matches with a computer player (14.11.2026, siritos: "the pool must not hand out AI replays, and they are not worth
# storing automatically - but a replay the player saved and puts in himself is in the pool") ----------
# Who sends a replay: the game itself after a match (MMFind/<ver>: temp.rec of every match with other people; EliteAI/<ver>: temp.rec of
# a skirmish against the new AI, X-Lobby newai - the AI team's test feed) or a person (the launcher's "put into the pool" with his
# sign-in token X-Token, the site's upload form, the Discord import). The game's own uploads are told by their User-Agent.
# - a game's own upload of a match with a computer: MMFind's is not stored (answered 200 {"stored": false, "reason": "computer_player"},
#   so it is not sent again); EliteAI's is stored HIDDEN (hidden = 'ai_auto': the AI team still reads it by its link, the pool never
#   lists it);
# - a person's upload is always stored and listed, AI or not; a person's upload of a hidden match makes it visible;
# - the lists (POST/GET /replay/api/list) leave hidden replays out; "ai": "all" (or true) lists them too, "ai": "none" (or false)
#   leaves out every match with a computer, also those people put in. "mine" lists all of the player's own.
# - 16.11.2026 (the launcher's "My replays", 1.6.16): "played" lists the matches the signed-in player played in - his Relic profile id
#   by his SteamID (relicstats, steam_pid below) among the players' ids of the replay; the answer says the id ("me_pid", null: not known
#   to Relic - nothing listed), the launcher filters its own files by it too. "mine" (the ones he uploaded) stays for 1.6.3-1.6.15.
# Replays stored before this (14.11.2026) are hidden by the same rule once (a computer + nobody's + a game's own file name).
AUTO_UA = ('MMFind/', 'EliteAI/')
AUTO_NAME = re.compile(r'^(?:match|MM-[\w.\-]+|NM-\d+)_\d{4}-\d\d-\d\d_\d\d-\d\d\.rec$')     # MMFind's name of temp.rec
def bot_match(players):   # a computer in the match: the new AI gives its orders inside the sim, a replay of it never plays back the same
    try: return any(p.get('pid') == 4294967295 or 'Computer Player' in (p.get('name') or '') for p in json.loads(players or '[]'))
    except ValueError: return False
if hide_backfill:
    with _ilock, idb() as c:
        rows = c.execute('SELECT rid, name, lobby, players FROM replays WHERE author_steam IS NULL AND hidden IS NULL').fetchall()
        hid = [rid for rid, name, lobby, pl in rows if bot_match(pl) and (lobby == 'newai' or AUTO_NAME.match(name or ''))]
        c.executemany("UPDATE replays SET hidden = 'ai_auto' WHERE rid = ?", [(x,) for x in hid])
    print('replays: %d automatic uploads of matches with a computer hidden from the lists' % len(hid), flush=True)

# Who is uploading: the launcher sends the session token of its Steam sign-in (X-Token / "token"); the ladder knows whose it is.
# This service reaches only localhost, the ladder answers there. A token seen is remembered for 10 minutes.
LADDER = os.environ.get('LADDER_URL', 'http://127.0.0.1:8217'); _who = {}
def who(token):
    token = str(token or '')[:80]
    if not re.fullmatch(r'[\w\-.]{16,80}', token): return None
    hit = _who.get(token)
    if hit and time.time() - hit[0] < 600: return hit[1]
    import urllib.request
    try:
        req = urllib.request.Request(LADDER + '/ladder/api/c/me', data=json.dumps({'token': token}).encode(), headers={'Content-Type': 'application/json'})
        d = json.loads(urllib.request.urlopen(req, timeout=8).read())
    except Exception: return None
    u = {'steam': str(d['steam']), 'name': (d.get('name') or 'Player')[:64]} if d.get('signed_in') and d.get('steam') else None
    if len(_who) > 5000: _who.clear()
    _who[token] = (time.time(), u)
    return u

# race filter: one key per army, whatever spelling the version uses (chaos_marines, z_tau of the Tau test builds, t_tau of 3.x)
RACE_KEYS = {'chaos': ('chaos',), 'eldar': ('eldar',), 'imperial_guard': ('imperial_guard',), 'ordo_malleus': ('ordo_malleus',),
             'orks': ('ork',), 'space_marines': ('space_marines',), 'tau': ('tau',), 'tyranids': ('tyranid',)}
def race_key(r):
    r = (r or '').lower()
    for k, subs in RACE_KEYS.items():
        if any(s in r for s in subs): return k
    return r
def mode_of(pl):
    teams = {p.get('team') for p in pl}; per = max(1, len(pl) // max(1, len(teams)))
    return '%dv%d' % (per, per) if len(teams) == 2 else ('ffa' if len(teams) > 2 else '?')
COLS = 'rid, name, lobby, map, players, ticks, recorded, uploaded, uploads, vhash, author, author_steam, descr, source, src_link, hidden, views'
def item(r, steam=None):
    rid, name, lobby, mp, pl, ticks, rec, up, ups, vh, author, a_steam, descr, source, link, hidden, views = r
    ai = bot_match(pl); pl = json.loads(pl or '[]'); cap = f'{STORE}/{rid}/caption.txt'
    return {'id': rid, 'name': name, 'lobby': lobby, 'map': mp, 'mode': mode_of(pl), 'nplayers': len(pl), 'players': pl,
            'races': sorted({race_key(p.get('race')) for p in pl}), 'duration': (ticks or 0) // 10, 'recorded': rec, 'uploaded': up,
            'uploads': ups, 'vhash': vh, 'version': vname(vh), 'author': author, 'descr': descr,
            'source': source or ('ladder' if (lobby or '').startswith('MM-') else 'site'), 'src_link': link,
            'mine': bool(steam and a_steam == steam), 'caption': open(cap).read() if os.path.exists(cap) else None,
            'sim': os.path.exists(f'{STORE}/{rid}/sim.json.gz'), 'sim_ok': vh in SIM_VERSIONS and (ticks or 0) >= 300 and not ai,
            'ai': ai, 'hidden': bool(hidden), 'views': views or 0}
def ai_mode(v):   # the lists' "ai": '' (default: no hidden ones) / 'all' (true, 1) / 'none' (false, 0: no match with a computer at all)
    if v is None or v == '': return ''
    if v is True or str(v).lower() in ('all', '1', 'true', 'yes'): return 'all'
    if v is False or str(v).lower() in ('none', '0', 'false', 'no'): return 'none'
    return ''
def replay_list(q='', mapk='', race='', mode='', page=0, n=30, version='', players='', author='', steam=None, mine=False, ai='', played=None):
    with idb() as c:
        if mine: rows = c.execute(f'SELECT {COLS} FROM replays WHERE author_steam = ? ORDER BY uploaded DESC', (steam or '-',)).fetchall()
        else: rows = c.execute(f'SELECT {COLS} FROM replays ORDER BY uploaded DESC LIMIT 20000').fetchall()
    q = (q or '').strip().lower(); author = (author or '').strip().lower()
    want = [race_key(x) for x in (race or '').split(',') if x.strip()]          # every race asked for has to be in the match
    out = []
    for r in rows:
        it = item(r, steam)
        if not mine and ((ai != 'all' and it['hidden']) or (ai == 'none' and it['ai'])): continue
        if played is not None and not any(p.get('pid') == played for p in it['players']): continue
        if mapk and it['map'] != mapk.lower(): continue
        if want and not all(w in it['races'] for w in want): continue
        if mode and it['mode'] != mode: continue
        if players and str(it['nplayers']) != str(players): continue
        if version and it['version'] != version: continue
        if author and author not in (it['author'] or '').lower(): continue
        if q and q not in ' '.join([it['name'] or '', it['lobby'] or '', it['map'] or '', it['author'] or '', it['descr'] or '']
                                   + [p.get('name') or '' for p in it['players']]).lower(): continue
        out.append(it)
    page = max(0, int(page or 0)); n = max(1, min(100, int(n or 30)))
    return {'total': len(out), 'page': page, 'items': out[page * n:(page + 1) * n], 'maps': sorted({i['map'] for i in out if i['map']})}
def version_list():
    with idb() as c: rows = c.execute('SELECT vhash, COUNT(*), MAX(uploaded) FROM replays WHERE hidden IS NULL GROUP BY vhash').fetchall()
    agg = {}
    for vh, n, last in rows:
        v = vname(vh) or 'unknown'; a = agg.setdefault(v, {'version': v, 'count': 0, 'last': 0}); a['count'] += n; a['last'] = max(a['last'], last or 0)
    return sorted(agg.values(), key=lambda a: -a['last'])

# ---------- player ratings on the page (14.11.2026, fb 1088) ----------
# 1) rating AT MATCH TIME: matches played through our ladder keep every player's rating in mm_history (/ladder/api/history, key = replay id)
# 2) otherwise the CURRENT Relic rating by profile id (relicstats /stats/api/lobby, name -> line with the profile id; a namesake with another id is dropped)
# Every player gets 'rating' + 'rating_kind' ('match' | 'now'); nothing when unknown. The lookups never hold the page for long (RATING_WAIT).
LADDER_API = 'http://127.0.0.1:8217/ladder/api/history'
RELIC_API = 'http://127.0.0.1:8216/stats/api/lobby'
RATING_WAIT = 2.0
_ladder = {'t': 0, 'by': {}}; _now = {}; _now_lock = threading.Lock(); _pool = ThreadPoolExecutor(4)
def _ladder_refresh():
    by = {}
    for off in range(0, 1000, 100):
        with urllib.request.urlopen(f'{LADDER_API}?n=100&off={off}', timeout=5) as r: d = json.load(r)
        for it in d.get('items', []):
            if it.get('replay'): by[it['replay']] = {p.get('pid'): p.get('rating') for p in it.get('players', []) if p.get('rating')}
        if off + 100 >= d.get('total', 0): break
    _ladder['by'] = by
def _ladder_safe():
    try: _ladder_refresh()
    except Exception: pass
def ladder_ratings(rid):
    if time.time() - _ladder['t'] > 120:
        first = not _ladder['t']; _ladder['t'] = time.time()      # one refresher at a time; later refreshes run in the background
        if first: _ladder_safe()
        else: threading.Thread(target=_ladder_safe, daemon=True).start()
    return _ladder['by'].get(rid) or {}
def _relic_fetch(names):
    qs = '&'.join('n=' + urllib.parse.quote(n[:64]) for n in names)
    try:
        with urllib.request.urlopen(f'{RELIC_API}?{qs}', timeout=6) as r: lines = r.read().decode('utf-8', 'replace').splitlines()
    except Exception: return
    got = {}
    for ln in lines:
        f = ln.split('\t')
        if len(f) >= 6 and f[1].isdigit() and f[5].isdigit(): got[(f[0], int(f[5]))] = int(f[1])
    with _now_lock:
        for n, pid in names.items():
            _now[pid] = (time.time(), got.get((n, pid)))
def relic_now(pl):
    need = {}
    with _now_lock:
        for p in pl:
            pid = p.get('pid')
            if not p.get('name') or not pid or pid >= 4294967295: continue
            c = _now.get(pid)
            if not c or time.time() - c[0] > (3600 if c[1] else 900): need[p['name']] = pid
    if need:
        fut = [_pool.submit(_relic_fetch, dict(list(need.items())[i:i + 12])) for i in range(0, len(need), 12)]
        end = time.time() + RATING_WAIT
        for f in fut:
            try: f.result(timeout=max(0.05, end - time.time()))
            except Exception: pass
    with _now_lock: return {p['pid']: _now[p['pid']][1] for p in pl if p.get('pid') in _now and _now[p['pid']][1]}
def add_ratings(it):
    pl = it.get('players') or []
    try:
        at = ladder_ratings(it['id']); rest = [p for p in pl if not at.get(p.get('pid'))]
        now = relic_now(rest) if rest else {}
        for p in pl:
            if at.get(p.get('pid')): p['rating'] = int(at[p['pid']]); p['rating_kind'] = 'match'
            elif now.get(p.get('pid')): p['rating'] = now[p['pid']]; p['rating_kind'] = 'now'
    except Exception: pass
    return it

# the Relic profile id of a SteamID (relicstats' line for "/steam/<id>", its 6th field), a day in the cache (10 min while unknown)
_pid_of = {}; _pid_lock = threading.Lock()
def steam_pid(steam):
    steam = str(steam or '')
    if not re.fullmatch(r'7656119\d{10}', steam): return None
    with _pid_lock: hit = _pid_of.get(steam)
    if hit and time.time() - hit[0] < (86400 if hit[1] else 600): return hit[1]
    pid = None
    try:
        with urllib.request.urlopen(f'{RELIC_API}?n=' + urllib.parse.quote('/steam/' + steam), timeout=6) as r:
            f = (r.read().decode('utf-8', 'replace').splitlines() or [''])[0].split('\t')
        if len(f) >= 6 and f[5].isdigit() and 0 < int(f[5]) < 4294967295: pid = int(f[5])
    except Exception: return hit[1] if hit else None       # relicstats down: the last answer, nothing cached
    with _pid_lock:
        if len(_pid_of) > 5000: _pid_of.clear()
        _pid_of[steam] = (time.time(), pid)
    return pid

def replay_meta(rid, steam=None):
    with idb() as c: r = c.execute(f'SELECT {COLS} FROM replays WHERE rid = ?', (rid,)).fetchone()
    if not r: return None
    it = item(r, steam); it.pop('caption', None); return add_ratings(it)

# ---------- download name (fb 1088): date, players with races per team, map, winner (only when the page's verdict names one: ?w=<team>) ----------
RACE_TAG = (('imperial_guard', 'IG'), ('space_marines', 'SM'), ('chaos', 'CSM'), ('ordo_malleus', 'OM'), ('ork', 'Orks'), ('eldar', 'Eldar'),
            ('tau', 'Tau'), ('tyranid', 'Tyr'), ('necron', 'Necrons'))
def race_tag(r):
    r = (r or '').lower()
    for k, t in RACE_TAG:
        if k in r: return t
    return re.sub(r'[^A-Za-z0-9]', '', r)[:6]
def fn_clean(t): return re.sub(r'\s+', ' ', re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', '', t or '')).strip(' .')
def rec_filename(it, win=None, limit=150):
    pl = [p for p in it.get('players') or [] if p.get('name')]
    m = re.match(r'(\d+)\.(\d+)\.(\d{4})', it.get('recorded') or '')
    date = f'{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}' if m else time.strftime('%Y-%m-%d', time.gmtime(it.get('uploaded') or time.time()))
    teams = sorted({p.get('team') for p in pl}, key=lambda t: (t is None, t))
    mp = re.sub(r'[^\w\-]+', '_', fn_clean(it.get('map') or 'map')).strip('_') or 'map'
    wtag = ''
    if win is not None and len(teams) == 2 and win in teams: wtag = '_win-' + ('Blue', 'Red')[teams.index(win)]
    for nl in (24, 18, 14, 11, 9, 7, 5, 3):
        side = lambda t: '+'.join('%s(%s)' % (fn_clean(p['name'])[:nl] or 'player', race_tag(p.get('race'))) for p in pl if p.get('team') == t)
        mid = '_vs_'.join(side(t) for t in teams) if teams else 'replay'
        base = f"{date}_{len(pl)}p_{mp}_{mid}" if not re.match(r'\d+p_', mp) else f"{date}_{mp}_{mid}"
        base += wtag
        if len(base) <= limit: break
    return base[:limit].rstrip(' .') + '.rec'
def disposition(fn):      # ASCII fallback + RFC 5987 name with the real (Unicode) nicks
    return 'attachment; filename="%s"; filename*=UTF-8\'\'%s' % (re.sub(r'[^A-Za-z0-9._()+\-]', '_', fn), urllib.parse.quote(fn, safe="()+-._"))

PAGE = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'page.html'), encoding='utf-8').read()

# перевод отчёта make_report.py на английский: фиксированные фразы + направления на карте
EN = [
 ('Разбежка (первые 90 секунд)', 'Opening (first 90 seconds)'), ('Заказы и тиры', 'Orders and tiers'),
 ('Контроль карты (доля кликов на чужой половине)', 'Map control (share of clicks on the enemy half)'),
 ('Вероятные потери (отряд исчез из лога)', 'Probable losses (squad disappears from the log)'),
 ('Захваты (приказы по точкам)', 'Captures (capture orders by point)'),
 ('Конец: маркера сдачи нет → **победа по очкам VP** (или обрыв записи) на', 'End: no surrender marker → **victory on VP points** (or the recording stopped) at'),
 ('Конец: **сдача/выход** в', 'End: **surrender/leave** at'), ('(маркер 0x61; отправитель ≠ сдавшийся)', '(marker 0x61; the sender is not necessarily the one who surrendered)'),
 ('Гипотеза о победителе (уверенность', 'Winner hypothesis (confidence'), ('Признаки:', 'Signs:'),
 ('ретриты в концовке', 'retreats in the endgame'), ('потери в концовке', 'losses in the endgame'),
 ('вероятный победитель', 'likely winner'), ('старт.отряд/герой', 'starting squad/hero'),
 ('Отступили:', 'Retreated:'), ('активны:', 'active:'), ('боевых команд', 'combat orders'), ('и ещё', 'and'),
 ('| Игрок | Раса | Ур. | Команда | APM | Тир | Ретриты |', '| Player | Race | Lvl | Team | APM | Tier | Retreats |'),
 ('## Игроки', '## Players'), ('## Бои', '## Fights'), ('## Итог', '## Result'),
 ('записан', 'recorded'), ('данные:', 'data:'), ('тиры:', 'tiers:'), ('капы:', 'captures:'), ('заказы:', 'orders:'),
 ('высокая', 'high'), ('средняя', 'medium'), ('низкая', 'low'), ('команда', 'team'), ('Команда', 'Team'),
 ('начало', 'early'), ('середина', 'mid'), ('конец', 'late'), ('ГЕРОЙ', 'HERO'), ('отряд', 'squad'),
 ('тираниды', 'Tyranids'), ('Ордо Маллеус', 'Ordo Malleus'), ('некроны', 'Necrons'), ('эльдары', 'Eldar'), ('хаос', 'Chaos'), ('орки', 'Orks'), ('тау', 'Tau'),
 ('ИГ', 'Imperial Guard'), ('СМ', 'Space Marines'), ('СР', 'Grey Knights'),
 ('реквизиция', 'requisition'), ('энергоузел', 'power node'), ('точка', 'point'), ('база', 'base'), (' у ', ' near '),
 ('в (', 'at ('),
]
DIRS = {'СЗ': 'NW', 'СВ': 'NE', 'ЮЗ': 'SW', 'ЮВ': 'SE', 'С': 'N', 'Ю': 'S', 'З': 'W', 'В': 'E', 'центр': 'centre'}
CHAT_EN = [('## Чат', '## Chat'), ('** (всем):', '** (to all):'), ('** (союзникам):', '** (to allies):'), ('** (наблюдатель):', '** (observer):')]
# race keys the report left raw (make_report.RACE_RU has no entry for them): readable Russian names; the English side goes through EN below
RACE_FIX = {'ordo_malleus': 'Ордо Маллеус', 'necrons': 'некроны', 'necron': 'некроны', 'z_unecron': 'некроны', 'tau': 'тау', 'chaos_space_marines': 'хаос'}
def ru_fix(t):
    if not t: return t
    head, sep, chat = t.partition('\n## Чат\n')   # players' chat lines are left as they are
    head = re.sub(r'(?<![\w])(' + '|'.join(RACE_FIX) + r')(?![\w])', lambda m: RACE_FIX[m.group(1)], head)
    return head + sep + chat

def to_en(t):
    if not t: return t
    head, sep, chat = t.partition('\n## Чат\n')   # реплики игроков не переводим: замены фраз отчёта ломали бы их текст
    if sep:
        chat = '\n'.join(next((l.replace(a, b, 1) for a, b in CHAT_EN[1:] if a in l), l) for l in chat.split('\n'))
        return to_en(head) + '\n## Chat\n' + chat
    t = re.sub(r'(VP|энергоузел|реквизиция|база)-(СЗ|СВ|ЮЗ|ЮВ|центр|С|Ю|З|В)\b', lambda m: m.group(1) + '-' + DIRS[m.group(2)], t)
    for a, b in EN: t = t.replace(a, b)
    t = re.sub(r'(\d+)\s*с\b', r'\1 s', t)
    t = re.sub(r'Т(\d)', r'T\1', t)          # кириллическая «Т» в тирах
    return t

def analyse(rid):
    d = f'{STORE}/{rid}'
    env = dict(os.environ, DIGEST=f'{d}/digest.json')
    env['DOW_BASE'] = ROOT          # make_report пишет в ROOT/reports, таблицы читает из APP
    r = subprocess.run(['python3', APP + '/make_report.py', f'{d}/replay.rec'], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=300)
    src = f"{ROOT}/reports/replay.md"
    if os.path.exists(src):
        rep = open(src).read(); os.remove(src)
        nm = open(f'{d}/name.txt').read() if os.path.exists(f'{d}/name.txt') else 'replay.rec'
        open(f'{d}/report.md', 'w').write(re.sub(r'^# replay\.rec', '# ' + nm, rep, count=1))
        if os.path.exists(src + '.caption'):   # data и reports в песочнице — разные точки монтирования: rename нельзя
            open(f'{d}/caption.txt', 'w').write(open(src + '.caption').read()); os.remove(src + '.caption')
    else:
        open(f'{d}/error.txt', 'w').write((r.stderr or r.stdout)[-3000:] or 'не удалось разобрать')

# ---- the detailed analysis on demand (13.11): the game's own simulation of a replay, run by the headless runner on prod_gpu.
# The page / launcher asks -> SIMQ/<rid>.req; prod_gpu (its mount of this folder) takes it -> <rid>.work, runs the replay,
# puts <rid>.csv.gz / .players.csv.gz / .points.csv.gz into ROOT/sim and writes <rid>.done (or <rid>.fail with the reason);
# here a thread turns .done into data/<rid>/sim.json.gz (sim_view.py). No emulator on this server.
SIMQ = ROOT + '/simq'; SIMDIR = ROOT + '/sim'
SIM_VERSIONS = {'819567f8', 'd6805b7d'}     # Elite 3.2.1, 3.2: the runner has their game data
SIM_MAXQ = 40
def sim_state(rid):
    if os.path.exists(f'{STORE}/{rid}/sim.json.gz'): return 'ready', None
    for st in ('fail', 'done', 'work', 'req'):
        f = f'{SIMQ}/{rid}.{st}'
        if os.path.exists(f):
            if st == 'fail':
                try: why = open(f).read().strip()[:200]
                except OSError: why = ''
                return 'failed', why
            return {'done': 'building', 'work': 'running', 'req': 'queued'}[st], None
    with idb() as c: r = c.execute('SELECT vhash, ticks, players FROM replays WHERE rid = ?', (rid,)).fetchone()
    if not r: return 'none', None
    if r[0] not in SIM_VERSIONS: return 'unsupported', None
    if (r[1] or 0) < 300: return 'unsupported', None
    if bot_match(r[2]): return 'unsupported', None
    return 'none', None
def sim_request(rid):
    st, _ = sim_state(rid)
    if st == 'failed':
        try: os.remove(f'{SIMQ}/{rid}.fail')
        except OSError: pass
        st = 'none'
    if st != 'none': return st
    os.makedirs(SIMQ, exist_ok=True)
    if len([f for f in os.listdir(SIMQ) if f.endswith('.req')]) >= SIM_MAXQ: return 'busy'
    tmp = f'{SIMQ}/.{rid}.tmp'
    open(tmp, 'w').write(json.dumps({'rid': rid, 'ts': time.time()})); os.replace(tmp, f'{SIMQ}/{rid}.req')
    return 'queued'
def sim_builder():
    while True:
        try:
            for f in sorted(os.listdir(SIMQ)) if os.path.isdir(SIMQ) else []:
                if not f.endswith('.done'): continue
                rid = f[:-5]
                if not re.fullmatch(r'[0-9a-f]{16}', rid): continue
                r = subprocess.run(['python3', APP + '/sim_view.py', rid], capture_output=True, text=True, timeout=600,
                                   env=dict(os.environ, REPLAY_ROOT=ROOT, SIM_DIR=SIMDIR, ASSETS_INDEX=ROOT + '/assets/index.json'))
                if os.path.exists(f'{STORE}/{rid}/sim.json.gz'):
                    for e in ('req', 'work', 'done', 'fail'):
                        try: os.remove(f'{SIMQ}/{rid}.{e}')
                        except OSError: pass
                else:
                    open(f'{SIMQ}/{rid}.fail', 'w').write('build: ' + ((r.stdout or '') + (r.stderr or ''))[-200:])
                    os.remove(f'{SIMQ}/{rid}.done')
        except Exception as e: print('sim_builder', repr(e), flush=True)
        time.sleep(5)

def _view_salt():
    f = f'{STORE}/.view_salt'
    if not os.path.exists(f): open(f, 'w').write(hashlib.sha256(os.urandom(32)).hexdigest())
    return open(f).read().strip()
def add_view(rid, ip):
    """One view of the match player per viewer per day (viewer = sha256(salt, day, address)[:16]); returns the count."""
    day = time.strftime('%F')
    who = hashlib.sha256(f'{_view_salt()}|{day}|{ip}'.encode()).hexdigest()[:16]
    with _ilock, idb() as c:
        if c.execute('INSERT OR IGNORE INTO views_seen (rid, who, day) VALUES (?, ?, ?)', (rid, who, day)).rowcount:
            c.execute('UPDATE replays SET views = COALESCE(views, 0) + 1 WHERE rid = ?', (rid,))
        c.execute('DELETE FROM views_seen WHERE day < ?', (time.strftime('%F', time.localtime(time.time() - 3 * 86400)),))
        r = c.execute('SELECT views FROM replays WHERE rid = ?', (rid,)).fetchone()
    return (r and r[0]) or 0

def queue_story(rid, lang):
    # историю пишет отдельный процесс (replay_story_worker от root, Claude без инструментов): у этого сервиса
    # нет доступа ни к логину Claude, ни к ключам. Заявка — файл в очереди, результат — story_<lang>.md в папке разбора.
    open(f'{QUEUE}/{rid}_{lang}.req', 'w').write(json.dumps({'rid': rid, 'lang': lang, 'ts': time.time()}))

def story_running(rid):
    return [l for l in ('ru', 'en') if os.path.exists(f'{QUEUE}/{rid}_{l}.req') or os.path.exists(f'{QUEUE}/{rid}_{l}.work')]

def recent(n=15):
    items = []
    with idb() as c: hid = {r[0] for r in c.execute('SELECT rid FROM replays WHERE hidden IS NOT NULL')}
    for rid in [x for x in sorted(os.listdir(STORE), key=lambda x: -os.path.getmtime(f'{STORE}/{x}')) if x not in hid][:n]:
        cap = f'{STORE}/{rid}/caption.txt'
        if os.path.exists(cap): items.append({'id': rid, 'name': open(f'{STORE}/{rid}/name.txt').read() if os.path.exists(f'{STORE}/{rid}/name.txt') else rid,
                                              'caption': ru_fix(open(cap).read()), 'caption_en': to_en(ru_fix(open(cap).read()))})
    return items

class H(BaseHTTPRequestHandler):
    def out(self, code, body, ctype='text/html; charset=utf-8'):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(b)))
        self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass
    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path.rstrip('/')
        if p in ('', '/replay'): return self.out(200, PAGE)
        if p == '/replay/api/recent': return self.out(200, json.dumps(recent(), ensure_ascii=False), 'application/json')
        if p == '/replay/api/list':
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query); g = lambda k: qs.get(k, [''])[0]
            try: return self.out(200, json.dumps(replay_list(g('q')[:64], g('map')[:64], g('race')[:120], g('mode')[:8], g('page') or 0, g('n') or 30,
                                                             g('version')[:40], g('players')[:2], g('author')[:64], ai=ai_mode(g('ai'))), ensure_ascii=False), 'application/json')
            except ValueError: return self.out(400, '{}', 'application/json')
        if p == '/replay/api/versions': return self.out(200, json.dumps(version_list(), ensure_ascii=False), 'application/json')
        if p == '/replay/api/vtable': return self.out(200, json.dumps({h: v['version'] for h, v in versions().items()}), 'application/json')   # the launcher names its own files' versions
        m = re.match(r'^/replay/api/by_lobby/([\w.\-]{1,80})$', p)
        if m:
            with idb() as c: r = c.execute('SELECT rid FROM replays WHERE lobby = ? ORDER BY ticks DESC LIMIT 1', (m.group(1),)).fetchone()
            return self.out(200 if r else 404, json.dumps({'id': r[0]} if r else {}), 'application/json')
        m = re.match(r'^/replay/api/r/([0-9a-f]{16})/replay\.rec$', p)
        if m and os.path.exists(f'{STORE}/{m.group(1)}/replay.rec'):
            nm = open(f'{STORE}/{m.group(1)}/name.txt').read() if os.path.exists(f'{STORE}/{m.group(1)}/name.txt') else 'replay.rec'
            b = open(f'{STORE}/{m.group(1)}/replay.rec', 'rb').read()
            try:
                w = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get('w', [''])[0]
                with idb() as c: r = c.execute(f'SELECT {COLS} FROM replays WHERE rid = ?', (m.group(1),)).fetchone()
                fn = rec_filename(item(r), int(w) if re.fullmatch(r'\d{1,3}', w) else None)
            except Exception: fn = re.sub(r'[^\w.\-\[\]]', '_', nm)
            self.send_response(200); self.send_header('Content-Type', 'application/octet-stream'); self.send_header('Content-Length', str(len(b)))
            self.send_header('Content-Disposition', disposition(fn)); self.end_headers(); self.wfile.write(b); return
        m = re.match(r'^/replay/api/r/([0-9a-f]{16})$', p)
        if m:
            d = f'{STORE}/{m.group(1)}'
            if not os.path.isdir(d): return self.out(404, '{}', 'application/json')
            rd = lambda f: open(f'{d}/{f}').read() if os.path.exists(f'{d}/{f}') else None
            return self.out(200, json.dumps({'name': rd('name.txt'), 'caption': ru_fix(rd('caption.txt')), 'report': ru_fix(rd('report.md')),
                'caption_en': to_en(ru_fix(rd('caption.txt'))), 'report_en': to_en(ru_fix(rd('report.md'))),
                'error': rd('error.txt'), 'story_ru': rd('story_ru.md'), 'story_en': rd('story_en.md'),
                'story_running': story_running(m.group(1)), 'meta': replay_meta(m.group(1)),
                'sim_state': sim_state(m.group(1))[0], 'sim_why': sim_state(m.group(1))[1]}, ensure_ascii=False), 'application/json')
        m = re.match(r'^/replay/r/([0-9a-f]{16})$', p)
        if m: return self.out(200, PAGE)
        if p == '/replay/sim.js':   # the match player (sim_view.py data); read per request so a deploy needs no restart
            return self.out(200, open(APP + '/sim.js', encoding='utf-8').read(), 'application/javascript; charset=utf-8')
        m = re.match(r'^/replay/api/r/([0-9a-f]{16})/sim\.json$', p)
        if m and os.path.exists(f'{STORE}/{m.group(1)}/sim.json.gz'):
            b = open(f'{STORE}/{m.group(1)}/sim.json.gz', 'rb').read()
            if 'gzip' not in (self.headers.get('Accept-Encoding') or ''): b = gzip.decompress(b); enc = None
            else: enc = 'gzip'
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(b)))
            self.send_header('Cache-Control', 'no-cache')
            if enc: self.send_header('Content-Encoding', enc)
            self.end_headers(); self.wfile.write(b); return
        m = re.match(r'^/replay/api/r/([0-9a-f]{16})/report(_en)?\.md$', p)
        if m and os.path.exists(f'{STORE}/{m.group(1)}/report.md'):
            t = ru_fix(open(f'{STORE}/{m.group(1)}/report.md').read())
            return self.out(200, to_en(t) if m.group(2) else t, 'text/markdown; charset=utf-8')
        self.out(404, 'not found', 'text/plain')
    def body(self, limit=64 * 1024):
        n = int(self.headers.get('Content-Length', 0) or 0)
        if n <= 0 or n > limit: return {}
        try: d = json.loads(self.rfile.read(n))
        except Exception: return {}
        return d if isinstance(d, dict) else {}
    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        J = lambda code, v: self.out(code, json.dumps(v, ensure_ascii=False), 'application/json')
        # ---- the launcher's Replays tab ----
        if p == '/replay/api/list':                   # the list with "mine" marked (and "only mine") for a signed-in player
            d = self.body(); u = who(d.get('token')); g = lambda k, n: str(d.get(k) or '')[:n]
            played = bool(d.get('played')); pid = steam_pid(u['steam']) if played and u else None
            try:
                out = replay_list(g('q', 64), g('map', 64), g('race', 120), g('mode', 8), d.get('page') or 0, d.get('n') or 30,
                                  g('version', 40), g('players', 2), g('author', 64), u and u['steam'], bool(d.get('mine')) and bool(u),
                                  ai_mode(d.get('ai')), (pid or -1) if played else None)
                if played: out['me_pid'] = pid; out['signed_in'] = bool(u)
                return J(200, out)
            except (ValueError, TypeError): return J(400, {})
        if p == '/replay/api/have':                   # which of the player's files are in the pool: sha256[:16] of a file -> its replay
            ids = [x for x in (self.body().get('ids') or [])[:2000] if isinstance(x, str) and re.fullmatch(r'[0-9a-f]{16}', x)]
            out = {}
            with idb() as c:
                for i in range(0, len(ids), 500):
                    part = ids[i:i + 500]; qm = ','.join('?' * len(part))
                    for rid, in c.execute(f'SELECT rid FROM replays WHERE rid IN ({qm})', part): out[rid] = rid
                    for sha, rid in c.execute(f'SELECT sha, rid FROM aliases WHERE sha IN ({qm})', part): out.setdefault(sha, rid)
            return J(200, out)
        m = re.match(r'^/replay/api/r/([0-9a-f]{16})/describe$', p)
        if m:                                         # the description: only the one who put the replay in the pool
            d = self.body(); u = who(d.get('token'))
            if not u: return J(401, {'error': 'sign_in'})
            text = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', str(d.get('text') or '')).strip()[:1000]
            with _ilock, idb() as c:
                r = c.execute('SELECT author_steam FROM replays WHERE rid = ?', (m.group(1),)).fetchone()
                if not r: return J(404, {'error': 'not_found'})
                if r[0] != u['steam']: return J(403, {'error': 'not_yours'})
                c.execute('UPDATE replays SET descr = ? WHERE rid = ?', (text or None, m.group(1)))
            return J(200, {'ok': True, 'meta': replay_meta(m.group(1), u['steam'])})
        if p == '/replay/api/upload':
            n = int(self.headers.get('Content-Length', 0))
            if n <= 0 or n > 30 * 1024 * 1024: return self.out(413, json.dumps({'error': 'file is empty or larger than 30 MB'}), 'application/json')
            ladder = (self.headers.get("X-Lobby") or "").startswith("MM-")   # sent by the game after a ladder match: several mirrors share one address
            if not ladder and not allow_upload(client_ip(self)): return self.out(429, json.dumps({'error': 'too many uploads, try again in an hour'}), 'application/json')
            if store_size() > STORE_MAX: return self.out(507, json.dumps({'error': 'storage is full, try later'}), 'application/json')
            data = self.rfile.read(n)
            if data[12:20] != b'DOW2_REC': return self.out(400, json.dumps({'error': 'not a Dawn of War II replay (.rec)'}), 'application/json')
            rid = hashlib.sha256(data).hexdigest()[:16]; d = f'{STORE}/{rid}'
            name = re.sub(r'[^\w.\-\[\] ]', '_', urllib.parse.unquote(self.headers.get('X-Filename', 'replay.rec')))[:120]
            lobby = re.sub(r'[^\w.\-]', '', self.headers.get('X-Lobby', ''))[:80]
            u = who(self.headers.get('X-Token'))         # the launcher's "put into the pool": the signed-in player is the author
            src = 'launcher' if self.headers.get('X-Token') else None
            auto = not self.headers.get('X-Token') and (self.headers.get('User-Agent') or '').startswith(AUTO_UA)   # the game's own temp.rec
            tmp = f'{STORE}/.up_{rid}.rec'; open(tmp, 'wb').write(data)
            try: meta = rec_meta(tmp)
            except Exception: meta = None
            if not meta or not meta['mkey']: meta = dict(meta or {'map': '', 'players': [], 'ticks': 0, 'recorded': None}, mkey='file:' + rid)
            hidden = None
            if auto and bot_match(json.dumps(meta['players'])):          # a match with a computer, sent by the game itself (see AUTO_UA)
                if lobby != 'newai':
                    os.remove(tmp)
                    return self.out(200, json.dumps({'stored': False, 'reason': 'computer_player'}), 'application/json')
                hidden = 'ai_auto'                    # EliteAI: the AI team's test feed - kept, never listed
            with _ilock, idb() as c:                  # проверка и запись в индекс — одним шагом: двое шлют один матч одновременно
                old = c.execute('SELECT rid, ticks, lobby FROM replays WHERE mkey = ?', (meta['mkey'],)).fetchone()
                if not old:
                    c.execute('INSERT OR IGNORE INTO replays (rid, mkey, name, lobby, map, players, ticks, recorded, uploaded, size, vhash, author, author_steam, source, hidden)'
                              ' VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                              (rid, meta['mkey'], name, lobby or None, meta['map'], json.dumps(meta['players'], ensure_ascii=False), meta['ticks'],
                               meta['recorded'], int(time.time()), len(data), vhash_of(tmp), u and u['name'], u and u['steam'], src, hidden))
                c.execute('INSERT OR REPLACE INTO aliases (sha, rid) VALUES (?, ?)', (rid, old[0] if old else rid))
            if old:                                   # этот матч уже есть: копию не храним, более полную запись — подменяем
                rid0, t0, lb0 = old; d0 = f'{STORE}/{rid0}'
                with _ilock, idb() as c:
                    c.execute('UPDATE replays SET uploads = uploads + 1, lobby = COALESCE(lobby, ?) WHERE rid = ?', (lobby or None, rid0))
                    if not auto: c.execute('UPDATE replays SET hidden = NULL WHERE rid = ?', (rid0,))   # a person put it in: listed
                    if u:                             # the match came in from the ladder or the site with nobody's name: the player claims it
                        c.execute('UPDATE replays SET author = ?, author_steam = ?, source = COALESCE(source, ?) WHERE rid = ? AND author_steam IS NULL',
                                  (u['name'], u['steam'], src, rid0))
                    mine = bool(u) and (c.execute('SELECT author_steam FROM replays WHERE rid = ?', (rid0,)).fetchone() or [None])[0] == u['steam']
                    if meta['ticks'] > (t0 or 0): c.execute('UPDATE replays SET ticks = ?, size = ? WHERE rid = ?', (meta['ticks'], len(data), rid0))
                if meta['ticks'] > (t0 or 0):
                    os.replace(tmp, f'{d0}/replay.rec')
                    for f in ('report.md', 'caption.txt', 'error.txt', 'digest.json'):
                        if os.path.exists(f'{d0}/{f}'): os.remove(f'{d0}/{f}')
                    analyse(rid0)
                else: os.remove(tmp)
                return self.out(200, json.dumps({'id': rid0, 'duplicate': True, 'mine': mine}), 'application/json')
            if not os.path.exists(f'{d}/report.md'):
                os.makedirs(d, exist_ok=True); os.replace(tmp, f'{d}/replay.rec'); open(f'{d}/name.txt', 'w').write(name)
                analyse(rid)
            elif os.path.exists(tmp): os.remove(tmp)
            return self.out(200, json.dumps({'id': rid, 'mine': bool(u)}), 'application/json')
        m = re.match(r'^/replay/api/r/([0-9a-f]{16})/view$', p)
        if m:                                         # the match player was started (counted once per viewer per day)
            if not os.path.exists(f'{STORE}/{m.group(1)}/sim.json.gz'): return J(404, {'error': 'not_found'})
            return J(200, {'views': add_view(m.group(1), client_ip(self))})
        m = re.match(r'^/replay/api/r/([0-9a-f]{16})/sim$', p)
        if m:                                         # ask for the detailed analysis (the game's own simulation)
            if not os.path.exists(f'{STORE}/{m.group(1)}/replay.rec'): return J(404, {'error': 'not_found'})
            st = sim_request(m.group(1))
            return J(429 if st == 'busy' else 400 if st == 'unsupported' else 200, {'state': st})
        m = re.match(r'^/replay/api/r/([0-9a-f]{16})/story/(ru|en)$', p)
        if m:
            rid, lang = m.groups(); d = f'{STORE}/{rid}'
            if not os.path.exists(f'{d}/report.md'): return self.out(404, '{}', 'application/json')
            if os.path.exists(f'{d}/story_{lang}.md') or lang in story_running(rid): return self.out(200, '{"ok":true}', 'application/json')
            day = time.strftime('%F')
            if story_today['day'] != day: story_today.update(day=day, n=0)
            if story_today['n'] >= STORY_LIMIT: return self.out(429, json.dumps({'error': 'лимит историй на сегодня исчерпан'}), 'application/json')
            story_today['n'] += 1; queue_story(rid, lang)
            return self.out(200, '{"ok":true}', 'application/json')
        self.out(404, 'not found', 'text/plain')

if __name__ == '__main__':
    print('replay web на', PORT, flush=True)
    threading.Thread(target=sim_builder, daemon=True).start()
    ThreadingHTTPServer(('127.0.0.1', PORT), H).serve_forever()
