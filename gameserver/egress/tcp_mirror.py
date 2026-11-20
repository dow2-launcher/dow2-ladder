#!/usr/bin/env python3
"""tcp_mirror.py - a plain TCP forwarder: the Moscow mirror of our lobby server (03.11.2026).
Players in Russia reach Moscow fine, but their streams to Europe stop after ~33 KB (DPI); server to server is not cut.
OwnLobby.dll 2 tries this mirror first. Bytes are passed as they are (TLS end to end: the mirror sees nothing).
  tcp_mirror.py LISTEN_HOST:PORT=TARGET:PORT [...]     e.g. 83.217.192.34:47443=37.27.234.236:47443

20.11.2026 - rewritten after the OOMs of 18-20.11 (rss 21 -> 250 MB within seconds, the whole mirror frozen for minutes).
The cause was NOT many connections: the old read loop was
    try: b = await asyncio.wait_for(r.read(65536), 10)
    except asyncio.TimeoutError: (idle check) continue
and since Python 3.11 asyncio.TimeoutError IS the builtin TimeoutError = OSError(ETIMEDOUT). When a peer's socket died by the
keepalive / TCP_USER_TIMEOUT (a player who stopped reading, a dead NAT), the StreamReader kept that ETIMEDOUT and raised the SAME
exception object at once on every read; the loop took it for its own 10 s poll timeout and spun without ever yielding to the event
loop (every other connection frozen, no stats line), ~200 000 times a second, each raise adding frames to that one exception's
traceback and leaving a cancelled timer in the loop: +15 MB/s until the idle check (120 s) or the OOM killer ended it.
Reproduced locally: one client that never reads behind an upstream that streams -> 1.8 GB in 2 minutes with the old code.

Now (no read loops, no wait_for at all): asyncio Protocols - data_received() writes straight into the other side's transport, and
when that one's buffer passes HIGH the source stops reading (pause_reading) until it drains (back pressure, like the kernel does).
Any error, EOF of both sides, or a side that sat paused for STALL_S, or nothing either way for IDLE s -> both sides closed, and a
side still closing after CLOSE_S is aborted. Memory per connection is bounded: HIGH + one recv (<=256 KB) per direction.
Limits (owner 20.11: "one connection per user"): measured on timeweb (journal 17-20.11, 6229 stats lines, and ss samples) one game
holds 2 connections to 47443 (the readSession long poll + calls, each ~1 min, own_lobby closes idle ones at 55 s) - 3 for a moment
when it reconnects, 4 seen once (a Cloudflare WARP address shared by players) - and 1 short one to 47445 (the 64 KB stream check).
So per client address AND listen port at most PER_KEY (47443: 3, 47445: 2; SHARED_MULT times that for SHARED prefixes such as WARP
104.28.*): a new connection over it closes the OLDEST of that address+port (a reconnecting game has abandoned it) and the event is
logged (once per 10 s per address, with counts), so a client opening connections in a loop shows up by name. Total MAX_CONN: when
full, the connection idle the longest is closed for the new one."""
import asyncio, os, socket, sys, time

MAX_CONN = int(os.environ.get('MIRROR_MAX_CONN', '400'))
PER_KEY = {int(k): int(v) for k, v in (x.split(':') for x in os.environ.get('MIRROR_PER_KEY', '47443:3,47445:2').split(',') if x)}
PER_KEY_DEFAULT = int(os.environ.get('MIRROR_PER_KEY_DEFAULT', '3'))
SHARED = tuple(x for x in os.environ.get('MIRROR_SHARED', '104.28.').split(',') if x)   # address prefixes shared by players
SHARED_MULT = int(os.environ.get('MIRROR_SHARED_MULT', '4'))
IDLE = float(os.environ.get('MIRROR_IDLE', '120'))     # s without a byte either way
HIGH = 64 * 1024                                     # unsent bytes on one side before its source stops reading
STALL_S = float(os.environ.get('MIRROR_STALL', '30'))   # s a side may stay over HIGH (peer not reading) before both are closed
HALF_S = float(os.environ.get('MIRROR_HALF', '15'))     # s a connection may stay half closed (one side sent FIN) before full close
CLOSE_S = 5                                          # s a closing side may flush; then aborted
CONNECT_S = 5
STATS_S = float(os.environ.get('MIRROR_STATS', '30'))
conns = set()
by_key = {}                                          # (ip, listen port) -> [Pair] oldest first
counters = dict(accepted=0, replaced=0, evicted=0, refused=0, idle=0, stalled=0, upfail=0)
cap_log = {}                                         # ip -> [replaced since last line, last line time]


def log(s): print(time.strftime('%H:%M:%S'), s, flush=True)


def keepalive(sock):
    if sock is None: return
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 20)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 5)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT, 30000)
    except (OSError, AttributeError): pass


def per_key_limit(ip, port):
    n = PER_KEY.get(port, PER_KEY_DEFAULT)
    return n * SHARED_MULT if ip.startswith(SHARED) else n


class Side(asyncio.Protocol):
    """one socket of a pair; what it receives goes to the other side's transport"""

    def __init__(self, pair, name):
        self.pair, self.name, self.tr = pair, name, None
        self.eof = False; self.paused_at = None; self.closing_at = None; self.tr_lost = False

    def connection_made(self, tr):
        self.tr = tr
        tr.set_write_buffer_limits(high=HIGH)
        keepalive(tr.get_extra_info('socket'))

    def data_received(self, data):
        p = self.pair; p.seen = time.monotonic()
        o = p.other(self)
        if o.tr is None:                                         # the upstream is still connecting: hold it (bounded)
            if p.closed: return
            p.pending.append(data); p.pending_n += len(data)
            if p.pending_n > HIGH:
                try: self.tr.pause_reading()
                except (RuntimeError, AttributeError): pass
            return
        if o.tr.is_closing(): return                             # the other side is gone: drop (close follows)
        o.tr.write(data)

    def eof_received(self):
        self.eof = True; p = self.pair
        o = p.other(self)
        if o.tr is None:                                         # FIN before the upstream is there: passed on after connect
            if p.closed: return False
            p.pending_eof = True; return True
        if p.half_at is None: p.half_at = time.monotonic()
        if o.eof: p.close('eof'); return False
        try: o.tr.write_eof()                                    # pass the FIN on after the pending bytes
        except (OSError, RuntimeError, AttributeError): p.close('eof'); return False
        return True                                              # keep reading the other way until it ends too

    def pause_writing(self):                                     # our unsent buffer passed HIGH: stop the source
        self.paused_at = time.monotonic()
        o = self.pair.other(self)
        if o.tr is not None and not o.tr.is_closing():
            try: o.tr.pause_reading()
            except (RuntimeError, AttributeError): pass

    def resume_writing(self):
        self.paused_at = None
        o = self.pair.other(self)
        if o.tr is not None and not o.tr.is_closing():
            try: o.tr.resume_reading()
            except (RuntimeError, AttributeError): pass

    def connection_lost(self, exc):
        self.tr_lost = True
        self.pair.close('lost' if exc is None else type(exc).__name__, lost=self)


class Pair:
    def __init__(self, ip, port, th, tp, client):
        self.ip, self.port, self.th, self.tp = ip, port, th, tp
        self.c = client; self.u = Side(self, 'up'); self.task = None
        self.t0 = self.seen = time.monotonic(); self.half_at = None; self.closed = False; self.why = None
        self.pending = []; self.pending_n = 0; self.pending_eof = False   # client bytes before the upstream connected

    def other(self, s): return self.u if s is self.c else self.c

    def register(self):
        conns.add(self); by_key.setdefault((self.ip, self.port), []).append(self)

    def unregister(self):
        conns.discard(self)
        lst = by_key.get((self.ip, self.port))
        if lst is not None:
            try: lst.remove(self)
            except ValueError: pass
            if not lst: by_key.pop((self.ip, self.port), None)

    async def connect_up(self):
        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(loop.create_connection(lambda: self.u, self.th, self.tp), CONNECT_S)
        except (OSError, asyncio.TimeoutError) as e:             # (any error of the connect only - nothing loops here)
            counters['upfail'] += 1
            log('to %s:%d: %r' % (self.th, self.tp, e)); self.close('upfail'); return
        except asyncio.CancelledError:
            self.close('cancelled'); raise
        if self.closed:
            if self.u.tr is not None: self.u.tr.abort()
            return
        if self.pending:
            self.u.tr.write(b''.join(self.pending)); self.pending = []; self.pending_n = 0
        if self.pending_eof:
            self.half_at = time.monotonic()
            try: self.u.tr.write_eof()
            except (OSError, RuntimeError): self.close('eof')
            return
        try: self.c.tr.resume_reading()                          # the client was held until the upstream was there
        except (RuntimeError, AttributeError): pass

    def close(self, why, lost=None):
        if self.closed: return
        self.closed = True; self.why = why
        self.unregister()
        t = self.task
        if t is not None and not t.done() and t is not asyncio.current_task(): t.cancel()   # still connecting upstream
        now = time.monotonic()
        for s in (self.c, self.u):
            if s.tr is None or s is lost: continue
            s.closing_at = now
            try: s.tr.close()                                    # flushes what is buffered, then FIN
            except Exception:
                try: s.tr.abort()
                except Exception: pass
        CLOSING.add(self)


CLOSING = set()   # closed pairs whose transports may still be flushing; aborted after CLOSE_S


def server_factory(th, tp, lport):
    def factory():
        return Accept(th, tp, lport)
    return factory


class Accept(Side):
    """the client side; builds its Pair on connection_made (the address is known only then)"""

    def __init__(self, th, tp, lport):
        self.th, self.tp, self.lport = th, tp, lport
        Side.__init__(self, None, 'client')

    def connection_made(self, tr):
        peer = tr.get_extra_info('peername') or ('?', 0)
        ip = peer[0]
        p = Pair(ip, self.lport, self.th, self.tp, self); self.pair = p
        Side.connection_made(self, tr)
        counters['accepted'] += 1
        tr.pause_reading()                                       # until the upstream is connected
        lst = by_key.get((ip, self.lport), [])
        lim = per_key_limit(ip, self.lport)
        while len(lst) >= lim:                                   # over the per address+port limit: the oldest goes
            old = lst[0]; age = time.monotonic() - old.t0
            old.close('replaced'); counters['replaced'] += 1
            c = cap_log.setdefault(ip, [0, 0.0, 0.0]); c[0] += 1; c[2] = max(c[2], age)
            if time.time() - c[1] >= 10:
                log('LIMIT %s port %d: %d connections already (limit %d) - closed the oldest; %d replaced from it since the last'
                    ' such line, oldest %.0f s old' % (ip, self.lport, lim, lim, c[0], c[2]))
                c[0] = 0; c[1] = time.time(); c[2] = 0.0
            lst = by_key.get((ip, self.lport), [])
        if len(conns) >= MAX_CONN:                               # total cap: the one idle the longest goes
            victim = min(conns, key=lambda x: x.seen)
            victim.close('evicted'); counters['evicted'] += 1
            log('FULL %d connections: closed %s port %d idle %.0f s' % (MAX_CONN, victim.ip, victim.port, time.monotonic() - victim.seen))
        p.register()
        p.task = asyncio.ensure_future(p.connect_up())


async def sweeper():
    """idle, stalled (peer not reading) and half closed connections; transports still closing after CLOSE_S"""
    while True:
        await asyncio.sleep(1)
        now = time.monotonic()
        for p in list(conns):
            if now - p.seen > IDLE: counters['idle'] += 1; p.close('idle'); continue
            if any(s.paused_at is not None and now - s.paused_at > STALL_S for s in (p.c, p.u)):
                counters['stalled'] += 1; p.close('stalled'); continue
            if p.half_at is not None and now - p.half_at > HALF_S: p.close('half')
        for p in list(CLOSING):
            done = True
            for s in (p.c, p.u):
                tr = s.tr
                if tr is None or getattr(s, 'tr_lost', False): continue
                if s.closing_at is not None and now - s.closing_at > CLOSE_S:
                    try: tr.abort()
                    except Exception: pass
                    s.tr_lost = True
                else: done = False
            if done: CLOSING.discard(p)


def rss_mb():
    try:
        with open('/proc/self/statm') as f: return int(f.read().split()[1]) * os.sysconf('SC_PAGE_SIZE') // (1 << 20)
    except Exception: return -1


async def stats():
    while True:
        await asyncio.sleep(STATS_S)
        per_ip = {}
        for p in conns: per_ip[p.ip] = per_ip.get(p.ip, 0) + 1
        top = sorted(per_ip.items(), key=lambda x: -x[1])[:3]
        buf = 0
        for p in conns:
            for s in (p.c, p.u):
                if s.tr is not None:
                    try: buf += s.tr.get_write_buffer_size()
                    except Exception: pass
        log('active %d, addresses %d, rss %d MB, unsent %d KB, closing %d, top %s, %s' % (
            len(conns), len(per_ip), rss_mb(), buf // 1024, len(CLOSING), top,
            ' '.join('%s=%d' % kv for kv in counters.items())))


async def main():
    loop = asyncio.get_running_loop()
    srvs = []
    for a in sys.argv[1:]:
        l, t = a.split('=')
        lh, lp = l.rsplit(':', 1); th, tp = t.rsplit(':', 1)
        srvs.append(await loop.create_server(server_factory(th, int(tp), int(lp)), lh, int(lp), reuse_address=True, backlog=256))
        log('%s -> %s' % (l, t))
    await asyncio.gather(stats(), sweeper(), *(s.serve_forever() for s in srvs))

if __name__ == '__main__':
    asyncio.run(main())
