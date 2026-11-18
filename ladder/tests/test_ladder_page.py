#!/usr/bin/env python3
"""17.11.2026 (SirItos, the preseason): one ladder page in the launcher's look and the hours in the site's API.
 - /ladder/, /ladder/table, /ladder/player/<steam> serve the one page (ladder.html); /ladder/rating/ still 301s to /ladder/table
   with only a checked mode / lang (nothing raw into the header)
 - hours_played (Retribution's hours in Steam, the lobby line's, as c/me) in /own/all per player, in /own rows, in /own/player;
   null when not known
usage: python3 ladder/tests/test_ladder_page.py [<repo dir>]   (a temp copy, an empty data dir; nothing live)"""
import json, os, shutil, sqlite3, sys, tempfile, threading, time, urllib.request, urllib.error
REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
T = tempfile.mkdtemp(prefix='ladder_page_')
shutil.copytree(REPO + '/ladder', T + '/app', ignore=shutil.ignore_patterns('__pycache__', '*.bak*', 'tests'))
os.makedirs(T + '/data'); sys.path.insert(0, T + '/app'); os.environ['LADDER_NO_CRAWL'] = '1'
import ladder as L
import own_matches as o
fails = []
def check(name, got, want):
    ok = got == want
    print('  %-74s %s' % (name, 'ok' if ok else 'FAIL: got %r, want %r' % (got, want)))
    if not ok: fails.append(name)

season = L.current_season()
A, B, C = '76561198000000001', '76561198000000002', '76561198000000003'
with L.db() as c:
    c.execute('CREATE TABLE IF NOT EXISTS own_ratings (steam TEXT, mode TEXT, season TEXT, rating REAL, rd REAL, cons REAL, games INTEGER, '
              'wins INTEGER, losses INTEGER, leaves INTEGER, cal_left INTEGER, last INTEGER, PRIMARY KEY (steam, mode, season))')
    cols = [r[1] for r in c.execute('PRAGMA table_info(own_ratings)')]
    for st, rt, rd, g, cl in ((A, 1700, 60, 9, 0), (B, 1500, 300, 2, 3), (C, 1600, 80, 7, 0)):
        row = {'steam': st, 'mode': '1v1', 'season': season, 'rating': rt, 'rd': rd, 'cons': rt - 2 * rd, 'games': g, 'wins': g, 'losses': 0,
               'leaves': 0, 'cal_left': cl, 'last': int(time.time())}
        c.execute('INSERT INTO own_ratings (%s) VALUES (%s)' % (','.join(k for k in cols if k in row), ','.join('?' for k in cols if k in row)),
                  [row[k] for k in cols if k in row])
L._HOURS[A] = (time.time(), 1234); L._HOURS[C] = (time.time(), None)      # A: known, C: private profile, B: never fetched

srv = L.Server(('127.0.0.1', 0), L.H); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
class NoRedir(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
op = urllib.request.build_opener(NoRedir)
def get(path):
    try: r = op.open('http://127.0.0.1:%d%s' % (port, path), timeout=10); return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e: return e.code, e.headers, e.read()

page = open(REPO + '/ladder/ladder.html', 'rb').read()
for p in ('/ladder/', '/ladder', '/ladder/table', '/ladder/table/', '/ladder/player/76561198000000001', '/ladder/player/76561198000000001/'):
    st, h, b = get(p)
    check('GET %s -> the one page' % p, (st, b == page), (200, True))
check('GET /ladder/player/abc -> 404', get('/ladder/player/abc')[0], 404)
st, h, b = get('/ladder/rating/?mode=2v2&lang=en&x=1')
check('/ladder/rating/ -> 301 /ladder/table, checked params only', (st, h.get('Location')), (301, '/ladder/table?mode=2v2&lang=en'))
st, h, b = get('/ladder/rating?mode=%0d%0aSet-Cookie:x')
check('... a raw value is dropped', (st, h.get('Location')), (301, '/ladder/table'))
check('the old rating.html is gone from the repo', os.path.exists(REPO + '/ladder/rating.html'), False)

# 17.11.2026 (SirItos: "with a bad connection the frame pictures do not load"): some Russian ISPs' DPI freezes any single answer over
# ~30 KB - every file the page loads stays under 30 KB uncompressed, fonts under 20 KB, pictures under 12 KB (only textures: the
# frames are CSS), and every file it names exists in site/
import re as _re
LIM = 30000
check('ladder.html <= 30 KB', len(page) <= LIM, True)
refs = set(_re.findall(r'/elite/((?:ui|fonts)/[\w.-]+)', page.decode('utf-8')))
for css in [r for r in refs if r.endswith('.css')]:
    refs |= set(_re.findall(r'/elite/((?:ui|fonts)/[\w.-]+)', open(REPO + '/site/' + css, encoding='utf-8').read()))
check('the page loads its style, script and fonts from /elite/', {'ui/ladder.css', 'ui/ladder-x.css', 'ui/ladder-t.js', 'ui/ladder.js', 'ui/ladder-x.js',
      'fonts/rc400.woff2', 'fonts/rc700.woff2', 'fonts/sp600.woff2', 'fonts/cinzel-logo.woff2'} <= refs, True)
for r in sorted(refs):
    fn = REPO + '/site/' + r; n = os.path.getsize(fn) if os.path.exists(fn) else -1
    lim = 20000 if r.startswith('fonts/') else 12000 if _re.search(r'\.(png|jpe?g|webp)$', r) else LIM
    check('/elite/%s exists, %d <= %d' % (r, n, lim), 0 <= n <= lim, True)
idx = json.load(open(REPO + '/site/assets/index.json', encoding='utf-8'))
miss = [m['minimap'] for m in idx['maps'].values() if _re.fullmatch(r'maps/[\w.-]+\.png', m.get('minimap') or '')
        and not os.path.exists(REPO + '/site/assets/maps_s/' + m['minimap'][5:-4] + '.webp')]
check('every minimap has its webp thumb (assets/maps_s/, <= 12 KB)', (miss, max(os.path.getsize(REPO + '/site/assets/maps_s/' + f)
      for f in os.listdir(REPO + '/site/assets/maps_s')) <= 12000), ([], True))
# 18.11.2026 (SirItos): the season maps' cards fill the section - a 232 px webp per minimap (assets/maps_m/, q70), each answer under 30 KB
miss = [m['minimap'] for m in idx['maps'].values() if _re.fullmatch(r'maps/[\w.-]+\.png', m.get('minimap') or '')
        and not os.path.exists(REPO + '/site/assets/maps_m/' + m['minimap'][5:-4] + '.webp')]
check('every minimap has its 256 px webp (assets/maps_m/, < 30 KB)', (miss, max(os.path.getsize(REPO + '/site/assets/maps_m/' + f)
      for f in os.listdir(REPO + '/site/assets/maps_m')) < LIM), ([], True))

o._CACHE.update(t=0)
d = json.loads(get('/ladder/api/own/all')[2])
pl = d['players']
check('/own/all: hours_played per player (known)', pl[A].get('hours_played'), 1234)
check('/own/all: private profile -> null', (C in pl, pl[C].get('hours_played', 'missing')), (True, None))
check('/own/all: never fetched -> null', pl[B].get('hours_played', 'missing'), None)
check('/own/all: the modes unchanged', (pl[A]['1v1']['c'], pl[A]['1v1']['rank'], pl[B]['1v1']['cal']), (1580, 1, 3))
rows = {r['steam']: r for r in json.loads(get('/ladder/api/own?mode=1v1')[2])['rows']}
check('/own rows: hours_played', (rows[A]['hours_played'], rows[B]['hours_played'], rows[C]['hours_played']), (1234, None, None))
check('/own/player: hours_played', json.loads(get('/ladder/api/own/player?steam=' + A)[2]).get('hours_played'), 1234)
check('c/me source and the site agree (_c_hours)', L._c_hours(A), 1234)
srv.shutdown()
shutil.rmtree(T, ignore_errors=True)
print('FAILED: %s' % ', '.join(fails) if fails else 'ALL OK'); sys.exit(1 if fails else 0)
