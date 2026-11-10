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
Connection test (DWRT, launcher 1.4.15, 06.11.2026): "DWRT" + version (1) + players (2 / 4 / 6) + seconds (<= 90) + flags +
2 reserved, then the game's own stream - hello, turns 0x17 ten a second, pings 0x14, proxy messages 0x10 to the other players.
Nothing of it touches the real sessions (never in `sessions`, DWRQ says N): the player is number 1 of a session of its own and
the others are virtual players here - each puts a turn into every 100 ms tick, sends the player proxy messages and now and
then a big 0x13 at the rates of a real 1v1 / 2v2 / 3v3, and answers every proxy message part it gets at once (so the launcher
sees the way there and back, and that each part reached the right player only). At the end one "7e" + JSON frame with what
came up here (turns, their stalls, proxy parts). udp_gateway puts the player's address in ("DWRU" + IPv4, only from loopback):
at most TEST_ADDR_LIVE tests at once and TEST_ADDR_RUNS in TEST_ADDR_WINDOW s from one address, TEST_LIVE_MAX on the node.
Usage: battle_relay.py [port] [bind]   (default 47100 127.0.0.1)
Peers silent for IDLE seconds are dropped (the game pings every ~3 s).
Reconnect (06.11.2026, feature/relay-reconnect, NOT deployed): the game's relay client reconnects on its own when its
connection breaks (RLink BattleServerRelay, RL_EnableReconnections default 1, RL_ClientReconnectMS default 15000) and its
hello then says how far it got: 15 <sid 4> 00000000 <id 8> 02 <game frames received, u32 LE> (DOW2.exe 0x63FB10 / 0x63FBD0;
flag 0 and no count = a first connection). Relic's relay sends the frames it missed; this one did not - the player came back
into the session (the same number, by player id) but without the ticks of the gap. Now every session keeps its ticks
(HISTORY at most) and a reconnecting player gets the ticks from his count on, before the live ones.
Live replay (DWRL, 06.11.2026): a spectator watches a running match as a replay that keeps growing, LIVE_DELAY s behind (the
floor here, whatever is asked: no peeking at a running match). Every session keeps the host's lobby state and the start message
(the 0x10 messages before the start, unpacked only until the start) and the time of each tick; live_rec.py makes the .rec of
it. "DWRL" + sid (4) + from record (u32 LE) + delay s (u32 LE) + game (1: 0 Elite, 1 vanilla) -> one envelope, then the
connection closes: "DWLR" ver flags available ticks header_len header body_len records[from:available] json_len json (all u32
LE; flags 1 = over and all given, 2 = not started / no lobby state, 4 = no such session). The ladder asks (its /live/ API).
A session that ended stays LIVE_KEEP s for the spectators who are behind.
Monitoring (05.11.2026): every RELAY_STATS_EVERY s (15) one ev=session_stats line per live session: members, and per player
for that interval turns, stalls (gaps > GAP), the longest stall, messages/s and KB/s that came from him, his send buffer.
Node quality per player (06.11.2026): the "leave" line of a player carries his Steam id (from his peer announce) and "solo" /
max_solo_ms - his stalls >= SOLO_GAP while the others' turns kept coming (his way here stuck, not the match); the ladder's
nodeq_collect.py joins it with the UDP gateway's "close" line of his connection (by the local port, "lport" there) for the
losses, and stops using a node that is bad for a player (ladder/nodeq.py).
"""
import asyncio, ipaddress, json, os, socket, struct, sys, time
try: import du_client                                # the UDP tunnel between our nodes (same directory)
except Exception: du_client = None
try: import live_rec                                  # the live replay: a running match as a replay (same directory)
except Exception: live_rec = None

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 47100
BIND = sys.argv[2] if len(sys.argv) > 2 else '127.0.0.1'
TICK = 0.1
IDLE = 60
HISTORY = int(os.environ.get('RELAY_HISTORY', '72000'))   # ticks a session keeps for reconnects (2 h of 0.1 s)
GRACE = float(os.environ.get('RELAY_RECONNECT_GRACE', '45'))  # s a player whose connection broke mid-game stays in the ticks (silent)
LONG_GRACE = float(os.environ.get('RELAY_REJOIN_GRACE', '170'))   # the same for a game whose Relay.dll (24+) keeps trying 3 min ("DWR5"): it gives up 180 s after its last data, we see the drop ~20 s after it (the UDP gateway's dead timer)
LAG = 3.0                                           # s without turns from a connected player: the others are told he is silent
VOTE = 0x7d                                         # Relay 25: "don't wait" from a DWR5 game: 7d <number of the player waited for>
NOTICE = 0x7e                                       # our own frame to "DWR5" games: who is away and how long more; Relay.dll takes it out
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
try: NODE = os.environ.get('RELAY_NODE') or socket.gethostname()   # the match protocol's "node" (the collector knows the ip anyway)
except Exception: NODE = ''
sessions = {}                                     # sid bytes -> Session
finished = {}                                       # sid bytes -> (Session, when it ended): for the live replay's spectators
LIVE_DELAY = float(os.environ.get('LIVE_DELAY', '120'))   # s: the least delay of the live replay (the server's setting)
LIVE_KEEP = float(os.environ.get('LIVE_KEEP', '1200'))    # s an ended session stays for spectators
LIVE_MAX = 6 * 1024 * 1024                          # bytes of records in one answer at most (the ladder asks again for the rest)
GAP = 0.25                                          # s: a player's turns this far apart count as a stall (a lost packet, a hiccup)
SOLO_GAP = 1.0                                      # s: a stall of one player alone this long counts against his way to this node
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


_mlog_errs = [0]
def mlog_err(where, e):
    """the match protocol (own rating step 1b, 10.11.2026: one "match_log" line per played session) never stops the relay:
    an error of it is logged (the first 20 of the process) and forgotten"""
    _mlog_errs[0] += 1
    if _mlog_errs[0] <= 20:
        try: log(ev='mlog_error', where=where, err=repr(e))
        except Exception: pass


class Peer:
    def __init__(self, w, addr):
        self.w, self.addr, self.sess, self.idx, self.pid = w, addr, None, 0, b''
        # what the connection was like, for the log when the player leaves: stalls in the turns (GAP), the longest one,
        # TCP rtt (the worst seen) and retransmissions, how far the player's send buffer got behind
        self.turns, self.last_turn, self.gaps, self.max_gap, self.max_rtt, self.retrans, self.max_buf = 0, 0.0, 0, 0.0, 0, 0, 0
        self.iv = dict(turns=0, gaps=0, max_gap=0.0, msgs=0, bytes=0)   # since the last session_stats line (STATS_EVERY)
        self.rejoin = False                               # "DWR5": its Relay.dll keeps reconnecting for 3 min and reads our notices
        self.solo, self.max_solo = 0, 0.0                 # stalls >= SOLO_GAP of his alone (the others' turns kept coming)
        self.turn_mark = 0                                # the session's turn count at his last turn
        self.why = None                                   # why the connection ended: fin / reset / idle / replaced / vote_drop / error
        self.pl = None                                    # his record in Session.plog (the match protocol)

    def stats(self):
        i = tcp_info(self.w)
        if i:
            self.max_rtt = max(self.max_rtt, i[0]); self.retrans = i[2]
        st = self.sess.steams.get(self.idx, '') if self.sess else ''
        return dict(peer=self.addr, idx=self.idx, **({'steam': st} if st else {}), solo=self.solo, max_solo_ms=round(self.max_solo * 1000),
                    turns=self.turns, gaps=self.gaps, max_gap_ms=round(self.max_gap * 1000),
                    rtt_ms=i[0] if i else None, rttvar_ms=i[1] if i else None, max_rtt_ms=self.max_rtt, retrans=self.retrans,
                    max_buf=self.max_buf)

    def send(self, m):
        if self.w.is_closing(): return
        self.w.write(len(m).to_bytes(2, 'big') + m)


class Session:
    def __init__(self, sid):
        self.sid, self.peers, self.next_idx, self.queue, self.ticker = sid, [], 1, [], None
        self.by_pid = {}                                  # player id -> its number in this session
        self.history = []                                 # every tick sent (0x0a frames), for players who reconnect
        self.tick_t = []                                  # the time each of them went out (the live replay's delay)
        self.lobby = self.start_msg = None                # the host's lobby state and the match start (the live replay's header)
        self.live = {}                                    # game ('elite' / 'vanilla') -> live_rec.LiveRec, built on the first request
        self.rx = {}                                      # player id -> game messages (0x09 / 0x17) received from him
        self.away = {}                                    # player id -> (his number, until): connection broke mid-game
        self.gone = set()                                 # player ids whose GRACE ran out: the others have dropped them
        self.names = {}                                   # number -> the player's name (from his peer announce)
        self.steams = {}                                  # number -> his Steam id (the same announce; node quality per player)
        self.lagging = set()                              # numbers told as "silent" (connected, no turns for LAG s)
        self.votes = {}                                   # number waited for -> player ids that voted "don't wait"
        self.started = time.time(); self.ticks = 0; self.turn_msgs = 0; self.late = 0; self.max_late = 0.0
        self.plog = {}                                    # player id -> his record for the "match_log" line (10.11.2026)

    def _plog_join(self, p, a):
        r = self.plog.get(p.pid)
        if r is None:
            r = self.plog[p.pid] = dict(idx=p.idx, join_t=round(time.time(), 3), rejoins=0, ftt=None, ltt=None, leave_t=None,
                                        leave_tick=None, leave_turns=None, reason=None, away_s=0.0, solo=0, max_solo_ms=0,
                                        gaps=0, max_gap_ms=0, turns=0, drops=[], peer=p.addr)
        else:
            r['rejoins'] += 1; r['peer'] = p.addr
            r['leave_t'] = r['leave_tick'] = r['leave_turns'] = r['reason'] = None
            if a: r['away_s'] += time.monotonic() - a[2]
        p.pl = r

    def _plog_leave(self, p, why):
        r = p.pl
        if r is None: return
        r['solo'] += p.solo; r['gaps'] += p.gaps; r['turns'] += p.turns
        r['max_solo_ms'] = max(r['max_solo_ms'], round(p.max_solo * 1000)); r['max_gap_ms'] = max(r['max_gap_ms'], round(p.max_gap * 1000))
        if len(r['drops']) < 20: r['drops'].append([round(time.time() - self.started, 1), self.ticks, why])
        if any(q.pid == p.pid for q in self.peers): return     # his newer connection is here already (replaced)
        r['leave_t'] = round(time.time(), 3); r['leave_tick'] = self.ticks; r['leave_turns'] = self.turn_msgs; r['reason'] = why

    def _plog_gone(self, pid, why, a):
        r = self.plog.get(pid)
        if r is None: return
        r['conn_reason'] = r['reason']; r['reason'] = why; r['drop_t'] = round(time.time(), 3); r['drop_tick'] = self.ticks
        if a: r['away_s'] += time.monotonic() - a[2]

    def match_log(self):
        now = time.time(); pl = []
        for pid, r in self.plog.items():
            x = dict(r); i = r['idx']
            x.update(pid=pid.hex(), steam=self.steams.get(i, ''), name=self.names.get(i, ''), first_turn_tick=x.pop('ftt'),
                     last_turn_tick=x.pop('ltt'), away_s=round(r['away_s'], 1), gw_reason=None)
            pl.append(x)
        lt = [x['leave_t'] for x in pl if x['leave_t']]
        return dict(ev='match_log', v=1, sid=int.from_bytes(self.sid, 'little'), node=NODE, started=round(self.started, 3),
                    t0=round(self.tick_t[0], 3) if self.tick_t else None, t_end=round(now, 3), ticks=self.ticks, turns=self.turn_msgs,
                    late_ticks=self.late, players=pl,
                    all_gone_within_s=round(max(lt) - min(lt), 1) if lt and len(lt) == len(pl) else None)

    def join(self, p):
        # 30.10.2026: a number per PLAYER, not per connection - the host numbers the players itself in the order they came
        # and a player who connects again (the same id) keeps the number; with a new number per connection the host's
        # messages to the next newcomer went to a number nobody had, and every later guest of that lobby failed to join
        old = [q for q in self.peers if q.pid == p.pid]
        for q in old:
            self.peers.remove(q); q.why = q.why or 'replaced'
            try: q.w.close()
            except Exception: pass
        if p.pid in self.by_pid: p.idx = self.by_pid[p.pid]
        else: p.idx = self.by_pid[p.pid] = self.next_idx; self.next_idx += 1
        p.sess = self; self.peers.append(p)
        a = self.away.pop(p.pid, None)
        try: self._plog_join(p, a)
        except Exception as e: mlog_err('join', e)
        if a:
            log(ev='back', sid=int.from_bytes(self.sid, 'little'), idx=p.idx, peer=p.addr, after_s=round(time.monotonic() - a[2], 1))
            self.votes.pop(p.idx, None)
            self.notice(a[0], None)

    def leave(self, p, why=None):
        if p in self.peers: self.peers.remove(p)
        try: self._plog_leave(p, p.why or why or 'closed')
        except Exception as e: mlog_err('leave', e)
        # 06.11.2026: a player whose connection breaks in the match stays in the ticks as silent for GRACE s - the game reconnects
        # by itself 15 s after the break; a player missing from a tick (neither sent nor silent) is dropped by the others at once
        if self.ticks and GRACE > 0 and p.pid and p.pid not in self.gone and not any(q.pid == p.pid for q in self.peers):
            g = LONG_GRACE if p.rejoin else GRACE
            self.away[p.pid] = (p.idx, time.monotonic() + g, p.last_turn or time.monotonic())   # away since his last turn
            log(ev='away', sid=int.from_bytes(self.sid, 'little'), idx=p.idx, peer=p.addr, grace=g, name=self.names.get(p.idx, ''))
            self.lagging.discard(p.idx)
        if not self.peers and not self.away: self.end()   # everyone away (the node's own network?): the ticks go on until GRACE

    def end(self):
        if sessions.get(self.sid) is not self: return
        if self.ticker and self.ticker is not asyncio.current_task(): self.ticker.cancel()
        sessions.pop(self.sid, None)
        if self.ticks and self.lobby and self.start_msg: finished[self.sid] = (self, time.time())   # spectators are minutes behind
        log(ev='session_end', sid=int.from_bytes(self.sid, 'little'), secs=round(time.time() - self.started), ticks=self.ticks, turns=self.turn_msgs,
            late_ticks=self.late, max_late_ms=round(self.max_late * 1000))
        if self.ticks:                                    # a played session: one line of who was here, when and why he left
            try: log(**self.match_log())
            except Exception as e: mlog_err('end', e)

    def vote(self, p, idx):
        """Relay 25: player p votes "don't wait" for player idx; when every other connected player has voted, idx is dropped at
        once - out of the next tick for everyone (as when GRACE runs out), his connection (if any) closed, no way back"""
        waited = idx in self.lagging or any(a[0] == idx for a in self.away.values())
        if not waited or p.idx == idx: return
        v = self.votes.setdefault(idx, set()); v.add(p.pid)
        need = {q.pid for q in self.peers if q.idx != idx}
        log(ev='vote', sid=int.from_bytes(self.sid, 'little'), idx=idx, by=p.idx, votes=len(v & need), need=len(need))
        if not need <= v:
            a = next((a for a in self.away.values() if a[0] == idx), None) or (idx, None, time.monotonic())
            self.notice(idx, a); return
        for pid, a in list(self.away.items()):
            if a[0] == idx:
                del self.away[pid]; self.gone.add(pid)
                try: self._plog_gone(pid, 'vote_drop', a)
                except Exception as e: mlog_err('vote', e)
        for q in [q for q in self.peers if q.idx == idx]:
            self.gone.add(q.pid); self.peers.remove(q); q.why = 'vote_drop'
            try: q.w.close()
            except Exception: pass
        self.lagging.discard(idx); self.votes.pop(idx, None)
        log(ev='vote_drop', sid=int.from_bytes(self.sid, 'little'), idx=idx, name=self.names.get(idx, ''))
        self.notice(idx, None)

    def notice(self, idx, a, now=None):
        """to the "DWR5" games here: player idx is away (a = (idx, until, since)) or back / dropped (a = None):
        7e <idx> <s left u16 BE> <s away u16 BE> <name len> <name utf-8>; left 0xFFFF = no longer waited for"""
        if a:
            now = now or time.monotonic(); gone = int(now - a[2])
            left = 0xFFFE if a[1] is None else max(0, min(0xFFFD, int(a[1] - now)))   # 0xFFFE: connected but silent (not dropped yet)
        else: left, gone = 0xFFFF, 0
        nm = (self.names.get(idx) or '').encode()[:60]
        need = [q.pid for q in self.peers if q.idx != idx]
        got = len(self.votes.get(idx, set()) & set(need))
        m = (bytes([NOTICE, idx]) + min(left, 0xFFFF).to_bytes(2, 'big') + min(gone, 0xFFFF).to_bytes(2, 'big') + bytes([len(nm)]) + nm
             + bytes([min(got, 255), min(len(need), 255)]))                # Relay 25: "don't wait" votes / players asked
        for q in self.peers:
            if q.rejoin: q.send(m)

    def queue_turn(self, p, data):
        self.queue.append((p.idx, data)); self.turn_msgs += 1
        now = time.monotonic()
        if p.last_turn:
            g = now - p.last_turn
            if g > GAP: p.gaps += 1; p.iv['gaps'] += 1
            p.max_gap = max(p.max_gap, g); p.iv['max_gap'] = max(p.iv['max_gap'], g)
            # a stall of his alone (node quality per player, 06.11.2026): the others' turns kept coming meanwhile (at least
            # half their 10 a second over the gap) - his way here stuck, not the match; in a lockstep a stall of one often
            # stops the others' turns too, and all restarting together is no "kept coming": then it counts for nobody
            others = sum(1 for q in self.peers if q is not p and q.last_turn)
            if g >= SOLO_GAP and others and self.turn_msgs - 1 - p.turn_mark >= max(3, 5 * (g - 0.3) * others):
                p.solo += 1; p.max_solo = max(p.max_solo, g)
        p.last_turn = now; p.turn_mark = self.turn_msgs; p.turns += 1; p.iv['turns'] += 1
        r = p.pl                                          # match protocol: his first / last turn's tick (no allocation)
        if r is not None:
            try:
                if r['ftt'] is None: r['ftt'] = self.ticks
                r['ltt'] = self.ticks
            except Exception as e: mlog_err('turn', e)
        if p.idx in self.lagging: self.lagging.discard(p.idx); self.votes.pop(p.idx, None); self.notice(p.idx, None)
        if not self.ticker: self.ticker = asyncio.ensure_future(self.tick_loop())

    async def tick_loop(self):
        nxt = time.monotonic()
        while self.peers or self.away:
            nxt += TICK
            await asyncio.sleep(max(0, nxt - time.monotonic()))
            late = time.monotonic() - nxt                    # the tick went out this much after its time
            if late > 0.03: self.late += 1
            self.max_late = max(self.max_late, late)
            if late > 0.5: nxt = time.monotonic()            # after a long hold: carry on from now, no burst of catch-up ticks
            q, self.queue = self.queue, []
            sent = {i for i, _ in q}
            silent = [p.idx for p in self.peers if p.idx not in sent]
            now = time.monotonic()
            if self.ticks % 10 == 0 and len(self.peers) > 1:              # connected but silent: the others wait for him already
                for p in self.peers:
                    if p.last_turn and now - p.last_turn > LAG and any(q.last_turn and now - q.last_turn < 1.5 for q in self.peers if q is not p):
                        self.lagging.add(p.idx); self.notice(p.idx, (p.idx, None, p.last_turn), now)
            for pid, a in list(self.away.items()):
                i, until = a[0], a[1]
                if until > now:
                    if i not in sent and i not in silent: silent.append(i)
                    if self.ticks % 10 == 0: self.notice(i, a, now)      # once a second
                else:
                    del self.away[pid]; self.gone.add(pid); log(ev='away_expired', sid=int.from_bytes(self.sid, 'little'), idx=i)
                    try: self._plog_gone(pid, 'grace_over', a)
                    except Exception as e: mlog_err('grace', e)
                    self.notice(i, None)
            m = bytearray(b'\x0a\xfe') + bytes([len(q)])
            for i, d in q: m += bytes([i]) + d
            m += bytes([len(silent)]) + bytes(silent)
            m = bytes(m)
            for p in list(self.peers): p.send(m)
            if len(self.history) < HISTORY: self.history.append(m); self.tick_t.append(time.time())
            self.ticks += 1
            # no waiting here for the players' connections to take the data (that held the tick for everyone when one
            # player's connection stalled): the data sits in that player's buffer, which is watched instead
            for p in self.peers:
                try: p.max_buf = max(p.max_buf, p.w.transport.get_write_buffer_size())
                except Exception: pass
            if self.ticks % 50 == 0:
                for p in self.peers: p.stats()                # the worst rtt is sampled every 5 s
        if not self.peers: self.end()                         # the last away player's GRACE ran out


def live_lobby(s, m):
    """before the start: the host's lobby state (the last one) and the start message out of the 0x10 messages (live replay)"""
    try:
        p = live_rec.lobby_payload(m)
        if not p: return
        if live_rec.is_room_state(p[1], s.sid): s.lobby = p[1]
        elif p[0] == 0x55 and live_rec.is_start(p[1]) and s.lobby:
            s.start_msg = p[1]; log(ev='live_start', sid=int.from_bytes(s.sid, 'little'), lobby=len(s.lobby))
    except Exception as e: log(ev='live_error', where='lobby', err=repr(e))


def live_answer(sid, frm, delay, game):
    """the DWRL envelope (see the docstring)"""
    s = sessions.get(sid); over = False
    if s is None and sid in finished: s, over = finished[sid][0], True
    if s is None: return b'DWLR' + struct.pack('<IIIIII', 1, 4, 0, 0, 0, 0) + struct.pack('<I', 0)
    if not (s.lobby and s.start_msg and live_rec):
        return b'DWLR' + struct.pack('<IIIIII', 1, 2, 0, 0, 0, 0) + struct.pack('<I', 0)
    lr = s.live.get(game)
    if lr is None:
        lr = live_rec.LiveRec(game, s.lobby, s.start_msg, s.sid); lr.header(0); lr.fed = 0   # (a header that can't be made: an exception -> not ready)
        s.live[game] = lr
    while lr.fed < len(s.history):
        lr.feed(s.history[lr.fed], s.tick_t[lr.fed]); lr.fed += 1
    cut = time.time() - max(LIVE_DELAY, delay)
    avail = len(lr.records)
    while avail > 0 and lr.times[avail - 1] > cut: avail -= 1
    frm = min(max(0, frm), avail); end = frm; size = 0
    while end < avail and size + len(lr.records[end]) <= LIVE_MAX: size += len(lr.records[end]); end += 1
    body = b''.join(lr.records[frm:end])
    nticks = sum(1 for r in lr.records[:end] if r[:4] == b'\0\0\0\0')
    head = lr.header(nticks) if frm == 0 else b''
    flags = 1 if over and end == len(lr.records) else 0
    meta = json.dumps({'map': lr.room.map, 'players': [lr.room.names.get(x['profile']) or '' for x in lr.room.slots],
                       'delay': max(LIVE_DELAY, delay), 'records': len(lr.records), 'over': over}).encode()
    return (b'DWLR' + struct.pack('<IIII', 1, flags, end, nticks) + struct.pack('<I', len(head)) + head + struct.pack('<I', len(body))
            + body + struct.pack('<I', len(meta)) + meta)


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
        now = time.time()
        for k in [k for k, v in finished.items() if now - v[1] > LIVE_KEEP]: finished.pop(k, None)
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


def announce_who(inner):
    """the player's name and Steam id from his peer announce (0f 05 ... zlib): "/steam/<id>" (u32 len + UTF-16), then u32 len +
    the name; ('', '') when it can't be read"""
    try:
        import zlib
        i = inner.find(b'\x78\x01')
        d = zlib.decompressobj().decompress(inner[i:]) if i >= 0 else b''
        k = d.find('/steam/'.encode('utf-16-le'))
        if k < 4: return '', ''
        plen = int.from_bytes(d[k - 4:k], 'little')
        path = d[k:k + 2 * plen].decode('utf-16-le', 'replace') if 0 < plen < 64 else ''
        steam = path[len('/steam/'):] if path[len('/steam/'):].isdigit() else ''
        o = k + 2 * plen + 4                                             # past the steam path and its trailing u32
        while o + 4 <= len(d) and int.from_bytes(d[o:o + 4], 'little') == 0: o += 4
        n = int.from_bytes(d[o:o + 4], 'little')
        return (d[o + 4:o + 4 + 2 * n].decode('utf-16-le', 'replace') if 0 < n < 64 else ''), steam
    except Exception: return '', ''


def announce_name(inner): return announce_who(inner)[0]


def hello_reply(m):
    """the answer to a hello: the hello itself; to a reconnect hello (flag 2 + the ticks the game got) flag 2 + the number of
    game messages we got from that player - the game then sends again the ones after it ("We have sent the server [N] game
    messages and it has received [M]") and waits for the ticks it missed"""
    if len(m) >= 22 and m[17] == 2:
        s = sessions.get(m[1:5]); n = s.rx.get(m[9:17], 0) if s else 0
        return m[:17] + b'\x02' + n.to_bytes(4, 'little') + m[22:]
    return m


def handle_msg(p, m, echo=True):
    p.iv['msgs'] += 1; p.iv['bytes'] += len(m) + 2
    t = m[0]
    if t == 0x15:                                                   # hello: join the session
        sid = m[1:5]
        again = len(m) >= 22 and m[17] == 2                         # a reconnect: the game frames it has got follow
        old = sessions.get(sid)
        if again and p.sess is None and (old is None or m[9:17] in old.gone):
            # too late: the session is over or the others have dropped him (a game that replays ticks without itself crashes,
            # stand test 06.11.2026) - the connection is closed, the game reports the lost connection itself
            log(ev='rejoin_refused', sid=int.from_bytes(sid, 'little'), peer=p.addr, why='no session' if old is None else 'grace over')
            p.w.close(); return
        if p.sess is None:
            s = sessions.get(sid) or sessions.setdefault(sid, Session(sid))
            p.pid = m[9:17]; s.join(p)
            log(ev='join', sid=int.from_bytes(sid, 'little'), idx=p.idx, peer=p.addr, pid=p.pid.hex(), members=len(s.peers),
                **({'reconnect_frames': int.from_bytes(m[18:22], 'little')} if again else {}))
        if echo: p.send(hello_reply(m))
        if again and p.sess is not None:                            # the ticks of the gap first, then the live ones
            have = int.from_bytes(m[18:22], 'little'); h = p.sess.history
            missed = h[have:] if 0 <= have <= len(h) else []
            for f in missed: p.send(f)
            log(ev='rejoin', sid=int.from_bytes(sid, 'little'), idx=p.idx, peer=p.addr, had=have, ticks=len(h), resent=len(missed),
                told=p.sess.rx.get(p.pid, 0))
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
            if p.idx not in s.names:
                nm, st = announce_who(inner)
                if nm: s.names[p.idx] = nm
                if st: s.steams[p.idx] = st
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
        if s.start_msg is None and live_rec: live_lobby(s, m)
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
    if t == VOTE:                                                    # Relay 25: never passed on
        if len(m) >= 2: s.vote(p, m[1])
        return
    if t in (0x09, 0x17): s.rx[p.pid] = s.rx.get(p.pid, 0) + 1   # what we tell him on a reconnect
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
        except asyncio.IncompleteReadError: p.why = p.why or 'fin'     # the player's side closed (FIN)
        except ConnectionError: p.why = p.why or 'reset'               # reset / broken
        except Exception: pass
        await q.put(None)
    try:
        pre = await asyncio.wait_for(r.readexactly(4), 15)
        if pre in (b'DWRT', b'DWRU'):                   # the launcher's connection test: a session of its own, never a real one
            ip = a[0]
            if pre == b'DWRU':                          # through our udp_gateway: it put the player's address in
                tag = await asyncio.wait_for(r.readexactly(4), 15)
                if ipaddress.ip_address(a[0]).is_loopback: ip = socket.inet_ntoa(tag)
            prm = await asyncio.wait_for(r.readexactly(6), 15)
            await test_run(r, w, ip, prm); return
        if pre == b'DWRL':                              # the live replay: a spectator (through the ladder) asks for records
            q = await asyncio.wait_for(r.readexactly(13), 5)
            sid, frm, delay = q[:4], int.from_bytes(q[4:8], 'little'), int.from_bytes(q[8:12], 'little')
            try: ans = live_answer(sid, frm, delay, 'vanilla' if q[12] == 1 else 'elite')
            except Exception as e:
                log(ev='live_error', where='answer', sid=int.from_bytes(sid, 'little'), err=repr(e))
                ans = b'DWLR' + struct.pack('<IIIIII', 1, 2, 0, 0, 0, 0) + struct.pack('<I', 0)
            w.write(ans); await w.drain(); w.close(); return
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
        if pre[:4] == b'DWR5':                          # Relay 24, native: reconnects for 3 min, wants our notices
            p.rejoin = True; pre = b'DWR1' + b'\0' * 6; log(ev='native', peer=p.addr, rejoin=1)
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
                    if m[:1] in (b'\x15', b'\x14'): p.send(hello_reply(m)); answered.append(m)
            while sid is None and len(held) < 64:
                m = await asyncio.wait_for(q.get(), IDLE)
                if m is None: return
                held.append(m)
                if m[:1] in (b'\x15', b'\x14'): p.send(hello_reply(m)); answered.append(m)
                if m[:1] == b'\x15': sid = m[1:5]
            away, end = False, time.time() + DECIDE
            while sid is not None and sid not in sessions:   # a new session here: its host, or a guest whose host is elsewhere?
                try: m = await asyncio.wait_for(q.get(), max(0.05, end - time.time()))
                except asyncio.TimeoutError: break           # no announce: the host
                if m is None: return
                held.append(m)
                if m[:1] in (b'\x15', b'\x14'): p.send(hello_reply(m)); answered.append(m); continue
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
    except (asyncio.IncompleteReadError, ConnectionError, asyncio.TimeoutError) as e:
        p.why = p.why or ('idle' if isinstance(e, asyncio.TimeoutError) else 'fin' if isinstance(e, asyncio.IncompleteReadError) else 'reset')
    except Exception as e: p.why = p.why or 'error'; log(ev='error', peer=p.addr, err=repr(e))
    finally:
        if rt: rt.cancel()
        if p.sess:
            log(ev='leave', sid=int.from_bytes(p.sess.sid, 'little'), **p.stats(), why=p.why, tick=p.sess.ticks)
            p.sess.leave(p)
        try: w.close()
        except Exception: pass


# ---------------------------------------------------------------- the launcher's connection test (DWRT, 06.11.2026)
TEST_SECS_MAX = 90                                   # s: a test never runs longer
TEST_IDLE = 10                                       # s without a frame from the player: over
TEST_LIVE_MAX = int(os.environ.get('RELAY_TEST_MAX', '32'))   # tests at once on this node
TEST_ADDR_LIVE, TEST_ADDR_RUNS, TEST_ADDR_WINDOW = 2, 12, 600  # per player address: at once; per window (s)
# what a virtual player sends the real one, per second: proxy messages (RLink ProxyMessage 0x10) and big 0x13 messages. From the
# Relic captures of 27.10 (1v1: ~0.2 proxy messages/s from the other player, sizes p50 44 B, p95 ~540 B; 0x13 up to 1138 B) and
# the warnings.txt counters of a 3v3 through Relic (03.11: 566 proxy messages/min received from 5 players = ~1.9/s each)
TEST_RATES = {2: (0.2, 0.02), 4: (1.2, 0.04), 6: (1.9, 0.05)}
_tests = dict(live=0, addr_live={}, addr_runs={})


def _test_admit(ip):
    """None = the test may run, else why not; the caller releases with _test_done(ip)"""
    now = time.time(); local = ipaddress.ip_address(ip).is_loopback
    runs = [t for t in _tests['addr_runs'].get(ip, []) if now - t < TEST_ADDR_WINDOW]
    if _tests['live'] >= TEST_LIVE_MAX: return 'busy'
    if not local and _tests['addr_live'].get(ip, 0) >= TEST_ADDR_LIVE: return 'running'
    if not local and len(runs) >= TEST_ADDR_RUNS: return 'too_often'
    _tests['addr_runs'][ip] = runs + [now]
    if len(_tests['addr_runs']) > 4096: _tests['addr_runs'] = {k: v for k, v in _tests['addr_runs'].items() if now - v[-1] < TEST_ADDR_WINDOW}
    _tests['live'] += 1; _tests['addr_live'][ip] = _tests['addr_live'].get(ip, 0) + 1
    return None


def _test_done(ip):
    _tests['live'] -= 1
    n = _tests['addr_live'].get(ip, 1) - 1
    if n > 0: _tests['addr_live'][ip] = n
    else: _tests['addr_live'].pop(ip, None)


def _frame(m): return len(m).to_bytes(2, 'big') + m


def _vproxy(src, seq, size):
    """a virtual player's proxy message to the player (number 1): one dst, its 15-byte info as the game's"""
    data = b'NV' + struct.pack('<IQ', seq, int(time.monotonic() * 1e6)) + b'\x5a' * max(0, size - 14)
    body = data + struct.pack('<BBIIB4x', src, 1, seq, 0, 0)
    return bytes([0x10, src, 1, 0, 1]) + len(body).to_bytes(2, 'little') + body


async def test_run(r, w, ip, prm):
    """the player's side is the real game stream; the n - 1 others are here. See the docstring (DWRT)."""
    import random
    n = prm[1] if prm[1] in (2, 4, 6) else 2
    secs = max(5, min(TEST_SECS_MAX, prm[2] or 60))
    why = _test_admit(ip)
    if why:
        log(ev='test_refused', ip=ip, why=why, live=_tests['live'])
        try: w.write(_frame(b'\x7e' + json.dumps({'v': 1, 'refused': why}).encode())); await w.drain()
        except Exception: pass
        await _test_close(r, w)
        return
    t0 = time.monotonic(); end = t0 + secs
    st = dict(turns=0, gaps=0, max_gap_ms=0, proxy_in=0, parts_in=0, parts_wrong=0, pings=0, msgs=0, bytes_in=0, bytes_out=0,
              ticks=0, late_ticks=0, max_late_ms=0, vproxy=0, vbig=0, reflected=0, hello=0)
    queue = []; last_turn = [0.0]; done = asyncio.Event()

    def send(m):
        if w.is_closing(): return
        b = _frame(m); w.write(b); st['bytes_out'] += len(b)

    async def ticker():                                   # as Session.tick_loop: every 100 ms one 0x0a to the player
        nxt = time.monotonic(); vseq = 0
        while not done.is_set():
            nxt += TICK
            await asyncio.sleep(max(0, nxt - time.monotonic()))
            late = time.monotonic() - nxt
            if late > 0.03: st['late_ticks'] += 1
            st['max_late_ms'] = max(st['max_late_ms'], round(late * 1000))
            if late > 0.5: nxt = time.monotonic()
            q = queue[:]; del queue[:]
            for i in range(2, n + 1):                    # every virtual player's turn: 16 bytes, as the game's
                q.append((i, (16).to_bytes(2, 'little') + b'VT' + struct.pack('<IQ', vseq, int(time.monotonic() * 1e6)) + b'\0\0'))
            vseq += 1
            silent = [] if any(i == 1 for i, _ in q) else [1]
            m = bytearray(b'\x0a\xfe') + bytes([len(q)])
            for i, d in q: m += bytes([i]) + d
            m += bytes([len(silent)]) + bytes(silent)
            send(bytes(m)); st['ticks'] += 1

    async def virtual(src):                               # one virtual player's own messages to the player
        rate, big = TEST_RATES[n]; seq = 0
        while not done.is_set():
            await asyncio.sleep(random.expovariate(rate + big))
            if done.is_set(): break
            if random.random() < big / (rate + big):
                send(bytes([0x13, 1, src]) + b'\x0f\x07' + b'\x5a' * 1100); st['vbig'] += 1
            else:
                x = random.random(); size = 44 if x < 0.8 else (120 if x < 0.95 else 540)
                send(_vproxy(src, seq, size)); seq += 1; st['vproxy'] += 1

    def on_msg(m):
        st['msgs'] += 1; st['bytes_in'] += len(m) + 2
        if not m: return
        t = m[0]
        if t == 0x15: st['hello'] += 1; send(m); return
        if t == 0x14: st['pings'] += 1; send(m); return
        if t in (0x09, 0x17):
            d = m[2:] if t == 0x09 else m[2 + 8 * m[1]:][2:] if m[2 + 8 * m[1]:][:1] == b'\x09' else None
            if d is None: return
            queue.append((1, d)); st['turns'] += 1
            now = time.monotonic()
            if last_turn[0]:
                g = now - last_turn[0]
                if g > GAP: st['gaps'] += 1
                st['max_gap_ms'] = max(st['max_gap_ms'], round(g * 1000))
            last_turn[0] = now
            return
        if t == 0x10:
            parts = proxy_split(m); st['proxy_in'] += 1
            for dst, one in parts or []:
                st['parts_in'] += 1
                if not 2 <= dst <= n: st['parts_wrong'] += 1; continue
                body = one[7:]                                      # a one-dst frame: 10 src 01 00 dst len(2) body
                if body[:2] != b'NP' or len(body) < 14 + 15: st['parts_wrong'] += 1; continue
                rb = b'NR' + body[2:14] + struct.pack('<BBIIB4x', dst, 1, 0, 0, 0)
                send(bytes([0x10, dst, 1, 0, 1]) + len(rb).to_bytes(2, 'little') + rb); st['reflected'] += 1
            return

    tasks = [asyncio.ensure_future(ticker())] + [asyncio.ensure_future(virtual(i)) for i in range(2, n + 1)]
    log(ev='test_start', ip=ip, players=n, secs=secs, live=_tests['live'])
    why = 'time'
    try:
        while True:
            left = end - time.monotonic()
            if left <= 0: break
            try:
                k = int.from_bytes(await asyncio.wait_for(r.readexactly(2), min(left, TEST_IDLE)), 'big')
                on_msg(await asyncio.wait_for(r.readexactly(k), TEST_IDLE) if k else b'')
            except asyncio.TimeoutError:
                if time.monotonic() < end: why = 'idle'; break
            await w.drain()
    except (asyncio.IncompleteReadError, ConnectionError): why = 'player'
    except Exception as e: why = 'error'; log(ev='error', peer=ip, err=repr(e), test=1)
    finally:
        done.set()
        for t in tasks: t.cancel()
        _test_done(ip)
    st.update(v=1, players=n, secs=round(time.monotonic() - t0, 1), end=why)
    log(ev='test_end', ip=ip, **st)
    if why == 'time':
        try: send(b'\x7e' + json.dumps(st).encode()); await w.drain()
        except Exception: pass
    await _test_close(r, w)


async def _test_close(r, w):
    """after the last frame the player closes (up to 5 s): our close right behind it would race it - udp_gateway sends its FIN at
    once and a FIN that passes the last data packet on the way loses it; and a close with unread bytes in the socket sends RST"""
    try:
        end = time.monotonic() + 5
        while time.monotonic() < end and await asyncio.wait_for(r.read(65536), end - time.monotonic()): pass
    except Exception: pass
    try: w.close()
    except Exception: pass


async def main():
    srv = await asyncio.start_server(handle, BIND, PORT)
    log(ev='start', bind=BIND, port=PORT)
    if STATS_EVERY > 0: asyncio.ensure_future(stats_loop())
    async with srv: await srv.serve_forever()

if __name__ == '__main__':
    asyncio.run(main())
