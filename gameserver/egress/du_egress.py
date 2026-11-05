#!/usr/bin/env python3
"""du_egress.py - on a Moscow node, the DWR3 bridge's TCP to a Relic relay goes to iggy over our UDP tunnel (03.11.2026).

battle_relay (uid of dow2-battle) opens TCP to the Relic relay (27000-27099); iptables nat REDIRECTs it here (127.0.0.1:12349,
rule kept by relic-egress). We read the address it wanted (SO_ORIGINAL_DST), open a DU connection to udp_gateway on iggy
(116.202.106.150:47100, the same protocol as Relay.dll 20: SYN version 2, DATA2/ACK2 with copies), send the preamble
"DWR3" + IPv4 + port (BE) of that Relic relay into the stream, and carry the bytes both ways. iggy's battle_relay bridges it
to Relic - from Germany; nothing crosses the border from Russia over TCP. In Russia TCP to foreign hosting degrades after a
few minutes (DPI), UDP passes, and DU resends a lost packet itself (copies fill a single loss at once).
No answer from iggy within OPEN s -> the connection goes straight to Relic over TCP as before (the game never notices).

Protocol (see udp_gateway.py, the other side): "DU" + type + cid (u32 LE) + body
  1 SYN version | 2 SYNACK [version] | 3 DATA seq ack sack bytes | 4 ACK ack sack | 5 FIN | 6 PING | 7 PONG
  8 DATA2 seq ack sack k k*(seq u32, len u16, bytes) bytes | 9 ACK2 ack sack k copies
Usage: du_egress.py [listen port] [gateway host:port]   (default 12349 116.202.106.150:47100)
The delivery is du_proto.py (05.11.2026, the same code as udp_gateway.py / du_client.py and in C Relay.dll 23): one resend
timer, at most 10 resends then FIN (ev=dead), budgets for resends and copies, 64 packets in flight with back pressure, a fuse
(ev=storm). du_proto.py is looked for next to this file, then in /srv/dow2battle (where the deploy puts it).
Log: one line per connection open/close (+ every 60 s while open): rtt, resent, lost_in, copies, filled.
"""
import asyncio, os, random, socket, struct, sys, time
sys.path[1:1] = [os.path.dirname(os.path.abspath(__file__)), '/srv/dow2battle']
import du_proto
from du_proto import SYN, SYNACK, MAXP

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 12349
GW = (sys.argv[2].rsplit(':', 1) if len(sys.argv) > 2 else ['116.202.106.150', '47100'])
GW = (GW[0], int(GW[1]))
OPEN = 1.5             # s for the DU handshake (SYN every 250 ms), then straight TCP
VERSION = 2
SO_ORIGINAL_DST = 80


def log(**k):
    print(time.strftime('%H:%M:%S') + ' ' + ' '.join('%s=%s' % kv for kv in k.items()), flush=True)


class Udp(asyncio.DatagramProtocol):
    def __init__(self, conn): self.conn = conn
    def datagram_received(self, d, addr): self.conn.datagram(d)
    def error_received(self, e): pass


class Conn:
    """the client side of one DU connection - du_proto.DuCore, as udp_gateway"""

    def __init__(self, w, relic):
        self.w, self.relic = w, relic
        self.cid = random.getrandbits(32); self.ver = 0; self.tr = None; self.core = None
        self.synack = asyncio.get_running_loop().create_future()
        self.started = time.time()
        self.room = asyncio.Event(); self.room.set()

    @property
    def closed(self): return self.core is None or self.core.closed

    def out(self, pkt):
        try: self.tr.sendto(pkt)
        except Exception: pass

    async def open(self):
        loop = asyncio.get_running_loop()
        self.tr, _ = await loop.create_datagram_endpoint(lambda: Udp(self), remote_addr=GW)
        end = time.time() + OPEN
        while time.time() < end:
            self.out(du_proto.hdr(SYN, self.cid) + bytes([VERSION]))
            try:
                self.ver = await asyncio.wait_for(asyncio.shield(self.synack), min(0.25, max(0.01, end - time.time())))
                self.core = du_proto.DuCore(self.cid, self.ver, out=self.out, deliver=self.deliver,
                                            log=lambda ev, **k: self.log(ev, **{a: b for a, b in k.items() if a not in ('cid', 'secs', 'srtt_ms')}),
                                            on_room=self.on_room, on_close=self.on_close)
                return True
            except asyncio.TimeoutError: pass
        self.tr.close(); return False

    def deliver(self, d):
        try: self.w.write(d)
        except Exception: pass

    def on_room(self):
        if self.core.closed or self.core.room(): self.room.set()
        else: self.room.clear()

    def datagram(self, d):
        if len(d) < 7 or d[:2] != b'DU' or struct.unpack('<I', d[3:7])[0] != self.cid: return
        t, body = d[2], d[7:]
        if t == SYNACK:
            if not self.synack.done(): self.synack.set_result(body[0] if body and body[0] >= 2 else 1)
            return
        if self.closed: return
        self.core.datagram(t, body)

    async def timers(self):
        last_log = time.time()
        while not self.closed:
            await asyncio.sleep(0.01)
            self.core.tick()
            if time.time() - last_log > 60: last_log = time.time(); self.log('stats')

    def log(self, ev, **k):
        c = self.core
        log(ev=ev, cid='%08x' % self.cid, relic='%s:%d' % self.relic, secs=round(time.time() - self.started, 1),
            srtt_ms=round(c.srtt * 1000) if c else None, **(c.stats if c else {}), **k)

    def on_close(self, by):
        try: self.tr.close()
        except Exception: pass
        try: self.w.close()
        except Exception: pass
        self.log('close', by=by, storm=int(self.core.fuse_tripped))

    def close(self, by, send_fin=True):
        if self.core: self.core.close(by, send_fin)


def original_dst(sock):
    b = sock.getsockopt(socket.SOL_IP, SO_ORIGINAL_DST, 16)
    return socket.inet_ntoa(b[4:8]), struct.unpack('>H', b[2:4])[0]


async def straight(r, w, relic, why):
    """no tunnel: the bytes go to the Relic relay over TCP, as without us"""
    try: ur, uw = await asyncio.wait_for(asyncio.open_connection(*relic), 10)
    except Exception as e: log(ev='straight_fail', relic='%s:%d' % relic, err=repr(e)); w.close(); return
    try: uw.get_extra_info('socket').setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except Exception: pass
    log(ev='straight', relic='%s:%d' % relic, why=why)

    async def pipe(a, b):
        try:
            while True:
                d = await a.read(65536)
                if not d: break
                b.write(d); await b.drain()
        except Exception: pass
        try: b.close()
        except Exception: pass
    await asyncio.gather(pipe(r, uw), pipe(ur, w))


async def handle(r, w):
    sock = w.get_extra_info('socket')
    try: sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except Exception: pass
    try: relic = original_dst(sock)
    except Exception as e: log(ev='no_orig_dst', err=repr(e)); w.close(); return
    if not 27000 <= relic[1] <= 27099 or relic[0].startswith('127.'):      # only redirected connections to Relic relays
        log(ev='refused', dest='%s:%d' % relic); w.close(); return
    c = Conn(w, relic)
    if not await c.open():
        await straight(r, w, relic, 'no SYNACK from %s:%d' % GW); return
    c.log('open')                     # ver is in the stats already (05.11: a second ver= raised TypeError, every forwarded game closed)
    t = asyncio.ensure_future(c.timers())
    c.core.write(b'DWR3' + socket.inet_aton(relic[0]) + struct.pack('>H', relic[1]))
    try:
        while not c.closed:
            if not c.core.room():                                   # window full: back pressure into battle_relay's socket
                c.room.clear(); await c.room.wait(); continue
            d = await r.read(MAXP)
            if not d: break
            c.core.write(d)
    except Exception: pass
    c.close('battle_relay')
    t.cancel()


async def main():
    srv = await asyncio.start_server(handle, '127.0.0.1', PORT)
    log(ev='start', port=PORT, gateway='%s:%d' % GW)
    async with srv: await srv.serve_forever()

if __name__ == '__main__':
    asyncio.run(main())
