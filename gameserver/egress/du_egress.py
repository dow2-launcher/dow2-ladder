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
Log: one line per connection open/close (+ every 60 s while open): rtt, resent, lost_in, copies, filled.
"""
import asyncio, os, random, socket, struct, sys, time

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 12349
GW = (sys.argv[2].rsplit(':', 1) if len(sys.argv) > 2 else ['116.202.106.150', '47100'])
GW = (GW[0], int(GW[1]))
OPEN = 1.5             # s for the DU handshake (SYN every 250 ms), then straight TCP
MAXP = 1200
WINDOW = 512
IDLE = 30.0
SYN, SYNACK, DATA, ACK, FIN, PING, PONG, DATA2, ACK2 = 1, 2, 3, 4, 5, 6, 7, 8, 9
VERSION = 2
COPIES = 2
BUDGET = 1240
SO_ORIGINAL_DST = 80


def log(**k):
    print(time.strftime('%H:%M:%S') + ' ' + ' '.join('%s=%s' % kv for kv in k.items()), flush=True)


# 05.11.2026: the resend timer never below DU_MIN_RTO (0.2 s, as TCP's minimum; was 0.06): with a 20-30 ms round trip a packet was
# sent again after 60 ms and a whole window (up to 64, each with its copies) every 20 ms tick - the gateway logged 6x more resends
# than packets (resent 3265, tx 535) and 4-player games choked; the copies still fill a single loss at once. RESEND_TICK: at most
# that many packets are sent again per 20 ms tick
MIN_RTO = float(os.environ.get('DU_MIN_RTO', '0.2'))
RESEND_TICK = int(os.environ.get('DU_RESEND_TICK', '8'))

class Udp(asyncio.DatagramProtocol):
    def __init__(self, conn): self.conn = conn
    def datagram_received(self, d, addr): self.conn.datagram(d)
    def error_received(self, e): pass


class Conn:
    """the client side of one DU connection - the same delivery as udp_gateway.Conn (seq/ack/sack, RTO, copies)"""

    def __init__(self, w, relic):
        self.w, self.relic = w, relic
        self.cid = random.getrandbits(32); self.ver = 0; self.tr = None
        self.synack = asyncio.get_running_loop().create_future()
        self.closed = False
        self.snd_next = 0; self.unacked = {}
        self.rcv_next = 0; self.ooo = {}
        self.srtt = 0.15; self.rttvar = 0.05; self.dup = 0; self.last_ack_seen = -1
        self.seen = self.sent = self.started = time.time()
        self.stats = dict(rx=0, tx=0, resent=0, lost_in=0, copies=0, filled=0, max_rtt_ms=0)
        self.can_send = asyncio.Event(); self.can_send.set()

    def hdr(self, t): return b'DU' + bytes([t]) + struct.pack('<I', self.cid)

    def out(self, pkt):
        try: self.tr.sendto(pkt)
        except Exception: pass
        self.sent = time.time()

    async def open(self):
        loop = asyncio.get_running_loop()
        self.tr, _ = await loop.create_datagram_endpoint(lambda: Udp(self), remote_addr=GW)
        end = time.time() + OPEN
        while time.time() < end:
            self.out(self.hdr(SYN) + bytes([VERSION]))
            try:
                self.ver = await asyncio.wait_for(asyncio.shield(self.synack), min(0.25, max(0.01, end - time.time())))
                return True
            except asyncio.TimeoutError: pass
        self.tr.close(); return False

    def sack(self):
        m = 0
        for i in range(32):
            if self.rcv_next + 1 + i in self.ooo: m |= 1 << i
        return m

    def copies(self, below, room):
        out = []
        for s in range(below - 1, max(-1, below - 17), -1):
            if len(out) == COPIES: break
            u = self.unacked.get(s)
            if u is None or 6 + len(u[0]) > room: continue
            out.append(struct.pack('<IH', s, len(u[0])) + u[0]); room -= 6 + len(u[0])
        self.stats['copies'] += len(out)
        return out

    def send_ack(self):
        if self.ver >= 2:
            c = self.copies(self.snd_next, BUDGET - 16)
            if c: self.out(self.hdr(ACK2) + struct.pack('<IIB', self.rcv_next, self.sack(), len(c)) + b''.join(c)); return
        self.out(self.hdr(ACK) + struct.pack('<II', self.rcv_next, self.sack()))

    def packet(self, seq):
        payload = self.unacked[seq][0]
        if self.ver < 2: return self.hdr(DATA) + struct.pack('<III', seq, self.rcv_next, self.sack()) + payload
        copies = self.copies(seq, BUDGET - 20 - len(payload))
        return self.hdr(DATA2) + struct.pack('<IIIB', seq, self.rcv_next, self.sack(), len(copies)) + b''.join(copies) + payload

    def send_data(self, payload):
        seq = self.snd_next; self.snd_next += 1; now = time.time()
        self.unacked[seq] = [payload, now, now, 1]
        self.out(self.packet(seq)); self.stats['tx'] += 1
        if len(self.unacked) >= WINDOW: self.can_send.clear()

    def resend(self, seq, now):
        u = self.unacked[seq]; u[2] = now; u[3] += 1; self.stats['resent'] += 1
        self.out(self.packet(seq))

    def rto(self): return min(1.0, max(MIN_RTO, self.srtt + 4 * self.rttvar))

    def on_ack(self, ack, sack):
        now = time.time()
        for s in [s for s in self.unacked if s < ack or (s > ack and s - ack - 1 < 32 and sack >> (s - ack - 1) & 1)]:
            u = self.unacked.pop(s)
            if u[3] == 1:                                       # Karn: the round trip only from packets sent once
                r = now - u[1]; self.rttvar = 0.75 * self.rttvar + 0.25 * abs(self.srtt - r); self.srtt = 0.875 * self.srtt + 0.125 * r
                self.stats['max_rtt_ms'] = max(self.stats['max_rtt_ms'], round(r * 1000))
        if ack == self.last_ack_seen and self.unacked and ack in self.unacked and sack:
            self.dup += 1
            if self.dup == 2: self.resend(ack, now)
        else: self.dup = 0
        self.last_ack_seen = ack
        if len(self.unacked) < WINDOW: self.can_send.set()

    def on_data(self, seq, payload, copy=False):
        if seq < self.rcv_next or seq in self.ooo: return False
        if seq - self.rcv_next > 4 * WINDOW: return False
        self.ooo[seq] = payload
        if copy: self.stats['filled'] += 1
        elif seq != self.rcv_next: self.stats['lost_in'] += 1
        while self.rcv_next in self.ooo:
            d = self.ooo.pop(self.rcv_next); self.rcv_next += 1; self.stats['rx'] += 1
            if d and not self.closed: self.w.write(d)
        return True

    def datagram(self, d):
        if len(d) < 7 or d[:2] != b'DU' or struct.unpack('<I', d[3:7])[0] != self.cid: return
        t, body = d[2], d[7:]
        if t == SYNACK:
            if not self.synack.done(): self.synack.set_result(body[0] if body and body[0] >= 2 else 1)
            return
        if not self.ver or self.closed: return
        self.seen = time.time()
        if t == DATA and len(body) >= 12:
            seq, ack, sack = struct.unpack('<III', body[:12])
            self.on_ack(ack, sack); self.on_data(seq, body[12:]); self.send_ack()
        elif (t == DATA2 and len(body) >= 13) or (t == ACK2 and len(body) >= 9):
            if t == DATA2: seq, ack, sack, k = struct.unpack('<IIIB', body[:13]); o = 13
            else: seq = None; ack, sack, k = struct.unpack('<IIB', body[:9]); o = 9
            copies, bad = [], False
            for _ in range(k):
                if o + 6 > len(body): bad = True; break
                s, n = struct.unpack('<IH', body[o:o + 6])
                if n > MAXP or o + 6 + n > len(body): bad = True; break
                copies.append((s, body[o + 6:o + 6 + n])); o += 6 + n
            self.on_ack(ack, sack)
            took = sum([self.on_data(s, b, copy=True) for s, b in reversed(copies)])
            if seq is not None and not bad and len(body) - o <= MAXP: self.on_data(seq, body[o:])
            if seq is not None or took: self.send_ack()
        elif t == ACK and len(body) >= 8:
            self.on_ack(*struct.unpack('<II', body[:8]))
        elif t == FIN:
            self.close('gateway', send_fin=False)

    async def timers(self):
        last_log = time.time()
        while not self.closed:
            await asyncio.sleep(0.02)
            now = time.time()
            if now - self.seen > IDLE: self.close('silent'); return
            rto = self.rto()
            n = 0
            for s in sorted(self.unacked)[:64]:
                if now - self.unacked[s][2] > rto * min(8, 2 ** (self.unacked[s][3] - 1)):
                    self.resend(s, now); n += 1
                    if n >= RESEND_TICK: break
            if now - self.sent > 1.0: self.send_ack()
            if now - last_log > 60: last_log = now; self.log('stats')

    def log(self, ev, **k):
        log(ev=ev, cid='%08x' % self.cid, relic='%s:%d' % self.relic, secs=round(time.time() - self.started, 1),
            srtt_ms=round(self.srtt * 1000), **self.stats, **k)

    def close(self, by, send_fin=True):
        if self.closed: return
        self.closed = True
        if send_fin:
            for _ in range(3): self.out(self.hdr(FIN))
        try: self.tr.close()
        except Exception: pass
        try: self.w.close()
        except Exception: pass
        self.log('close', by=by)


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
    c.log('open', ver=c.ver)
    t = asyncio.ensure_future(c.timers())
    c.send_data(b'DWR3' + socket.inet_aton(relic[0]) + struct.pack('>H', relic[1]))
    try:
        while not c.closed:
            d = await r.read(MAXP)
            if not d: break
            await c.can_send.wait()
            if c.closed: break
            c.send_data(d)
    except Exception: pass
    c.close('battle_relay')
    t.cancel()


async def main():
    srv = await asyncio.start_server(handle, '127.0.0.1', PORT)
    log(ev='start', port=PORT, gateway='%s:%d' % GW)
    async with srv: await srv.serve_forever()

if __name__ == '__main__':
    asyncio.run(main())
