#!/usr/bin/env python3
"""e2e on a COPY of the ladder (temp dir, own port, LADDER_NO_CRAWL): the launcher rooms in the Online block (06.11.2026, owner: "I made
a room in the launcher and the Online list on the main page does not show it - nobody in the chat sees that someone made a game").
 1. an anonymous stream (as a launcher that is not signed in) gets the snapshot with "lrooms": [] and every room event
 2. A creates a room -> "lroom" on the stream; c/live and lroom/list carry it with its owner (steam), mode, game, players 1/2;
    the owner's card is in c/live users
 3. B joins -> "lroom" with two players; c/live: 2/2
 4. both leave -> "lroom_gone"; c/live: no rooms
usage: python3 e2e_lroom_live.py <ladder app dir>"""
import json, os, queue, random, shutil, socket, sqlite3, subprocess, sys, tempfile, threading, time, urllib.request
APP = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = tempfile.mkdtemp(prefix='lrlive_e2e_'); shutil.copytree(APP, T + '/app', ignore=shutil.ignore_patterns('__pycache__', '*.bak*', 'tests'))
os.makedirs(T + '/data')
A, B = '76561190000000201', '76561190000000202'
def free():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p
port = free()
env = dict(os.environ, LADDER_PORT=str(port), LADDER_NO_CRAWL='1')
log = open(T + '/ladder.log', 'w')
srv = subprocess.Popen([sys.executable, T + '/app/ladder.py'], env=env, stdout=log, stderr=subprocess.STDOUT, cwd=T + '/app')
def call(path, body=None):
    req = urllib.request.Request('http://127.0.0.1:%d/ladder/api/%s' % (port, path), data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return json.load(r)
    except urllib.error.HTTPError as e: return {'http': e.code}
for i in range(60):
    try: call('mm/status'); break
    except Exception: time.sleep(0.5)
TOK = '%016x' % random.getrandbits(64)
with sqlite3.connect(T + '/data/community.sqlite') as c:     # the test copy's own db: a session per player
    c.execute('CREATE TABLE IF NOT EXISTS sess (token TEXT PRIMARY KEY, steam TEXT, ts INTEGER)')
    c.execute('INSERT OR REPLACE INTO sess VALUES(?,?,?)', ('tokA' + TOK, A, int(time.time())))
    c.execute('INSERT OR REPLACE INTO sess VALUES(?,?,?)', ('tokB' + TOK, B, int(time.time())))
TA, TB = 'tokA' + TOK, 'tokB' + TOK
EV = queue.Queue()
def listen():   # the stream as an anonymous launcher: (event, data) into EV
    r = urllib.request.urlopen('http://127.0.0.1:%d/ladder/api/c/stream?after=all:0' % port, timeout=60)
    ev = None
    for line in r:
        line = line.decode('utf-8').rstrip('\n')
        if line.startswith('event: '): ev = line[7:]
        elif line.startswith('data: ') and ev: EV.put((ev, json.loads(line[6:]))); ev = None
threading.Thread(target=listen, daemon=True).start()
def wait(name, cond=lambda d: True, secs=8):
    end = time.time() + secs
    while time.time() < end:
        try: ev, d = EV.get(timeout=max(0.1, end - time.time()))
        except queue.Empty: break
        if ev == name and cond(d): return d
    return None
fails = []
def check(name, ok, info=''):
    print('%-4s %s %s' % ('ok' if ok else 'FAIL', name, info if not ok or os.environ.get('V') else '')); ok or fails.append(name)
try:
    print('== 1. the snapshot')
    snap = wait('online')
    check('the stream snapshot has lrooms (empty)', snap is not None and snap.get('lrooms') == [], snap)
    check('c/live has lrooms (empty)', call('c/live').get('lrooms') == [], '')
    print('== 2. A creates a room')
    cr = call('lroom/create', {'token': TA, 'mode': '1v1', 'name': 'e2e room', 'game': 'elite', 'ver': '3.2'}); rid = (cr.get('room') or {}).get('id')
    check('created', cr.get('ok') and rid, cr)
    d = wait('lroom', lambda d: d.get('id') == rid)
    check('"lroom" on the anonymous stream', d is not None and d.get('owner') == A and d.get('mode') == '1v1', d)
    lv = call('c/live'); rs = lv.get('lrooms') or []
    x = rs[0] if rs else {}
    check('c/live: the room', len(rs) == 1 and x.get('id') == rid and x.get('owner') == A and x.get('name') == 'e2e room' and x.get('game') == 'elite'
          and x.get('mode') == '1v1' and x.get('players') == 1 and x.get('cap') == 2 and x.get('state') == 'lobby', rs)
    check('c/live: the owner\'s card in users', A in (lv.get('users') or {}), list((lv.get('users') or {}).keys()))
    ls = (call('lroom/list').get('rooms') or [{}])[0]
    check('lroom/list: the owner\'s steam too', ls.get('owner') == A and ls.get('owner_name'), ls)
    print('== 3. B joins')
    jr = call('lroom/join', {'token': TB, 'id': rid})
    d = wait('lroom', lambda d: d.get('id') == rid and len([s for s in d.get('slots') or [] if s]) == 2)
    check('joined, "lroom" with two players', jr.get('ok') and d is not None, jr)
    x = (call('c/live').get('lrooms') or [{}])[0]
    check('c/live: 2/2', x.get('players') == 2 and x.get('cap') == 2 and x.get('owner') == A, x)
    print('== 4. both leave')
    call('lroom/leave', {'token': TB}); call('lroom/leave', {'token': TA})
    d = wait('lroom_gone', lambda d: d.get('id') == rid)
    check('"lroom_gone" on the stream', d is not None, d)
    check('c/live: no rooms', call('c/live').get('lrooms') == [], '')
    check('the stream is alive (no "skipped" in the log)', 'stream: skipped' not in open(T + '/ladder.log').read(), '')
finally:
    srv.terminate(); srv.wait(10); log.close()
    if fails: print(open(T + '/ladder.log').read()[-3000:])
    shutil.rmtree(T, ignore_errors=True)
print('FAILED: %s' % fails if fails else 'ALL OK')
sys.exit(1 if fails else 0)
