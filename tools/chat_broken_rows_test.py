#!/usr/bin/env python3
# Test of "one broken chat row does not break the chat and the stream" on a TEST instance (own port, own data copy).
# usage (on rts, as root): ROWS=all python3 tools/chat_broken_rows_test.py <app dir> <free port, e.g. 18217>
# - copies community.sqlite / feedback.sqlite of the live ladder (sqlite backup API, read-only source) into a temp ROOT,
#   un-deletes message 799 there (BLOB text/t_ru/t_en, as it was written) and adds rows with other odd values;
# - starts <app dir>/ladder.py on <port> (LADDER_NO_CRAWL=1), checks c/msgs, c/stream, fb/thread, fb admin list;
# - prints PASS/FAIL per check, and the service's stdout lines about the broken rows.
import json, os, shutil, sqlite3, subprocess, sys, tempfile, time, urllib.request, socket

APP, PORT = sys.argv[1], int(sys.argv[2])
LIVE = '/srv/ladder/data'
T = tempfile.mkdtemp(prefix='ladder_t_')
os.makedirs(T + '/data'); shutil.copytree(APP, T + '/app', ignore=shutil.ignore_patterns('__pycache__', '*.bak*'))
for f in ('community.sqlite', 'feedback.sqlite'):
    src = sqlite3.connect('file:%s/%s?mode=ro' % (LIVE, f), uri=True); dst = sqlite3.connect(T + '/data/' + f)
    src.backup(dst); src.close(); dst.close()
for f in ('fb_mod.json', 'relays.json', 'relay_links.json', 'nm_maps.json', 'mm_block.txt'):
    if os.path.exists(LIVE + '/' + f): shutil.copy(LIVE + '/' + f, T + '/data/' + f)
open(T + '/data/fb_admin_token', 'w').write('testadmintoken0123456789abcdef00')
MODE = os.environ.get('ROWS', '799')
with sqlite3.connect(T + '/data/community.sqlite') as c:
    c.execute('UPDATE msg SET deleted=0 WHERE id=799')                       # the row as it was before the manual fix
    if MODE == 'all':                                                       # other odd values a direct write could leave
        mx = c.execute('SELECT max(id) FROM msg').fetchone()[0]
        c.execute("INSERT INTO msg(room, steam, text, ts, lang, t_ru, t_en, cid) VALUES('all','76561198028305259','ts null',NULL,'ru','a','a',NULL)")
        c.execute("INSERT INTO msg(room, steam, text, ts, lang, t_ru, t_en, cid) VALUES('all','76561198028305259','ts text','1793962836x','ru','a','a',NULL)")
        c.execute("INSERT INTO msg(room, steam, text, ts, lang, t_ru, t_en, cid) VALUES('all',76561198028305259,NULL,1793962836,NULL,NULL,NULL,NULL)")
        c.execute("INSERT INTO msg(room, steam, text, ts, lang, t_ru, t_en, cid) VALUES('all','76561198028305259',X'C328',1793962836,'ru',X'FF','x',7)")
        c.execute("INSERT INTO msg(room, steam, text, ts, lang, t_ru, t_en, cid) VALUES('all','76561198028305259','ok after',1793962836,'ru','ok','ok',NULL)")
        c.execute("UPDATE users SET name=CAST('pivolan' AS BLOB), avatar=NULL, avatar_ts=NULL, alias=5 WHERE steam='76561198021199732'")
open(T + '/data/ladder.sqlite', 'w').close()
env = dict(os.environ, LADDER_PORT=str(PORT), LADDER_NO_CRAWL='1', PYTHONUNBUFFERED='1', NM_LOBBY_STATUS='http://127.0.0.1:1')
log = open(T + '/out.log', 'w')
p = subprocess.Popen([sys.executable, T + '/app/ladder.py'], cwd=T, env=env, stdout=log, stderr=subprocess.STDOUT)
B = 'http://127.0.0.1:%d' % PORT
ok_all = True
def check(name, cond, info=''):
    global ok_all
    ok_all &= bool(cond); print('%s %s %s' % ('PASS' if cond else 'FAIL', name, info), flush=True)
def get(path):
    try:
        with urllib.request.urlopen(B + path, timeout=10) as r: return r.status, r.read()
    except urllib.error.HTTPError as e: return e.code, e.read()
def stream(after, secs=4):
    # raw socket: the events until the connection closes or secs pass
    s = socket.create_connection(('127.0.0.1', PORT), timeout=secs)
    s.sendall(('GET /ladder/api/c/stream?after=%s HTTP/1.1\r\nHost: x\r\n\r\n' % after).encode())
    buf = b''; t = time.time(); closed = False
    while time.time() - t < secs:
        try: d = s.recv(65536)
        except socket.timeout: break
        if not d: closed = True; break
        buf += d
    s.close()
    ev = [l[7:] for l in buf.decode('utf-8', 'replace').split('\n') if l.startswith('event: ')]
    return ev, closed, buf
try:
    for i in range(60):
        try:
            if get('/ladder/api/c/live')[0] == 200: break
        except Exception: pass
        time.sleep(0.5)
    st, b = get('/ladder/api/c/msgs?room=all&after=0&limit=120')
    ids = [m['id'] for m in json.loads(b)['msgs']] if st == 200 else []
    check('msgs all after=0 limit=120 -> 200', st == 200, '(%s, %d msgs, 799 in: %s)' % (st, len(ids), 799 in ids))
    if st == 200:
        m799 = [m for m in json.loads(b)['msgs'] if m['id'] == 799]
        check('  799 served as text or skipped', not m799 or isinstance(m799[0]['text'], str), m799 and repr(m799[0]['text'][:40]))
    for room in ('ru', 'en'):
        st, b = get('/ladder/api/c/msgs?room=%s&after=0&limit=120' % room); check('msgs %s -> 200' % room, st == 200, st)
    st, b = get('/ladder/api/c/msgs?room=all&after=790'); check('msgs after=790 -> 200', st == 200, st)
    st, b = get('/ladder/api/c/msgs?room=all&before=805&limit=20'); check('msgs before=805 -> 200', st == 200, st)
    ev, closed, raw = stream('all:700,ru:700,en:700')
    check('stream after=all:700 reaches online and stays open', 'online' in ev and not closed,
          '(events %d, msg %d, online %s, closed %s)' % (len(ev), ev.count('msg'), 'online' in ev, closed))
    check('  stream body has no HTTP status line inside', b'HTTP/1.0 500' not in raw.split(b'\r\n\r\n', 1)[-1])
    st, b = get('/ladder/api/fb/thread?uid=f75257bed4a3e8ebfaefbd35bb37935ad91a'); check('fb thread with BLOB dev reply -> 200', st == 200, st)
    req = urllib.request.Request(B + '/ladder/api/fb/admin', headers={'X-Admin': 'testadmintoken0123456789abcdef00'})
    st, b = get('/ladder/api/fb/admin?token=testadmintoken0123456789abcdef00'); check('fb admin list -> 200', st == 200, '%s %s' % (st, b[:80]))
    st, b = get('/ladder/api/fb/thread?uid=f75257bed4a3e8ebfaefbd35bb37935ad91a&after=x')   # a ValueError inside: a 500
    time.sleep(0.5); o = open(T + '/out.log').read()
    check('500 answer unchanged, traceback in the service output', st == 500 and b == b'{"error":"ValueError"}' and 'ladder: 500 GET /ladder/api/fb/thread Traceback' in o, st)
finally:
    p.terminate(); p.wait(10); log.close()
    out = open(T + '/out.log').read()
    print('--- service output (lines about broken rows / tracebacks):')
    print('\n'.join(l for l in out.splitlines() if 'msg' in l or 'Traceback' in l or 'Error' in l or 'error' in l)[:4000])
    if os.environ.get('KEEP') != '1': shutil.rmtree(T)
    print('RESULT', 'ALL PASS' if ok_all else 'SOME FAIL')
