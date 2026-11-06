#!/usr/bin/env python3
"""live replay (06.11.2026): python3 gameserver/tests/test_live_replay.py
1. live_rec.py on the server's own ticks of a stand match (capture data/live_c1.jsonl.gz: the first 40 s of a 1v1 through our
   battle_relay, 06.11.2026) gives the very bytes the host's game wrote into its temp.rec: the header from the map on
   (data/live_c1_header.bin) and every record (data/live_c1_stream.bin is the start of that replay's records).
2. A battle_relay of this checkout (random local port, LIVE_DELAY=0): two fake games send what the stand games sent (lobby,
   start, turns), then "DWRL" gets the envelope: a header like the game's and the records live_rec makes of the ticks the
   relay sent; a second request from the middle gets the rest; an unknown session = flag 4; the delay floor holds."""
import asyncio, gzip, json, os, socket, struct, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); GS = os.path.join(HERE, '..'); sys.path.insert(0, GS)
import live_rec
D = os.path.join(HERE, 'data')
rows = [json.loads(l) for l in gzip.open(os.path.join(D, 'live_c1.jsonl.gz'), 'rt')]
HEAD = open(os.path.join(D, 'live_c1_header.bin'), 'rb').read()
STREAM = open(os.path.join(D, 'live_c1_stream.bin'), 'rb').read()


def header_part(b):
    a = b.find(b'DATASDSC'); c = b.find(b'Relic Chunky', a - 40)
    return b[a:a + len(HEAD)]


def build_from(frames_up, ticks):
    sid = None; room = start = None
    for m in frames_up:
        if m[:1] == b'\x15' and sid is None: sid = m[1:5]
        if m[:1] == b'\x10':
            p = live_rec.lobby_payload(m)
            if p and live_rec.is_room_state(p[1], sid) and start is None: room = p[1]
            elif p and p[0] == 0x55 and live_rec.is_start(p[1]) and start is None: start = p[1]
    lr = live_rec.LiveRec('elite', room, start, sid)
    for t in ticks: lr.feed(t, 0.0)
    return lr


def test_builder():
    up = [bytes.fromhex(r['hex']) for r in rows if r['d'] == 'up' and r['n'] == 1]
    ticks = [bytes.fromhex(r['hex']) for r in rows if r['d'] == 'down' and r['n'] == 1 and r['hex'][:2] == '0a']
    lr = build_from(up, ticks)
    h = lr.header()
    assert header_part(h) == HEAD, 'header differs from the game\'s'
    body = b''.join(lr.records)
    n = min(len(body), len(STREAM)) - 200                 # the last records of the 40 s cut may be cut in the game's file
    assert body[:n] == STREAM[:n], 'records differ at %d' % next(i for i in range(n) if body[i] != STREAM[i])
    print('builder: header and %d records as the game wrote them' % len(lr.records))


async def envelope(port, sid, frm, delay):
    r, w = await asyncio.open_connection('127.0.0.1', port)
    w.write(b'DWRL' + sid + struct.pack('<II', frm, delay) + b'\0'); await w.drain()
    b = await r.read(); w.close()
    assert b[:4] == b'DWLR', b[:16]
    ver, flags, avail, nticks, hl = struct.unpack_from('<IIIII', b, 4); o = 24
    head = b[o:o + hl]; o += hl; bl = struct.unpack_from('<I', b, o)[0]; o += 4; body = b[o:o + bl]; o += bl
    jl = struct.unpack_from('<I', b, o)[0]; meta = json.loads(b[o + 4:o + 4 + jl] or b'{}')
    return flags, avail, nticks, head, body, meta


async def play(port):
    """the two stand games again: each connection's frames as they went up, in their order (faster), the ticks back"""
    conns = {}; got = {1: [], 2: []}; sid = None
    for k in (1, 2):
        r, w = await asyncio.open_connection('127.0.0.1', port); w.write(b'DWR1' + b'\0' * 6); conns[k] = (r, w)
        async def rd(r=r, k=k):
            try:
                while True:
                    n = int.from_bytes(await r.readexactly(2), 'big'); m = await r.readexactly(n)
                    if m[:1] == b'\x0a': got[k].append(m)
            except Exception: pass
        asyncio.ensure_future(rd())
    t0 = None
    for x in rows:
        if x['d'] != 'up': continue
        m = bytes.fromhex(x['hex'])
        if m[:1] == b'\x15' and sid is None: sid = m[1:5]
        if t0 is None: t0 = x['t']
        conns[x['n']][1].write(len(m).to_bytes(2, 'big') + m)
        if m[:1] in (b'\x15',): await asyncio.sleep(0.3)        # the host's session first, then the guest
        await asyncio.sleep(0.002)
    await asyncio.sleep(1.0)
    up = [bytes.fromhex(x['hex']) for x in rows if x['d'] == 'up' and x['n'] == 1]
    return conns, got, sid, up


async def main(port):
    conns, got, sid, up = await play(port)
    flags, avail, nticks, head, body, meta = await envelope(port, sid, 0, 0)
    lr = build_from(up, got[1])
    assert header_part(head) == HEAD, 'DWRL header differs from the game\'s'
    assert flags == 0 and avail == len(lr.records) and body == b''.join(lr.records), (flags, avail, len(lr.records))
    assert meta.get('map') == '2p_calderisdunes' and meta.get('players') == ['igor.pechenikin', 'pivolan'], meta
    k = avail // 2
    f2, a2, _, h2, b2, _ = await envelope(port, sid, k, 0)
    assert h2 == b'' and b2 == b''.join(lr.records[k:]), 'the rest from the middle'
    f3, a3, _, _, b3, _ = await envelope(port, b'\x01\x02\x03\x04', 0, 0)
    assert f3 == 4 and a3 == 0, 'unknown session'
    print('relay: DWRL %d records (%d ticks), the header as the game\'s, the rest from %d, unknown session flagged' % (avail, nticks, k))
    for r, w in conns.values(): w.close()


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p


async def floor(port):
    conns, got, sid, up = await play(port)
    flags, avail, nticks, head, body, meta = await envelope(port, sid, 0, 0)
    assert avail == 4 and meta['delay'] == 3600, (avail, meta)    # only the start-up records: nothing is an hour old
    print('relay: the delay floor holds (asked 0 s, served %d s)' % meta['delay'])
    for r, w in conns.values(): w.close()


if __name__ == '__main__':
    test_builder()
    for env, fn in (({'LIVE_DELAY': '0'}, main), ({'LIVE_DELAY': '3600'}, floor)):
        port = free_port()
        p = subprocess.Popen([sys.executable, os.path.join(GS, 'battle_relay.py'), str(port)], env=dict(os.environ, RELAY_PEERS='', RELAY_LOG=os.devnull, **env),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(0.8); asyncio.run(fn(port))
        finally: p.terminate(); p.wait()
    print('OK')
