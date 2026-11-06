#!/usr/bin/env python3
"""battle_relay reconnect (06.11.2026): python3 gameserver/tests/test_reconnect.py
Two fake games in one session on a relay of this checkout (a random local port): both send turns, the ticks flow; B's
connection breaks, A goes on alone (B silent in those ticks); B comes back with the reconnect hello (flag 2 + the frames it
got) and must get exactly the ticks it missed, in order, then the live ones - the same bytes A got."""
import asyncio, os, socket, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); RELAY = os.path.join(HERE, '..', 'battle_relay.py')
SID = (123456).to_bytes(4, 'little')

def hello(pid, frames=None):
    m = b'\x15' + SID + b'\0' * 4 + pid + (b'\x02' + frames.to_bytes(4, 'little') if frames is not None else b'\x00')
    return len(m).to_bytes(2, 'big') + m

async def frames_of(r, out, stop):
    try:
        while not stop.is_set():
            n = int.from_bytes(await r.readexactly(2), 'big'); m = await r.readexactly(n)
            if m[:1] == b'\x0a': out.append(m)
    except Exception: pass

async def main(port):
    A, B = b'A' * 8, b'B' * 8
    ra, wa = await asyncio.open_connection('127.0.0.1', port); wa.write(b'DWR1' + b'\0' * 6 + hello(A))
    rb, wb = await asyncio.open_connection('127.0.0.1', port); wb.write(b'DWR1' + b'\0' * 6 + hello(B))
    ga, gb, stop = [], [], asyncio.Event()
    ta = asyncio.ensure_future(frames_of(ra, ga, stop)); tb = asyncio.ensure_future(frames_of(rb, gb, stop))
    turn = lambda w, x: w.write((5).to_bytes(2, 'big') + b'\x09\xfe\x02\x00' + x)
    for i in range(10): turn(wa, b'a'); turn(wb, b'b'); await asyncio.sleep(0.1)
    await asyncio.sleep(0.3)
    wb.close(); tb.cancel(); got_b = len(gb)                      # B's connection breaks
    for i in range(15): turn(wa, b'a'); await asyncio.sleep(0.1)
    rb, wb = await asyncio.open_connection('127.0.0.1', port)
    wb.write(b'DWR1' + b'\0' * 6 + hello(B, got_b)); gb2 = []
    tb = asyncio.ensure_future(frames_of(rb, gb2, stop))
    for i in range(5): turn(wa, b'a'); turn(wb, b'b'); await asyncio.sleep(0.1)
    await asyncio.sleep(0.5); stop.set(); wa.close(); wb.close()
    allb = gb + gb2
    assert len(gb) > 5 and len(ga) > 25, (len(ga), len(gb))
    n = min(len(ga), len(allb))
    assert allb[:n] == ga[:n], 'B (before + after the reconnect) must have the same ticks as A, in order'
    print(f'reconnect ok: A {len(ga)} ticks, B {len(gb)} before the break + {len(gb2)} after (incl. the gap), identical')

if __name__ == '__main__':
    s = socket.socket(); s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, RELAY_PEERS='', RELAY_STATS_EVERY='0')
    srv = subprocess.Popen([sys.executable, RELAY, str(port), '127.0.0.1'], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        time.sleep(1.0); asyncio.run(main(port))
    finally:
        srv.terminate(); out = srv.communicate(timeout=5)[0].decode(errors='replace')
        print('\n'.join(l for l in out.splitlines() if 'rejoin' in l or 'error' in l))
