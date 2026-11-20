#!/usr/bin/env python3
"""tcp_mirror.py - a plain TCP forwarder: the Moscow mirror of our lobby server (03.11.2026).
Players in Russia reach Moscow fine, but their streams to Europe stop after ~33 KB (DPI); server to server is not cut.
OwnLobby.dll 2 tries this mirror first. Bytes are passed as they are (TLS end to end: the mirror sees nothing).
06.11.2026: TCP keepalive on both sockets (probes after 20 s of silence, dead after 3 unanswered, unacked data dropped after
30 s) and a connection with no bytes either way for IDLE s is closed - a connection that died quietly during a match no longer
hangs here forever (own_lobby closes idle game connections at 55 s itself, as Relic does at 60 s).
  tcp_mirror.py LISTEN_HOST:PORT=TARGET:PORT [...]     e.g. 83.217.192.34:47443=37.27.234.236:47443"""
import asyncio, os, socket, sys, time
# 17.11.2026: OOM on timeweb (894 MB, no swap) - the mirror grew to ~500-550 MB (53 kills since 07.11, the node froze 2-3 min
# each time with dow2-battle/udpgw: a 3v3 lost at 21:55 MSK). Bounded now: MAX_CONN 400 (~100 MB worst case), at most
# PER_IP connections from one address, a write that can't drain in DRAIN_S is dropped, the count is logged every minute.

MAX_CONN = int(os.environ.get('MIRROR_MAX_CONN', '400'))
PER_IP = int(os.environ.get('MIRROR_PER_IP', '24'))
DRAIN_S = 30
BUF_MAX = 1 << 20   # a connection whose unsent buffer passes 1 MB is closed (one stuck peer must not eat the node)
IDLE = int(os.environ.get('MIRROR_IDLE', '120'))   # s without a byte either way
active = 0
per_ip = {}

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

async def pipe(r, w, seen):
    try:
        while True:
            try: b = await asyncio.wait_for(r.read(65536), 10)
            except asyncio.TimeoutError:
                if time.monotonic() - seen[0] > IDLE: break
                continue
            if not b: break
            seen[0] = time.monotonic()
            w.write(b)
            if w.transport.get_write_buffer_size() > BUF_MAX:
                log('closing: unsent %d B to %s' % (w.transport.get_write_buffer_size(), w.get_extra_info('peername'))); break
            await asyncio.wait_for(w.drain(), DRAIN_S)
    except (ConnectionError, OSError, asyncio.CancelledError, asyncio.TimeoutError): pass
    finally:
        try: w.close()
        except Exception: pass

def server(th, tp):
    async def handle(cr, cw):
        global active
        ip = (cw.get_extra_info('peername') or ('?',))[0]
        if active >= MAX_CONN or per_ip.get(ip, 0) >= PER_IP: cw.close(); return
        active += 1; per_ip[ip] = per_ip.get(ip, 0) + 1
        try:
            keepalive(cw.get_extra_info('socket'))
            try: ur, uw = await asyncio.wait_for(asyncio.open_connection(th, tp), 5)
            except (OSError, asyncio.TimeoutError) as e:
                log('to %s:%d: %r' % (th, tp, e)); cw.close(); return
            keepalive(uw.get_extra_info('socket'))
            seen = [time.monotonic()]
            await asyncio.gather(pipe(cr, uw, seen), pipe(ur, cw, seen))
        finally:
            active -= 1; per_ip[ip] -= 1
            if per_ip[ip] <= 0: per_ip.pop(ip, None)
    return handle

async def stats():
    while True:
        await asyncio.sleep(30)
        top = sorted(per_ip.items(), key=lambda x: -x[1])[:3]
        try: rss = int(open('/proc/self/statm').read().split()[1]) * 4 // 1024
        except Exception: rss = -1
        log('active %d, addresses %d, rss %d MB, top %s' % (active, len(per_ip), rss, top))

async def main():
    srvs = []
    for a in sys.argv[1:]:
        l, t = a.split('=')
        lh, lp = l.rsplit(':', 1); th, tp = t.rsplit(':', 1)
        srvs.append(await asyncio.start_server(server(th, int(tp)), lh, int(lp), reuse_address=True))
        log('%s -> %s' % (l, t))
    await asyncio.gather(stats(), *(s.serve_forever() for s in srvs))

asyncio.run(main())
