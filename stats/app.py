#!/usr/bin/env python3
"""Статистика игроков DoW2 Retribution / Elite по данным Relic: https://rts.fintebtc.de/stats/
Источник — публичный community API Relic (dow-api.reliclink.com, title=dow2r): каждый сетевой матч
игра отправляет туда сама, сервер ведёт Elo. API отдаёт ~10 последних матчей игрока, поэтому всё
увиденное копим в sqlite — история со временем растёт.
Слушает 127.0.0.1:8216, nginx проксирует /stats/."""
import base64, json, os, re, sqlite3, struct, threading, time, urllib.parse, urllib.request, zlib
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor

APP = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(APP); DB = ROOT + '/data/relic.sqlite'; PORT = 8216
RELIC = 'https://dow-api.reliclink.com/community/leaderboard/'
UA = 'rts.fintebtc.de stats (DoW2 Elite community page)'
PAGE = open(APP + '/page.html', encoding='utf-8').read()
STATIC = APP + '/static'
CT = {'.png': 'image/png', '.css': 'text/css', '.js': 'application/javascript', '.svg': 'image/svg+xml', '.zip': 'application/zip'}

# Номера рас у Relic = racebps race_id ТОЙ игры, что сыграла матч, а таблиц три (racebps по алфавиту, 05.11.2026, chuzar:
# «статистика знает секретного героя Тау» — бои Тиранид весны 2026 показывались как Тау):
#   ваниль 3.19:          0 Хаос, 1 Эльдары, 2 ИГ, 3 Орки, 4 СМ, 5 Тираниды (нет Ордо Маллеус и Тау);
#   Elite до Тау (2.x):   0 Хаос, 1 Эльдары, 2 ИГ, 3 ОМ, 4 Орки, 5 СМ, 6 Тираниды;
#   Elite 3.x:            0 Хаос, 1 Эльдары, 2 ИГ, 3 ОМ, 4 Орки, 5 СМ, 6 Тау, 7 Тираниды, 8 Некроны (t_tau / z_unecron).
# Здесь всё приводится к номерам Elite 3.x. Какая таблица у матча — по значкам армий в slotinfo (значок расовый: sm_*, ork_*,
# tau_*...; у Тиранид и ОМ его нет), по номерам 6-8, суффиксу _elite у армий и картам только Elite (ladder/maps.txt).
# Герои: ha/hb/hc = hero_list[0..2] того же racebps. У Тау в Elite 3.2 их два (Командир «Кризис», Эфирный).
RACES = {
    0: ('chaos', 'Chaos Space Marines', 'Хаос', [('csm_lord', 'Chaos Lord', 'Лорд Хаоса'), ('csm_plaguemarine', 'Plague Champion', 'Чумной чемпион'), ('csm_sorceror', 'Sorcerer', 'Колдун')]),
    1: ('eldar', 'Eldar', 'Эльдары', [('eldar_warlock', 'Warlock', 'Варлок'), ('eldar_spyder', 'Warp Spider Exarch', 'Экзарх Варп-пауков'), ('eldar_farseer', 'Farseer', 'Провидец')]),
    2: ('ig', 'Imperial Guard', 'Имперская гвардия', [('ig_inquisitor', 'Inquisitor', 'Инквизитор'), ('ig_commissar_lord', 'Lord Commissar', 'Лорд-комиссар'), ('ig_commander', 'Lord General', 'Лорд-генерал')]),
    3: ('gk', 'Ordo Malleus', 'Ордо Маллеус', [('gk_brother_captain', 'Brother-Captain', 'Брат-капитан'), ('gk_eversor_assassin', 'Eversor Assassin', 'Ассасин Эверсор'), ('gk_daemonhunter', 'Daemonhunter', 'Охотник на демонов')]),
    4: ('ork', 'Orks', 'Орки', [('ork_warboss', 'Warboss', 'Варбосс'), ('ork_kommando', 'Kommando Nob', 'Коммандо-ноб'), ('ork_mekboy', 'Mekboy', 'Мекбой')]),
    5: ('sm', 'Space Marines', 'Космодесант', [('sm_fcommander', 'Force Commander', 'Командор'), ('sm_apothecary', 'Apothecary', 'Апотекарий'), ('sm_techmarine', 'Techmarine', 'Техмарин')]),
    6: ('tau', 'Tau Empire', 'Империя Тау', [('tau_commander', 'Crisis Commander', 'Командир «Кризис»'), ('tau_ethereal', 'Ethereal', 'Эфирный')]),
    7: ('tyranid', 'Tyranids', 'Тираниды', [('tyranid_hive_tyrant', 'Hive Tyrant', 'Тиран улья'), ('tyranid_ravener', 'Ravener Alpha', 'Альфа-потрошитель'), ('tyranid_lictor', 'Lictor Alpha', 'Альфа-ликтор')]),
    8: ('necron', 'Necrons', 'Некроны', []),
}
TABLES = {'vanilla': {0: 0, 1: 1, 2: 2, 3: 4, 4: 5, 5: 7},
          'elite2': {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 7},
          'elite3': {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8}}
BADGE_RACE = {'chaos': 0, 'csm': 0, 'eldar': 1, 'ig': 2, 'gk': 3, 'ork': 4, 'sm': 5, 'tau': 6, 'necron': 8}
TAU_FROM = 1781481600       # 15.06.2026: первые значки tau_* у номера 6 в архиве; раньше 6 без значка — Тираниды Elite 2.x
def _maps():
    van, elite = set(), set()
    for f in (APP + '/maps.txt', ROOT + '/ladder/maps.txt'):
        try:
            for line in open(f):
                p = line.split()
                if p and p[0] == 'VAN': van = set(p[1:])
                elif p and p[0] == 'ELITE_ONLY': elite = set(p[1:])
            break
        except OSError: continue
    return van, elite
VAN_MAPS, ELITE_MAPS = _maps()

def _slot_head(raw, p):
    # a slot: profile id, 3 ints (-1 -1 -1 empty / 0 join order 0), team, hero, race, a byte, -1 (as ladder/ladder.py _slots)
    if p < 0 or p + 43 > len(raw) or raw[p + 29:p + 33] != b'\xff\xff\xff\xff': return False
    pid, a, b, c, team, hero, race = struct.unpack_from('<7i', raw, p)
    if not (0 <= team < 16 and (0 <= hero < 8 or hero == 255) and (0 <= race < 16 or race == 255)): return False
    return (pid == -1 and a == b == c == -1) or (pid > 0 and a == 0 and 0 < b < 256 and c == 0)
def slots(m):
    """[{pid, army, badge}] из slotinfo: после шапки слота — u32 n + имя армии (UTF-16), 4 байта, u32 n + путь значка."""
    try: raw = zlib.decompress(base64.b64decode(m.get('slotinfo') or ''))
    except Exception: return []
    if len(raw) < 6: return []
    n = struct.unpack_from('<H', raw, 4)[0]; off = 6; out = []
    for k in range(min(n, 16)):
        if not _slot_head(raw, off): break
        pid = struct.unpack_from('<i', raw, off)[0]; army = badge = ''
        try:
            q = off + 43; ln = struct.unpack_from('<I', raw, q)[0]
            if 0 < ln < 64:
                army = raw[q + 4:q + 4 + 2 * ln].decode('utf-16-le', 'replace'); q += 4 + 2 * ln + 4
                bl = struct.unpack_from('<I', raw, q)[0]
                if 0 < bl < 160: badge = raw[q + 4:q + 4 + bl].decode('latin-1').rstrip('\x00')
        except Exception: pass
        if pid > 0: out.append({'pid': pid, 'army': army, 'badge': badge})
        off += 43
        if k == n - 1: break
        if not _slot_head(raw, off):
            off = next((q for q in range(off, min(len(raw) - 42, off + 600)) if _slot_head(raw, q)), None)
            if off is None: break
    return out
def _badge(b):
    b = (b or '').replace('\\', '/').split('/')[-1].lower()
    return b, (None if not b or b == 'nobadge' or ':' in b else BADGE_RACE.get(b.split('_')[0]))
def match_races(m):
    """{profile_id: номер расы Elite 3.x или None} для участников матча (номера Relic приведены по таблице этой игры)."""
    mem = m.get('matchhistorymember', [])
    ids = {x['race_id'] for x in mem}
    ok = {'vanilla', 'elite2', 'elite3'}; score = dict.fromkeys(ok, 0); own = {}
    if ids & {7, 8}: ok -= {'vanilla', 'elite2'}
    if 6 in ids: ok -= {'vanilla'}
    mn = (m.get('mapname') or '').lower()
    if mn in ELITE_MAPS and mn not in VAN_MAPS: ok -= {'vanilla'}
    race_of = {x['profile_id']: x.get('race_id') for x in mem}
    for s in slots(m):
        r = race_of.get(s['pid'])
        if r is None: continue
        name, br = _badge(s['badge'])
        if (s['army'] or '').lower().endswith('_elite') or br in (3, 6, 8): ok -= {'vanilla'}
        if br is not None:
            own[s['pid']] = br                                   # the badge names the race the player had in the lobby
            for t in score:
                tr = TABLES[t].get(r)
                if tr is not None: score[t] += 1 if tr == br else -3
        elif name == 'nobadge':                                  # races that come without badges
            if r == 5: score['vanilla'] += 1                     # vanilla Tyranids (Elite SM nearly always have one)
            if r == 3: score['elite2'] += 1; score['elite3'] += 1   # Ordo Malleus (vanilla Orks nearly always have one)
            if r == 6: score['elite2'] += 1                      # Tyranids before Tau (Tau get tau_default)
    late = (m.get('startgametime') or 0) >= TAU_FROM
    order = ('elite3', 'elite2', 'vanilla') if late else ('elite2', 'elite3', 'vanilla')
    t = max(ok or {'elite3'}, key=lambda k: (score[k], -order.index(k)))
    out = {}
    for x in mem:
        r = x.get('race_id'); br = own.get(x['profile_id'])
        out[x['profile_id']] = br if br is not None and TABLES[t].get(r) is not None else TABLES[t].get(r)
    return out
# Relic ведёт рейтинг кастомок не одним числом: номера 0-6 — общий счёт, а 7, 8 и 255 («случайная») — у каждого свой
# (проверено по архиву 05.11.2026: рейтинг и счёт побед идут подряд между боями за 0-6 и обрываются при переходе на 7).
# Тираниды Elite с выходом Тау стали номером 7 — у тех, кто играл за них раньше (номер 6), это новый счёт с нуля, а не
# «падение за неактивность»: Relic за перерыв рейтинг не снижает.
def rating_pool(race_id): return 'main' if race_id is not None and 0 <= race_id <= 6 else str(race_id)

COUNTERS = ['ukill', 'uprod', 'plost', 'pseized', 'hkill', 'hlost', 'mvp', 'revived', 'sbuilt', 'wg']

# ---------- хранилище ----------
os.makedirs(os.path.dirname(DB), exist_ok=True)
_db_lock = threading.Lock()
def db():
    c = sqlite3.connect(DB, timeout=30); c.execute('PRAGMA journal_mode=WAL'); return c
with db() as c:
    c.executescript('''
    CREATE TABLE IF NOT EXISTS matches (id INTEGER PRIMARY KEY, start INTEGER, data TEXT);
    CREATE TABLE IF NOT EXISTS members (profile_id INTEGER, match_id INTEGER, start INTEGER, PRIMARY KEY (profile_id, match_id));
    CREATE INDEX IF NOT EXISTS members_p ON members (profile_id, start);
    CREATE TABLE IF NOT EXISTS profiles (profile_id INTEGER PRIMARY KEY, alias TEXT, steam TEXT, country TEXT, xp INTEGER, updated INTEGER);
    CREATE INDEX IF NOT EXISTS profiles_alias ON profiles (alias COLLATE NOCASE);
    CREATE TABLE IF NOT EXISTS steam (steamid TEXT PRIMARY KEY, hours REAL, h2wk REAL, privacy TEXT, updated INTEGER);
    CREATE TABLE IF NOT EXISTS tracked (profile_id INTEGER PRIMARY KEY, ps TEXT, requested INTEGER, refreshed INTEGER);
    CREATE TABLE IF NOT EXISTS aliases (alias TEXT PRIMARY KEY, cands TEXT, updated INTEGER);
    ''')
KEEP = 86400          # запрошенного игрока держим сутки с последнего запроса
REFRESH = 3600        # и раз в час обновляем его данные у Relic в фоне

# ---------- Relic ----------
_out = threading.Semaphore(4)          # не больше 4 одновременных запросов наружу
_cache = {}; _cache_lock = threading.Lock()
def relic(ep, ttl=60, **kw):
    q = urllib.parse.urlencode({'title': 'dow2r', **{k: json.dumps(v, separators=(',', ':')) for k, v in kw.items()}})
    url = RELIC + ep + '?' + q
    with _cache_lock:
        hit = _cache.get(url)
        if hit and time.time() - hit[0] < ttl: return hit[1]
    with _out:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=20) as r: data = json.load(r)
    if data.get('result', {}).get('code') != 0: raise RuntimeError('Relic: ' + str(data.get('result')))
    with _cache_lock:
        if len(_cache) > 2000: _cache.clear()
        _cache[url] = (time.time(), data)
    return data

def save_profiles(stat_groups):
    now = int(time.time()); rows = []
    for g in stat_groups or []:
        for m in g.get('members', []):
            rows.append((m['profile_id'], m.get('alias', ''), m.get('name', '').replace('/steam/', ''), m.get('country', ''), m.get('xp', 0), now))
    if rows:
        with _db_lock, db() as c: c.executemany('INSERT OR REPLACE INTO profiles VALUES (?,?,?,?,?,?)', rows)

def profiles_by_ids(ids):
    """Ники для списка profile_id: из кэша (сутки), остальное — пачками у Relic."""
    ids = [int(i) for i in set(ids) if int(i) > 0]; out = {}
    if not ids: return out
    with db() as c:
        for r in c.execute('SELECT profile_id, alias, steam, country, updated FROM profiles WHERE profile_id IN (%s)' % ','.join('?' * len(ids)), ids):
            if time.time() - r[4] < 86400: out[r[0]] = {'alias': r[1], 'steam': r[2], 'country': r[3]}
    need = [i for i in ids if i not in out]
    def fetch(chunk):
        try: return relic('getPersonalStat', ttl=3600, profile_ids=chunk).get('statGroups', [])
        except Exception:
            if len(chunk) == 1: return []
            h = len(chunk) // 2; return fetch(chunk[:h]) + fetch(chunk[h:])
    for i in range(0, len(need), 10):
        groups = fetch(need[i:i + 10]); save_profiles(groups)
        for g in groups:
            for m in g['members']: out[m['profile_id']] = {'alias': m.get('alias', ''), 'steam': m.get('name', '').replace('/steam/', ''), 'country': m.get('country', '')}
    return out

def store_matches(ms):
    with _db_lock, db() as c:
        for m in ms:
            c.execute('INSERT OR REPLACE INTO matches VALUES (?,?,?)', (m['id'], m['startgametime'], json.dumps(m, separators=(',', ':'))))
            for x in m.get('matchhistorymember', []):
                c.execute('INSERT OR IGNORE INTO members VALUES (?,?,?)', (x['profile_id'], m['id'], m['startgametime']))

# ---------- часы в Steam ----------
# Без ключа: публичный XML профиля, где Retribution есть только в «недавно игравшихся» (последние 2 недели).
# С ключом Steam Web API (файл data/steam_api_key) — GetOwnedGames, работает для любого публичного профиля.
APPID = 56400
KEYFILE = ROOT + '/data/steam_api_key'
def steam_hours(steamid, max_age=KEEP):
    if not re.fullmatch(r'7656119\d{10}', steamid or ''): return {}
    with db() as c:
        r = c.execute('SELECT hours, h2wk, privacy, updated FROM steam WHERE steamid = ?', (steamid,)).fetchone()
    if r and time.time() - r[3] < max_age: return {'hours': r[0], 'h2wk': r[1], 'privacy': r[2]}
    hours = h2wk = None; privacy = ''
    try:
        req = urllib.request.Request('https://steamcommunity.com/profiles/%s/?xml=1' % steamid, headers={'User-Agent': UA})
        with _out, urllib.request.urlopen(req, timeout=15) as resp: x = resp.read(400000).decode('utf-8', 'replace')
        pm = re.search(r'<privacyState>(\w+)</privacyState>', x); privacy = pm.group(1) if pm else ''
        g = re.search(r'<gameLink><!\[CDATA\[https://steamcommunity.com/app/%d\]\]></gameLink>(.*?)</mostPlayedGame>' % APPID, x, re.S)
        if g:
            hr = re.search(r'<hoursOnRecord>([\d,.]+)</hoursOnRecord>', g.group(1)); h2 = re.search(r'<hoursPlayed>([\d,.]+)</hoursPlayed>', g.group(1))
            if hr: hours = float(hr.group(1).replace(',', ''))
            if h2: h2wk = float(h2.group(1).replace(',', ''))
    except Exception: pass
    if hours is None and os.path.exists(KEYFILE) and privacy != 'private':
        try:
            key = open(KEYFILE).read().strip()
            q = urllib.parse.urlencode({'key': key, 'steamid': steamid, 'include_played_free_games': 1, 'appids_filter[0]': APPID, 'format': 'json'})
            with _out, urllib.request.urlopen('https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?' + q, timeout=15) as resp:
                for gm in json.load(resp).get('response', {}).get('games', []):
                    if gm.get('appid') == APPID:
                        hours = round(gm.get('playtime_forever', 0) / 60, 1); h2wk = round(gm.get('playtime_2weeks', 0) / 60, 1)
        except Exception: pass
    with _db_lock, db() as c: c.execute('INSERT OR REPLACE INTO steam VALUES (?,?,?,?,?)', (steamid, hours, h2wk, privacy, int(time.time())))
    return {'hours': hours, 'h2wk': h2wk, 'privacy': privacy}

# ---------- поиск ----------
STEAM_RE = re.compile(r'(7656119\d{10})')
def resolve(q):
    q = q.strip()[:200]
    if not q: return []
    m = STEAM_RE.search(q)
    if m: return lookup(profile_names=['/steam/' + m.group(1)])
    v = re.search(r'steamcommunity\.com/id/([A-Za-z0-9_-]{2,64})', q)
    if v:
        try:
            req = urllib.request.Request('https://steamcommunity.com/id/%s/?xml=1' % v.group(1), headers={'User-Agent': UA})
            with _out, urllib.request.urlopen(req, timeout=15) as r: x = r.read(200000).decode('utf-8', 'replace')
            s = re.search(r'<steamID64>(\d+)</steamID64>', x)
            if s: return lookup(profile_names=['/steam/' + s.group(1)])
        except Exception: pass
        return []
    if q.isdigit() and len(q) <= 10: return lookup(profile_ids=[int(q)])
    seen = {}
    for a in dict.fromkeys([q, q.lower()]):
        for r in lookup(aliases=[a]): seen[r['profile_id']] = r
    return sorted(seen.values(), key=lambda r: -(r.get('last') or 0))

def lookup(**kw):
    alias = kw['aliases'][0] if list(kw) == ['aliases'] else None
    if alias is not None:
        with db() as c: r = c.execute('SELECT cands, updated FROM aliases WHERE alias = ?', (alias,)).fetchone()
        if r and time.time() - r[1] < KEEP: return json.loads(r[0])
    if alias is not None and len(alias) < 2:        # Relic refuses aliases shorter than 2 characters - profiles we have seen, by Steam id
        with db() as c: steams = [r[0] for r in c.execute('SELECT steam FROM profiles WHERE alias = ? AND steam <> "" ORDER BY updated DESC LIMIT 5', (alias,))]
        res = []
        for st in steams: res += lookup(profile_names=['/steam/' + st])
        return res
    try: ps = relic('getPersonalStat', ttl=300, **kw)
    except Exception: return []
    res = lookup_parse(ps)
    if alias is not None:
        with _db_lock, db() as c: c.execute('INSERT OR REPLACE INTO aliases VALUES (?,?,?)', (alias, json.dumps(res), int(time.time())))
    return res

def lookup_parse(ps):
    groups = ps.get('statGroups', []); save_profiles(groups)
    cust = {s['statgroup_id']: s for s in ps.get('leaderboardStats', []) if s['leaderboard_id'] == 0}
    res = []
    for g in groups:
        for m in g['members']:
            s = cust.get(m.get('personal_statgroup_id')) or {}
            res.append({'profile_id': m['profile_id'], 'alias': m.get('alias', ''), 'steam': m.get('name', '').replace('/steam/', ''),
                        'country': m.get('country', ''), 'wins': s.get('wins', 0), 'losses': s.get('losses', 0), 'last': s.get('lastmatchdate', 0)})
    return res[:25]

# ---------- профиль ----------
def refresh(pid):
    """Свежие данные игрока у Relic: личная статистика + последние матчи (в базу), часы Steam."""
    ps = relic('getPersonalStat', ttl=0, profile_ids=[pid]); save_profiles(ps.get('statGroups', []))
    try: store_matches(relic('getRecentMatchHistory', ttl=0, profile_ids=[pid]).get('matchHistoryStats', []))
    except Exception: pass
    me = next((m for g in ps.get('statGroups', []) for m in g['members'] if m['profile_id'] == pid), None)
    if me: steam_hours(me.get('name', '').replace('/steam/', ''), max_age=REFRESH)
    with _db_lock, db() as c:
        c.execute('INSERT INTO tracked VALUES (?,?,?,?) ON CONFLICT(profile_id) DO UPDATE SET ps = excluded.ps, refreshed = excluded.refreshed',
                  (pid, json.dumps(ps, separators=(',', ':')), int(time.time()), int(time.time())))
    return ps

def tracked_ps(pid):
    """Данные игрока из нашей базы; если их нет или они старше часа — обновить сейчас. Отмечает запрос (держим сутки)."""
    now = int(time.time())
    with _db_lock, db() as c:
        r = c.execute('SELECT ps, refreshed FROM tracked WHERE profile_id = ?', (pid,)).fetchone()
        if r: c.execute('UPDATE tracked SET requested = ? WHERE profile_id = ?', (now, pid))
    if r and now - r[1] < REFRESH: return json.loads(r[0])
    try: return refresh(pid)
    except Exception:
        if r: return json.loads(r[0])          # Relic не ответил — отдаём то, что есть
        raise

def refresher():
    """Фон: раз в 5 минут обновляем тех, кого спрашивали за сутки и чьи данные старше часа; старых забываем."""
    while True:
        try:
            now = int(time.time())
            with _db_lock, db() as c:
                c.execute('DELETE FROM tracked WHERE requested < ?', (now - KEEP,))
                c.execute('DELETE FROM aliases WHERE updated < ?', (now - KEEP,))
            with db() as c:
                due = [r[0] for r in c.execute('SELECT profile_id FROM tracked WHERE refreshed < ? ORDER BY refreshed LIMIT 200', (now - REFRESH,))]
            for pid in due:
                try: refresh(pid)
                except Exception: pass
                time.sleep(1)
        except Exception: pass
        time.sleep(300)

def match_by_lobby(lobby, pid):
    """Матч Relic по имени лобби (description) — так ладдер узнаёт результат своего матча. pid — кто-то из игроков."""
    pid = int(pid)
    try: store_matches(relic('getRecentMatchHistory', ttl=60, profile_ids=[pid]).get('matchHistoryStats', []))
    except Exception: pass
    with db() as c:
        for (d,) in c.execute('SELECT m.data FROM members x JOIN matches m ON m.id = x.match_id WHERE x.profile_id = ? ORDER BY x.start DESC LIMIT 60', (pid,)):
            j = json.loads(d)
            if j.get('description') == lobby: return j
    return None

def player(pid):
    pid = int(pid)
    ps = tracked_ps(pid)
    me = next((m for g in ps.get('statGroups', []) for m in g['members'] if m['profile_id'] == pid), None)
    if not me: return None
    with db() as c:
        rows = c.execute('SELECT m.data FROM members x JOIN matches m ON m.id = x.match_id WHERE x.profile_id = ? ORDER BY x.start DESC LIMIT 300', (pid,)).fetchall()
    ms = [json.loads(r[0]) for r in rows]
    names = profiles_by_ids([x['profile_id'] for m in ms[:40] for x in m.get('matchhistorymember', [])])
    lb = {s['leaderboard_id']: s for s in ps.get('leaderboardStats', [])}
    cust = lb.get(0, {})
    matches, races, heroes, totals, n_tot = [], {}, {}, {k: 0 for k in COUNTERS}, 0
    pools = {}                                       # Relic's own rating tracks (rating_pool): pool -> [(time, rating, race)]
    for m in ms:
        mem = {x['profile_id']: x for x in m.get('matchhistorymember', [])}
        res = {x['profile_id']: x for x in m.get('matchhistoryreportresults', [])}
        if pid not in mem: continue
        rid = match_races(m)
        x = mem[pid]; r = res.get(pid, {}); my = rid.get(pid)
        try: cnt = json.loads(r.get('counters') or '{}')
        except Exception: cnt = {}
        hero = next((i for i, k in enumerate(('ha', 'hb', 'hc')) if cnt.get(k)), None)
        last_stand = m.get('matchtype_id') == 5
        win = x.get('outcome') == 1
        players = []
        for oid, o in mem.items():
            oc = {}
            try: oc = json.loads(res.get(oid, {}).get('counters') or '{}')
            except Exception: pass
            players.append({'profile_id': oid, 'alias': names.get(oid, {}).get('alias', ''), 'team': o.get('teamid'), 'race': rid.get(oid),
                            'hero': next((i for i, k in enumerate(('ha', 'hb', 'hc')) if oc.get(k)), None), 'win': o.get('outcome') == 1,
                            'rating': o.get('newrating'), 'delta': (o.get('newrating') or 0) - (o.get('oldrating') or 0)})
        matches.append({'id': m['id'], 'start': m['startgametime'], 'duration': max(0, m.get('completiontime', 0) - m['startgametime']),
                        'map': m.get('mapname', ''), 'name': m.get('description', ''), 'type': m.get('matchtype_id'), 'size': len(mem),
                        'race': my, 'hero': hero, 'team': x.get('teamid'), 'win': win, 'old': x.get('oldrating'), 'new': x.get('newrating'),
                        'pool': rating_pool(x.get('race_id')),
                        'counters': {k: cnt.get(k, 0) for k in COUNTERS}, 'players': players})
        if last_stand: continue
        if x.get('newrating'): pools.setdefault(rating_pool(x.get('race_id')), []).append((m['startgametime'], x['newrating'], my))
        rr = races.setdefault(my, {'games': 0, 'wins': 0}); rr['games'] += 1; rr['wins'] += win
        if hero is not None and my is not None and hero < len(RACES.get(my, ('', '', '', []))[3]):
            hh = heroes.setdefault('%s:%s' % (my, hero), {'games': 0, 'wins': 0}); hh['games'] += 1; hh['wins'] += win
        n_tot += 1
        for k in COUNTERS: totals[k] += cnt.get(k, 0) or 0
    pvp = [mt for mt in matches if mt['type'] != 5]
    latest = pvp[0] if pvp else None
    # the chart: the track of the latest rated battle only (two tracks in one line looked like a fall of 1000 points);
    # the others are listed under it, each with its last rating
    for v in pools.values(): v.sort()
    cur = next((mt['pool'] for mt in pvp if mt['new']), None)
    series = [(t, v) for t, v, _ in pools.get(cur, [])]
    tracks = sorted(({'pool': k, 'rating': v[-1][1], 'last': v[-1][0], 'games': len(v), 'current': k == cur,
                      'races': sorted({rc for _, _, rc in v if rc is not None})} for k, v in pools.items()), key=lambda t: -t['last'])
    streak = 0
    for mt in pvp:
        if streak == 0: streak = 1 if mt['win'] else -1
        elif (streak > 0) == mt['win']: streak += 1 if mt['win'] else -1
        else: break
    return {
        'profile_id': pid, 'alias': me.get('alias', ''), 'steam': me.get('name', '').replace('/steam/', ''), 'country': me.get('country', ''),
        'xp': me.get('xp', 0), 'rating': latest['new'] if latest else None, 'peak': max((v for _, v in series), default=None),
        'wins': cust.get('wins', 0), 'losses': cust.get('losses', 0), 'drops': cust.get('drops', 0), 'disputes': cust.get('disputes', 0),
        'last': max(cust.get('lastmatchdate') or 0, matches[0]['start'] if matches else 0), 'streak': streak,   # leaderboard 0 is the 0-6 track only
        'series': series[-200:], 'tracks': tracks, 'races': races, 'heroes': heroes, 'avg': {k: round(v / n_tot, 1) for k, v in totals.items()} if n_tot else {},
        'sample': n_tot, 'matches': matches[:60], 'stored': len(ms),
        'steam_hours': steam_hours(me.get('name', '').replace('/steam/', '')),
        'automatch': [{'id': s['leaderboard_id'], 'wins': s['wins'], 'losses': s['losses']} for s in ps.get('leaderboardStats', []) if s['leaderboard_id'] != 0 and s['wins'] + s['losses'] > 0],
    }

def lobby_line(name):
    """Одна строка для DLL лобби: ключ, рейтинг, победы, поражения, часы, profile_id.
    Ключ — ник или /steam/<SteamID64> (точнее: тёзки и переименования не мешают). Тёзок по нику выбираем по свежести игры."""
    if re.fullmatch(r'/steam/7656119\d{10}', name): cands = lookup(profile_names=[name])
    else: cands = [c for c in lookup(aliases=[name]) if c['alias'] == name] or lookup(aliases=[name])
    if not cands: return name + '\t-'
    c = max(cands, key=lambda r: (r.get('last') or 0, r['wins'] + r['losses']))
    pid = c['profile_id']
    try: ps = tracked_ps(pid)
    except Exception: ps = {}
    cust = next((s for s in ps.get('leaderboardStats', []) if s['leaderboard_id'] == 0), None) or c
    rating = ''
    with db() as d:
        for (data,) in d.execute('SELECT m.data FROM members x JOIN matches m ON m.id = x.match_id WHERE x.profile_id = ? ORDER BY x.start DESC LIMIT 20', (pid,)):
            m = json.loads(data)
            x = next((x for x in m.get('matchhistorymember', []) if x['profile_id'] == pid), None)
            if x and m.get('matchtype_id') != 5 and x.get('newrating'): rating = str(x['newrating']); break
    h = steam_hours(c.get('steam', '')).get('hours')
    return '\t'.join([name, rating or '-', str(cust.get('wins', 0)), str(cust.get('losses', 0)), str(int(h)) if h is not None else '-', str(pid)])

def meta():
    return {'races': {k: {'key': v[0], 'en': v[1], 'ru': v[2], 'heroes': [{'img': h[0], 'en': h[1], 'ru': h[2]} for h in v[3]]} for k, v in RACES.items()}}

# ---------- HTTP ----------
hits = {}; hits_lock = threading.Lock()
def allow(ip, limit=40):
    now = time.time()
    with hits_lock:
        h = [t for t in hits.get(ip, []) if now - t < 60]
        if len(h) >= limit: hits[ip] = h; return False
        h.append(now); hits[ip] = h
        if len(hits) > 5000: hits.clear()
        return True

# ---------- anonymous launcher usage count ----------
# Elite Launcher sends once a day: a 128-bit hash that changes every day (it can't be linked across days), its version,
# the OS and the installed Elite version. No IP or anything else is stored; nginx doesn't log this request.
USAGE_DB = '/srv/relicstats/data/usage.db'
usage_lock = threading.Lock()
def usage_ping(qs):
    g = lambda k: (qs.get(k, [''])[0])
    h, v, osn, el = g('h'), g('v'), g('os'), g('elite')
    if not re.fullmatch(r'[0-9a-f]{32}', h) or not re.fullmatch(r'[0-9.]{1,12}', v) or osn not in ('windows', 'linux', 'macos') \
            or not re.fullmatch(r'[A-Za-z0-9.-]{1,16}', el):
        return False
    day = time.strftime('%Y-%m-%d', time.gmtime())
    with usage_lock:
        c = sqlite3.connect(USAGE_DB)
        try:
            c.execute('CREATE TABLE IF NOT EXISTS ping (day TEXT, h TEXT, v TEXT, os TEXT, elite TEXT, PRIMARY KEY (day, h))')
            if c.execute('SELECT COUNT(*) FROM ping WHERE day=?', (day,)).fetchone()[0] < 200000:
                c.execute('INSERT OR IGNORE INTO ping VALUES (?,?,?,?,?)', (day, h, v, osn, el))
            c.commit()
        finally:
            c.close()
    return True

LOGDIR = '/srv/relicstats/logs'

class H(BaseHTTPRequestHandler):
    server_version = 'stats'
    def log_message(self, *a): pass
    def ip(self): return self.headers.get('CF-Connecting-IP') or self.headers.get('X-Real-IP') or self.client_address[0]
    def send(self, code, body, ctype='application/json; charset=utf-8', cache='no-store'):
        if isinstance(body, (dict, list)): body = json.dumps(body, ensure_ascii=False, separators=(',', ':'))
        if isinstance(body, str): body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', cache); self.send_header('X-Content-Type-Options', 'nosniff')
        if ctype.startswith('text/html'):
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.send_header('Referrer-Policy', 'same-origin')
        self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        # логи из лаунчера Elite (кнопка «Отправить логи»): текстовый пакет, храним сжатым, дальше их забирает logs-notify
        u = urllib.parse.urlparse(self.path); qs = urllib.parse.parse_qs(u.query)
        if u.path != '/stats/api/logs': return self.send(404, {'error': 'not found'})
        if not allow(self.ip()): return self.send(429, {'error': 'Too many requests, slow down a little.'})
        try: n = int(self.headers.get('Content-Length') or 0)
        except ValueError: n = 0
        if n <= 0 or n > 40 * 1024 * 1024: return self.send(413, {'error': 'empty or too large (max 40 MB)'})
        body = self.rfile.read(n)
        import gzip
        os.makedirs(LOGDIR, exist_ok=True)
        rid = time.strftime('%Y%m%d-%H%M%S') + '-' + os.urandom(3).hex()
        who = re.sub(r'[^\w.-]', '_', (qs.get('who', ['anon'])[0]))[:32] or 'anon'
        dst = f'{LOGDIR}/{rid}_{who}.txt.gz'
        uid = (qs.get('uid', [''])[0])
        if re.fullmatch(r'[A-Za-z0-9_-]{16,64}', uid):        # the launcher chat id: the answer about these logs goes into that chat
            with open(f'{LOGDIR}/{rid}.uid', 'w') as f: f.write(uid)
        with gzip.open(dst + '.part', 'wb') as f: f.write(body)   # writes to .part first: the Telegram notifier
        os.replace(dst + '.part', dst)                              # must only ever see complete archives
        return self.send(200, {'ok': True, 'id': rid})
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); p = u.path; qs = urllib.parse.parse_qs(u.query)
        try:
            if p in ('/stats', '/stats/') or re.fullmatch(r'/stats/p/\d{1,12}', p):
                return self.send(200, PAGE, 'text/html; charset=utf-8')
            if p.startswith('/stats/static/'):
                f = os.path.normpath(STATIC + '/' + p[len('/stats/static/'):])
                if not f.startswith(STATIC + '/') or not os.path.isfile(f): return self.send(404, {'error': 'not found'})
                return self.send(200, open(f, 'rb').read(), CT.get(os.path.splitext(f)[1], 'application/octet-stream'), 'public, max-age=86400')
            if p == '/stats/api/meta': return self.send(200, meta(), cache='public, max-age=3600')
            if p == '/stats/api/ping': return self.send(200 if usage_ping(qs) else 400, {'ok': True})   # before the rate limiter: it would hold the address
            if not allow(self.ip()): return self.send(429, {'error': 'Too many requests, slow down a little.'})
            if p == '/stats/api/lobby':
                names = [n[:64] for n in qs.get('n', []) if n.strip()][:12]
                with ThreadPoolExecutor(4) as ex: lines = list(ex.map(lobby_line, names))
                return self.send(200, '\n'.join(lines) + '\n', 'text/plain; charset=utf-8')
            if p == '/stats/api/search':
                return self.send(200, {'results': resolve(qs.get('q', [''])[0])})
            if p == '/stats/api/match':
                lobby, pid = qs.get('lobby', [''])[0][:80], qs.get('pid', [''])[0]
                if not lobby or not pid.isdigit(): return self.send(400, {'error': 'lobby and pid are needed'})
                d = match_by_lobby(lobby, pid)
                return self.send(200, d) if d else self.send(404, {'error': 'not found'})
            m = re.fullmatch(r'/stats/api/player/(\d{1,12})', p)
            if m:
                d = player(m.group(1))
                return self.send(200, d) if d else self.send(404, {'error': 'Player not found'})
            return self.send(404, {'error': 'not found'})
        except Exception as e:
            return self.send(502, {'error': 'Relic server did not answer: %s' % type(e).__name__})

if __name__ == '__main__':
    threading.Thread(target=refresher, daemon=True).start()
    ThreadingHTTPServer(('127.0.0.1', PORT), H).serve_forever()
