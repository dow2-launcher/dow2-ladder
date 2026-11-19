#!/usr/bin/env python3
# 19.11.2026 (launcher 1.6.28, SirItos: "a player's tip on the Replays tab's names"): every player of a replay carries his SteamID
# ("steam") - the replay lists, a replay's page data (/replay/api/r/<id>) and POST /replay/api/steams (the launcher's own files) - from
# relicstats' /stats/api/steams (Relic profile ids -> SteamIDs). Here both services for real (temp copies, empty data), Relic itself
# stood in: relicstats answers from its profiles cache and asks "Relic" (getPersonalStat) for the rest.
# usage: python3 replay/tests/test_steams.py   (nothing live)
import http.client, json, os, shutil, sqlite3, sys, tempfile, threading, time, importlib.util
from http.server import ThreadingHTTPServer
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
T = tempfile.mkdtemp(prefix='replay_steams_')
for d in ('replay', 'stats'):
    shutil.copytree(REPO + '/' + d, T + '/' + d + '/app', ignore=shutil.ignore_patterns('__pycache__', '*.bak*', 'tests'))
    os.makedirs(T + '/' + d + '/data')
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec)
    sys.path.insert(0, os.path.dirname(path)); spec.loader.exec_module(m); return m
sys.argv = ['app']
S = load('stats_app', T + '/stats/app/app.py')
A = load('replay_app', T + '/replay/app/app.py')
A.analyse = lambda rid: None
# "Relic": profile 111 and 222 known (SteamIDs), 333 a profile without a Steam name, anything else unknown
RELIC = {111: '/steam/76561198000000111', 222: '/steam/76561198000000222', 333: 'someone'}
relic_asked = []
def fake_relic(ep, ttl=60, **kw):
    ids = kw.get('profile_ids') or []; relic_asked.append(list(ids))
    return {'statGroups': [{'members': [{'profile_id': i, 'alias': 'p%d' % i, 'name': RELIC[i], 'country': 'de'}]} for i in ids if i in RELIC]}
S.relic = fake_relic
st = ThreadingHTTPServer(('127.0.0.1', 0), S.H); threading.Thread(target=st.serve_forever, daemon=True).start()
A.STEAMS_API = 'http://127.0.0.1:%d/stats/api/steams' % st.server_address[1]
A.RELIC_API = 'http://127.0.0.1:%d/stats/api/lobby' % st.server_address[1]
A.relic_now = lambda pl: {}          # the ratings' lookup is not what is tested here
A.ladder_ratings = lambda rid: {}
def pl(*pids): return [{'name': 'p%d' % p, 'team': i % 2, 'race': 'space_marines', 'hero': 0, 'pid': p, 'level': 1} for i, p in enumerate(pids)]
A.index_add('00000000000000c1', {'mkey': 'k1', 'map': '2p_fen_dunloch', 'players': pl(111, 4294967295), 'ticks': 3000, 'recorded': '2026-11-19'}, 'a.rec', '', 100)
A.index_add('00000000000000c2', {'mkey': 'k2', 'map': '4p_argusgate', 'players': pl(111, 222, 333, 444), 'ticks': 3000, 'recorded': '2026-11-19'}, 'b.rec', '', 100)
os.makedirs(A.STORE + '/00000000000000c2', exist_ok=True)   # a replay's folder (the page data answers 404 without it)
srv = ThreadingHTTPServer(('127.0.0.1', 0), A.H); threading.Thread(target=srv.serve_forever, daemon=True).start()
def req(method, path, body=None, port=None, headers=None):
    c = http.client.HTTPConnection('127.0.0.1', port or srv.server_address[1], timeout=30)
    c.request(method, path, json.dumps(body).encode() if body is not None else None, dict({'Content-Type': 'application/json'}, **(headers or {})))
    r = c.getresponse(); return r.status, json.loads(r.read() or b'{}')
fails = []
def check(name, got, want):
    ok = got == want
    print('  %-74s %s' % (name, 'ok' if ok else 'FAIL: got %r, want %r' % (got, want)))
    if not ok: fails.append(name)
steams = lambda it: {p['pid']: p.get('steam') for p in it['players']}

print('relicstats /stats/api/steams')
code, d = req('GET', '/stats/api/steams?p=111&p=222&p=333&p=444&p=4294967295&p=abc', port=st.server_address[1])
check('SteamIDs of the known, none for no Steam name / unknown / the computer', (code, d), (200, {'111': '76561198000000111', '222': '76561198000000222'}))
check('  ... Relic asked once for the real ids only', [sorted(x) for x in relic_asked], [[111, 222, 333, 444]])
n = len(relic_asked); req('GET', '/stats/api/steams?p=111&p=222', port=st.server_address[1])
check('  ... the known from its profiles cache (Relic not asked)', len(relic_asked), n)
check('  ... at most 60 ids', len(S.profiles_by_ids.__code__.co_varnames) > 0 and req('GET', '/stats/api/steams?' + '&'.join('p=%d' % i for i in range(1000, 1100)), port=st.server_address[1])[0], 200)
check('  ... and asked Relic for 60 of the 100 only', sum(len(x) for x in relic_asked[n:]), 60)

print('the replay service')
relic_asked.clear()
code, d = req('POST', '/replay/api/list', {})
by = {it['id'][-2:]: steams(it) for it in d['items']}
check('the list: every player with his SteamID, the computer and unknown without', by,
      {'c1': {111: '76561198000000111', 4294967295: None}, 'c2': {111: '76561198000000111', 222: '76561198000000222', 333: None, 444: None}})
check('  ... GET list (the site) the same', {it['id'][-2:]: steams(it) for it in req('GET', '/replay/api/list')[1]['items']}, by)
n = len(relic_asked); req('POST', '/replay/api/list', {})
check('  ... cached here: relicstats / Relic not asked again', len(relic_asked), n)
code, d = req('GET', '/replay/api/r/00000000000000c2')
check("a replay's data (the launcher's detail panel): the same", steams(d.get('meta') or d), {111: '76561198000000111', 222: '76561198000000222', 333: None, 444: None})
code, d = req('POST', '/replay/api/steams', {'pids': [222, 4294967295, 'x', 999]})
check('POST /replay/api/steams (the launcher\'s own files)', (code, d), (200, {'222': '76561198000000222'}))
print('relicstats down')
A._steam_of.clear(); A.STEAMS_API = 'http://127.0.0.1:9/stats/api/steams'
t0 = time.time(); code, d = req('POST', '/replay/api/list', {})
check('the list still answers, no SteamIDs, quickly', (code, all('steam' not in p for it in d['items'] for p in it['players']), time.time() - t0 < A.RATING_WAIT + 1.5), (200, True, True))
print('FAILED: %s' % ', '.join(fails) if fails else 'all ok')
st.shutdown(); srv.shutdown(); shutil.rmtree(T, ignore_errors=True)
sys.exit(1 if fails else 0)
