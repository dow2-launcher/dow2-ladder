#!/usr/bin/env python3
"""udp_gateway.py - the game's connection to our battle server over UDP (Relay.dll 15 "UDP to our server", 01.11.2026).
In Russia TCP to foreign hosting is cut after ~16-30 KB (DPI on the way) while UDP passes (NetProbe). Relay.dll carries
the game's TCP stream to us in UDP packets with its own delivery; here each such stream becomes an ordinary TCP
connection to battle_relay on this machine, so battle_relay does not know the difference.

Packet: "DU" + type (1) + connection id (u32 LE, random, chosen by the player) + body
  1 SYN     player -> us: version (1)                 -> we connect to battle_relay, answer SYNACK (again on a repeat)
  2 SYNACK  us -> player: + version (1) when the player's is 2+ (Relay 20); bare (as before) for version 1 (Relay 15-19)
  3 DATA    both: seq (u32) + ack (u32) + sack (u32) + bytes (<= 1200)
  4 ACK     both: ack (u32) + sack (u32)              ack = next packet number expected, sack bit i = ack+1+i arrived
  5 FIN     both: the connection is over
  6 PING    player -> us: up to 1200 bytes            -> 7 PONG with at most the first 32 of them (never more than came in);
            no connection is made. Relay 17 measures the delay with small ones; Relay 18 also sends a burst of 40 x 1000 bytes
            and counts the answers: some paths (DPI) pass a short ping but stop a stream after ~33 KB (owner 03.11.2026)
  8 DATA2   both, version 2 (Relay 20, 03.11.2026): seq + ack + sack + k (u8) + k x (seq u32, len u16, bytes) + bytes:
            the packet also carries copies of the newest (up to 2) earlier packets not acknowledged yet, as long as the
            datagram stays within BUDGET - a single lost packet (or two in a row) is filled by the next one, no resend wait.
  9 ACK2    both, version 2: ack + sack + k (u8) + k copies as in DATA2 - an ACK carrying copies (k >= 1, else a plain
            ACK): the acks of the other way's packets come about as often as the data, so a lost packet is filled sooner.
            Since 05.11.2026 (du_proto rule 5) never answered at once: a hole it filled is told with the next packet or a
            plain ACK at the next tick, and a plain ACK nobody answers - the two sides never bounce acks.
            Version 1 connections get DATA and ACK as before. The stream after the SYN is carried as is: battle_relay tells a
            Relay.dll preamble (DWR1-3) from a native game stream (our lobby server's rooms, no preamble) by itself.
Packets are numbered from 0 on each side. The delivery itself (resends, copies, acks, the limits) is du_proto.py since
05.11.2026 - the same code as du_client.py / du_egress.py and, in C, Relay.dll 23 (relay/du_tunnel.h): one resend timer
(oldest first, doubling 200 ms .. 3 s), 10 resends at most then FIN (ev=dead), a resend budget, copies at most twice per
packet, 64 packets / 64 KB in flight with back pressure, duplicate acks at most every 20 ms, a fuse (ev=storm). The
wire format did not change: old Relay.dll 15-22 work with this gateway and Relay.dll 23 with an old one.
Per player address at most ADDR_RATE packets/s come in (burst ADDR_BURST), our own nodes (TRUSTED) excepted - a client
in a storm can't flood the node (05.11.2026: one 2v2 host sent 2380 packets/s for 10 minutes).
The launcher's connection test (06.11.2026): a stream that starts with "DWRT" goes to battle_relay as "DWRU" + the player's
IPv4 + the rest (battle_relay's limits per address); every other stream is passed on byte for byte as before. And "DU" 10 STATQ
(cid, padded to 64+ bytes) -> 11 STATA + JSON of that connection's counters here (rx, holes lost_in, copies that filled one,
duplicates, resends): how the player's packets arrived - its losses on the way up, which its own end can't see when a copy
fills the hole. Only for a live connection from its own address, never bigger than the request.
Keepalive: an ACK each second; 30 s without a packet = gone.
Monitoring: every UDPGW_STATS_EVERY s (15) one ev=conn_stats line per live connection - packets/s in / out in that interval,
data packets, resends, holes (lost_in), copies, filled, srtt, unacked, storm (the fuse) - and ev=storm / ev=dead / addr_limit
as they happen. `journalctl -u dow2-udpgw | grep conn_stats`.
Usage: udp_gateway.py [port] [battle_relay host:port]   (default 47100 127.0.0.1:47100)
"""
import asyncio, json, os, socket, struct, sys, time
import du_proto
from du_proto import SYN, SYNACK, DATA, ACK, FIN, PING, PONG, DATA2, ACK2, MAXP

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 47100
BR = (sys.argv[2].rsplit(':', 1) if len(sys.argv) > 2 else ['127.0.0.1', '47100'])
BR = (BR[0], int(BR[1]))
STATQ, STATA = 10, 11   # the launcher's connection test: what this end saw of a connection (below)
PER_IP = 16            # connections per address
# our nodes: no per-address limit - all bridges of a Moscow node (du_egress, 03.11.2026) and all players another node passes on
# here (battle_relay over du_client, the relay chain 04.11.2026) come from that node's one address
TRUSTED = set(os.environ.get('UDPGW_TRUSTED', '83.217.192.34,91.107.122.186,15.220.68.107,116.202.106.150').split(','))
ADDR_RATE = float(os.environ.get('UDPGW_ADDR_RATE', '1000'))   # packets/s from one player address (all its connections)
ADDR_BURST = 2 * ADDR_RATE
# the newest we speak: 2 = DATA2 with copies. UDPGW_VERSION=1 (05.11.2026, owner): no copies at all - a bare SYNACK, so every
# Relay.dll falls back to plain DATA / ACK and resends only what is really lost (a 2v2 on Relay 22 went into a storm of copies:
# ~650 packets/s, 1.07 M copies in 10 min, the game choking on old retries)
VERSION = max(1, min(2, int(os.environ.get('UDPGW_VERSION', '2'))))
STATS_EVERY = float(os.environ.get('UDPGW_STATS_EVERY', '15'))   # s: an ev=conn_stats line per live connection, 0 = none
# 10.11.2026 (own rating step 1b): every "close" also as a JSON line here, so the match collector on rts does not depend on the
# journal's retention; the unit gives the directory (StateDirectory=dow2udpgw). Empty = journal only, as before
GWLOG = os.environ.get('UDPGW_LOG', '')


def gwlog(**k):
    if not GWLOG: return
    try:
        k['t'] = round(time.time(), 3)
        with open(GWLOG, 'a') as f: f.write(json.dumps(k, default=str) + '\n')
    except Exception: pass


def log(**k):
    print(time.strftime('%H:%M:%S') + ' ' + ' '.join('%s=%s' % kv for kv in k.items()), flush=True)


class Conn:
    def __init__(self, gw, cid, addr, ver=1):
        self.gw, self.cid, self.addr, self.ver = gw, cid, addr, ver
        self.w = None; self.ready = False; self.prev_stats = None; self.head = b''; self.tst = {}
        self.room = asyncio.Event(); self.room.set()
        self.core = du_proto.DuCore(cid, ver, out=lambda pkt: gw.tr.sendto(pkt, self.addr), deliver=self.deliver,
                                    log=lambda ev, **k: log(ev=ev, peer=self.addr[0], **k),
                                    on_room=self.on_room, on_close=self.on_close)
        self.started = time.time()

    @property
    def closed(self): return self.core.closed

    def deliver(self, d):
        if self.head is not None:                       # the stream's first 4 bytes: the launcher's connection test (DWRT,
            self.head += d                              # 06.11.2026) gets the player's address put in - battle_relay limits
            if len(self.head) < 4: return               # tests per address and sees only us (127.0.0.1)
            d, self.head = self.head, None
            if d[:4] == b'DWRT': d = b'DWRU' + socket.inet_aton(self.addr[0]) + d[4:]; self.track()
        if self.w: self.w.write(d)

    def track(self):
        """the launcher's connection test only: how many of the player's packets were lost on the way up. A packet that came only
        as a copy (its own never followed within a second) or that filled a hole late (a resend) is lost; one that came a little
        after a later one, or after its copy, was only reordered. Its own end can't see this: the copies hide its losses. STATA."""
        core = self.core; orig = core.on_data; byc = {}; holes = {}; hi = [None]; self.tst = dict(up_lost=0, up_reord=0)
        late = lambda: max(core.srtt / 2, 0.03)

        def on_data(seq, payload, copy=False):
            rn = core.rcv_next
            new = orig(seq, payload, copy); now = time.monotonic(); st = self.tst
            if not new:
                if not copy and seq in byc and now - byc.pop(seq) < 1.0: st['up_lost'] -= 1; st['up_reord'] += 1
                return new
            if seq in holes:
                if not copy and now - holes.pop(seq) < late(): st['up_reord'] += 1
                else: st['up_lost'] += 1
            elif copy:
                st['up_lost'] += 1; byc[seq] = now
            if hi[0] is None or seq > hi[0]:
                for x in range(max(rn, hi[0] + 1 if hi[0] is not None else rn), min(seq, rn + 64)): holes.setdefault(x, now)
                hi[0] = seq
            if len(byc) > 512 or len(holes) > 512:
                for d in (byc, holes):
                    for k in [k for k, t in d.items() if now - t > 2]: del d[k]
            return new
        core.on_data = on_data

    def on_room(self):
        if self.core.room(): self.room.set()
        else: self.room.clear()

    def synack(self): return du_proto.hdr(SYNACK, self.cid) + (bytes([VERSION]) if self.ver >= 2 else b'')

    async def run(self):
        try:
            r, self.w = await asyncio.wait_for(asyncio.open_connection(*BR), 5)
        except Exception as e:
            log(ev='br_fail', cid=self.cid, peer=self.addr[0], err=repr(e)); self.core.close('br_fail'); return
        self.ready = True; self.gw.tr.sendto(self.synack(), self.addr)
        try: self.lport = self.w.get_extra_info('sockname')[1]     # battle_relay sees this connection as 127.0.0.1:<lport>
        except Exception: self.lport = 0
        log(ev='open', cid=self.cid, peer='%s:%d' % self.addr, ver=self.ver, lport=self.lport)
        try:
            while not self.closed:
                if not self.core.room():                    # window full: battle_relay waits in its TCP socket (back pressure)
                    self.room.clear(); await self.room.wait(); continue
                d = await r.read(MAXP)
                if not d: break
                self.core.write(d)
        except Exception: pass
        self.core.close('battle_relay')

    def on_close(self, by):
        try:
            if self.w: self.w.close()
        except Exception: pass
        self.gw.conns.pop(self.cid, None)
        st = self.core.stats
        log(ev='close', cid=self.cid, peer=self.addr[0], lport=getattr(self, 'lport', 0), secs=round(time.time() - self.started, 1), srtt_ms=round(self.core.srtt * 1000),
            by=by, storm=int(self.core.fuse_tripped), **st)
        try: gwlog(ev='close', cid=self.cid, peer=self.addr[0], lport=getattr(self, 'lport', 0), by=by,
                   secs=round(time.time() - self.started, 1), srtt_ms=round(self.core.srtt * 1000), **st)
        except Exception: pass


class Gateway(asyncio.DatagramProtocol):
    def __init__(self): self.conns = {}; self.addr_buckets = {}; self.limited = {}

    def connection_made(self, tr): self.tr = tr

    def addr_ok(self, ip):
        """rule 7: at most ADDR_RATE packets/s from one player address (all its connections), our nodes excepted"""
        if ip in TRUSTED: return True
        b = self.addr_buckets.get(ip)
        if b is None: b = self.addr_buckets[ip] = du_proto.Bucket(ADDR_RATE, ADDR_BURST)
        if b.take(time.monotonic()): return True
        n = self.limited.get(ip, [0, 0.0]); n[0] += 1
        if time.time() - n[1] > 10: log(ev='addr_limit', peer=ip, dropped=n[0], rate=ADDR_RATE); n = [0, time.time()]
        self.limited[ip] = n
        return False

    def datagram_received(self, d, addr):
        if len(d) < 7 or d[:2] != b'DU': return
        if not self.addr_ok(addr[0]): return
        t, cid = d[2], struct.unpack('<I', d[3:7])[0]; body = d[7:]
        if t == PING:                                           # stateless echo, small (no amplification)
            if len(body) <= 1200: self.tr.sendto(b'DU' + bytes([PONG]) + d[3:7] + body[:32], addr)
            return
        c = self.conns.get(cid)
        if c and c.addr[0] != addr[0]: return                   # an id is bound to its address (the port may change: NAT)
        if t == STATQ:                                          # the launcher's connection test asks how its packets arrived here:
            if c and c.ready and len(body) >= 64:               # the copies that filled a hole and the holes = its losses on the way up.
                st = c.core.stats                               # Never more bytes than came in (no amplification); old ends ignore it.
                j = json.dumps(dict(rx=st['rx'], pkts_in=st['pkts_in'], lost_in=st['lost_in'], filled=st['filled'], dup_in=st['dup_in'],
                                    tx=st['tx'], resent=st['resent'], copies=st['copies'], srtt_ms=round(c.core.srtt * 1000), storm=int(c.core.fuse_tripped), **c.tst),
                               separators=(',', ':')).encode()
                if 7 + len(j) <= len(d): self.tr.sendto(du_proto.hdr(STATA, cid) + j, addr)
            return
        if t == SYN:
            if not c:
                if addr[0] not in TRUSTED and sum(1 for x in self.conns.values() if x.addr[0] == addr[0]) >= PER_IP: return
                c = self.conns[cid] = Conn(self, cid, addr, min(VERSION, body[0]) if body else 1)
                asyncio.ensure_future(c.run())
            elif c.ready: self.tr.sendto(c.synack(), addr)
            return
        if not c or not c.ready: return
        c.addr = addr
        c.core.datagram(t, body)

    async def timers(self):
        last_stats = time.monotonic()
        while True:
            await asyncio.sleep(0.01)
            now = time.monotonic()
            for c in list(self.conns.values()):
                if c.ready: c.core.tick(now)
            if len(self.addr_buckets) > 4096: self.addr_buckets.clear()
            if STATS_EVERY > 0 and now - last_stats >= STATS_EVERY:
                self.conn_stats(now - last_stats); last_stats = now

    def conn_stats(self, secs):
        """live monitoring (owner 05.11.2026): one line per live connection every STATS_EVERY s - packets/s in and out in that
        interval (a game is ~10-40/s; the storm of 05.11 was 650-2400/s), and what of it were resends / copies / holes"""
        for c in list(self.conns.values()):
            if not c.ready: continue
            st = c.core.stats; prev = c.prev_stats or {}
            d = {k: st[k] - prev.get(k, 0) for k in ('pkts_in', 'pkts_out', 'tx', 'rx', 'resent', 'lost_in', 'copies', 'filled')}
            c.prev_stats = dict(st)
            log(ev='conn_stats', cid=c.cid, peer='%s:%d' % c.addr, ver=c.ver, secs=round(time.time() - c.started),
                pps_in=round(d['pkts_in'] / secs, 1), pps_out=round(d['pkts_out'] / secs, 1), data_in=d['rx'], data_out=d['tx'],
                resent=d['resent'], lost_in=d['lost_in'], copies=d['copies'], filled=d['filled'], srtt_ms=round(c.core.srtt * 1000),
                unacked=len(c.core.unacked), storm=int(c.core.fuse_tripped))


async def main():
    loop = asyncio.get_running_loop()
    tr, gw = await loop.create_datagram_endpoint(Gateway, local_addr=('0.0.0.0', PORT))
    log(ev='start', port=PORT, battle_relay='%s:%d' % BR, version=VERSION)
    await gw.timers()

if __name__ == '__main__':
    asyncio.run(main())
