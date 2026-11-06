#!/usr/bin/env python3
"""battle_relay reconnect (06.11.2026): python3 gameserver/tests/test_reconnect.py
Two fake games in one session on a relay of this checkout (a random local port): both send turns, the ticks flow; B's
connection breaks, A goes on alone and B must stay in those ticks as silent (the real game drops a player missing from a
tick at once - stand test 06.11.2026); B comes back with the reconnect hello (flag 2 + the ticks it got): the answer must
carry flag 2 + the number of game messages the relay got from B, then exactly the ticks B missed, in order, then the live
ones - the same bytes A got."""
import asyncio, os, socket, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); RELAY = os.path.join(HERE, '..', 'battle_relay.py')
SID = (123456).to_bytes(4, 'little')

def hello(pid, frames=None):
    m = b'\x15' + SID + b'\0' * 4 + pid + (b'\x02' + frames.to_bytes(4, 'little') if frames is not None else b'\x00')
    return len(m).to_bytes(2, 'big') + m

HELLOS = []
async def frames_of(r, out, stop):
    try:
        while not stop.is_set():
            n = int.from_bytes(await r.readexactly(2), 'big'); m = await r.readexactly(n)
            if m[:1] == b'\x0a': out.append(m)
            if m[:1] == b'\x15': HELLOS.append(m)
    except Exception: pass

def silent_of(tick):                                       # 0a fe <n> n*(idx u16len data) <m> m*idx
    o = 3
    for _ in range(tick[2]): o += 1; o += 2 + int.from_bytes(tick[o:o + 2], 'little')
    return list(tick[o + 1:o + 1 + tick[o]])

async def main(port):
    A, B = b'A' * 8, b'B' * 8
    ra, wa = await asyncio.open_connection('127.0.0.1', port); wa.write(b'DWR1' + b'\0' * 6 + hello(A))
    rb, wb = await asyncio.open_connection('127.0.0.1', port); wb.write(b'DWR1' + b'\0' * 6 + hello(B))
    ga, gb, stop = [], [], asyncio.Event()
    ta = asyncio.ensure_future(frames_of(ra, ga, stop)); tb = asyncio.ensure_future(frames_of(rb, gb, stop))
    turn = lambda w, x: w.write((5).to_bytes(2, 'big') + b'\x09\xfe\x01\x00' + x)
    for i in range(10): turn(wa, b'a'); turn(wb, b'b'); await asyncio.sleep(0.1)
    await asyncio.sleep(0.3)
    wb.close(); tb.cancel(); got_b = len(gb)                      # B's connection breaks
    gap_from = len(ga)
    for i in range(15): turn(wa, b'a'); await asyncio.sleep(0.1)
    gap = ga[gap_from + 3:]
    assert gap and all(2 in silent_of(t) for t in gap), 'B must stay in the ticks as silent while away'
    rb, wb = await asyncio.open_connection('127.0.0.1', port)
    wb.write(b'DWR1' + b'\0' * 6 + hello(B, got_b)); gb2 = []
    tb = asyncio.ensure_future(frames_of(rb, gb2, stop))
    for i in range(5): turn(wa, b'a'); turn(wb, b'b'); await asyncio.sleep(0.1)
    await asyncio.sleep(0.5); stop.set(); wa.close(); wb.close()
    allb = gb + gb2
    rep = HELLOS[-1]
    assert rep[17] == 2 and int.from_bytes(rep[18:22], 'little') == 10, ('reconnect answer', rep.hex())
    assert len(gb) > 5 and len(ga) > 25, (len(ga), len(gb))
    n = min(len(ga), len(allb))
    assert allb[:n] == ga[:n], 'B (before + after the reconnect) must have the same ticks as A, in order'
    print(f'reconnect ok: A {len(ga)} ticks, B {len(gb)} before the break + {len(gb2)} after (incl. the gap), identical')

async def votes(port):
    """Relay 25, three DWR5 games: C breaks; A votes "don't wait" -> the notices say 1 of 2 and C is still silent in the ticks;
    B votes -> C is out of the next tick for both (neither sent nor silent: the games drop him), the clear notice comes, and
    C's reconnect is refused"""
    A, B, C = b'G' * 8, b'H' * 8, b'I' * 8
    con = {}
    for k, pid in (('a', A), ('b', B), ('c', C)):
        r, w = await asyncio.open_connection('127.0.0.1', port); w.write(b'DWR5' + b'\0' * 6 + hello(pid)); con[k] = (r, w)
        await asyncio.sleep(0.1)
    turn = lambda w, x: w.write((5).to_bytes(2, 'big') + b'\x09\xfe\x01\x00' + x)
    for i in range(5):
        for k in 'abc': turn(con[k][1], k.encode())
        await asyncio.sleep(0.1)
    got = {'a': [], 'b': []}
    async def rd(k):
        r = con[k][0]
        try:
            while True:
                n = int.from_bytes(await r.readexactly(2), 'big'); got[k].append(await r.readexactly(n))
        except Exception: pass
    ts = [asyncio.ensure_future(rd(k)) for k in 'ab']
    con['c'][1].close()
    for i in range(12): turn(con['a'][1], b'a'); turn(con['b'][1], b'b'); await asyncio.sleep(0.1)
    vote = lambda w: w.write((2).to_bytes(2, 'big') + b'\x7d\x03')
    vote(con['a'][1])
    for i in range(12): turn(con['a'][1], b'a'); turn(con['b'][1], b'b'); await asyncio.sleep(0.1)
    n1 = [x for x in got['b'] if x[:1] == b'\x7e' and x[1] == 3 and int.from_bytes(x[2:4], 'big') < 0xFFFE]
    assert n1 and n1[-1][-2:] == bytes([1, 2]), ('1 of 2', [x.hex() for x in n1[-2:]])
    ticks_before = [x for x in got['a'] if x[:1] == b'\x0a']
    assert 3 in silent_of(ticks_before[-1]), 'C still waited for after one vote'
    mark = len(got['a']); vote(con['b'][1])
    for i in range(6): turn(con['a'][1], b'a'); turn(con['b'][1], b'b'); await asyncio.sleep(0.1)
    after = [x for x in got['a'][mark:] if x[:1] == b'\x0a']
    assert after and 3 not in silent_of(after[-1]), 'C must be out of the ticks after both votes'
    assert any(x[:1] == b'\x7e' and x[1] == 3 and x[2:4] == b'\xff\xff' for x in got['b']), 'the clear notice'
    r, w = await asyncio.open_connection('127.0.0.1', port); w.write(b'DWR5' + b'\0' * 6 + hello(C, 5)); back = []
    try:
        while True:
            n = int.from_bytes(await asyncio.wait_for(r.readexactly(2), 2), 'big'); back.append(await r.readexactly(n))
    except Exception: pass
    assert not any(x[:1] == b'\x0a' for x in back), 'C dropped by vote: no way back'
    for t in ts: t.cancel()
    for k in 'ab': con[k][1].close()
    print('votes ok: 1 of 2 shown, both votes -> C out of the ticks for everyone, his reconnect refused')

if __name__ == '__main__':
    s = socket.socket(); s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, RELAY_PEERS='', RELAY_STATS_EVERY='0')
    srv = subprocess.Popen([sys.executable, RELAY, str(port), '127.0.0.1'], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        time.sleep(1.0); asyncio.run(votes(port))
    finally:
        srv.terminate(); out = srv.communicate(timeout=5)[0].decode(errors='replace')
        print('\n'.join(l for l in out.splitlines() if 'vote' in l or 'refused' in l or 'error' in l))

if __name__ == '__main__':
    s = socket.socket(); s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, RELAY_PEERS='', RELAY_STATS_EVERY='0')
    srv = subprocess.Popen([sys.executable, RELAY, str(port), '127.0.0.1'], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        time.sleep(1.0); asyncio.run(main(port))
    finally:
        srv.terminate(); out = srv.communicate(timeout=5)[0].decode(errors='replace')
        print('\n'.join(l for l in out.splitlines() if 'rejoin' in l or 'error' in l or 'away' in l or 'back' in l))


async def too_late(port):
    """GRACE 1 s: B breaks, comes back after 2 s -> the others have dropped him: the reconnect is refused (closed, no ticks)"""
    A, B = b'C' * 8, b'D' * 8
    ra, wa = await asyncio.open_connection('127.0.0.1', port); wa.write(b'DWR1' + b'\0' * 6 + hello(A))
    rb, wb = await asyncio.open_connection('127.0.0.1', port); wb.write(b'DWR1' + b'\0' * 6 + hello(B))
    turn = lambda w, x: w.write((5).to_bytes(2, 'big') + b'\x09\xfe\x01\x00' + x)
    for i in range(5): turn(wa, b'a'); turn(wb, b'b'); await asyncio.sleep(0.1)
    wb.close(); await asyncio.sleep(2.5)
    rb, wb = await asyncio.open_connection('127.0.0.1', port); wb.write(b'DWR1' + b'\0' * 6 + hello(B, 5)); got = []
    try:
        while True:
            n = int.from_bytes(await asyncio.wait_for(rb.readexactly(2), 3), 'big'); got.append(await rb.readexactly(n))
    except Exception: pass
    assert not any(m[:1] == b'\x0a' for m in got), 'a reconnect after GRACE must get no ticks'
    wa.close(); print('too late ok: the reconnect after GRACE was refused')

async def notices(port):
    """Relay 24 games ("DWR5"): B (DWR5) breaks -> A (DWR5) gets our 0x7e notices about B once a second (number 2, seconds left
    near RELAY_REJOIN_GRACE, B's name from his peer announce), and the "no longer waited for" one when B is back"""
    import zlib
    A, B = b'E' * 8, b'F' * 8
    name = 'stand two'.encode('utf-16-le')
    blob = zlib.compress(b'\0' * 8 + (12).to_bytes(4, 'little') + '/steam/76561'.encode('utf-16-le') + b'\0' * 4 + (9).to_bytes(4, 'little') + name, 1)
    ann = b'\x0f\x05' + b'\0' * 16 + b'\x78\x01' + blob[2:]
    ra, wa = await asyncio.open_connection('127.0.0.1', port); wa.write(b'DWR5' + b'\0' * 6 + hello(A))
    rb, wb = await asyncio.open_connection('127.0.0.1', port); wb.write(b'DWR5' + b'\0' * 6 + hello(B))
    await asyncio.sleep(0.3)
    m = b'\x13\x00\x02' + ann; wb.write(len(m).to_bytes(2, 'big') + m)
    turn = lambda w, x: w.write((5).to_bytes(2, 'big') + b'\x09\xfe\x01\x00' + x)
    for i in range(5): turn(wa, b'a'); turn(wb, b'b'); await asyncio.sleep(0.1)
    got, stop = [], asyncio.Event()
    async def rd():
        try:
            while True:
                n = int.from_bytes(await ra.readexactly(2), 'big'); x = await ra.readexactly(n)
                if x[:1] == b'\x7e': got.append(x)
        except Exception: pass
    t = asyncio.ensure_future(rd())
    wb.close()
    for i in range(25): turn(wa, b'a'); await asyncio.sleep(0.1)
    rb, wb = await asyncio.open_connection('127.0.0.1', port); wb.write(b'DWR5' + b'\0' * 6 + hello(B, 10))
    await asyncio.sleep(0.5); wa.close(); wb.close(); t.cancel()
    away = [x for x in got if int.from_bytes(x[2:4], 'big') != 0xFFFF]
    assert away and away[0][1] == 2 and 160 <= int.from_bytes(away[0][2:4], "big") <= 170, [x.hex() for x in got]
    assert away[0][7:7 + away[0][6]].decode() == 'stand two', away[0]
    assert got[-1][1] == 2 and int.from_bytes(got[-1][2:4], 'big') == 0xFFFF, 'the clear notice when B is back'
    print('notices ok: %d away notices, name %r, then the clear one' % (len(away), away[0][7:7 + away[0][6]].decode()))

if __name__ == '__main__':
    s = socket.socket(); s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, RELAY_PEERS='', RELAY_STATS_EVERY='0')
    srv = subprocess.Popen([sys.executable, RELAY, str(port), '127.0.0.1'], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        time.sleep(1.0); asyncio.run(notices(port))
    finally:
        srv.terminate(); out = srv.communicate(timeout=5)[0].decode(errors='replace')
        print('\n'.join(l for l in out.splitlines() if 'away' in l or 'back' in l or 'error' in l))

if __name__ == '__main__':
    s = socket.socket(); s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, RELAY_PEERS='', RELAY_STATS_EVERY='0', RELAY_RECONNECT_GRACE='1')
    srv = subprocess.Popen([sys.executable, RELAY, str(port), '127.0.0.1'], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        time.sleep(1.0); asyncio.run(too_late(port))
    finally:
        srv.terminate(); out = srv.communicate(timeout=5)[0].decode(errors='replace')
        print('\n'.join(l for l in out.splitlines() if 'refused' in l or 'expired' in l or 'error' in l))
