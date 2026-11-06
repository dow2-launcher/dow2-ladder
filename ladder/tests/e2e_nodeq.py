#!/usr/bin/env python3
"""e2e on a COPY of the ladder (temp dir, own port, LADDER_NO_CRAWL, fake own_lobby status): synthetic measurements through the
HTTP API only. Player A has a bad Poland (2 launcher runs, 35-38 % losses); B is fine everywhere.
 1. nq/test x2 -> nq/marks: Poland avoided for A (the mark text data), B none
 2. classic mm/join A + B with Relay pings (Poland best for both) -> the match on Germany, not Poland
 3. native: mm/native hints + nm/join -> the native match's relay Germany
 4. B reaches only Poland (Germany cut on his side) + chains: native -> Germany with B chained through Poland
 5. a launcher room A + B (lroom API): net.pick Germany, A's row carries the Poland mark
 6. A presses "use it anyway" (nq/force) -> classic match on Poland again; undo -> Germany
 7. the collector's nq/match: refused without the token / through nginx headers; with it a bad match of B on Germany x2 -> B
    avoids Germany too -> classic A vs B: nothing good for both -> the marks ignored (the match still happens)
usage: python3 e2e_nodeq.py <ladder app dir> <live data dir to copy relays.json / relay_links.json from>"""
import json, os, random, shutil, socket, sqlite3, subprocess, sys, tempfile, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
APP, LIVE = sys.argv[1], sys.argv[2]
T = tempfile.mkdtemp(prefix='nq_e2e_'); shutil.copytree(APP, T + '/app', ignore=shutil.ignore_patterns('__pycache__', '*.bak*', 'tests'))
os.makedirs(T + '/data')
for f in ('relays.json', 'relay_links.json'): shutil.copy(LIVE + '/' + f, T + '/data/' + f)
TOK = '%032x' % random.getrandbits(128); open(T + '/data/nm_token', 'w').write(TOK)
PL, DE, MSK, MSK2 = '15.220.68.107', '116.202.106.150', '83.217.192.34', '91.107.122.186'
A, B = '76561190000000101', '76561190000000102'
def free():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p
class Lobby(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        b = b'{"native": true, "here": true}'; self.send_response(200); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
lp = free(); threading.Thread(target=HTTPServer(('127.0.0.1', lp), Lobby).serve_forever, daemon=True).start()
port = free()
env = dict(os.environ, LADDER_PORT=str(port), LADDER_NO_CRAWL='1', NM_LOBBY_STATUS='http://127.0.0.1:%d' % lp)
log = open(T + '/ladder.log', 'w')
srv = subprocess.Popen([sys.executable, T + '/app/ladder.py'], env=env, stdout=log, stderr=subprocess.STDOUT, cwd=T + '/app')
def call(path, body=None, headers=None):
    req = urllib.request.Request('http://127.0.0.1:%d/ladder/api/%s' % (port, path), data=json.dumps(body).encode() if body is not None else None,
                                 headers=dict({'Content-Type': 'application/json'}, **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return json.load(r)
    except urllib.error.HTTPError as e: return {'http': e.code}
for i in range(60):
    try: call('mm/status'); break
    except Exception: time.sleep(0.5)
with sqlite3.connect(T + '/data/community.sqlite') as c:     # the test copy's own db: a session per player
    c.execute('CREATE TABLE IF NOT EXISTS sess (token TEXT PRIMARY KEY, steam TEXT, ts INTEGER)')
    c.execute('INSERT OR REPLACE INTO sess VALUES(?,?,?)', ('tokA' + TOK[:8], A, int(time.time())))
    c.execute('INSERT OR REPLACE INTO sess VALUES(?,?,?)', ('tokB' + TOK[:8], B, int(time.time())))
TA, TB = 'tokA' + TOK[:8], 'tokB' + TOK[:8]
fails = []
def check(name, ok, info=''):
    print('%-4s %s %s' % ('ok' if ok else 'FAIL', name, info if not ok or os.environ.get('V') else '')); ok or fails.append(name)
def node(ip, **k):
    r = dict(ip=ip, transport='udp', verdict='excellent', why=[], med=30, loss_up=0.4, loss_down=0, stall_ms=None, max_gap_ms=110, cut=False, secs=60); r.update(k); return r
def run(tok, ts, nodes): return call('nq/test', {'token': tok, 'v': 1, 'ts': ts, 'mode': '1v1', 'vpn': False, 'launcher': '1.4.23', 'nodes': nodes})
try:
    now = time.time()
    print('== 1. two connection checks of A with a bad Poland')
    r1 = run(TA, now - 600, [node(PL, verdict='down', why=['cut', 'stall', 'loss_up'], loss_up=35, stall_ms=24000, cut=True), node(DE), node(MSK, med=70)])
    check('nq/test answers with the marks (one bad run: none yet)', r1.get('ok') and r1.get('marks') == {}, r1)
    r2 = run(TA, now - 60, [node(PL, verdict='laggy', why=['loss_up'], loss_up=38), node(DE), node(MSK, med=70)])
    m = (r2.get('marks') or {}).get(PL) or {}
    check('second bad run: Poland avoided for A', m.get('avoid') is True and m.get('loss') == 38.0 and m.get('why') == ['loss'], r2)
    check('nq/marks of B: none', call('nq/marks', {'token': TB}).get('marks') == {}, '')
    check('nq/marks without a session: auth', call('nq/marks', {'token': 'nope'}).get('error') == 'auth', '')
    run(TB, now - 60, [node(PL, med=32), node(DE, med=40), node(MSK, med=55)])

    print('== 2. classic automatch (Relay pings: Poland best for both)')
    def classic(pa, pb):
        call('mm/leave', {'steam': A}); call('mm/leave', {'steam': B})
        call('mm/join', {'steam': A, 'mode': '1v1', 'own_server': True, 'relay_ping': pa, 'game': 'elite-3.2'})
        call('mm/join', {'steam': B, 'mode': '1v1', 'own_server': True, 'relay_ping': pb, 'game': 'elite-3.2'})
        a = call('mm/poll', {'steam': A}); return a.get('relay_host'), a.get('state')
    PA = {PL: 30, DE: 36, MSK: 70, MSK2: 75}; PB = {PL: 32, DE: 40, MSK: 55, MSK2: 60}
    got = classic(PA, PB)
    check('A vs B -> Germany (not Poland)', got == (DE, 'matched'), got)

    print('== 3. native automatch (mm/native hints + nm/join)')
    def native(pa, pb):
        for s in (A, B): call('nm/leave', {'steam': s}, {'X-NM-Token': TOK}); call('mm/leave', {'steam': s})
        out = None
        for s, p in ((A, pa), (B, pb)):
            h = call('mm/native', {'steam': s, 'mode': '1v1', 'relay_ping': p})
            if not h.get('native'): return 'mm/native: %r' % h
            out = call('nm/join', {'steam': s, 'mode': '1v1', 'game': 'elite', 'race': 0, 'key': 'e2e'}, {'X-NM-Token': TOK})
        return out.get('relay'), out.get('state')
    chain = {'0.0.0.22': 22}
    got = native(dict(PA, **chain), dict(PB, **chain))
    check('native A vs B -> Germany', got == (DE, 'matched'), got)
    print('== 4. B reaches only Poland (Germany and Moscow cut on his side), both chain')
    got = native(dict(PA, **chain), dict({PL: 32, DE: -1, MSK: -1, MSK2: -1}, **chain))
    check('native -> Germany, B chained through Poland', got == (DE, 'matched'), got)
    lg = open(T + '/ladder.log').read()
    check('the ladder log says it took Germany instead of Poland', "node quality - '116.202.106.150' instead of '15.220.68.107'" in lg, '')
    for s in (A, B): call('nm/leave', {'steam': s}, {'X-NM-Token': TOK})

    print('== 5. a launcher room A + B')
    cr = call('lroom/create', {'token': TA, 'mode': '1v1', 'name': 'e2e'}); rid = (cr.get('room') or {}).get('id')
    jr = call('lroom/join', {'token': TB, 'id': rid})
    call('lroom/pings', {'token': TA, 'pings': PA, 'chain': True}); call('lroom/pings', {'token': TB, 'pings': PB, 'chain': True}); v = call('lroom/get', {'token': TA})
    net = ((v.get('room') or {}).get('net')) or {}
    rows = {r['steam']: r for r in net.get('rows', [])}
    check('room: the match would go to Germany', (net.get('pick'), net.get('nq_ignored')) == (DE, False), {k: net.get(k) for k in ('pick', 'worst', 'why', 'nq_ignored')})
    check("room: A's row carries the Poland mark, B's none", list((rows.get(A) or {}).get('nq', {})) == [PL] and (rows.get(B) or {}).get('nq') == {}, rows)
    call('lroom/leave', {'token': TB}); call('lroom/leave', {'token': TA})

    print('== 6. "use it anyway" (24 h) and undo')
    f = call('nq/force', {'token': TA, 'ip': PL, 'on': True})
    check('force: the mark stays shown, not avoided', ((f.get('marks') or {}).get(PL) or {}).get('avoid') is False and 'forced_until' in f['marks'][PL], f)
    got = classic(PA, PB); check('classic A vs B -> Poland again', got == (PL, 'matched'), got)
    call('nq/force', {'token': TA, 'ip': PL, 'on': False})
    got = classic(PA, PB); check('undo -> Germany', got == (DE, 'matched'), got)
    check('force of an unknown node refused', call('nq/force', {'token': TA, 'ip': '1.2.3.4', 'on': True}).get('error') == 'node', '')

    print("== 7. the collector's real matches")
    ms = [dict(steam=B, ip=DE, t=time.time() - 10 + i, ref='e2e:%d' % i, rx=5000, tx=5000, resent=1900, lost_in=3, filled=2, solo_stalls=0, dead=False) for i in range(2)]
    check('nq/match without the token: 403', call('nq/match', {'samples': ms}).get('http') == 403, '')
    check('nq/match through nginx (X-Real-IP): 403', call('nq/match', {'samples': ms}, {'X-NM-Token': TOK, 'X-Real-IP': '1.2.3.4'}).get('http') == 403, '')
    a = call('nq/match', {'samples': ms}, {'X-NM-Token': TOK})
    check('nq/match with the token: 2 new', a.get('added') == 2, a)
    check('the same lines again: 0 new', call('nq/match', {'samples': ms}, {'X-NM-Token': TOK}).get('added') == 0, '')
    mb = call('nq/marks', {'token': TB}).get('marks') or {}
    check('B: Germany avoided now (losses 38 % in a match)', (mb.get(DE) or {}).get('avoid') is True and mb[DE].get('src') == 'match', mb)
    got = classic({PL: 30, DE: 36, MSK: -1, MSK2: -1}, {PL: 32, DE: 40, MSK: -1, MSK2: -1})
    check('A (bad PL) vs B (bad DE), nothing else: the marks ignored, the match still on our node', got[1] == 'matched' and got[0] in (PL, DE), got)
    got = classic(PA, PB)
    check('A (bad PL) vs B (bad DE) with Moscow good for both -> Moscow', got == (MSK, 'matched'), got)
finally:
    srv.terminate(); srv.wait(10); log.close()
    if fails: print(open(T + '/ladder.log').read()[-3000:])
    shutil.rmtree(T, ignore_errors=True)
print('FAILED: %s' % fails if fails else 'ALL OK')
sys.exit(1 if fails else 0)
