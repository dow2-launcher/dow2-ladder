#!/usr/bin/env python3
"""Moscow lobby mirror (20.11.2026, the OOMs of 18-20.11): python3 gameserver/tests/test_tcp_mirror.py [path/to/tcp_mirror.py]
Runs the mirror of this checkout on random local ports in front of three test upstreams (echo, the 64 KB stream check, an endless
stream) with short timings (stall 2 s, stats every 1 s) and checks:
- bytes pass whole both ways (2 MB echo, 64 KB stream check + EOF, half close each way);
- a client that never reads behind the endless stream: the mirror stays responsive (an echo answers within 0.5 s the whole time),
  closes that connection after the stall time, and its rss stays small - the old read loop spun here (ETIMEDOUT re-raised by the
  StreamReader and taken for its own poll timeout: 1.8 GB in 2 minutes, every other connection frozen);
- per address and port at most MIRROR_PER_KEY: the 4th and 5th connection from one address close the two oldest (EOF on them),
  the newest three still work, and a LIMIT line names the address;
- 300 connect/close cycles leave no connection behind (active 0 in the stats line)."""
import os, re, socket, subprocess, sys, threading, time
HERE = os.path.dirname(os.path.abspath(__file__))
MIRROR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'egress', 'tcp_mirror.py')
DATA = os.urandom(65536)
fails = []


def check(name, ok, info=''):
    print('  %-78s %s' % (name, 'ok' if ok else 'FAIL %s' % info), flush=True)
    if not ok: fails.append(name)


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p


def upstream(handler):
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(('127.0.0.1', 0)); s.listen(128)
    def one(c):
        try: handler(c)
        except OSError: pass
        finally: c.close()
    def loop():
        while True:
            c, _ = s.accept(); threading.Thread(target=one, args=(c,), daemon=True).start()
    threading.Thread(target=loop, daemon=True).start()
    return s.getsockname()[1]


def echo(c):
    while True:
        b = c.recv(65536)
        if not b: c.shutdown(socket.SHUT_WR); c.recv(1); return
        c.sendall(b)


def probe(c): c.sendall(DATA)


def flood(c):
    while True: c.sendall(DATA)


def conn(port, src='127.0.0.1', rcvbuf=None):
    s = socket.socket()
    if rcvbuf: s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf)
    s.bind((src, 0)); s.settimeout(5); s.connect(('127.0.0.1', port)); return s


def recv_all(s):
    out = bytearray()
    while True:
        b = s.recv(65536)
        if not b: return bytes(out)
        out += b


def ping(port, src='127.0.0.2'):
    s = conn(port, src); t = time.monotonic(); s.sendall(b'ping'); b = s.recv(16); s.close()
    return b == b'ping', time.monotonic() - t


def main():
    ue, up, uf = upstream(echo), upstream(probe), upstream(flood)
    me, mp, mf = free_port(), free_port(), free_port()
    env = dict(os.environ, MIRROR_STALL='2', MIRROR_STATS='1', MIRROR_HALF='3', MIRROR_PER_KEY='%d:3,%d:2,%d:3' % (me, mp, mf))
    proc = subprocess.Popen([sys.executable, MIRROR, '127.0.0.1:%d=127.0.0.1:%d' % (me, ue), '127.0.0.1:%d=127.0.0.1:%d' % (mp, up),
                             '127.0.0.1:%d=127.0.0.1:%d' % (mf, uf)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = []
    threading.Thread(target=lambda: [out.append(l) for l in proc.stdout], daemon=True).start()
    time.sleep(1)
    rss = lambda: int(open('/proc/%d/statm' % proc.pid).read().split()[1]) * os.sysconf('SC_PAGE_SIZE') // (1 << 20)
    try:
        print('mirror', MIRROR)
        # bytes pass whole
        s = conn(mp); got = recv_all(s); s.close()
        check('stream check: 64 KB whole, then EOF', got == DATA, len(got))
        s = conn(me); data = os.urandom(2 << 20); got = bytearray()
        t = threading.Thread(target=lambda: got.extend(recv_all(s))); t.start(); s.sendall(data); s.shutdown(socket.SHUT_WR); t.join()
        check('echo 2 MB whole, client half close passes, EOF back', bytes(got) == data, len(got)); s.close()

        # a client that never reads behind an endless stream
        r0 = rss()
        slow = conn(mf, '127.0.0.3', rcvbuf=4096)
        worst, bad, t0, closed_at = 0.0, 0, time.monotonic(), None
        slow.settimeout(0.05)
        while time.monotonic() - t0 < 7:
            ok, dt = ping(me); worst = max(worst, dt); bad += not ok
            time.sleep(0.2)
        # it must be closed now: read what is buffered until EOF / reset
        slow.settimeout(2); end = None
        try:
            while True:
                b = slow.recv(1 << 20)
                if not b: end = 'eof'; break
        except ConnectionResetError: end = 'reset'
        except socket.timeout: end = 'still open'
        slow.close()
        check('non-reading client: echo stays answered (worst %.3f s)' % worst, bad == 0 and worst < 0.5, (bad, worst))
        check('non-reading client: closed after the stall time', end in ('eof', 'reset'), end)
        check('non-reading client: rss %d -> %d MB' % (r0, rss()), rss() - r0 < 20)

        # per address + port limit: 5 from one address, the oldest two are closed
        ss = [conn(me, '127.0.0.4') for _ in range(5)]
        time.sleep(0.5)
        res = []
        for s in ss:
            try: s.sendall(b'x'); s.settimeout(1); res.append(s.recv(4) == b'x')
            except OSError: res.append(False)
        for s in ss: s.close()
        check('limit 3 per address+port: the 2 oldest closed, the newest 3 work', res == [False, False, True, True, True], res)
        time.sleep(0.3)
        check('LIMIT line names the address', any('LIMIT 127.0.0.4 port %d' % me in l for l in out))

        # churn: nothing left behind
        for i in range(300):
            s = conn(me, '127.0.1.%d' % (i % 250 + 1)); s.sendall(b'hi'); s.recv(2); s.close()
        time.sleep(4)
        last = [l for l in out if ' active ' in l][-1]
        n = int(re.search(r'active (\d+)', last).group(1))
        check('300 connect/close: active 0 afterwards (%s)' % last.split(', top')[0].split(' ', 1)[1], n == 0, last)
    finally:
        proc.terminate(); proc.wait(5)
    print('FAILED: %s' % fails if fails else 'all ok')
    sys.exit(1 if fails else 0)


main()
