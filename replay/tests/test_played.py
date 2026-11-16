#!/usr/bin/env python3
# 16.11.2026 (the launcher's "My replays", 1.6.16): "played" in POST /replay/api/list - the matches the signed-in player played in,
# by his Relic profile id (relicstats' line for /steam/<SteamID>); the answer says the id (me_pid). Not signed in / not known to
# Relic: nothing listed. The other filters and the pages work with it; "mine" (his uploads) stays as it was.
# usage: python3 replay/tests/test_played.py   (a temp copy, a fake relicstats; nothing live)
import http.client, json, os, shutil, sys, tempfile, threading, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = tempfile.mkdtemp(prefix='replay_played_'); shutil.copytree(HERE, T + '/app', ignore=shutil.ignore_patterns("__pycache__", "*.bak*", "tests"))
os.makedirs(T + '/data')
ME, OTHER, NOBODY = '76561198000000001', '76561198000000002', '76561198000000003'
# relicstats' lobby line: key, rating, wins, losses, hours, profile_id ("-" when the profile is unknown)
RELIC = {'/steam/' + ME: '/steam/%s\t1800\t10\t5\t300\t111' % ME, '/steam/' + OTHER: '/steam/%s\t1500\t1\t1\t20\t222' % OTHER}
asked = []
class F(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        n = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get('n', [''])[0]; asked.append(n)
        b = RELIC.get(n, n + '\t-').encode(); self.send_response(200); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
fk = ThreadingHTTPServer(('127.0.0.1', 0), F); threading.Thread(target=fk.serve_forever, daemon=True).start()
sys.argv = ['app']; sys.path.insert(0, T + '/app')
import app as A
A.analyse = lambda rid: None
A.RELIC_API = 'http://127.0.0.1:%d/stats/api/lobby' % fk.server_address[1]
TOK = {'tok-me-0123456789abc': ME, 'tok-other-0123456789': OTHER, 'tok-nobody-012345678': NOBODY}
A.who = lambda tok: {'steam': TOK[tok], 'name': 'P'} if tok in TOK else None
def pl(*pids): return [{'name': 'p%d' % p, 'team': i % 2, 'race': 'space_marines', 'hero': 0, 'pid': p, 'level': 1} for i, p in enumerate(pids)]
ROWS = {'00000000000000b1': (pl(111, 333), '2p_fen_dunloch'), '00000000000000b2': (pl(222, 333), '2p_fen_dunloch'),
        '00000000000000b3': (pl(111, 222, 333, 444), '4p_argusgate'), '00000000000000b4': (pl(555, 666), '2p_fen_dunloch')}
for i, (rid, (p, mp)) in enumerate(sorted(ROWS.items())):
    A.index_add(rid, {'mkey': 'k%d' % i, 'map': mp, 'players': p, 'ticks': 3000, 'recorded': '2026-11-16'}, 'x.rec', '', 100,
                author='P' if rid == '00000000000000b4' else None, author_steam=ME if rid == '00000000000000b4' else None)
srv = ThreadingHTTPServer(('127.0.0.1', 0), A.H); threading.Thread(target=srv.serve_forever, daemon=True).start()
def lst(**q):
    c = http.client.HTTPConnection('127.0.0.1', srv.server_address[1], timeout=30)
    c.request('POST', '/replay/api/list', json.dumps(q).encode(), {'Content-Type': 'application/json'}); r = c.getresponse()
    return json.loads(r.read() or b'{}')
ids = lambda j: sorted(x['id'][-2:] for x in j.get('items', []))
fails = []
def check(name, got, want):
    ok = got == want
    print('  %-70s %s' % (name, 'ok' if ok else 'FAIL: got %r, want %r' % (got, want)))
    if not ok: fails.append(name)

print('played')
j = lst(token='tok-me-0123456789abc', played=True)
check('my matches: by my profile id (111), not the one I only uploaded', (ids(j), j.get('total'), j.get('me_pid')), (['b1', 'b3'], 2, 111))
check('  ... relicstats asked for /steam/<my id>', asked[-1], '/steam/' + ME)
n = len(asked); lst(token='tok-me-0123456789abc', played=True)
check('  ... the id cached (relicstats not asked again)', len(asked), n)
check('another player: his matches', ids(lst(token='tok-other-0123456789', played=True)), ['b2', 'b3'])
check('with a filter: map and mode on top of it', ids(lst(token='tok-me-0123456789abc', played=True, map='2p_fen_dunloch')), ['b1'])
j = lst(token='tok-me-0123456789abc', played=True, n=1, page=1)
check('pages: total 2, the second page one item', (j['total'], len(j['items'])), (2, 1))
j = lst(token='tok-nobody-012345678', played=True)
check('a player Relic does not know: nothing, me_pid null', (ids(j), j.get('me_pid'), j.get('signed_in')), ([], None, True))
j = lst(played=True)
check('not signed in: nothing, signed_in false', (ids(j), j.get('signed_in')), ([], False))
print('the rest as before')
check('no "played": every replay, no me_pid', (ids(lst(token='tok-me-0123456789abc')), 'me_pid' in lst()), (['b1', 'b2', 'b3', 'b4'], False))
check('"mine" (my uploads) as before', ids(lst(token='tok-me-0123456789abc', mine=True)), ['b4'])
check('steam_pid: not a SteamID - no request', A.steam_pid('../etc'), None)
print('FAILED: %s' % ', '.join(fails) if fails else 'all ok')
shutil.rmtree(T, ignore_errors=True)
sys.exit(1 if fails else 0)
