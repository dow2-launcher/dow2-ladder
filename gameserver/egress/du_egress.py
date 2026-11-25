#!/usr/bin/env python3
"""du_egress.py - on a Moscow node, the DWR3 bridge's TCP to a Relic relay leaves Russia over our UDP tunnel (03.11.2026;
v2 17.11.2026: several egress nodes, warm flows, VLESS before straight TCP).

battle_relay (uid of dow2-battle) opens TCP to the Relic relay (27000-27099); iptables nat REDIRECTs it here (127.0.0.1:12349,
rule kept by relic-egress). We read the address it wanted (SO_ORIGINAL_DST) and carry the bytes, the first way that works:
  1. UDP (DU) to udp_gateway of the egress nodes in order (iggy 116.202.106.150:47100, then Poland: Azure 74.248.144.168:47100 from 23.11.2026; AWS Poland retired 25.11.2026): the
     preamble "DWR3" + IPv4 + port (BE) of that Relic relay goes into the stream, that node's battle_relay bridges to Relic.
  2. VLESS to iggy (xray-relic dokodemo 127.0.0.1:12348 -> iggy's battle_relay), the same preamble - TCP over the tunnel.
  3. straight TCP to Relic from Russia (as without us) - only when nothing else answers; logged with TCP stats per flow.
Warm flows (17.11.2026): in Russia a UDP flow (one source port) sometimes loses every reply for minutes while the next port
works (firstvds 17.11: 13 of 45 opens got no SYNACK, a ping test 8 ports x 20: two ports 0/20 and 1/20, the rest 20/20). So
each egress keeps SOCKS pre-opened sockets (ports) pinged every PING_EVERY s; a new connection sends its SYN on the PAR best
of them at once (the same cid - the gateway answers each SYN once it is ready) and keeps the first port that answers. Egress
k+1 joins after STAGGER s (at once when egress k has no healthy port); OPEN s in all, then VLESS, then straight. A socket
that misses DEAD_MISSES pings in a row is replaced by a new port (only while no connection rides it); a live connection whose
port stops answering pings moves to a healthy port of the same egress (the gateway follows the source port of the newest
packet from our address). One ev=choose line per connection says which way and why.
Status for relic-egress (no probe sockets of its own any more): TCP 127.0.0.1:STATUS_PORT -> one JSON line.

Protocol (see udp_gateway.py, the other side): "DU" + type + cid (u32 LE) + body
  1 SYN version | 2 SYNACK [version] | 3 DATA seq ack sack bytes | 4 ACK ack sack | 5 FIN | 6 PING | 7 PONG
  8 DATA2 seq ack sack k k*(seq u32, len u16, bytes) bytes | 9 ACK2 ack sack k copies
Usage: du_egress.py [listen port] [egress list] (default 12349 iggy=116.202.106.150:47100,azurepl=74.248.144.168:47100);
       an old single "host:port" still works. Env: DU_EGRESS_VLESS (127.0.0.1:12348, empty = no VLESS step),
       DU_EGRESS_STATUS (12350, 0 = none), DU_EGRESS_SOCKS (4).
       du_egress.py probe <egress host:port | none> <relic ip:port> [secs]  - one flow with the preamble through that egress
       (test; "none" + DU_EGRESS_VLESS=127.0.0.1:12348 tests the VLESS step)
The delivery is du_proto.py (05.11.2026, the same code as udp_gateway.py / du_client.py and in C Relay.dll 23), looked for
next to this file, then in /srv/dow2battle.
Log: ev=choose per connection; DU: open/close (+ every 60 s stats), migrate; TCP ways: tcp_open, tcp_stats every 30 s, tcp_close
(rtt, rttvar, retrans, lost, max gap down, stalls >250 ms); egress health changes: ev=egress.
"""
import asyncio, json, os, random, socket, struct, sys, time
sys.path[1:1] = [os.path.dirname(os.path.abspath(__file__)), '/srv/dow2battle']
import du_proto
from du_proto import SYN, SYNACK, FIN, PING, PONG, MAXP

DEFAULT_EGRESS = 'iggy=116.202.106.150:47100,azurepl=74.248.144.168:47100'
OPEN = 3.0             # s for the UDP handshake over all egress nodes, then VLESS, then straight TCP
STAGGER = 1.0          # s egress k has alone (when healthy) before egress k+1 joins
SYN_EVERY = 0.15       # s between SYN rounds
PAR = 3                # sockets (ports) of one egress a SYN goes out on at once
SOCKS = int(os.environ.get('DU_EGRESS_SOCKS', '4'))      # warm sockets per egress
PING_EVERY = 1.0       # s
HEALTHY = 3.0          # s since the last PONG for a socket to count as healthy
DEAD_MISSES = 4        # pings in a row unanswered -> the socket (port) is replaced, if no connection rides it
MOVE_MISSES = 2        # a live connection leaves a socket that missed this many pings in a row ...
MOVE_SILENT = 1.2      # ... or that has been silent this long (the gateway sends at least an ACK every 1 s) while a sibling answers
VERSION = 2
SO_ORIGINAL_DST = 80
TCP_STATS_EVERY = 30.0
STALL = 0.25           # s: a gap between two downstream reads counted as a stall on the TCP ways
VLESS_CHECK = 20.0     # s between DWRQ checks of the VLESS tunnel
VLESS_FRESH = 60.0     # s a good check counts


def _hp(s, port=47100):
    h, _, p = s.rpartition(':')
    return (h, int(p)) if h else (s, port)


def parse_egress(spec):
    out = []
    for i, item in enumerate(x for x in spec.split(',') if x):
        name, _, addr = item.rpartition('=')
        hp = _hp(addr)
        out.append((name or hp[0], hp))
    return out


def log(**k):
    print(time.strftime('%H:%M:%S') + ' ' + ' '.join('%s=%s' % kv for kv in k.items()), flush=True)


CONNS = {}       # cid -> Conn (live DU connections, any egress)
OPENING = {}     # cid -> Opener (SYN sent, no SYNACK yet)
ABANDONED = {}   # cid -> (egress, time): a SYN went out, another way won - a late SYNACK gets a FIN


class WarmSock(asyncio.DatagramProtocol):
    """one UDP socket (one source port = one flow) to an egress; pinged, carries any number of DU connections (by cid)"""

    def __init__(self, eg):
        self.eg = eg; self.tr = None; self.port = 0
        self.ping_cid = random.getrandbits(32); self.seq = 0; self.out_ping = None   # (seq, sent at)
        self.last_pong = 0.0; self.misses = 0; self.rtt = None; self.pings = self.pongs = 0
        self.conns = set(); self.born = time.monotonic(); self.closed = False

    def connection_made(self, tr):
        self.tr = tr
        try: self.port = tr.get_extra_info('sockname')[1]
        except Exception: self.port = 0

    def error_received(self, e): pass

    def connection_lost(self, e): self.closed = True

    def send(self, pkt):
        try: self.tr.sendto(pkt)
        except Exception: pass

    def ping(self, now):
        if self.out_ping is not None: self.misses += 1          # the previous one never came back
        self.seq += 1; self.out_ping = (self.seq, now); self.pings += 1
        self.send(du_proto.hdr(PING, self.ping_cid) + b'EGK' + struct.pack('<I', self.seq) + b'\0' * 9)

    def healthy(self, now):
        return not self.closed and self.misses < MOVE_MISSES and now - self.last_pong < HEALTHY

    def score(self, now):
        """higher is better: healthy first, then fewer misses, then the faster"""
        return (self.healthy(now), -self.misses, self.last_pong > 0, -(self.rtt or 9.9))

    def datagram_received(self, d, addr):
        if len(d) < 7 or d[:2] != b'DU': return
        t = d[2]; cid = struct.unpack('<I', d[3:7])[0]; body = d[7:]
        if cid == self.ping_cid:
            if t == PONG and body[:3] == b'EGK' and len(body) >= 7 and self.out_ping:
                seq = struct.unpack('<I', body[3:7])[0]
                if seq == self.out_ping[0]:
                    now = time.monotonic(); r = now - self.out_ping[1]
                    self.rtt = r if self.rtt is None else 0.8 * self.rtt + 0.2 * r
                    self.out_ping = None; self.misses = 0; self.last_pong = now; self.pongs += 1
            return
        if t == SYNACK:
            o = OPENING.get(cid)
            if o: o.synack(self, body); return
            if cid in ABANDONED:                                  # the loser of a race answered late: let its gateway go
                self.send(du_proto.hdr(FIN, cid)); return
        c = CONNS.get(cid)
        if c: c.datagram(t, body, self)

    def close(self):
        self.closed = True
        try: self.tr.close()
        except Exception: pass


class Egress:
    def __init__(self, name, addr):
        self.name, self.addr = name, addr
        self.socks = []; self.logged = None; self.rounds = 0; self.fill_err = False

    async def new_sock(self):
        loop = asyncio.get_running_loop()
        _, s = await loop.create_datagram_endpoint(lambda: WarmSock(self), remote_addr=self.addr)
        self.socks.append(s); return s

    def healthy(self, now=None):
        now = now or time.monotonic()
        return [s for s in self.socks if s.healthy(now)]

    def best(self, n, now=None):
        now = now or time.monotonic()
        return sorted((s for s in self.socks if not s.closed), key=lambda s: s.score(now), reverse=True)[:n]

    def info(self, now=None):
        now = now or time.monotonic(); h = self.healthy(now)
        rtts = [s.rtt for s in h if s.rtt is not None]
        return dict(name=self.name, addr='%s:%d' % self.addr, healthy=len(h), socks=len(self.socks),
                    rtt_ms=round(min(rtts) * 1000) if rtts else None, conns=sum(len(s.conns) for s in self.socks),
                    ports={s.port: dict(ok=int(s.healthy(now)), misses=s.misses, rtt_ms=round(s.rtt * 1000) if s.rtt else None,
                                        conns=len(s.conns)) for s in self.socks})

    async def fill(self):
        """open sockets up to SOCKS; an OSError (22.11.2026: "Network is unreachable" while the node had no network) is logged
        once per outage and tried again next round - before, it killed keep() for good and the egress stayed DOWN until a restart"""
        while len(self.socks) < SOCKS:
            try: await self.new_sock()
            except OSError as e:
                if not self.fill_err: log(ev='egress_sock_failed', egress=self.name, err=repr(e))
                self.fill_err = True; return
        if self.fill_err: log(ev='egress_sock_ok', egress=self.name); self.fill_err = False

    async def keep(self):
        """warm flows: SOCKS sockets pinged every PING_EVERY s; dead ones replaced, connections moved off failing ones.
        Never ends: a round that fails is logged and the next one comes PING_EVERY later (22.11.2026)."""
        while True:
            try: await self.round()
            except asyncio.CancelledError: raise
            except Exception as e: log(ev='egress_round_error', egress=self.name, err=repr(e))
            await asyncio.sleep(PING_EVERY)

    async def round(self):
        if True:
            now = time.monotonic()
            for s in list(self.socks):
                if s.closed: self.socks.remove(s); continue
                if s.misses >= DEAD_MISSES and not s.conns:
                    if self.healthy(now):                  # a single dead flow while its siblings answer: worth a line
                        log(ev='flow_replaced', egress=self.name, port=s.port, misses=s.misses, pongs=s.pongs, pings=s.pings)
                    s.close(); self.socks.remove(s)        # (the whole egress down: ev=egress state=DOWN says it once)
            await self.fill()
            for s in self.socks: s.ping(now)
            h = len(self.healthy(now)) > 0; self.rounds += 1
            if self.rounds > 2 and h != self.logged:               # (the first pongs are not back yet in round 1)
                i = self.info(now); i.pop('ports'); self.logged = h
                log(ev='egress', state='up' if h else 'DOWN', **i)
            for s in self.socks:                                   # live connections on a port that stopped answering
                for cid in list(s.conns):
                    c = CONNS.get(cid)
                    if c: c.check_move(now)
                    else: s.conns.discard(cid)


EGRESS = []
VLESS = None                                   # (host, port) of xray-relic's dokodemo to iggy's battle_relay, or None
VSTATE = dict(ok=None, at=0.0, err=None)


async def tcp_open(host, port, timeout):
    """one TCP connection (tests replace this)"""
    return await asyncio.wait_for(asyncio.open_connection(host, port), timeout)


async def vless_check_once():
    try:
        r, w = await tcp_open(*VLESS, 3)
        w.write(b'DWRQ' + os.urandom(4)); await w.drain()
        a = await asyncio.wait_for(r.read(1), 5); w.close()
        ok, err = a in (b'Y', b'N'), None if a in (b'Y', b'N') else 'answer %r' % a
    except Exception as e: ok, err = False, repr(e)
    if ok != VSTATE['ok']: log(ev='vless', state='up' if ok else 'DOWN', addr='%s:%d' % VLESS, err=err)
    VSTATE.update(ok=ok, at=time.monotonic(), err=err)


async def vless_keep():
    while True:
        await vless_check_once()
        await asyncio.sleep(VLESS_CHECK)


def vless_ok():
    return VLESS is not None and VSTATE['ok'] and time.monotonic() - VSTATE['at'] < VLESS_FRESH


class Opener:
    """one connection's race: SYN (the same cid) on the PAR best ports of an egress; the first SYNACK wins"""

    def __init__(self, eg):
        self.eg = eg; self.cid = random.getrandbits(32); self.socks = []; self.sent = 0
        self.won = asyncio.get_running_loop().create_future(); self.started = None

    def syn(self, now):
        if self.started is None:
            self.started = now; OPENING[self.cid] = self
            self.socks = self.eg.best(PAR, now)
        for s in self.socks:
            s.send(du_proto.hdr(SYN, self.cid) + bytes([VERSION])); self.sent += 1

    def synack(self, sock, body):
        if not self.won.done(): self.won.set_result((sock, body[0] if body and body[0] >= 2 else 1, time.monotonic()))

    def drop(self, why):
        """lost the race / gave up: a late SYNACK gets a FIN (the gateway may have connected its battle_relay already)"""
        OPENING.pop(self.cid, None)
        if self.started is not None:
            ABANDONED[self.cid] = (self.eg, time.monotonic())
            for s in self.socks: s.send(du_proto.hdr(FIN, self.cid))


async def open_du(relic):
    """-> (Conn-to-be: (egress, sock, cid, ver, ms), why) or (None, why); the order: EGRESS list, STAGGER apart, OPEN s in all"""
    t0 = time.monotonic()
    for cid, (e, t) in list(ABANDONED.items()):
        if t0 - t > 30: ABANDONED.pop(cid, None)
    starts, t = [], 0.0
    for e in EGRESS:
        starts.append(t)
        if e.healthy(t0): t += STAGGER            # a healthy egress gets STAGGER s alone; an unhealthy one is no reason to wait
    ops = [Opener(e) for e in EGRESS]
    health = {e.name: '%d/%d' % (len(e.healthy(t0)), len(e.socks)) for e in EGRESS}
    winner = None
    try:
        while True:
            now = time.monotonic(); el = now - t0
            if el >= OPEN: break
            for o, st in zip(ops, starts):
                if el >= st: o.syn(now)
            live = [o.won for o in ops if o.started is not None and not o.won.done()]
            nxt = min([st for st in starts if st > el] + [el + SYN_EVERY, OPEN])
            if live: await asyncio.wait(live, timeout=max(0.005, nxt - el), return_when=asyncio.FIRST_COMPLETED)
            else: await asyncio.sleep(max(0.005, nxt - el))
            done = [o for o in ops if o.won.done()]
            if done:
                # several may be done in the same wake-up: the earlier in the list (iggy before Poland) wins
                winner = done[0]; break
    finally:
        for o in ops:
            if o is not winner: o.drop('lost' if winner else 'timeout')
    if winner:
        OPENING.pop(winner.cid, None)
        sock, ver, at = winner.won.result()
        tried = [o.eg.name for o in ops if o.started is not None]
        why = 'synack %dms port %d (tried %s, healthy %s)' % ((at - t0) * 1000, sock.port, '+'.join(tried),
                                                               ','.join('%s %s' % kv for kv in health.items()))
        return (winner.eg, sock, winner.cid, ver, round((at - t0) * 1000)), why
    tried = ['%s %d syn on %d ports' % (o.eg.name, o.sent, len(o.socks)) for o in ops if o.started is not None]
    return None, 'no SYNACK in %.1fs (%s; healthy %s)' % (OPEN, ', '.join(tried) or 'no egress',
                                                          ','.join('%s %s' % kv for kv in health.items()))


class Conn:
    """the client side of one DU connection - du_proto.DuCore, as udp_gateway; rides a WarmSock, may move to a sibling"""

    def __init__(self, w, relic, eg, sock, cid, ver):
        self.w, self.relic, self.eg, self.sock, self.cid, self.ver = w, relic, eg, sock, cid, ver
        self.started = time.time(); self.moves = 0; self.last_move = 0.0
        self.room = asyncio.Event(); self.room.set()
        self.core = du_proto.DuCore(cid, ver, out=self.out, deliver=self.deliver,
                                    log=lambda ev, **k: self.log(ev, **{a: b for a, b in k.items() if a not in ('cid', 'secs', 'srtt_ms')}),
                                    on_room=self.on_room, on_close=self.on_close)
        CONNS[cid] = self; sock.conns.add(cid)

    @property
    def closed(self): return self.core.closed

    def out(self, pkt): self.sock.send(pkt)

    def deliver(self, d):
        try: self.w.write(d)
        except Exception: pass

    def on_room(self):
        if self.core.closed or self.core.room(): self.room.set()
        else: self.room.clear()

    def datagram(self, t, body, sock):
        if self.closed: return
        self.core.datagram(t, body)

    def check_move(self, now):
        """the port stopped answering pings (or went silent while a sibling answers): carry on from the best healthy sibling;
        the gateway takes the source port of our newest packet as the address to answer"""
        if self.closed or now - self.last_move < 2.0: return
        s = self.sock
        silent = now - self.core.seen
        if not (s.misses >= MOVE_MISSES or silent > MOVE_SILENT): return
        cand = [x for x in self.eg.healthy(now) if x is not s]
        if not cand: return
        n = max(cand, key=lambda x: x.score(now))
        s.conns.discard(self.cid); n.conns.add(self.cid); self.sock = n; self.moves += 1; self.last_move = now
        self.log('migrate', from_port=s.port, to_port=n.port, misses=s.misses, silent_ms=round(silent * 1000))
        try: self.core.send_ack(now)               # tell the gateway the new port at once
        except Exception: pass

    async def timers(self):
        last_log = time.time()
        while not self.closed:
            await asyncio.sleep(0.01)
            self.core.tick()
            if not self.closed: self.check_move(time.monotonic())
            if time.time() - last_log > 60: last_log = time.time(); self.log('stats')

    def log(self, ev, **k):
        c = self.core
        log(ev=ev, cid='%08x' % self.cid, egress=self.eg.name, port=self.sock.port, relic='%s:%d' % self.relic,
            secs=round(time.time() - self.started, 1), srtt_ms=round(c.srtt * 1000), moves=self.moves, **c.stats, **k)

    def on_close(self, by):
        CONNS.pop(self.cid, None); self.sock.conns.discard(self.cid)
        try: self.w.close()
        except Exception: pass
        self.log('close', by=by, storm=int(self.core.fuse_tripped))

    def close(self, by, send_fin=True):
        self.core.close(by, send_fin)


def original_dst(sock):
    b = sock.getsockopt(socket.SOL_IP, SO_ORIGINAL_DST, 16)
    return socket.inet_ntoa(b[4:8]), struct.unpack('>H', b[2:4])[0]


def tcp_info(sock):
    """Linux struct tcp_info: rtt / rttvar (ms), retransmits now, lost, total_retrans"""
    try:
        b = sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_INFO, 104)
        u = struct.unpack('8B24I', b[:104])
        i = u[8:]
        return dict(rtt_ms=round(i[15] / 1000, 1), rttvar_ms=round(i[16] / 1000, 1), rto_ms=round(i[0] / 1000),
                    retrans=i[7], lost=i[6], total_retrans=i[23], unacked=i[4], cwnd=i[18])
    except Exception: return {}


async def tcp_way(r, w, relic, way, why, host, port, pre=b''):
    """straight to Relic, or VLESS to iggy's battle_relay with the preamble; per flow TCP stats (17.11.2026: the straight way
    stalls 1-3 s every few minutes from Russia - the stats show it)"""
    try: ur, uw = await tcp_open(host, port, 10)
    except Exception as e:
        log(ev='tcp_fail', way=way, relic='%s:%d' % relic, err=repr(e)); return False
    us = uw.get_extra_info('socket')
    try: us.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except Exception: pass
    if pre: uw.write(pre)
    log(ev='choose', way=way, relic='%s:%d' % relic, why=why)
    st = dict(up=0, down=0, max_gap_ms=0, stalls=0, last=None, ti={})
    t0 = time.time()

    def line(ev, **k):
        log(ev=ev, way=way, relic='%s:%d' % relic, secs=round(time.time() - t0, 1), up_bytes=st['up'], down_bytes=st['down'],
            max_gap_down_ms=st['max_gap_ms'], stalls=st['stalls'], **((tcp_info(us) if us else {}) or st['ti']), **k)

    async def pipe(a, b, key):
        try:
            while True:
                d = await a.read(65536)
                if not d: break
                st[key] += len(d)
                if key == 'down':
                    now = time.monotonic()
                    if st['last'] is not None:
                        g = now - st['last']; st['max_gap_ms'] = max(st['max_gap_ms'], round(g * 1000))
                        if g >= STALL: st['stalls'] += 1
                    st['last'] = now
                b.write(d); await b.drain()
        except Exception: pass
        if not st['ti'] and us: st['ti'] = tcp_info(us)       # the last numbers before the socket goes
        try: b.close()
        except Exception: pass

    async def stats():
        while True:
            await asyncio.sleep(TCP_STATS_EVERY); line('tcp_stats')
    s = asyncio.ensure_future(stats())
    try: await asyncio.gather(pipe(r, uw, 'up'), pipe(ur, w, 'down'))
    finally:
        s.cancel(); line('tcp_close')
    return True


async def handle(r, w):
    sock = w.get_extra_info('socket')
    try: sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except Exception: pass
    try: relic = original_dst(sock)
    except Exception as e: log(ev='no_orig_dst', err=repr(e)); w.close(); return
    if not 27000 <= relic[1] <= 27099 or relic[0].startswith('127.'):      # only redirected connections to Relic relays
        log(ev='refused', dest='%s:%d' % relic); w.close(); return
    await carry(r, w, relic)


async def carry(r, w, relic):
    pre = b'DWR3' + socket.inet_aton(relic[0]) + struct.pack('>H', relic[1])
    got, why = await open_du(relic) if EGRESS else (None, 'no egress configured')
    if got is None:
        if vless_ok():
            if await tcp_way(r, w, relic, 'vless', 'UDP: ' + why, VLESS[0], VLESS[1], pre): return
            why += '; vless connect failed'
        else: why += '; vless %s' % ('not configured' if VLESS is None else 'down (%s)' % VSTATE['err'] if VSTATE['ok'] is False else 'unchecked/stale')
        if not await tcp_way(r, w, relic, 'straight', why, relic[0], relic[1]):
            w.close()
        return
    eg, s, cid, ver, ms = got
    c = Conn(w, relic, eg, s, cid, ver)
    log(ev='choose', way='udp', egress=eg.name, relic='%s:%d' % relic, cid='%08x' % cid, why=why)
    c.log('open')
    t = asyncio.ensure_future(c.timers())
    c.core.write(pre)
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


def status():
    now = time.monotonic()
    return dict(t=round(time.time(), 1), pid=os.getpid(), egress=[e.info(now) for e in EGRESS],
                vless=dict(addr='%s:%d' % VLESS if VLESS else None, ok=VSTATE['ok'], age_s=round(now - VSTATE['at'], 1) if VSTATE['at'] else None),
                live=len(CONNS), udp_ok=any(e.healthy(now) for e in EGRESS))


async def status_handle(r, w):
    try: w.write(json.dumps(status(), separators=(',', ':')).encode() + b'\n'); await w.drain()
    except Exception: pass
    w.close()


def setup(egress_spec, vless):
    global VLESS
    EGRESS[:] = [Egress(n, a) for n, a in parse_egress(egress_spec)]
    VLESS = _hp(vless) if vless else None


async def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 12349
    setup(sys.argv[2] if len(sys.argv) > 2 else DEFAULT_EGRESS, os.environ.get('DU_EGRESS_VLESS', '127.0.0.1:12348'))
    for e in EGRESS: asyncio.ensure_future(e.keep())
    if VLESS: asyncio.ensure_future(vless_keep())
    sp = int(os.environ.get('DU_EGRESS_STATUS', '12350'))
    if sp: await asyncio.start_server(status_handle, '127.0.0.1', sp)
    srv = await asyncio.start_server(handle, '127.0.0.1', port)
    log(ev='start', port=port, egress=','.join('%s=%s:%d' % (e.name, *e.addr) for e in EGRESS),
        vless='%s:%d' % VLESS if VLESS else None, status_port=sp, socks=SOCKS)
    async with srv: await srv.serve_forever()


async def probe(egress, relic, secs):
    """test: one flow with the DWR3 preamble through one egress ("none": no UDP egress -> the VLESS step when
    DU_EGRESS_VLESS is set, else straight), held secs; no game bytes"""
    setup('' if egress == 'none' else 'probe=' + egress, os.environ.get('DU_EGRESS_VLESS', '') if egress == 'none' else '')
    for e in EGRESS: asyncio.ensure_future(e.keep())
    if VLESS: asyncio.ensure_future(vless_keep())
    await asyncio.sleep(PING_EVERY * 2.5)
    for e in EGRESS: print('egress', json.dumps(e.info()), flush=True)

    class W:
        def write(self, d): print('got %d bytes from the far side' % len(d), flush=True)
        def close(self): pass
    r = asyncio.StreamReader()
    asyncio.get_running_loop().call_later(secs, r.feed_eof)
    await carry(r, W(), _hp(relic))
    print('probe done', flush=True)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'probe':
        asyncio.run(probe(sys.argv[2], sys.argv[3], float(sys.argv[4]) if len(sys.argv) > 4 else 5))
    else:
        asyncio.run(main())
