#!/usr/bin/env python3
"""du_client.py - battle_relay's connection to ANOTHER of our nodes over our UDP tunnel (DU), 04.11.2026 (relay chain).

When a player's game is on a node it can't reach itself, it plays through its own node: player -> its node -> the node of the
session (Relay.dll 22 "DWR4", and the older pass-on of a guest whose host is elsewhere). That hop between our servers goes
over UDP like du_egress.py (Moscow -> iggy): TCP Moscow <-> Europe stalls (DPI: pauses of 250+ ms after a few minutes),
UDP with our own delivery does not (03.11.2026: 0 stalls in 10 min). The other node's udp_gateway (UDP, same port as its
battle_relay) turns it into a local TCP connection to its battle_relay, so the far side does not change at all.

open_du(host, port) -> (reader, writer) like asyncio.open_connection, or None when no SYNACK comes within OPEN s (the caller
then uses TCP). reader = asyncio.StreamReader; writer: write / drain / close / is_closing / get_extra_info / transport
.get_write_buffer_size / du_stats(). The delivery is the one of udp_gateway.py / Relay.dll 20 (version 2): numbered packets,
ack + sack, resend after an RTO from the round trip (min 60 ms) or at once on two duplicate acks, DATA2 / ACK2 carrying
copies of the newest unacknowledged packets, keepalive ACK every second, 30 s of silence = gone.
"""
import asyncio, collections, random, struct, time, os

OPEN = 1.5             # s for the handshake (a SYN every 250 ms)
MAXP = 1200
WINDOW = 512
IDLE = 30.0
SYN, SYNACK, DATA, ACK, FIN, PING, PONG, DATA2, ACK2 = 1, 2, 3, 4, 5, 6, 7, 8, 9
VERSION = 2
COPIES = 2
BUDGET = 1240


# 05.11.2026: the resend timer never below DU_MIN_RTO (0.2 s, as TCP's minimum; was 0.06): with a 20-30 ms round trip a packet was
# sent again after 60 ms and a whole window (up to 64, each with its copies) every 20 ms tick - the gateway logged 6x more resends
# than packets (resent 3265, tx 535) and 4-player games choked; the copies still fill a single loss at once. RESEND_TICK: at most
# that many packets are sent again per 20 ms tick
MIN_RTO = float(os.environ.get('DU_MIN_RTO', '0.2'))
RESEND_TICK = int(os.environ.get('DU_RESEND_TICK', '8'))

class _Udp(asyncio.DatagramProtocol):
    def __init__(self, c): self.c = c
    def datagram_received(self, d, addr): self.c.datagram(d)
    def error_received(self, e): pass


class DUStream:
    def __init__(self, host, port):
        self.dest = (host, port)
        self.cid = random.getrandbits(32); self.ver = 0; self.tr = None
        self.reader = asyncio.StreamReader()
        self.synack = asyncio.get_running_loop().create_future()
        self.closed = False; self.closed_by = None
        self.snd_next = 0; self.unacked = {}; self.pending = collections.deque()
        self.rcv_next = 0; self.ooo = {}
        self.srtt = 0.15; self.rttvar = 0.05; self.dup = 0; self.last_ack_seen = -1
        self.seen = self.sent = self.started = time.time()
        self.stats = dict(rx=0, tx=0, resent=0, lost_in=0, copies=0, filled=0, max_rtt_ms=0)
        self.room = asyncio.Event(); self.room.set()
        self.timer = None
        self.transport = self                           # pass_on / BridgeStats ask writer.transport.get_write_buffer_size()

    # ---- the writer side, as asyncio.StreamWriter is used by battle_relay ----
    def write(self, data):
        if self.closed: return
        for i in range(0, len(data), MAXP): self.pending.append(bytes(data[i:i + MAXP]))
        self.flush()

    async def drain(self):
        while self.pending and not self.closed:
            self.room.clear(); await self.room.wait()
        if self.closed: raise ConnectionResetError('DU connection closed')

    def is_closing(self): return self.closed
    def get_extra_info(self, name, default=None): return default
    def get_write_buffer_size(self): return sum(len(x) for x in self.pending) + sum(len(u[0]) for u in self.unacked.values())

    def du_stats(self):
        return dict(self.stats, srtt_ms=round(self.srtt * 1000), ver=self.ver, secs=round(time.time() - self.started, 1))

    def close(self, by='us', send_fin=True):
        if self.closed: return
        self.closed = True; self.closed_by = by
        if send_fin and self.tr:
            for _ in range(3): self.out(self.hdr(FIN))
        try: self.tr.close()
        except Exception: pass
        if self.timer: self.timer.cancel()
        self.reader.feed_eof(); self.room.set()

    async def wait_closed(self): pass

    # ---- the delivery ----
    def hdr(self, t): return b'DU' + bytes([t]) + struct.pack('<I', self.cid)

    def out(self, pkt):
        try: self.tr.sendto(pkt)
        except Exception: pass
        self.sent = time.time()

    async def open(self):
        loop = asyncio.get_running_loop()
        self.tr, _ = await loop.create_datagram_endpoint(lambda: _Udp(self), remote_addr=self.dest)
        end = time.time() + OPEN
        while time.time() < end:
            self.out(self.hdr(SYN) + bytes([VERSION]))
            try:
                self.ver = await asyncio.wait_for(asyncio.shield(self.synack), min(0.25, max(0.01, end - time.time())))
                self.timer = asyncio.ensure_future(self.timers())
                return True
            except asyncio.TimeoutError: pass
        self.tr.close(); self.closed = True
        return False

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

    def flush(self):                                     # what was written goes out as far as the window allows
        while self.pending and len(self.unacked) < WINDOW and not self.closed:
            payload = self.pending.popleft()
            seq = self.snd_next; self.snd_next += 1; now = time.time()
            self.unacked[seq] = [payload, now, now, 1]
            self.out(self.packet(seq)); self.stats['tx'] += 1
        if not self.pending: self.room.set()

    def resend(self, seq, now):
        u = self.unacked[seq]; u[2] = now; u[3] += 1; self.stats['resent'] += 1
        self.out(self.packet(seq))

    def rto(self): return min(1.0, max(MIN_RTO, self.srtt + 4 * self.rttvar))

    def on_ack(self, ack, sack):
        now = time.time()
        for s in [s for s in self.unacked if s < ack or (s > ack and s - ack - 1 < 32 and sack >> (s - ack - 1) & 1)]:
            u = self.unacked.pop(s)
            if u[3] == 1:                                    # Karn: the round trip only from packets sent once
                r = now - u[1]; self.rttvar = 0.75 * self.rttvar + 0.25 * abs(self.srtt - r); self.srtt = 0.875 * self.srtt + 0.125 * r
                self.stats['max_rtt_ms'] = max(self.stats['max_rtt_ms'], round(r * 1000))
        if ack == self.last_ack_seen and self.unacked and ack in self.unacked and sack:
            self.dup += 1
            if self.dup == 2: self.resend(ack, now)
        else: self.dup = 0
        self.last_ack_seen = ack
        self.flush()

    def on_data(self, seq, payload, copy=False):
        if seq < self.rcv_next or seq in self.ooo: return False
        if seq - self.rcv_next > 4 * WINDOW: return False
        self.ooo[seq] = payload
        if copy: self.stats['filled'] += 1
        elif seq != self.rcv_next: self.stats['lost_in'] += 1
        while self.rcv_next in self.ooo:
            d = self.ooo.pop(self.rcv_next); self.rcv_next += 1; self.stats['rx'] += 1
            if d and not self.closed: self.reader.feed_data(d)
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
            self.close('peer', send_fin=False)

    async def timers(self):
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


async def open_du(host, port, timeout=OPEN):
    """(reader, writer) of a DU connection to the udp_gateway at host:port, None when it does not answer"""
    c = DUStream(host, port)
    try:
        if not await asyncio.wait_for(c.open(), timeout + 1): return None
    except Exception:
        try: c.tr and c.tr.close()
        except Exception: pass
        return None
    return c.reader, c


async def ping(host, port, n=5, timeout=1.0):
    """the round trip to a udp_gateway in ms (median of n PING/PONG), -1 = no answer"""
    loop = asyncio.get_running_loop(); got = {}; cid = random.getrandbits(32); fut = {}

    class P(asyncio.DatagramProtocol):
        def datagram_received(self, d, addr):
            if d[:3] == b'DU\x07' and struct.unpack('<I', d[3:7])[0] == cid and len(d) >= 11:
                k = struct.unpack('<I', d[7:11])[0]
                if k in fut and not fut[k].done(): fut[k].set_result(time.perf_counter())
    tr, _ = await loop.create_datagram_endpoint(P, remote_addr=(host, port))
    rtts = []
    try:
        for k in range(n):
            fut[k] = loop.create_future(); t = time.perf_counter()
            tr.sendto(b'DU\x06' + struct.pack('<I', cid) + struct.pack('<I', k) + b'r22')
            try: rtts.append((await asyncio.wait_for(fut[k], timeout)) - t)
            except asyncio.TimeoutError: pass
            await asyncio.sleep(0.05)
    finally: tr.close()
    if not rtts: return -1
    rtts.sort(); return round(rtts[len(rtts) // 2] * 1000, 1)
