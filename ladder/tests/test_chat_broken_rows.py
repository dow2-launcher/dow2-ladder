#!/usr/bin/env python3
# Which odd values in a msg row / users row break the chat history (c/msgs -> JSON) and the stream's missed messages,
# usage: python3 ladder/tests/test_chat_broken_rows.py [<app dir>, default: this ladder/]
# against the app in <app dir> (a temp copy with an empty community.sqlite; nothing live is touched).
# Then (fixed code only): a row whose build raises is skipped and logged, the others are served; the stream skips an
# event it cannot build and keeps the connection; LIVE() failing skips only the snapshot.
import io, json, os, shutil, sqlite3, sys, tempfile, threading, time, contextlib
APP = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = tempfile.mkdtemp(prefix='ladder_u_'); shutil.copytree(APP, T + '/app', ignore=shutil.ignore_patterns('__pycache__', '*.bak*'))
os.makedirs(T + '/data'); sys.path.insert(0, T + '/app')
import users; users.PROFILE_SECS = 10 ** 10                # no Steam fetches from the test
import community, stream
U = '76561198000000001'
CASES = [
    ('text BLOB (as #799)',      "INSERT INTO msg(room,steam,text,ts,lang,t_ru,t_en) VALUES('all',?,CAST('привет' AS BLOB),?, 'ru',CAST('привет' AS BLOB),CAST('hi' AS BLOB))"),
    ('ts NULL, not translated',  "INSERT INTO msg(room,steam,text,ts,lang,t_ru,t_en) VALUES('all',?,'x',NULL,NULL,NULL,NULL)"),
    ('ts text, not translated',  "INSERT INTO msg(room,steam,text,ts,lang,t_ru,t_en) VALUES('all',?,'x','17939x',NULL,NULL,NULL)"),
    ('ts NULL, translated',      "INSERT INTO msg(room,steam,text,ts,lang,t_ru,t_en) VALUES('all',?,'x',NULL,'ru','x','x')"),
    ('text NULL',                "INSERT INTO msg(room,steam,text,ts,lang,t_ru,t_en) VALUES('all',?,NULL,?,'ru','x','x')"),
    ('steam integer, cid int',   "INSERT INTO msg(room,steam,text,ts,lang,t_ru,t_en,cid) VALUES('all',CAST(? AS INTEGER),'x',?,'ru','x','x',7)"),
    ('invalid UTF-8 BLOB',       "INSERT INTO msg(room,steam,text,ts,lang,t_ru,t_en) VALUES('all',?,X'C328FF',?,'ru',X'FF','x')"),
]
def run(sql):
    with community.db() as c:
        c.execute('DELETE FROM msg')
        n = sql.count('?'); c.execute(sql, (U, int(time.time()) - 100)[:n])
    res = []
    for room in ('all', 'ru', 'en'):
        try: json.dumps(community.msgs(room, 0, 120)); res.append('%s ok' % room)
        except Exception as e: res.append('%s %s' % (room, type(e).__name__))
    try: [stream.frame(ev, d) for ev, d in community.missed('all:0')]; res.append('stream ok')
    except Exception as e: res.append('stream %s' % type(e).__name__)
    return res
print('== odd values in a msg row:')
for name, sql in CASES: print('  %-26s %s' % (name, ', '.join(run(sql))))
print('== odd values in the users row of the author (name BLOB, alias number, avatar NULL, avatar_ts NULL):')
with community.db() as c:
    c.execute('DELETE FROM msg'); c.execute("INSERT INTO msg(room,steam,text,ts,lang,t_ru,t_en) VALUES('all',?,'x',?,'ru','x','x')", (U, int(time.time())))
    c.execute("INSERT OR REPLACE INTO users(steam,name,avatar,avatar_ts,alias,banned) VALUES(?,CAST('nm' AS BLOB),NULL,NULL,5,NULL)", (U,))
users.USERS.clear(); users.load()
res = []
for room in ('all', 'ru'):
    try: json.dumps(community.msgs(room, 0, 120)); res.append('%s ok' % room)
    except Exception as e: res.append('%s %s' % (room, type(e).__name__))
try: json.dumps(community.online()); res.append('online ok')
except Exception as e: res.append('online %s' % type(e).__name__)
print('  ', ', '.join(res))

if hasattr(community, '_built'):
    print('== a row whose build raises (fixed code):')
    with community.db() as c:
        c.execute('DELETE FROM msg')
        for i in range(3): c.execute("INSERT INTO msg(room,steam,text,ts,lang,t_ru,t_en) VALUES('all',?,?,?,'ru','x','x')", (U, 'm%d' % i, int(time.time())))
    ids = [r[0] for r in community.db().execute('SELECT id FROM msg ORDER BY id')]
    orig = community._msg
    def bad(r, room=None, *a):                               # 13.11.2026: _msg takes the page's quotes too
        if r[0] == ids[1]: raise TypeError('forced for the test')
        return orig(r, room, *a)
    community._msg = bad
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        a = [m['id'] for m in community.msgs('all', 0, 120)['msgs']]; b = [d['id'] for ev, d in community.missed('all:0')]
        community.msgs('all', 0, 120)                         # the same broken row again: no second line within 10 min
    community._msg = orig
    lines = [l for l in out.getvalue().splitlines() if 'msg-skipped' in l]
    print('  msgs ids %s, missed ids %s (expected %s), log lines %d: %s' % (a, b, [ids[0], ids[2]], len(lines), lines[0][:160] if lines else ''))
    print('  PASS' if a == b == [ids[0], ids[2]] and len(lines) == 1 and 'Traceback' in lines[0] else '  FAIL')

    print('== the stream: an event it cannot build, LIVE() failing (fixed code):')
    import socket, http.server
    stream.LIVE = lambda: {'searching': [], 'ingame': [], 'launcher': [], 'users': {}}
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            if self.path == '/broken-live':
                old = stream.LIVE; stream.LIVE = lambda: 1 / 0
                try: stream.serve(self, '1', None, lambda: None, lambda: [('msg', {'id': 1, 'x': {1, 2}}), ('msg', {'id': 2})], lambda: None)
                finally: stream.LIVE = old
            else: stream.serve(self, '1', None, lambda: None, lambda: [('msg', {'id': 1, 'x': {1, 2}}), ('msg', {'id': 2})], lambda: None)
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    def read(path, then=None, secs=2.5):
        s = socket.create_connection(srv.server_address, timeout=0.2); s.sendall(('GET %s HTTP/1.1\r\nHost: x\r\n\r\n' % path).encode())
        buf = b''; t = time.time(); sent = False; closed = False
        while time.time() - t < secs:
            if then and not sent and time.time() - t > 0.5: then(); sent = True
            try: d = s.recv(65536)
            except socket.timeout: continue
            if not d: closed = True; break
            buf += d
        s.close(); return buf.decode('utf-8', 'replace'), closed
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        body, closed = read('/', then=lambda: (stream.publish('msg', {'id': 3, 'bad': object()}), stream.publish('msg', {'id': 4})))
        body2, closed2 = read('/broken-live')
    ok1 = '"id":2' in body and 'event: online' in body and '"id":4' in body and '"id":1' not in body and '"id":3' not in body and not closed
    ok2 = '"id":2' in body2 and 'event: online' not in body2 and not closed2
    print('  bad missed event skipped, online sent, bad live event skipped, next one delivered, open: %s' % ok1)
    print('  LIVE() raising: snapshot skipped, connection open: %s' % ok2)
    print('  log: ' + ' // '.join(l[:110] for l in out.getvalue().splitlines()))
    print('  PASS' if ok1 and ok2 else '  FAIL')
    srv.shutdown()
shutil.rmtree(T)
