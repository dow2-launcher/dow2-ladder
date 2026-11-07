#!/usr/bin/env python3
"""du_proto.py - the delivery of our UDP tunnel "DU", one code for every Python end (05.11.2026, after the 2v2 storm):
udp_gateway.py (the node side of Relay.dll and of the other nodes), du_client.py (node -> node, the relay chain) and
du_egress.py (Moscow -> iggy). Relay.dll 23 (relay/du_tunnel.h in Dow2-patches) does exactly the same in C.

The wire format is the one of Relay.dll 15-22 and udp_gateway since 01.11 - nothing new on the wire, so every old end keeps
working with a new one and the other way round:
  "DU" + type (1) + connection id (u32 LE) + body
  1 SYN version | 2 SYNACK [version] | 3 DATA seq ack sack bytes | 4 ACK ack sack | 5 FIN | 6 PING | 7 PONG
  8 DATA2 seq ack sack k k*(seq u32, len u16, bytes) bytes | 9 ACK2 ack sack k copies
  ack = the next number expected, sack bit i = ack+1+i arrived.

What changed is only how much each end sends (the limits the owner asked for, 05.11.2026):
 1. one resend timer per connection (as TCP, Karn): when it runs out only the OLDEST unacknowledged packet goes again (and
    the holes the peer's sack shows below the newest one it has), never the whole window; the timer doubles on each
    expiry, floor RTO_MIN, ceiling RTO_MAX; the round trip is never measured on a packet sent twice.
    A tail probe (TCP's TLP) comes first: when nothing came back for RTT + 2 x RTTVAR + 10 ms (at least 20 ms) the NEWEST packet goes once
    more - a lost last packet has no later one to carry its copy - once per ack that moves on.
 2. a packet sent MAX_SENDS times without an ack = the connection is dead: FIN, ev=dead - the game sees a lost connection
    (as with any cut), which is better than a storm.
 3. a budget (token bucket) for resends: max(RESEND_FLOOR/s, RESEND_SHARE of the fresh packets/s); copies: every packet is
    copied at most COPY_MAX times in its life and only while younger than max(2 x RTT, RTO_MIN); an ACK2 (an ack carrying
    copies) at most once per RTT/4 (ACK_DELAY at least) - once per round trip made the copy of a lost packet wait for the next
    game packet (~100 ms; turn p99 +10 ms at 5 % loss in relay/test); the copies stay bounded by COPY_MAX per packet anyway.
 4. at most WIN_PKTS packets / WIN_BYTES bytes in flight; full -> the source is not read (back pressure: the bytes wait in
    the TCP socket and come out later in bigger packets), and fresh packets are paced to PACE packets/s (burst PACE_BURST).
 5. acks: in-order data at most one plain ack per ACK_DELAY (10 ms; a hole is told at once), a duplicate at most once per
    DUP_ACK_GAP (20 ms); an ACK / ACK2 is never answered at once - when the copies
    in an ACK2 filled a hole that only goes out with the next packet or as a plain ACK at the next tick (a plain ACK is
    answered by nobody, old ends included, so two ends can never bounce acks).
 6. a fuse: if in FUSE_WINDOW seconds the resends + copies are more than FUSE_EXTRA (3) x the fresh packets, or more than
    FUSE_RATE packets/s go out, this connection's copies are switched off and its resends cut to the floor; ev=storm with
    the numbers is logged.
Numbers (see the report relay_udp_storm.md): a game sends ~10 packets/s each way (8.5 min 1v1 = 4842), a 2v2 ~10-20/s;
the 10 MB/s-ish ceiling of PACE x MAXP is far above anything a game sends; RTO_MIN 200 ms is the TCP floor and above the
worst round trip of a usable node (Moscow-Germany ~50 ms); MAX_SENDS 10 with doubling = ~20 s of total silence before
giving up (the game itself drops a peer after ~10 s without a word).
"""
import collections, os, struct, time

SYN, SYNACK, DATA, ACK, FIN, PING, PONG, DATA2, ACK2 = 1, 2, 3, 4, 5, 6, 7, 8, 9
MAXP = 1200            # payload bytes per packet
BUDGET = 1240          # bytes per datagram with the copies
COPIES = 2             # copies carried by one packet at most
RECV_AHEAD = 2048      # out of order packets kept ahead of the next expected (old ends keep up to 512 in flight)

WIN_PKTS = 64          # in flight at most (packets)
WIN_BYTES = 64 * 1024  # in flight at most (bytes)
RTO_MIN, RTO_MAX = float(os.environ.get('DU_MIN_RTO', '0.2')), 3.0   # DU_MIN_RTO: the knob of 95ac8ea (05.11), same meaning
RESEND_TICK = int(os.environ.get('DU_RESEND_TICK', '8'))            # at most this many holes resent at one expiry of the timer
MAX_SENDS = 11         # the first send + 10 resends; one more = dead
RESEND_FLOOR = 20.0    # resends per second always allowed
RESEND_SHARE = 0.25    # ... or this share of the fresh packets per second
COPY_MAX = 2           # copies of one packet in its whole life
PACE, PACE_BURST = 250.0, 20.0    # fresh packets per second, burst (20 x 1240 B = 25 KB: an old client's 8-64 KB socket buffer is not overrun)
DUP_ACK_GAP = 0.02     # s between two acks of duplicates
ACK_DELAY = 0.01       # in-order data: at most one plain ack per 10 ms (the ack rides on our next data packet anyway)
TLP_MIN = 0.02         # tail probe: the newest unacknowledged packet once more after max(RTT + 2 x RTTVAR + ACK_DELAY, 20 ms) of silence
KEEPALIVE = 1.0        # s without sending anything -> an ACK
IDLE = 30.0            # s without a packet from the peer -> gone
FUSE_WINDOW = 5.0
FUSE_EXTRA = 3.0       # resends + copies > 3 x fresh in the window (copies alone are at most COPY_MAX = 2 x fresh by design)
FUSE_RATE = 300.0      # or more than this many packets/s out
FUSE_MIN = 100         # ... and at least this many extra packets in the window (a few resends on a quiet line are no storm)


def hdr(t, cid): return b'DU' + bytes([t]) + struct.pack('<I', cid)


class Bucket:
    def __init__(self, rate, cap):
        self.rate, self.cap, self.tok, self.t = rate, cap, cap, time.monotonic()

    def take(self, now, n=1.0):
        self.tok = min(self.cap, self.tok + (now - self.t) * self.rate); self.t = now
        if self.tok >= n: self.tok -= n; return True
        return False


class DuCore:
    """one DU connection's delivery, no I/O of its own: out(bytes) sends a datagram, deliver(bytes) hands the peer's bytes
    on in order, log(ev, **k) writes a line, on_room() is called when the window has room again, on_close(by) once"""

    def __init__(self, cid, ver, out, deliver, log=None, on_room=None, on_close=None):
        self.cid, self.ver = cid, ver
        self._out, self._deliver, self._log = out, deliver, log or (lambda ev, **k: None)
        self._on_room, self._on_close = on_room or (lambda: None), on_close or (lambda by: None)
        now = time.monotonic()
        self.closed = False; self.closed_by = None
        self.pending = collections.deque()               # written, not sent yet (window full or pacing)
        self.snd_next = 0; self.unacked = {}             # seq -> [payload, first, last, sends, copies_made]
        self.inflight_bytes = 0
        self.rcv_next = 0; self.ooo = {}
        self.srtt = 0.15; self.rttvar = 0.05; self.have_rtt = False
        self.backoff = 1; self.rto_at = None; self.tlp_done = False
        self.last_ack_seen = -1; self.dups = 0; self.fast_done = -1; self.peer_ack = 0; self.peer_sack = 0
        self.seen = self.sent = self.started = now
        self.last_ack_out = 0.0; self.last_ack2 = 0.0; self.ack_due = 0
        self.pace = Bucket(PACE, PACE_BURST)
        self.rbucket = Bucket(RESEND_FLOOR, RESEND_FLOOR)
        self.fresh_rate = 0.0; self._fresh_mark = (now, 0)
        self.copies_on = ver >= 2
        self.fuse_tripped = False
        self._win = dict(t=now, fresh=0, extra=0, out=0)
        self.stats = dict(rx=0, tx=0, resent=0, lost_in=0, ver=ver, copies=0, filled=0, max_rtt_ms=0, acks=0, dup_in=0,
                          paced=0, budget_skip=0, pkts_in=0, pkts_out=0)

    # ---------- sending ----------
    def out(self, pkt, now, kind):
        self._out(pkt); self.sent = now; self._win['out'] += 1; self.stats['pkts_out'] += 1
        if kind == 'fresh': self._win['fresh'] += 1
        elif kind == 'resend': self._win['extra'] += 1

    def rto(self):
        base = min(RTO_MAX, max(RTO_MIN, self.srtt + 4 * self.rttvar))
        return min(RTO_MAX, base * self.backoff)

    def room(self):
        return not self.closed and len(self.unacked) + len(self.pending) < WIN_PKTS and self.inflight_bytes < WIN_BYTES

    def drained(self):
        """everything written was sent and acknowledged (07.11.2026: FIN has no number - a FIN sent with packets still on
        the way makes the peer drop them; an end that closes on its own first waits for this, see udp_gateway.run)"""
        return not self.pending and not self.unacked

    def write(self, data):
        """bytes from the local side (game / battle_relay); never refused - the caller waits for room() (back pressure)"""
        if self.closed or not data: return
        for i in range(0, len(data), MAXP):
            chunk = bytes(data[i:i + MAXP])
            if self.pending and len(self.pending[-1]) + len(chunk) <= MAXP: self.pending[-1] += chunk   # pacing: one packet
            else: self.pending.append(chunk)
        self.flush(time.monotonic())

    def flush(self, now):
        while self.pending and not self.closed and len(self.unacked) < WIN_PKTS and self.inflight_bytes < WIN_BYTES:
            if not self.pace.take(now): self.stats['paced'] += 1; break
            payload = self.pending.popleft()
            seq = self.snd_next; self.snd_next += 1
            self.unacked[seq] = [payload, now, now, 1, 0]; self.inflight_bytes += len(payload)
            self.out(self.packet(seq, now), now, 'fresh'); self.stats['tx'] += 1
            if self.rto_at is None: self.rto_at = now + self.rto()
        if self.room(): self._on_room()

    def sack(self):
        m = 0
        for i in range(32):
            if self.rcv_next + 1 + i in self.ooo: m |= 1 << i
        return m

    def copies(self, below, room, now):
        if not self.copies_on: return []
        out = []; age = max(2 * self.srtt, RTO_MIN)
        for s in range(below - 1, max(-1, below - 17), -1):
            if len(out) == COPIES: break
            u = self.unacked.get(s)
            if u is None or u[4] >= COPY_MAX or now - u[1] > age or 6 + len(u[0]) > room: continue
            out.append(struct.pack('<IH', s, len(u[0])) + u[0]); room -= 6 + len(u[0]); u[4] += 1
        self.stats['copies'] += len(out); self._win['extra'] += len(out)
        return out

    def packet(self, seq, now):
        payload = self.unacked[seq][0]
        self.ack_due = 0; self.last_ack_out = now
        if self.ver < 2: return hdr(DATA, self.cid) + struct.pack('<III', seq, self.rcv_next, self.sack()) + payload
        c = self.copies(seq, BUDGET - 20 - len(payload), now)
        return hdr(DATA2, self.cid) + struct.pack('<IIIB', seq, self.rcv_next, self.sack(), len(c)) + b''.join(c) + payload

    def send_ack(self, now, copies_ok=True):
        self.ack_due = 0; self.last_ack_out = now; self.stats['acks'] += 1
        if self.ver >= 2 and copies_ok and now - self.last_ack2 >= max(self.srtt / 4, ACK_DELAY):
            c = self.copies(self.snd_next, BUDGET - 16, now)
            if c:
                self.last_ack2 = now
                self.out(hdr(ACK2, self.cid) + struct.pack('<IIB', self.rcv_next, self.sack(), len(c)) + b''.join(c), now, 'ack')
                return
        self.out(hdr(ACK, self.cid) + struct.pack('<II', self.rcv_next, self.sack()), now, 'ack')

    def resend(self, seq, now):
        u = self.unacked[seq]
        if u[3] >= MAX_SENDS: self.dead(seq, now); return False
        if not self.rbucket.take(now): self.stats['budget_skip'] += 1; return False
        u[2] = now; u[3] += 1; self.stats['resent'] += 1
        self.out(self.packet(seq, now), now, 'resend')
        return True

    def dead(self, seq, now):
        self.log('dead', seq=seq, sends=self.unacked[seq][3], unacked=len(self.unacked))
        self.close('dead')

    # ---------- receiving ----------
    def on_ack(self, ack, sack, now):
        advanced = False; clean = self.peer_sack == 0; newest = None
        for s in [s for s in self.unacked if s < ack or (s > ack and s - ack - 1 < 32 and sack >> (s - ack - 1) & 1)]:
            u = self.unacked.pop(s); self.inflight_bytes -= len(u[0])
            if s < ack: advanced = True
            if u[3] > 1 or u[4] > 0: clean = False
            if newest is None or s > newest[0]: newest = (s, u)
        # the round trip: Karn (never on a packet sent twice) and only from an ack that came cleanly - no hole before it, no
        # resent or copied packet in what it covers. An ack that jumps over a hole once it is filled covers packets that
        # arrived long ago (beyond the 32 of the sack they look unacknowledged): that is no round trip - 05.11.2026 such
        # samples took a chain connection's srtt to 14 s (resent 3137 of 3815)
        if clean and newest is not None and newest[1][3] == 1:
            r = now - newest[1][1]
            if not self.have_rtt: self.srtt, self.rttvar, self.have_rtt = r, r / 2, True
            else: self.rttvar = 0.75 * self.rttvar + 0.25 * abs(self.srtt - r); self.srtt = 0.875 * self.srtt + 0.125 * r
            self.stats['max_rtt_ms'] = max(self.stats['max_rtt_ms'], round(r * 1000))
        if advanced:
            self.backoff = 1; self.tlp_done = False
            self.rto_at = now + self.rto() if self.unacked else None
        elif not self.unacked: self.rto_at = None
        # fast resend: the same ack twice more while later packets got there - the oldest once per ack value
        if ack == self.last_ack_seen and sack and ack in self.unacked:
            self.dups += 1
            if self.dups >= 2 and self.fast_done != ack:
                self.fast_done = ack; self.resend(ack, now)
        else: self.dups = 0
        self.last_ack_seen = ack; self.peer_ack, self.peer_sack = ack, sack
        self.flush(now)

    def on_data(self, seq, payload, copy=False):
        if seq < self.rcv_next or seq in self.ooo: return False
        if seq - self.rcv_next > RECV_AHEAD: return False
        self.ooo[seq] = payload
        if copy: self.stats['filled'] += 1
        elif seq != self.rcv_next: self.stats['lost_in'] += 1
        while self.rcv_next in self.ooo:
            d = self.ooo.pop(self.rcv_next); self.rcv_next += 1; self.stats['rx'] += 1
            if d and not self.closed: self._deliver(d)
        return True

    def datagram(self, t, body):
        """one packet of this connection (type, body after the cid); SYN / SYNACK / PING are the caller's"""
        if self.closed: return
        now = time.monotonic(); self.seen = now; self.stats['pkts_in'] += 1
        if t == DATA and len(body) >= 12:
            seq, ack, sack = struct.unpack('<III', body[:12])
            self.on_ack(ack, sack, now)
            self.got_data(self.on_data(seq, body[12:]), now)
        elif (t == DATA2 and len(body) >= 13) or (t == ACK2 and len(body) >= 9):
            if t == DATA2: seq, ack, sack, k = struct.unpack('<IIIB', body[:13]); o = 13
            else: seq = None; ack, sack, k = struct.unpack('<IIB', body[:9]); o = 9
            copies, bad = [], False
            for _ in range(k):
                if o + 6 > len(body): bad = True; break
                s, n = struct.unpack('<IH', body[o:o + 6])
                if n > MAXP or o + 6 + n > len(body): bad = True; break
                copies.append((s, body[o + 6:o + 6 + n])); o += 6 + n
            self.on_ack(ack, sack, now)
            took = sum([self.on_data(s, b, copy=True) for s, b in reversed(copies)])   # oldest first
            if seq is not None:
                new = (not bad and len(body) - o <= MAXP and self.on_data(seq, body[o:])) or took > 0
                self.got_data(new, now)
            elif took: self.ack_due = 1                       # an ACK2 is never answered at once (rule 5)
        elif t == ACK and len(body) >= 8:
            self.on_ack(*struct.unpack('<II', body[:8]), now)
        elif t == FIN:
            self.close('peer', send_fin=False)

    def got_data(self, new, now):
        """a data packet came: new bytes -> ack now (out of order / a hole filled: at once, so the sender learns of the hole;
        in order: at most one per ACK_DELAY, the rest at the next tick); only a duplicate -> at most one per DUP_ACK_GAP"""
        if new:
            if self.ooo or now - self.last_ack_out >= ACK_DELAY: self.send_ack(now)
            else: self.ack_due = 1
        else:
            self.stats['dup_in'] += 1
            if now - self.last_ack_out >= DUP_ACK_GAP: self.send_ack(now, copies_ok=False)
            elif not self.ack_due: self.ack_due = 2               # 2 = only duplicates wait (DUP_ACK_GAP)

    # ---------- the clock (call every ~10-20 ms) ----------
    def tick(self, now=None):
        if self.closed: return
        now = now or time.monotonic()
        if now - self.seen > IDLE: self.close('silent'); return
        # the fresh rate (for the resend budget), once a second
        t0, n0 = self._fresh_mark
        if now - t0 >= 1.0:
            self.fresh_rate = 0.7 * self.fresh_rate + 0.3 * (self.stats['tx'] - n0) / (now - t0)
            self._fresh_mark = (now, self.stats['tx'])
            r = RESEND_FLOOR if self.fuse_tripped else max(RESEND_FLOOR, RESEND_SHARE * self.fresh_rate)
            self.rbucket.rate = r; self.rbucket.cap = r
        # the tail probe (as TCP's TLP): a lost LAST packet has no later one to carry its copy or to bring duplicate acks - after
        # RTT + 2 x RTTVAR + ACK_DELAY without an ack the newest packet goes once more (with copies of the ones before it), well
        # before the RTO (200 ms at least); once per ack that moves on, and inside the resend budget
        if self.unacked and not self.tlp_done and self.rto_at is not None and now < self.rto_at:
            newest = max(self.unacked)
            if now - self.unacked[newest][2] >= max(self.srtt + 2 * self.rttvar + ACK_DELAY, TLP_MIN):
                self.tlp_done = True; self.resend(newest, now)
                if self.closed: return
        # the one resend timer
        if self.rto_at is not None and now >= self.rto_at and self.unacked:
            base = min(self.unacked)
            self.resend(base, now)
            if self.closed: return
            hb = self.peer_sack.bit_length()                  # the peer has ack+hb; what we still hold below that is a hole
            for s in range(base + 1, min(self.peer_ack + hb, base + 1 + RESEND_TICK)):
                u = self.unacked.get(s)
                if u and now - u[2] > self.srtt and not self.resend(s, now): break
                if self.closed: return
            if self.backoff * min(RTO_MAX, max(RTO_MIN, self.srtt + 4 * self.rttvar)) < RTO_MAX: self.backoff *= 2
            self.rto_at = now + self.rto()
        self.flush(now)
        if self.ack_due and now - self.last_ack_out >= (DUP_ACK_GAP if self.ack_due == 2 else ACK_DELAY): self.send_ack(now, copies_ok=self.ack_due == 1)
        elif now - self.sent > KEEPALIVE: self.send_ack(now)
        # the fuse
        w = self._win
        if now - w['t'] >= FUSE_WINDOW:
            secs = now - w['t']
            if not self.fuse_tripped and ((w['extra'] > FUSE_EXTRA * max(1, w['fresh']) and w['extra'] >= FUSE_MIN)
                                          or w['out'] / secs > FUSE_RATE):
                self.fuse_tripped = True; self.copies_on = False
                self.rbucket.rate = self.rbucket.cap = RESEND_FLOOR
                self.log('storm', window_s=round(secs, 1), fresh=w['fresh'], extra=w['extra'], out=w['out'],
                         out_per_s=round(w['out'] / secs), unacked=len(self.unacked), pending=len(self.pending))
            self._win = dict(t=now, fresh=0, extra=0, out=0)

    def log(self, ev, **k):
        self._log(ev, cid=self.cid, secs=round(time.monotonic() - self.started, 1), srtt_ms=round(self.srtt * 1000), **k)

    def close(self, by='us', send_fin=True):
        if self.closed: return
        self.closed = True; self.closed_by = by
        if send_fin:
            for _ in range(3):
                try: self._out(hdr(FIN, self.cid))
                except Exception: pass
        self._on_close(by)
        self._on_room()
