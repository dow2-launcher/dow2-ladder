#!/usr/bin/env python3
"""07.11.2026 - a live replay answer cut off by the way (python3 gameserver/tests/test_live_cut.py):
 1. du_proto: a 200 KB answer written and then closed at once (the gateway before) loses its tail at the peer; closed after
    drained() (the gateway now) - every byte arrives;
 2. ladder/live.py whole_envelope: a cut DWLR envelope -> its header (length = its steps) and whole records, available =
    from + their number; a whole one passes as it is; one without a whole header -> None."""
import asyncio, os, struct, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..')); sys.path.insert(0, os.path.join(HERE, '..', '..', 'ladder'))
import du_proto as dp
from test_du_proto import Net, check
import live


async def answer_then_close(graceful):
    net = Net(delay=0.03); got = bytearray(); cores = [[None], [None]]; closed = {}
    a = dp.DuCore(1, 2, net.link(0, cores[1]), lambda d: None)
    b = dp.DuCore(1, 2, net.link(1, cores[0]), lambda d: got.extend(d), on_close=lambda by: closed.setdefault('b', by))
    cores[0][0], cores[1][0] = a, b
    data = bytes(i % 251 for i in range(200 * 1024)); fed = 0; stop = time.monotonic() + 20
    async def ticker():
        while time.monotonic() < stop and not (a.closed and b.closed): a.tick(); b.tick(); await asyncio.sleep(0.01)
    async def gateway():
        nonlocal fed
        while fed < len(data):                                  # as udp_gateway.run: read while there is room
            while not a.room(): await asyncio.sleep(0.005)
            a.write(data[fed:fed + dp.MAXP]); fed += dp.MAXP
        if graceful:
            end = time.monotonic() + 15
            while not a.drained() and time.monotonic() < end: await asyncio.sleep(0.02)
        a.close('battle_relay')
    await asyncio.gather(ticker(), gateway())
    return bytes(got), data


def env(head, recs, frm=0, flags=0, end=None):
    body = b''.join(recs); meta = b'{"x":1}'
    return (b'DWLR' + struct.pack('<IIII', 1, flags, end if end is not None else frm + len(recs), 7) + struct.pack('<I', len(head)) + head
            + struct.pack('<I', len(body)) + body + struct.pack('<I', len(meta)) + meta)


def main():
    ok = True
    got, data = asyncio.run(answer_then_close(False))
    ok &= check('close at once: the tail is lost (the bug)', len(got) < len(data) and data.startswith(got), '%d of %d' % (len(got), len(data)))
    got, data = asyncio.run(answer_then_close(True))
    ok &= check('close after drained(): every byte arrives', got == data, '%d of %d' % (len(got), len(data)))
    head = b'XXXX' + b'DATADATA' + struct.pack('<IIIii', 4, 4, 0, -1, 0) + struct.pack('<I', 999) + b'YYYY'
    recs = [struct.pack('<II', 0, 20) + bytes(20) if i % 3 else struct.pack('<II', 1, 10) + bytes(10) for i in range(50)]
    full = env(head, recs)
    ok &= check('whole envelope passes as it is', live.whole_envelope(full, 0) is full)
    cut = full[:24 + len(head) + 4 + 300]
    w = live.whole_envelope(cut, 0)
    ver, flags, end, nticks, hl = struct.unpack_from('<IIIII', w, 4); h = w[24:24 + hl]; bl = struct.unpack_from('<I', w, 24 + hl)[0]
    n_whole = 0; o = 0; ticks = 0
    for r in recs:
        if o + len(r) > 300: break
        o += len(r); n_whole += 1; ticks += r[:4] == b'\0\0\0\0'
    ok &= check('cut: available = its whole records, not over', end == n_whole and flags == 0, 'end %d whole %d' % (end, n_whole))
    ok &= check('cut: the records are the whole ones', w[28 + hl:28 + hl + bl] == b''.join(recs[:n_whole]))
    ok &= check('cut: the header length = its steps', struct.unpack_from('<I', h, 4 + 28)[0] == ticks and len(h) == len(head), str(ticks))
    ok &= check('cut: a later answer (from 40) keeps the header out and counts from 40',
                struct.unpack_from('<I', live.whole_envelope(env(b'', recs[:5], frm=40)[:24 + 4 + 70], 40), 12)[0] == 40 + 2)
    ok &= check('no whole header -> None', live.whole_envelope(full[:30], 0) is None)
    print('ALL OK' if ok else 'SOME FAILED'); return ok


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
