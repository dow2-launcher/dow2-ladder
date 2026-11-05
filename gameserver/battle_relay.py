#!/usr/bin/env python3
"""Our own DoW2 battle relay - replaces Relic's battleserverrelay (AWS Virginia) so players near the server do not
send every game turn across the ocean. Protocol learned from captures (capture_proxy.py, 27.10.2026):

  frame:  u16 BE length + message, message[0] = type
  15  hello      15 <sid u32 LE> 00000000 <id 8> <flag>        -> join session sid, echo back. Peer index = join order (1..)
  14  ping       14 <stamp 4>                                   -> echo back
  13  to peer    13 <dst> <src> <inner>                         -> to peer #dst unchanged; inner "0f 05.." (peer announce)
                                                                   goes to everyone in the session, header stripped
  10  proxy      10 <src> <n u16 LE> n*<dst> <u16 LE len> <data + n*15 bytes, one info per dst>
                 (the game's RLink ProxyMessage, session message type 0x10: one message to several peers, each with its own
                 15-byte reliable header) -> to EACH dst in the list, as a message of its own with only that dst and its
                 info (05.11.2026; before: unchanged to every other peer, see proxy_split)
  09  turn data  09 fe <u16 LE len + data>                      -> queued for the next tick
  17  turn+sync  17 <n> n*(crc 4 + turn u32) 09 fe <...>         -> the embedded 09 is queued (crc pairs: sync check, ignored)
  0a  tick (server -> all, every 100 ms):
                 0a fe <count> count*(<sender idx> <u16 LE len + data>) <m> m*<idx of peers silent in this tick>

The client first sends a preamble: "DWR1" + IPv4 + port of the Relic relay the game wanted (Relay.dll 5-7), or since
Relay.dll 8 "DWR2" + the same + 1 byte (players in the lobby, informational): "DWR2" = the player allows Relic as fallback.
The game opens this connection when a lobby is created (host) or joined (guest) and keeps it through the match.
Compatibility (DWR2): a guest whose session is not here (its host is not on this server) is passed on - to the one of
our other servers (RELAY_PEERS) that has the session, else to the Relic relay its game wanted (the host plays without
the add-on). A guest is told apart by its first peer announce "13 00 .. 0f 05" (it doesn't know its number yet).
Until then hello and ping are answered right away (as Relic would) and the rest is held; when passing on, what the
peer sent goes first and the answers we already gave are not repeated. Servers ask each other "DWRQ" + sid -> Y/N.
Bridge (DWR3, Relay.dll 15, 01.11.2026): "DWR3" + IPv4 + port of the Relic relay - the player plays on Relic (with anybody)
and we only carry the connection: everything is passed on to that Relic relay at once, nothing is hosted here. For players
whose own path to Relic is bad or cut on the way (Russia: DPI on foreign hosting) - the server near them carries it.
Native (02.11.2026, own lobby server experiment): no preamble - the game itself was sent here by our lobby server
(lobby/own_lobby.py answers host/join with this server as the room's relay), so the stream starts with the game's own first
frame (u16 length, then 15 hello). Hosted here like DWR1; a guest whose session is on another of our servers is passed there.
Chain (DWR4, Relay.dll 22, 04.11.2026): "DWR4" + IPv4 + port (BE) of the node of the session (the one our lobby server gave
the game as the room's relay), then the game's native stream. The player can't reach that node itself (no UDP answer, or the
stream check of Relay 18 failed: DPI), so it came to its own best node: this one passes it on to the session's node at once
(player -> this node -> the session's node, never more), hosted here only when that node is this one, the session is here
already, or the node can't be reached (then guests find it here by DWRQ). Our nodes talk to each other over our UDP tunnel
(du_client.py -> the other node's udp_gateway, like du_egress.py): TCP Russia <-> Europe stalls, UDP does not; TCP when the
other node's udp_gateway does not answer (RELAY_PEER_DU=0: TCP only). The same way carries "DWRQ" and every pass-on to ours.
The hop adds the round trip between the two nodes (Poland - Germany ~19 ms, Germany - Moscow ~47, Poland - Moscow ~54) and
about a millisecond in each gateway; no second tick - only the session's node ticks, the passing node carries frames as
they come.
Usage: battle_relay.py [port] [bind]   (default 47100 127.0.0.1)
Peers silent for IDLE seconds are dropped (the game pings every ~3 s).
Monitoring (05.11.2026): every RELAY_STATS_EVERY s (15) one ev=session_stats line per live session: members, and per player
for that interval turns, stalls (gaps > GAP), the longest stall, messages/s and KB/s that came from him, his send buffer.
"""
import asyncio, ipaddress, json, os, socket, struct, sys, time
try: import du_client                                # the UDP tunnel between our nodes (same directory)
except Exception: du_client = None

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 47100
BIND = sys.argv[2] if len(sys.argv) > 2 else '127.0.0.1'
TICK = 0.1
IDLE = 60
DECIDE = 5                                          # s: no peer announce from a new session's first peer -> it's the host
RETRY = 8                                           # s: a guest whose session no node has yet asks our other nodes again (DWR1 / native)
PEERS = [h for h in os.environ.get('RELAY_PEERS', '83.217.192.34,116.202.106.150,15.220.68.107,91.107.122.186').split(',') if h]
PEER_DU = os.environ.get('RELAY_PEER_DU', '1') != '0' and du_client is not None   # our other nodes over UDP (udp_gateway), else TCP


def _hp(h):                                         # "ip" or "ip:port" of RELAY_PEERS
    return (h.rsplit(':', 1)[0], int(h.rsplit(':', 1)[1])) if ':' in h else (h, PORT)


def _local(ip):                                     # an address of this machine (a node behind NAT - AWS - does not know its own)
    try:
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); u.connect((ip, 9)); me = u.getsockname()[0]; u.close()
        return me == ip
    except Exception: return False


SELF = set(x for x in os.environ.get('RELAY_SELF', '').split(',') if x) | {h for h, _ in map(_hp, PEERS) if _local(h)}
_last_warn = {}
LOG = os.environ.get('RELAY_LOG', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'battle_relay.jsonl'))
sessions = {}                                       # sid bytes -> Session
GAP = 0.25                                          # s: a player's turns this far apart count as a stall (a lost packet, a hiccup)
TCP_QUICKACK, TCP_THIN_LINEAR_TIMEOUTS = 12, 16     # Linux socket options (not in the socket module everywhere)


def tcp_info(w):
    # (rtt ms, rttvar ms, retransmitted segments in all, lost now) of a peer connection, from Linux TCP_INFO; None elsewhere
    try:
        b = w.get_extra_info('socket').getsockopt(socket.IPPROTO_TCP, socket.TCP_INFO, 104)
        lost, rtt, rttvar, total = struct.unpack_from('<I', b, 32)[0], struct.unpack_from('<I', b, 68)[0], struct.unpack_from('<I', b, 72)[0], struct.unpack_from('<I', b, 100)[0]
        return rtt // 1000, rttvar // 1000, total, lost
    except Exception: return None


def tcp_stats(sock):
    """the TCP state of one connection from Linux TCP_INFO (struct tcp_info, linux/tcp.h), {} elsewhere: rtt/rttvar/min_rtt/rto
    in ms, retrans = segments out again right now, lost = counted lost right now, total_retrans = in all, backoff = RTOs in a
    row, cwnd, unacked, bytes_retrans, last_rx_ms = since the last data came in"""
    try: b = sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_INFO, 232)
    except Exception: return {}
    u = lambda o: struct.unpack_from('<I', b, o)[0] if len(b) >= o + 4 else None
    d = dict(rtt=u(68), rttvar=u(72), rto=u(8), retrans=u(36), lost=u(32), total_retrans=u(100), backoff=b[4] if len(b) > 4 else None,
             cwnd=u(80), unacked=u(24), last_rx_ms=u(52), min_rtt=u(148))
    for k in ('rtt', 'rttvar', 'rto', 'min_rtt'):
        if d[k] is not None: d[k] = round(d[k] / 1000, 1)
    if len(b) >= 216: d['bytes_retrans'] = struct.unpack_from('<Q', b, 208)[0]
    return {k: v for k, v in d.items() if v is not None}


def log(**k):
    k['t'] = round(time.time(), 3)
    with open(LOG, 'a') as f: f.write(json.dumps(k) + '\n')
    print(time.strftime('%T'), ' '.join(f'{a}={b}' for a, b in k.items() if a != 't'), flush=True)


class Peer:
    def __init__(self, w, addr):
        self.w, self.addr, self.sess, self.idx, self.pid = w, addr, None, 0, b''
        # what the connection was like, for the log when the player leaves: stalls in the turns (GAP), the longest one,
        # TCP rtt (the worst seen) and retransmissions, how far the player's send buffer got behind
        self.turns, self.last_turn, self.gaps, self.max_gap, self.max_rtt, self.retrans, self.max_buf = 0, 0.0, 0, 0.0, 0, 0, 0
        self.iv = dict(turns=0, gaps=0, max_gap=0.0, msgs=0, bytes=0)   # since the last session_stats line (STATS_EVERY)

    def stats(self):
        i = tcp_info(self.w)
        if i:
            self.max_rtt = max(self.max_rtt, i[0]); self.retrans = i[2]
        return dict(peer=self.addr, idx=self.idx, turns=self.turns, gaps=self.gaps, max_gap_ms=round(self.max_gap * 1000),
                    rtt_ms=i[0] if i else None, rttvar_ms=i[1] if i else None, max_rtt_ms=self.max_rtt, retrans=self.retrans,
                    max_buf=self.max_buf)

    def send(self, m):
        if self.w.is_closing(): return
        self.w.write(len(m).to_bytes(2, 'big') + m)


class Session:
    def __init__(self, sid):
        self.sid, self.peers, self.next_idx, self.queue, self.ticker = sid, [], 1, [], None
        self.by_pid = {}                                  # player id -> its number in this session
        self.started = time.time(); self.ticks = 0; self.turn_msgs = 0; self.late = 0; self.max_late = 0.0

    def join(self, p):
        # 30.10.2026: a number per PLAYER, not per connection - the host numbers the players itself in the order they came
        # and a player who connects again (the same id) keeps the number; with a new number per connection the host's
        # messages to the next newcomer went to a number nobody had, and every later guest of that lobby failed to join
        old = [q for q in self.peers if q.pid == p.pid]
        for q in old:
            self.peers.remove(q)
            try: q.w.close()
            except Exception: pass
        if p.pid in self.by_pid: p.idx = self.by_pid[p.pid]
        else: p.idx = self.by_pid[p.pid] = self.next_idx; self.next_idx += 1
        p.sess = self; self.peers.append(p)

    def leave(self, p):
        if p in self.peers: self.peers.remove(p)
        if not self.peers:
            if self.ticker: self.ticker.cancel()
            sessions.pop(self.sid, None)
            log(ev='session_end', sid=int.from_bytes(self.sid, 'little'), secs=round(time.time() - self.started), ticks=self.ticks, turns=self.turn_msgs,
                late_ticks=self.late, max_late_ms=round(self.max_late * 1000))

    def queue_turn(self, p, data):
        self.queue.append((p.idx, data)); self.turn_msgs += 1
        now = time.monotonic()
        if p.last_turn:
            g = now - p.last_turn
            if g > GAP: p.gaps += 1; p.iv['gaps'] += 1
            p.max_gap = max(p.max_gap, g); p.iv['max_gap'] = max(p.iv['max_gap'], g)
        p.last_turn = now; p.turns += 1; p.iv['turns'] += 1
        if not self.ticker: self.ticker = asyncio.ensure_future(self.tick_loop())

    async def tick_loop(self):
        nxt = time.monotonic()
        while self.peers:
            nxt += TICK
            await asyncio.sleep(max(0, nxt - time.monotonic()))
            late = time.monotonic() - nxt                    # the tick went out this much after its time
            if late > 0.03: self.late += 1
            self.max_late = max(self.max_late, late)
            if late > 0.5: nxt = time.monotonic()            # after a long hold: carry on from now, no burst of catch-up ticks
            q, self.queue = self.queue, []
            sent = {i for i, _ in q}
            silent = [p.idx for p in self.peers if p.idx not in sent]
            m = bytearray(b'\x0a\xfe') + bytes([len(q)])
            for i, d in q: m += bytes([i]) + d
            m += bytes([len(silent)]) + bytes(silent)
            for p in list(self.peers): p.send(bytes(m))
            self.ticks += 1
            # no waiting here for the players' connections to take the data (that held the tick for everyone when one
            # player's connection stalled): the data sits in that player's buffer, which is watched instead
            for p in self.peers:
                try: p.max_buf = max(p.max_buf, p.w.transport.get_write_buffer_size())
                except Exception: pass
            if self.ticks % 50 == 0:
                for p in self.peers: p.stats()                # the worst rtt is sampled every 5 s


def proxy_split(m):
    """a 0x10 frame (RLink ProxyMessage) -> [(dst, frame for that dst only)], None when it does not parse.
    Layout (captures of Relic's relay 27.10, every 0x10 frame of m1/m3 fits): 10 <src> <n u16 LE> n*<dst u8> <u16 LE len>
    <payload>; the payload ends with n infos of 15 bytes, one per dst in the list order (ProxyMessage::GetProxyInfos reads
    them from the end, FUN_006400c0). The game sends ONE such message for several peers (the host's and every peer's
    messages to the others) and the relay hands each listed peer its own copy - 05.11.2026: we passed it unchanged to
    EVERY other peer, which is the same with 2 players but with 3+ every peer got the messages meant for the others
    ("dropping PROXY message from peerID 4 via peerID 4 for peer 3 (we're not host)" by the thousand), the host passed them
    on once more, the reliable layers retried, and a 2v2 / 3v3 sent 300-2400 packets/s per player (Relic: ~10/s).
    One dst: the frame as it came (byte for byte what Relic gave in the captures)."""
    if len(m) < 7: return None
    n = m[2] | m[3] << 8
    o = 4 + n
    if n < 1 or n > 16 or len(m) < o + 2: return None
    size = m[o] | m[o + 1] << 8
    if len(m) != o + 2 + size or size < 15 * n: return None
    dsts = m[4:o]
    if n == 1: return [(dsts[0], m)]
    data, infos = m[o + 2:len(m) - 15 * n], m[len(m) - 15 * n:]
    out = []
    for i, d in enumerate(dsts):
        body = data + infos[15 * i:15 * i + 15]
        out.append((d, bytes([0x10, m[1], 1, 0, d]) + len(body).to_bytes(2, 'little') + body))
    return out


STATS_EVERY = float(os.environ.get('RELAY_STATS_EVERY', '15'))   # s: a session_stats line per live session (owner 05.11.2026)


async def stats_loop():
    """live monitoring: every STATS_EVERY s one line per live session - its members and, per player, what came from him in
    that interval: turns, stalls (turns more than GAP apart), the longest stall, messages and bytes of every kind (a storm
    shows as msgs/s far above the ~10-20 turns+messages a second of a normal game)"""
    while True:
        await asyncio.sleep(STATS_EVERY)
        for s in list(sessions.values()):
            if not s.peers: continue
            pl = {}
            for p in s.peers:
                iv = p.iv
                pl[str(p.idx)] = dict(turns=iv['turns'], gaps=iv['gaps'], max_gap_ms=round(iv['max_gap'] * 1000),
                                      msgs_s=round(iv['msgs'] / STATS_EVERY, 1), kbps_in=round(iv['bytes'] / STATS_EVERY / 1024, 1),
                                      buf=p.w.transport.get_write_buffer_size() if not p.w.is_closing() else None)
                p.iv = dict(turns=0, gaps=0, max_gap=0.0, msgs=0, bytes=0)
            log(ev='session_stats', sid=int.from_bytes(s.sid, 'little'), members=len(s.peers), secs=round(time.time() - s.started),
                late_ticks=s.late, players=pl)


def handle_msg(p, m, echo=True):
    p.iv['msgs'] += 1; p.iv['bytes'] += len(m) + 2
    t = m[0]
    if t == 0x15:                                                   # hello: join the session
        sid = m[1:5]
        if p.sess is None:
            s = sessions.get(sid) or sessions.setdefault(sid, Session(sid))
            p.pid = m[9:17]; s.join(p)
            log(ev='join', sid=int.from_bytes(sid, 'little'), idx=p.idx, peer=p.addr, pid=p.pid.hex(), members=len(s.peers))
        if echo: p.send(m)
        return
    if t == 0x14:                                                    # ping
        if echo: p.send(m)
        return
    s = p.sess
    if s is None: log(ev='no_session', type=t, peer=p.addr); return
    if t == 0x13:
        inner = m[3:]
        if inner[:2] == b'\x0f\x05' and m[1] == 0 and len(s.peers) == 1:   # a guest (does not know its number yet) alone here:
            log(ev='mixed', sid=int.from_bytes(s.sid, 'little'), peer=p.addr)  # this lobby's host plays on Relic's servers
            p.w.write(b'DWRERR:mixed\n'); p.w.close(); return              # Relay.dll 7 shows why and closes the game
        if inner[:2] == b'\x0f\x05':                                 # peer announce: everyone, header stripped
            for q in s.peers: q.send(inner)
            return
        dst = m[1]
        targets = [q for q in s.peers if q.idx == dst] if dst else list(s.peers)
        if not targets:                                              # e.g. the game still talks to a peer that left: log once a minute
            k = (s.sid, dst); now = time.time()
            if now - _last_warn.get(k, 0) > 60: _last_warn[k] = now; log(ev='no_target', sid=int.from_bytes(s.sid, 'little'), dst=dst, src=p.idx)
        for q in targets: q.send(m)
        return
    if t == 0x10:
        parts = proxy_split(m)
        if parts is None:                                            # not the layout we know: as before (log once a minute)
            k = (s.sid, 'proxy'); now = time.time()
            if now - _last_warn.get(k, 0) > 60: _last_warn[k] = now; log(ev='proxy_unparsed', sid=int.from_bytes(s.sid, 'little'), len=len(m), head=m[:12].hex())
            others = [q for q in s.peers if q is not p]
            for q in (others or [p]): q.send(m)
            return
        for dst, one in parts:
            # dst 0 (never seen in a capture): as before, everybody else
            targets = [q for q in s.peers if q.idx == dst] if dst else ([q for q in s.peers if q is not p] or [p])
            if not targets:
                k = (s.sid, dst); now = time.time()
                if now - _last_warn.get(k, 0) > 60: _last_warn[k] = now; log(ev='no_target', sid=int.from_bytes(s.sid, 'little'), dst=dst, src=p.idx, proxy=1)
            for q in targets: q.send(one)
        return
    if t == 0x09:
        s.queue_turn(p, m[2:]); return
    if t == 0x17:
        n = m[1]; rest = m[2 + 8 * n:]
        if rest[:1] == b'\x09': s.queue_turn(p, rest[2:])
        return
    log(ev='unknown', type=hex(t), len=len(m), head=m[:24].hex(), peer=p.addr)


async def peer_connect(hp, timeout=10, du=True):
    """a connection to another of our nodes: over our UDP tunnel to its udp_gateway (same port), TCP when that does not
    answer -> (reader, writer, 'du' | 'tcp')"""
    if du and PEER_DU:
        c = await du_client.open_du(*hp)
        if c: return c[0], c[1], 'du'
    r, w = await asyncio.wait_for(asyncio.open_connection(*hp), timeout)
    try: w.get_extra_info('socket').setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except Exception: pass
    return r, w, 'tcp'


async def ask_peer(hp, sid):
    """does that node have the session: "DWRQ" + sid -> Y/N; over UDP, then TCP once more when UDP gave no answer"""
    for du in ((True, False) if PEER_DU else (False,)):
        try:
            r2, w2, _ = await peer_connect(hp, 2, du)
            w2.write(b'DWRQ' + sid); await w2.drain()
            a = await asyncio.wait_for(r2.readexactly(1), 2); w2.close()
            return a == b'Y'
        except Exception: pass
    return False


async def find_peer(sid):
    """which of our other servers has this session (its host) - all asked at once"""
    hps = [hp for hp in map(_hp, PEERS) if hp[0] not in SELF]
    if not hps: return None
    res = await asyncio.gather(*[ask_peer(hp, sid) for hp in hps])
    return next((hp for hp, y in zip(hps, res) if y), None)


class BridgeStats:
    """03.11.2026: what the passed-on connection (our node -> the Relic relay, or -> our other server) was like - logged every
    STATS_EVERY s while it lives (ev=bridge_stats) and when it closes (ev=bridge_end), so that a lag "3-4 minutes into the
    match" shows whether the way from the node (Russia) to Relic stalls or chokes: TCP_INFO of that connection (rtt/rttvar,
    retransmissions, lost, RTOs in a row), the bytes both ways, the longest pause in what Relic sends (it ticks every 100 ms
    in a match: a pause of 250+ ms is a stall), the same for the game's side, and the connection's age."""
    EVERY, SAMPLE, STALL = 30, 1.0, 0.25

    def __init__(self, p, dest, to, usock, du=None):
        self.p, self.dest, self.to, self.usock, self.du = p, f'{dest[0]}:{dest[1]}', to, usock, du
        self.t0 = time.monotonic(); self.up = self.down = self.up_n = self.down_n = 0
        self.last_rx = self.last_tx = None; self.closed_by = None; self.final_tcp = {}
        self.all_rx_gap = self.all_tx_gap = 0.0; self.all_rx_stalls = 0; self.all_max_rtt = 0.0; self.all_max_backoff = 0
        self.new_window()

    def new_window(self):
        self.w_rx_gap = self.w_tx_gap = 0.0; self.w_rx_stalls = 0; self.w_up = self.w_down = 0
        self.w_max_rtt = 0.0; self.w_max_rto = 0.0; self.w_max_backoff = 0; self.w_max_unacked = 0; self.w_max_buf = 0

    def rx(self, n):                                   # a frame from Relic (n bytes with its length)
        now = time.monotonic(); self.down += n; self.w_down += n; self.down_n += 1
        if self.last_rx is not None:
            g = now - self.last_rx
            if g > self.STALL: self.w_rx_stalls += 1; self.all_rx_stalls += 1
            self.w_rx_gap = max(self.w_rx_gap, g); self.all_rx_gap = max(self.all_rx_gap, g)
        self.last_rx = now

    def tx(self, n):                                   # a frame from the game, on its way to Relic
        now = time.monotonic(); self.up += n; self.w_up += n; self.up_n += 1
        if self.last_tx is not None:
            g = now - self.last_tx; self.w_tx_gap = max(self.w_tx_gap, g); self.all_tx_gap = max(self.all_tx_gap, g)
        self.last_tx = now

    def sample(self, uw):                              # every SAMPLE s: the worst of the TCP state between two log lines
        i = tcp_stats(self.usock)
        self.w_max_rtt = max(self.w_max_rtt, i.get('rtt', 0)); self.w_max_rto = max(self.w_max_rto, i.get('rto', 0))
        self.w_max_backoff = max(self.w_max_backoff, i.get('backoff', 0)); self.w_max_unacked = max(self.w_max_unacked, i.get('unacked', 0))
        self.all_max_rtt = max(self.all_max_rtt, self.w_max_rtt); self.all_max_backoff = max(self.all_max_backoff, self.w_max_backoff)
        try: self.w_max_buf = max(self.w_max_buf, uw.transport.get_write_buffer_size())
        except Exception: pass
        # the open pause right now counts too (Relic silent for a while and still silent)
        if self.last_rx is not None: self.w_rx_gap = max(self.w_rx_gap, time.monotonic() - self.last_rx)

    def snap(self):                                    # TCP_INFO before our side closes the socket (it is gone after)
        self.final_tcp = tcp_stats(self.usock) or self.final_tcp

    def line(self, ev):
        now = time.monotonic(); win = ev == 'bridge_stats'
        k = dict(ev=ev, peer=self.p.addr, dest=self.dest, to=self.to, secs=round(now - self.t0),
                 up_bytes=self.up, down_bytes=self.down, up_msgs=self.up_n, down_msgs=self.down_n,
                 tcp=tcp_stats(self.usock) or self.final_tcp)
        if self.du: k['du'] = self.du.du_stats()          # our UDP tunnel to the other node: rtt, resent, lost_in, copies, filled
        if win:
            k.update(win_up=self.w_up, win_down=self.w_down, max_rx_gap_ms=round(self.w_rx_gap * 1000), rx_stalls=self.w_rx_stalls,
                     max_tx_gap_ms=round(self.w_tx_gap * 1000), max_rtt=self.w_max_rtt, max_rto=self.w_max_rto,
                     max_backoff=self.w_max_backoff, max_unacked=self.w_max_unacked, max_buf=self.w_max_buf)
        else:
            k.update(closed_by=self.closed_by, max_rx_gap_ms=round(self.all_rx_gap * 1000), rx_stalls=self.all_rx_stalls,
                     max_tx_gap_ms=round(self.all_tx_gap * 1000), max_rtt=self.all_max_rtt, max_backoff=self.all_max_backoff,
                     since_rx_ms=round((now - self.last_rx) * 1000) if self.last_rx is not None else None)
        log(**k)
        if win: self.new_window()


async def pass_on(q, w, p, dest, held, answered, pre=b'', why=None):
    """pass this peer on (to our other server or to the Relic relay its game wanted): what it sent so far, then both
    ways as they are. False = that server could not be reached (nothing was sent to the game)"""
    how = 'tcp'
    try:
        if pre: ur, uw, how = await peer_connect(dest, 3)   # ours: our UDP tunnel when its udp_gateway answers (1.5 s), else TCP (3 s)
        else: ur, uw = await asyncio.wait_for(asyncio.open_connection(*dest), 10)
    except Exception as e:
        log(ev='pass_fail', peer=p.addr, dest=f'{dest[0]}:{dest[1]}', err=repr(e)); return False
    usock = uw.get_extra_info('socket')
    try: usock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except Exception: pass
    to = 'ours' if pre else ('relic' if held else 'relic_bridge')
    log(ev='pass_on', peer=p.addr, dest=f'{dest[0]}:{dest[1]}', to=to, held=len(held), via=how, **({'why': why} if why else {}))
    st = BridgeStats(p, dest, to, usock, uw if how == 'du' else None)
    if pre: uw.write(pre)
    for m in held: uw.write(len(m).to_bytes(2, 'big') + m); st.tx(len(m) + 2)
    await uw.drain()

    async def up():                                     # game -> Relic, frame by frame as it came
        try:
            while True:
                m = await q.get()
                if m is None: st.closed_by = st.closed_by or 'game'; break
                uw.write(len(m).to_bytes(2, 'big') + m); st.tx(len(m) + 2); await uw.drain()
        except Exception as e: st.closed_by = st.closed_by or f'up:{type(e).__name__}'
        finally: st.snap(); uw.close()

    async def down():                                   # Relic -> game; its echoes of hello/ping we answered already are dropped
        try:
            while True:
                n = int.from_bytes(await ur.readexactly(2), 'big')
                m = await ur.readexactly(n) if n else b''
                st.rx(n + 2)
                if answered and m in answered: answered.remove(m); continue
                w.write(n.to_bytes(2, 'big') + m); await w.drain()
        except asyncio.IncompleteReadError: st.closed_by = st.closed_by or 'relic'
        except Exception as e: st.closed_by = st.closed_by or f'down:{type(e).__name__}'
        finally: st.snap(); w.close()

    async def watch():                                  # the TCP state every second, a log line every 30 s
        n = 0
        while True:
            await asyncio.sleep(st.SAMPLE); n += 1
            st.sample(uw)
            if n % int(st.EVERY / st.SAMPLE) == 0: st.line('bridge_stats')
    wt = asyncio.ensure_future(watch())
    try: await asyncio.gather(up(), down())
    finally:
        wt.cancel()
        try: st.sample(uw)
        except Exception: pass
        st.line('bridge_end')
    return True


async def handle(r, w):
    sock = w.get_extra_info('socket')
    for opt in (socket.TCP_NODELAY, TCP_THIN_LINEAR_TIMEOUTS):   # thin stream: a lost packet is sent again without the
        try: sock.setsockopt(socket.IPPROTO_TCP, opt, 1)           # exponential back-off of the timeouts
        except Exception: pass
    a = w.get_extra_info('peername'); p = Peer(w, f'{a[0]}:{a[1]}')
    q = asyncio.Queue(); rt = None

    async def reader(first=None):                       # one reader per peer: frames into q, None at the end
        try:
            if first is not None: await q.put(first)
            while True:
                n = int.from_bytes(await r.readexactly(2), 'big')
                await q.put(await r.readexactly(n) if n else b'')
                try: sock.setsockopt(socket.IPPROTO_TCP, TCP_QUICKACK, 1)   # acknowledge at once: the player's next turn
                except Exception: pass                                    # does not wait for our delayed ack
        except Exception: pass
        await q.put(None)
    try:
        pre = await asyncio.wait_for(r.readexactly(4), 15)
        if pre == b'DWRQ':                              # another server of ours asks: is this session here?
            sid = await asyncio.wait_for(r.readexactly(4), 5)
            w.write(b'Y' if sid in sessions else b'N'); await w.drain(); w.close(); return
        native = None
        if pre[:3] != b'DWR':                           # native: our lobby server sent the game here, pre = its first frame's start
            n = int.from_bytes(pre[:2], 'big')
            if n < 2 or pre[2] != 0x15: log(ev='bad_preamble', peer=p.addr, hex=pre.hex()); w.close(); return
            native = pre[2:4] + await asyncio.wait_for(r.readexactly(n - 2), 15)
            pre = b'DWR1' + b'\0' * 6                   # hosted here; no Relic relay behind it
            log(ev='native', peer=p.addr)
        else:
            pre += await asyncio.wait_for(r.readexactly(6), 15)
        if pre[:4] == b'DWR3':                    # bridge: straight on to the Relic relay the game wanted
            dest = (socket.inet_ntoa(pre[4:8]), int.from_bytes(pre[8:10], 'big'))
            ip = ipaddress.ip_address(dest[0])          # only Relic relay ports on public addresses: not an open proxy
            if not 27000 <= dest[1] <= 27099 or not ip.is_global:
                log(ev='bridge_refused', peer=p.addr, dest=f'{dest[0]}:{dest[1]}'); w.close(); return
            rt = asyncio.ensure_future(reader())
            await pass_on(q, w, p, dest, [], []); return
        chain = None
        if pre[:4] == b'DWR4':                          # Relay 22: the player can't reach the session's node - it came here
            chain = socket.inet_ntoa(pre[4:8])
            log(ev='chain', peer=p.addr, node=f'{chain}:{int.from_bytes(pre[8:10], "big")}')
            pre = b'DWR1' + b'\0' * 6                   # what this node does with it, if it does not pass it on: native
        if pre[:4] not in (b'DWR1', b'DWR2'): log(ev='bad_preamble', peer=p.addr, hex=pre.hex()); w.close(); return
        compat = pre[:4] == b'DWR2'
        if compat: await asyncio.wait_for(r.readexactly(1), 15)
        rt = asyncio.ensure_future(reader(native))
        if True:   # 30.10.2026: a guest whose lobby is on another of our servers is passed on there in the strict mode (DWR1) too
            relic = (socket.inet_ntoa(pre[4:8]), int.from_bytes(pre[8:10], 'big'))
            held, answered, sid = [], [], None
            if chain:                                   # up to the hello (the session), nothing answered: the session's node answers
                while sid is None and len(held) < 64:
                    m = await asyncio.wait_for(q.get(), IDLE)
                    if m is None: return
                    held.append(m)
                    if m[:1] == b'\x15': sid = m[1:5]
                hp = next((hp for hp in map(_hp, PEERS) if hp[0] == chain), None)
                if hp and chain not in SELF and sid is not None and sid not in sessions:
                    if await pass_on(q, w, p, hp, held, [], pre=b'DWR1' + b'\0' * 6, why='chain'): return
                # hosted here: the session's node is this one / not ours / can't be reached, or the session is here already
                log(ev='chain_here', peer=p.addr, node=chain, sid=int.from_bytes(sid, 'little') if sid else None,
                    why='self' if chain in SELF else 'not ours' if not hp else 'session here' if sid in sessions else 'unreachable')
                for m in held:
                    if m[:1] in (b'\x15', b'\x14'): p.send(m); answered.append(m)
            while sid is None and len(held) < 64:
                m = await asyncio.wait_for(q.get(), IDLE)
                if m is None: return
                held.append(m)
                if m[:1] in (b'\x15', b'\x14'): p.send(m); answered.append(m)
                if m[:1] == b'\x15': sid = m[1:5]
            away, end = False, time.time() + DECIDE
            while sid is not None and sid not in sessions:   # a new session here: its host, or a guest whose host is elsewhere?
                try: m = await asyncio.wait_for(q.get(), max(0.05, end - time.time()))
                except asyncio.TimeoutError: break           # no announce: the host
                if m is None: return
                held.append(m)
                if m[:1] in (b'\x15', b'\x14'): p.send(m); answered.append(m); continue
                away = m[:1] == b'\x13' and m[1] == 0 and m[3:5] == b'\x0f\x05'
                break
            if away and sid not in sessions:
                h = await find_peer(sid)
                # 04.11.2026: no node has it yet and there is no Relic to fall back to (DWR1 / native) - its host may be on the way
                # (a chained host is passed on, or hosted on its own node only after the hop failed): ask again for a few seconds
                retry_end = time.time() + (RETRY if not compat else 0)
                while not h and sid not in sessions and time.time() < retry_end:
                    await asyncio.sleep(1); h = sid not in sessions and await find_peer(sid)
                if h and await pass_on(q, w, p, h, held, answered, pre=b'DWR1' + pre[4:10]): return
                if compat: await pass_on(q, w, p, relic, held, answered); return
                # strict (DWR1) and none of ours has it: the lobby is on Relic - handled below ("mixed", Relay.dll explains)
            for m in held:
                if m: handle_msg(p, m, echo=False)
        while True:
            m = await asyncio.wait_for(q.get(), IDLE)
            if m is None: break
            if m: handle_msg(p, m)
            await w.drain()
    except (asyncio.IncompleteReadError, ConnectionError, asyncio.TimeoutError): pass
    except Exception as e: log(ev='error', peer=p.addr, err=repr(e))
    finally:
        if rt: rt.cancel()
        if p.sess:
            log(ev='leave', sid=int.from_bytes(p.sess.sid, 'little'), **p.stats())
            p.sess.leave(p)
        try: w.close()
        except Exception: pass


async def main():
    srv = await asyncio.start_server(handle, BIND, PORT)
    log(ev='start', bind=BIND, port=PORT)
    if STATS_EVERY > 0: asyncio.ensure_future(stats_loop())
    async with srv: await srv.serve_forever()

if __name__ == '__main__':
    asyncio.run(main())
