#!/usr/bin/env python3
"""Страница разбора реплеев DoW2 Retribution / Elite: https://rts.fintebtc.de/replay/
Загрузка .rec (сырые байты из браузера) → make_report.py → страница результатов с постоянной ссылкой.
По кнопке — история матча (Claude по выжимке фактов), с суточным лимитом.
Слушает 127.0.0.1:8215, nginx проксирует /replay/."""
import hashlib, html, json, os, re, sqlite3, subprocess, sys, threading, time, urllib.parse
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
    for col, typ in (('vhash', 'TEXT'), ('author', 'TEXT'), ('author_steam', 'TEXT'), ('descr', 'TEXT'), ('source', 'TEXT'), ('src_link', 'TEXT')):
        if col not in have: c.execute(f'ALTER TABLE replays ADD COLUMN {col} {typ}')
    c.execute('CREATE INDEX IF NOT EXISTS replays_author ON replays (author_steam)')

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
COLS = 'rid, name, lobby, map, players, ticks, recorded, uploaded, uploads, vhash, author, author_steam, descr, source, src_link'
def item(r, steam=None):
    rid, name, lobby, mp, pl, ticks, rec, up, ups, vh, author, a_steam, descr, source, link = r
    pl = json.loads(pl or '[]'); cap = f'{STORE}/{rid}/caption.txt'
    return {'id': rid, 'name': name, 'lobby': lobby, 'map': mp, 'mode': mode_of(pl), 'nplayers': len(pl), 'players': pl,
            'races': sorted({race_key(p.get('race')) for p in pl}), 'duration': (ticks or 0) // 10, 'recorded': rec, 'uploaded': up,
            'uploads': ups, 'vhash': vh, 'version': vname(vh), 'author': author, 'descr': descr,
            'source': source or ('ladder' if (lobby or '').startswith('MM-') else 'site'), 'src_link': link,
            'mine': bool(steam and a_steam == steam), 'caption': open(cap).read() if os.path.exists(cap) else None}
def replay_list(q='', mapk='', race='', mode='', page=0, n=30, version='', players='', author='', steam=None, mine=False):
    with idb() as c:
        if mine: rows = c.execute(f'SELECT {COLS} FROM replays WHERE author_steam = ? ORDER BY uploaded DESC', (steam or '-',)).fetchall()
        else: rows = c.execute(f'SELECT {COLS} FROM replays ORDER BY uploaded DESC LIMIT 20000').fetchall()
    q = (q or '').strip().lower(); author = (author or '').strip().lower()
    want = [race_key(x) for x in (race or '').split(',') if x.strip()]          # every race asked for has to be in the match
    out = []
    for r in rows:
        it = item(r, steam)
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
    with idb() as c: rows = c.execute('SELECT vhash, COUNT(*), MAX(uploaded) FROM replays GROUP BY vhash').fetchall()
    agg = {}
    for vh, n, last in rows:
        v = vname(vh) or 'unknown'; a = agg.setdefault(v, {'version': v, 'count': 0, 'last': 0}); a['count'] += n; a['last'] = max(a['last'], last or 0)
    return sorted(agg.values(), key=lambda a: -a['last'])

def replay_meta(rid, steam=None):
    with idb() as c: r = c.execute(f'SELECT {COLS} FROM replays WHERE rid = ?', (rid,)).fetchone()
    if not r: return None
    it = item(r, steam); it.pop('caption', None); return it

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
 ('тираниды', 'Tyranids'), ('эльдары', 'Eldar'), ('хаос', 'Chaos'), ('орки', 'Orks'), ('тау', 'Tau'),
 ('ИГ', 'Imperial Guard'), ('СМ', 'Space Marines'), ('СР', 'Grey Knights'),
 ('реквизиция', 'requisition'), ('энергоузел', 'power node'), ('точка', 'point'), ('база', 'base'), (' у ', ' near '),
 ('в (', 'at ('),
]
DIRS = {'СЗ': 'NW', 'СВ': 'NE', 'ЮЗ': 'SW', 'ЮВ': 'SE', 'С': 'N', 'Ю': 'S', 'З': 'W', 'В': 'E', 'центр': 'centre'}
CHAT_EN = [('## Чат', '## Chat'), ('** (всем):', '** (to all):'), ('** (союзникам):', '** (to allies):'), ('** (наблюдатель):', '** (observer):')]
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

def queue_story(rid, lang):
    # историю пишет отдельный процесс (replay_story_worker от root, Claude без инструментов): у этого сервиса
    # нет доступа ни к логину Claude, ни к ключам. Заявка — файл в очереди, результат — story_<lang>.md в папке разбора.
    open(f'{QUEUE}/{rid}_{lang}.req', 'w').write(json.dumps({'rid': rid, 'lang': lang, 'ts': time.time()}))

def story_running(rid):
    return [l for l in ('ru', 'en') if os.path.exists(f'{QUEUE}/{rid}_{l}.req') or os.path.exists(f'{QUEUE}/{rid}_{l}.work')]

def recent(n=15):
    items = []
    for rid in sorted(os.listdir(STORE), key=lambda x: -os.path.getmtime(f'{STORE}/{x}'))[:n]:
        cap = f'{STORE}/{rid}/caption.txt'
        if os.path.exists(cap): items.append({'id': rid, 'name': open(f'{STORE}/{rid}/name.txt').read() if os.path.exists(f'{STORE}/{rid}/name.txt') else rid,
                                              'caption': open(cap).read(), 'caption_en': to_en(open(cap).read())})
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
                                                             g('version')[:40], g('players')[:2], g('author')[:64]), ensure_ascii=False), 'application/json')
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
            self.send_response(200); self.send_header('Content-Type', 'application/octet-stream'); self.send_header('Content-Length', str(len(b)))
            self.send_header('Content-Disposition', 'attachment; filename="%s"' % re.sub(r'[^\w.\-\[\]]', '_', nm)); self.end_headers(); self.wfile.write(b); return
        m = re.match(r'^/replay/api/r/([0-9a-f]{16})$', p)
        if m:
            d = f'{STORE}/{m.group(1)}'
            if not os.path.isdir(d): return self.out(404, '{}', 'application/json')
            rd = lambda f: open(f'{d}/{f}').read() if os.path.exists(f'{d}/{f}') else None
            return self.out(200, json.dumps({'name': rd('name.txt'), 'caption': rd('caption.txt'), 'report': rd('report.md'),
                'caption_en': to_en(rd('caption.txt')), 'report_en': to_en(rd('report.md')),
                'error': rd('error.txt'), 'story_ru': rd('story_ru.md'), 'story_en': rd('story_en.md'),
                'story_running': story_running(m.group(1)), 'meta': replay_meta(m.group(1))}, ensure_ascii=False), 'application/json')
        m = re.match(r'^/replay/r/([0-9a-f]{16})$', p)
        if m: return self.out(200, PAGE)
        m = re.match(r'^/replay/api/r/([0-9a-f]{16})/report(_en)?\.md$', p)
        if m and os.path.exists(f'{STORE}/{m.group(1)}/report.md'):
            t = open(f'{STORE}/{m.group(1)}/report.md').read()
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
            try: return J(200, replay_list(g('q', 64), g('map', 64), g('race', 120), g('mode', 8), d.get('page') or 0, d.get('n') or 30,
                                           g('version', 40), g('players', 2), g('author', 64), u and u['steam'], bool(d.get('mine')) and bool(u)))
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
            tmp = f'{STORE}/.up_{rid}.rec'; open(tmp, 'wb').write(data)
            try: meta = rec_meta(tmp)
            except Exception: meta = None
            if not meta or not meta['mkey']: meta = dict(meta or {'map': '', 'players': [], 'ticks': 0, 'recorded': None}, mkey='file:' + rid)
            with _ilock, idb() as c:                  # проверка и запись в индекс — одним шагом: двое шлют один матч одновременно
                old = c.execute('SELECT rid, ticks, lobby FROM replays WHERE mkey = ?', (meta['mkey'],)).fetchone()
                if not old:
                    c.execute('INSERT OR IGNORE INTO replays (rid, mkey, name, lobby, map, players, ticks, recorded, uploaded, size, vhash, author, author_steam, source)'
                              ' VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                              (rid, meta['mkey'], name, lobby or None, meta['map'], json.dumps(meta['players'], ensure_ascii=False), meta['ticks'],
                               meta['recorded'], int(time.time()), len(data), vhash_of(tmp), u and u['name'], u and u['steam'], src))
                c.execute('INSERT OR REPLACE INTO aliases (sha, rid) VALUES (?, ?)', (rid, old[0] if old else rid))
            if old:                                   # этот матч уже есть: копию не храним, более полную запись — подменяем
                rid0, t0, lb0 = old; d0 = f'{STORE}/{rid0}'
                with _ilock, idb() as c:
                    c.execute('UPDATE replays SET uploads = uploads + 1, lobby = COALESCE(lobby, ?) WHERE rid = ?', (lobby or None, rid0))
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
    ThreadingHTTPServer(('127.0.0.1', PORT), H).serve_forever()
