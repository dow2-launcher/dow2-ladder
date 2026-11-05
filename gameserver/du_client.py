#!/usr/bin/env python3
"""du_client.py - battle_relay's connection to ANOTHER of our nodes over our UDP tunnel (DU), 04.11.2026 (relay chain).

When a player's game is on a node it can't reach itself, it plays through its own node: player -> its node -> the node of the
session (Relay.dll 22 "DWR4", and the older pass-on of a guest whose host is elsewhere). That hop between our servers goes
over UDP like du_egress.py (Moscow -> iggy): TCP Moscow <-> Europe stalls (DPI: pauses of 250+ ms after a few minutes),
UDP with our own delivery does not (03.11.2026: 0 stalls in 10 min). The other node's udp_gateway (UDP, same port as its
battle_relay) turns it into a local TCP connection to its battle_relay, so the far side does not change at all.

open_du(host, port) -> (reader, writer) like asyncio.open_connection, or None when no SYNACK comes within OPEN s (the caller
then uses TCP). reader = asyncio.StreamReader; writer: write / drain / close / is_closing / get_extra_info / transport
.get_write_buffer_size / du_stats(). The delivery is du_proto.py (05.11.2026) - the same code as udp_gateway.py and
du_egress.py, and in C Relay.dll 23: one resend timer, at most 10 resends then FIN, budgets for resends and copies,
64 packets in flight with back pressure (drain() waits), a fuse against storms; the wire format of DU v2 as before.
"""
import asyncio, random, struct, time
import du_proto
from du_proto import SYN, SYNACK, MAXP

OPEN = 1.5             # s for the handshake (a SYN every 250 ms)
VERSION = 2


class _Udp(asyncio.DatagramProtocol):
    def __init__(self, c): self.c = c
    def datagram_received(self, d, addr): self.c.datagram(d)
    def error_received(self, e): pass


class DUStream:
    def __init__(self, host, port):
        self.dest = (host, port)
        self.cid = random.getrandbits(32); self.ver = 0; self.tr = None; self.core = None
        self.reader = asyncio.StreamReader()
        self.synack = asyncio.get_running_loop().create_future()
        self._closed = False; self.closed_by = None
        self.room = asyncio.Event(); self.room.set()
        self.timer = None; self.started = time.time()
        self.transport = self                           # pass_on / BridgeStats ask writer.transport.get_write_buffer_size()

    @property
    def closed(self): return self._closed or (self.core is not None and self.core.closed)

    # ---- the writer side, as asyncio.StreamWriter is used by battle_relay ----
    def write(self, data):
        if not self.closed and self.core: self.core.write(data)

    async def drain(self):
        while self.core and not self.core.closed and not self.core.room():
            self.room.clear(); await self.room.wait()
        if self.closed: raise ConnectionResetError('DU connection closed')

    def is_closing(self): return self.closed
    def get_extra_info(self, name, default=None): return default
    def get_write_buffer_size(self):
        if not self.core: return 0
        return sum(len(x) for x in self.core.pending) + self.core.inflight_bytes

    def du_stats(self):
        c = self.core
        if not c: return dict(ver=0, secs=round(time.time() - self.started, 1))
        return dict(c.stats, srtt_ms=round(c.srtt * 1000), ver=self.ver, secs=round(time.time() - self.started, 1),
                    storm=int(c.fuse_tripped))

    def close(self, by='us', send_fin=True):
        if self._closed: return
        self._closed = True; self.closed_by = self.closed_by or by
        if self.core: self.core.close(by, send_fin)
        try: self.tr.close()
        except Exception: pass
        if self.timer: self.timer.cancel()
        self.reader.feed_eof(); self.room.set()

    async def wait_closed(self): pass

    # ---- the delivery: du_proto ----
    def _out(self, pkt):
        try: self.tr.sendto(pkt)
        except Exception: pass

    def _on_room(self):
        if self.core and (self.core.closed or self.core.room()): self.room.set()

    def _on_close(self, by):
        self.closed_by = self.closed_by or by
        if not self._closed:                                 # closed by the delivery (FIN from the peer, dead, silent)
            self._closed = True
            try: self.tr.close()
            except Exception: pass
            self.reader.feed_eof(); self.room.set()

    def _deliver(self, d):
        if not self._closed: self.reader.feed_data(d)

    async def open(self):
        loop = asyncio.get_running_loop()
        self.tr, _ = await loop.create_datagram_endpoint(lambda: _Udp(self), remote_addr=self.dest)
        end = time.time() + OPEN
        while time.time() < end:
            self._out(du_proto.hdr(SYN, self.cid) + bytes([VERSION]))
            try:
                self.ver = await asyncio.wait_for(asyncio.shield(self.synack), min(0.25, max(0.01, end - time.time())))
                self.core = du_proto.DuCore(self.cid, self.ver, out=self._out, deliver=self._deliver,
                                            log=lambda ev, **k: print(time.strftime('%T'), 'du_client', 'ev=%s' % ev,
                                                                      ' '.join('%s=%s' % kv for kv in k.items()), flush=True),
                                            on_room=self._on_room, on_close=self._on_close)
                self.timer = asyncio.ensure_future(self.timers())
                return True
            except asyncio.TimeoutError: pass
        self.tr.close(); self._closed = True
        return False

    def datagram(self, d):
        if len(d) < 7 or d[:2] != b'DU' or struct.unpack('<I', d[3:7])[0] != self.cid: return
        t, body = d[2], d[7:]
        if t == SYNACK:
            if not self.synack.done(): self.synack.set_result(body[0] if body and body[0] >= 2 else 1)
            return
        if not self.core or self.closed: return
        self.core.datagram(t, body)

    async def timers(self):
        while not self.closed:
            await asyncio.sleep(0.01)
            self.core.tick()


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
