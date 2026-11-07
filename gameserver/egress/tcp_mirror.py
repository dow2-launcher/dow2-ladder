#!/usr/bin/env python3
"""tcp_mirror.py - a plain TCP forwarder: the Moscow mirror of our lobby server (03.11.2026).
Players in Russia reach Moscow fine, but their streams to Europe stop after ~33 KB (DPI); server to server is not cut.
OwnLobby.dll 2 tries this mirror first. Bytes are passed as they are (TLS end to end: the mirror sees nothing).
06.11.2026: TCP keepalive on both sockets (probes after 20 s of silence, dead after 3 unanswered, unacked data dropped after
30 s) and a connection with no bytes either way for IDLE s is closed - a connection that died quietly during a match no longer
hangs here forever (own_lobby closes idle game connections at 55 s itself, as Relic does at 60 s).
  tcp_mirror.py LISTEN_HOST:PORT=TARGET:PORT [...]     e.g. 83.217.192.34:47443=37.27.234.236:47443"""
import asyncio, os, socket, sys, time

MAX_CONN = 2000
IDLE = int(os.environ.get('MIRROR_IDLE', '120'))   # s without a byte either way
active = 0

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
            w.write(b); await w.drain()
    except (ConnectionError, OSError, asyncio.CancelledError): pass
    finally:
        try: w.close()
        except Exception: pass

def server(th, tp):
    async def handle(cr, cw):
        global active
        if active >= MAX_CONN: cw.close(); return
        active += 1
        try:
            keepalive(cw.get_extra_info('socket'))
            try: ur, uw = await asyncio.wait_for(asyncio.open_connection(th, tp), 5)
            except (OSError, asyncio.TimeoutError) as e:
                log('to %s:%d: %r' % (th, tp, e)); cw.close(); return
            keepalive(uw.get_extra_info('socket'))
            seen = [time.monotonic()]
            await asyncio.gather(pipe(cr, uw, seen), pipe(ur, cw, seen))
        finally: active -= 1
    return handle

async def main():
    srvs = []
    for a in sys.argv[1:]:
        l, t = a.split('=')
        lh, lp = l.rsplit(':', 1); th, tp = t.rsplit(':', 1)
        srvs.append(await asyncio.start_server(server(th, int(tp)), lh, int(lp), reuse_address=True))
        log('%s -> %s' % (l, t))
    await asyncio.gather(*(s.serve_forever() for s in srvs))

asyncio.run(main())
