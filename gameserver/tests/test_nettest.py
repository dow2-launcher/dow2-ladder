#!/usr/bin/env python3
"""battle_relay's connection test mode (DWRT, 06.11.2026): python3 gameserver/tests/test_nettest.py
A player (this script) runs a short 3v3 test against battle_relay on a local port, directly over TCP and through udp_gateway
(DU over UDP, du_client): every 100 ms a tick with 6 turns, its own turns come back in them, every proxy message part comes
back from the right virtual player only, pings are echoed, the end frame has the counts; nothing shows in the real sessions;
the limits per address refuse a third test at once."""
import asyncio, json, os, struct, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ.setdefault('RELAY_PEERS', '')
os.environ['RELAY_LOG'] = '/dev/null'
os.environ['RELAY_STATS_EVERY'] = '0'
import battle_relay as br
PORT = 47391


def frame(m): return len(m).to_bytes(2, 'big') + m


async def player(r, w, players=6, secs=6, pre=b'DWRT'):
    w.write(pre + bytes([1, players, secs, 0, 0, 0]))
    w.write(frame(b'\x15' + struct.pack('<I', 7) + b'\0' * 4 + b'P' * 8 + b'\0'))
    res = dict(ticks=0, own=0, lat=[], vturns=0, reflect={}, vproxy=0, vbig=0, pings=0, end=None, silent=0)
    sent = {}; t0 = time.monotonic()

    async def writer():
        k = 0
        while time.monotonic() - t0 < secs - 0.3:
            d = b'NT' + struct.pack('<IQ', k, int(time.monotonic() * 1e6)) + b'\0\0'
            w.write(frame(b'\x17\x01' + b'\0' * 8 + b'\x09\xfe' + len(d).to_bytes(2, 'little') + d))
            sent[k] = time.monotonic()
            if k % 3 == 0: w.write(frame(b'\x14' + struct.pack('<I', k)))
            if k % 5 == 0:                                  # a proxy message to all the others
                dsts = list(range(2, players + 1))
                data = b'NP' + struct.pack('<IQ', k, int(time.monotonic() * 1e6)) + b'x' * 30
                infos = b''.join(struct.pack('<BBIIB4x', 1, d, k, 0, 0) for d in dsts)
                body = data + infos
                w.write(frame(bytes([0x10, 1]) + len(dsts).to_bytes(2, 'little') + bytes(dsts) + len(body).to_bytes(2, 'little') + body))
            k += 1
            await asyncio.sleep(0.1)
    wt = asyncio.ensure_future(writer())
    try:
        while True:
            n = int.from_bytes(await asyncio.wait_for(r.readexactly(2), 15), 'big'); m = await r.readexactly(n)
            if m[0] == 0x0a:
                res['ticks'] += 1; c = m[2]; o = 3
                for _ in range(c):
                    i = m[o]; L = m[o + 1] | m[o + 2] << 8; d = m[o + 3:o + 3 + L]; o += 3 + L
                    if i == 1 and d[:2] == b'NT': res['own'] += 1; res['lat'].append(time.monotonic() - sent[struct.unpack('<I', d[2:6])[0]])
                    elif d[:2] == b'VT': res['vturns'] += 1
                res['silent'] += m[o]
            elif m[0] == 0x10:
                src = m[1]; body = m[7:]
                if body[:2] == b'NR': res['reflect'].setdefault(struct.unpack('<I', body[2:6])[0], []).append(src)
                elif body[:2] == b'NV': res['vproxy'] += 1
            elif m[0] == 0x13: res['vbig'] += 1
            elif m[0] == 0x14: res['pings'] += 1
            elif m[0] == 0x7e: res['end'] = json.loads(m[1:]); break
    finally:
        wt.cancel(); w.close()
    return res


def check(res, players=6, secs=6):
    assert res['end'] and res['end']['end'] == 'time', res['end']
    assert res['ticks'] >= secs * 10 - 3, res['ticks']
    assert res['vturns'] == res['ticks'] * (players - 1), (res['vturns'], res['ticks'])
    assert res['own'] >= secs * 10 - 6, res['own']
    assert max(res['lat']) < 0.25, max(res['lat'])
    assert res['pings'] >= secs * 10 // 3 - 2
    for k, srcs in res['reflect'].items(): assert sorted(srcs) == list(range(2, players + 1)), (k, srcs)
    assert len(res['reflect']) >= secs * 2 - 2, len(res['reflect'])
    e = res['end']; assert e['parts_wrong'] == 0 and e['turns'] == res['own'] or e['turns'] >= res['own'], e
    assert e['players'] == players


async def main():
    srv = await asyncio.start_server(br.handle, '127.0.0.1', PORT)
    # 1) straight over TCP (as a player whose UDP does not pass)
    r, w = await asyncio.open_connection('127.0.0.1', PORT)
    res = await player(r, w); check(res)
    print('tcp ok: ticks %d, own turns %d (max %.0f ms), reflections %d, virtual proxies %d, big %d' % (
        res['ticks'], res['own'], max(res['lat']) * 1000, len(res['reflect']), res['vproxy'], res['vbig']))
    assert not br.sessions, 'a test must not make a real session'
    # 2) through udp_gateway (DU), the gateway puts the address in: DWRU
    sys.argv = ['udp_gateway.py', str(PORT + 1), '127.0.0.1:%d' % PORT]
    import importlib, udp_gateway as gw, du_client
    loop = asyncio.get_running_loop()
    tr, g = await loop.create_datagram_endpoint(gw.Gateway, local_addr=('127.0.0.1', PORT + 1))
    tt = asyncio.ensure_future(g.timers())
    c = await du_client.open_du('127.0.0.1', PORT + 1); assert c, 'no SYNACK'
    res = await player(*c, players=4, secs=5); check(res, 4, 5)
    print('du ok: ticks %d, own turns %d (max %.0f ms), reflections %d' % (res['ticks'], res['own'], max(res['lat']) * 1000, len(res['reflect'])))
    # 2b) STATQ: the gateway tells how the player's packets arrived (only a padded request, never bigger than it)
    r2, w2 = await du_client.open_du('127.0.0.1', PORT + 1)
    w2.write(b'DWRT' + bytes([1, 2, 5, 0, 0, 0]) + frame(b'\x15' + struct.pack('<I', 9) + b'\0' * 4 + b'Q' * 8 + b'\0'))
    await asyncio.sleep(0.5)
    got = []; orig = w2.datagram
    w2.datagram = lambda d: got.append(d) if d[2:3] == b'\x0b' else orig(d)
    w2.tr.sendto(b'DU\x0a' + struct.pack('<I', w2.cid) + b'\0' * 10); await asyncio.sleep(0.3)
    assert not got, 'a short STATQ gets nothing'
    w2.tr.sendto(b'DU\x0a' + struct.pack('<I', w2.cid) + b'\0' * 400); await asyncio.sleep(0.3)
    assert got and len(got[0]) <= 407, got
    st = json.loads(got[0][7:]); assert st['rx'] >= 1 and 'up_lost' in st, st
    print('statq ok:', st)
    w2.close()
    # 3) limits: a third test at once from one address is refused; a forged DWRU from a non-loopback peer can't happen here
    #    (only loopback) - so the address limit is checked with the DWRU tag of a public address
    async def tagged(ip, secs=4):
        r, w = await asyncio.open_connection('127.0.0.1', PORT)
        return await player(r, w, 2, secs, pre=b'DWRU' + bytes(map(int, ip.split('.'))))
    a = await asyncio.gather(tagged('203.0.113.9'), tagged('203.0.113.9'), tagged('203.0.113.9', 2))
    refused = [x for x in a if x['end'].get('refused')]
    assert len(refused) == 1 and refused[0]['end']['refused'] == 'running', [x['end'] for x in a]
    print('limit ok: 2 at once ran, the third was refused (%s)' % refused[0]['end']['refused'])
    br._tests['addr_runs']['203.0.113.10'] = [time.time()] * br.TEST_ADDR_RUNS
    x = await tagged('203.0.113.10'); assert x['end'].get('refused') == 'too_often', x['end']
    print('limit ok: too often refused; live now', br._tests['live'])
    assert br._tests['live'] == 0 and not br._tests['addr_live']
    tt.cancel(); tr.close(); srv.close()
    print('nettest ok')

asyncio.run(main())
