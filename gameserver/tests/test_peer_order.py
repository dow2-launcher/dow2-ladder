#!/usr/bin/env python3
"""battle_relay peer numbers (20.11.2026, SirItos 19.11 "one nick shown, another player plays"): python3 gameserver/tests/test_peer_order.py
A fake host and two fake guests on a relay of this checkout (random local ports). The host numbers its guests as the real game does:
in the order their peer announces (13 00 .. 0f 05, passed on header stripped) reach it, then it sends each guest "you are N" by its
own number (13 <N> 01 ..) and reads the guests' turns in the ticks by the relay's sender number. Guest G1 says hello first, G2 30 ms
later; G2 is "chained" (hello + announce together), G1 announces only 300 ms after its hello echo (a direct game) - the race of
m19 / m20. With the new numbering (RELAY_NUMBER_AT=announce, the default) every guest must get its own "you are" and its turns must
carry the host's number for it; with the old one (RELAY_NUMBER_AT=hello) the two must come out swapped - the bug, reproduced.
Both runs: the relay's log must have ev=order_mismatch and the session's match_log order_mismatch / swapped (true only for hello).
Then RELAY_FIN_GRACE: a player whose game closes its connection (FIN) is out of the ticks at once with RELAY_FIN_GRACE=0, and stays
in them as silent (the old wait) with it off (-1)."""
import asyncio, json, os, socket, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); RELAY = os.path.join(HERE, '..', 'battle_relay.py')
SID = (777001).to_bytes(4, 'little')
fails = []


def check(name, ok, info=''):
    print('  %-78s %s' % (name, 'ok' if ok else 'FAIL %s' % info))
    if not ok: fails.append(name)


def frame(m): return len(m).to_bytes(2, 'big') + m
def hello(pid): return frame(b'\x15' + SID + b'\0' * 4 + pid + b'\x00')
def announce(name): return frame(b'\x13\x00\x00' + b'\x0f\x05' + name)          # a guest does not know its number yet
def turn(data): return frame(b'\x09\xfe' + len(data).to_bytes(2, 'little') + data)


async def reader(r, out):
    try:
        while True:
            n = int.from_bytes(await r.readexactly(2), 'big'); out.append(await r.readexactly(n))
    except Exception: pass


def ticks_senders(frames):
    """{data: sender number} from 0a fe <n> n*(<idx> <u16 LE len> data) ..."""
    out = {}
    for m in frames:
        if m[:2] != b'\x0a\xfe': continue
        o = 3
        for _ in range(m[2]):
            i = m[o]; n = int.from_bytes(m[o + 1:o + 3], 'little'); d = m[o + 3:o + 3 + n]; o += 3 + n
            out.setdefault(d, i)
    return out


async def order_run(port):
    """-> (host's number per guest, what each guest was told it is, the relay's sender number per guest's turn)"""
    rh, wh = await asyncio.open_connection('127.0.0.1', port); wh.write(b'DWR1' + b'\0' * 6 + hello(b'H' * 8))
    host_in = []; th = asyncio.ensure_future(reader(rh, host_in))
    await asyncio.sleep(5.6)                         # the relay's DECIDE (5 s): no announce from the first peer -> it is the host
    r1, w1 = await asyncio.open_connection('127.0.0.1', port)
    r2, w2 = await asyncio.open_connection('127.0.0.1', port)
    g1, g2 = [], []; t1 = asyncio.ensure_future(reader(r1, g1)); t2 = asyncio.ensure_future(reader(r2, g2))
    w1.write(b'DWR1' + b'\0' * 6 + hello(b'1' * 8))  # G1: hello first (direct: its announce waits for the echo + its game)
    await asyncio.sleep(0.03)
    w2.write(b'DWR1' + b'\0' * 6 + hello(b'2' * 8) + announce(b'G2'))   # G2: 30 ms later, hello + announce at once (chained)
    for _ in range(100):
        if any(m[:1] == b'\x15' for m in g1): break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.3); w1.write(announce(b'G1'))
    # the host's game: numbers in the order the announces reach it, then tells each guest its number by that number
    num = {}; told = set()
    for _ in range(300):
        for m in host_in:
            if m[:2] == b'\x0f\x05' and m[2:] not in num: num[m[2:]] = 2 + len(num)
        for nm, n in num.items():
            if nm not in told: wh.write(frame(b'\x13' + bytes([n, 1]) + b'YOU' + nm)); told.add(nm)
        if len(told) == 2: break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.4)
    got = {}
    for nm, inbox in ((b'G1', g1), (b'G2', g2)):
        you = [m[6:] for m in inbox if m[:1] == b'\x13' and m[3:6] == b'YOU']
        got[nm] = you[0] if you else None
    for i in range(3):                               # turns: each guest's own name; the host reads the senders' numbers in the ticks
        w1.write(turn(b'G1')); w2.write(turn(b'G2')); wh.write(turn(b'HH')); await asyncio.sleep(0.12)
    await asyncio.sleep(0.4)
    snd = ticks_senders(host_in)
    for w in (w1, w2, wh): w.close()
    await asyncio.sleep(0.3)
    for t in (th, t1, t2): t.cancel()
    return num, got, snd


def relay(env_extra, logf):
    s = socket.socket(); s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, RELAY_PEERS='', RELAY_STATS_EVERY='0', RELAY_LOG=logf, RELAY_RECONNECT_GRACE='0.5', RELAY_REJOIN_GRACE='0.5', **env_extra)
    srv = subprocess.Popen([sys.executable, RELAY, str(port), '127.0.0.1'], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    time.sleep(1.0)
    return srv, port


def events(logf):
    try: return [json.loads(l) for l in open(logf) if l.strip()]
    except FileNotFoundError: return []


def order_case(mode):
    logf = tempfile.mktemp(prefix='relay_order_', suffix='.jsonl')
    srv, port = relay({'RELAY_NUMBER_AT': mode}, logf)
    try: num, got, snd = asyncio.run(order_run(port)); time.sleep(2.0)   # the away grace (0.5 s) runs out: the session ends, match_log
    finally: srv.terminate(); srv.communicate(timeout=5)
    time.sleep(0.2); ev = events(logf)
    right = all(got.get(nm) == nm for nm in num) and all(snd.get(nm) == n for nm, n in num.items())
    print('  host numbered %s; guests told %s; senders in the ticks %s' % (
        {k.decode(): v for k, v in num.items()}, {k.decode(): (v.decode() if v else v) for k, v in got.items()}, {k.decode(): v for k, v in snd.items()}))
    mism = [e for e in ev if e.get('ev') == 'order_mismatch']
    ml = [e for e in ev if e.get('ev') == 'match_log']
    return right, num, mism, ml


async def fin_run(port):
    """A and B in a session with ticks; B's game closes its connection (FIN): is B still in the ticks as silent after 0.5 s?"""
    ra, wa = await asyncio.open_connection('127.0.0.1', port); wa.write(b'DWR1' + b'\0' * 6 + hello(b'A' * 8))
    ia = []; ta = asyncio.ensure_future(reader(ra, ia))
    await asyncio.sleep(5.6)
    rb, wb = await asyncio.open_connection('127.0.0.1', port); wb.write(b'DWR1' + b'\0' * 6 + hello(b'B' * 8) + announce(b'B'))
    for i in range(6): wa.write(turn(b'a')); wb.write(turn(b'b')); await asyncio.sleep(0.1)
    wb.write_eof(); wb.close()                       # FIN from B's side
    await asyncio.sleep(0.6); k = len(ia)
    for i in range(4): wa.write(turn(b'a')); await asyncio.sleep(0.1)
    later = [m for m in ia[k:] if m[:2] == b'\x0a\xfe']
    def silent(m):
        o = 3
        for _ in range(m[2]): o += 3 + int.from_bytes(m[o + 1:o + 3], 'little')
        return list(m[o + 1:o + 1 + m[o]])
    wa.close(); await asyncio.sleep(0.2); ta.cancel()
    return later and all(2 in silent(m) for m in later), bool(later)


def fin_case(val, grace='30'):
    logf = tempfile.mktemp(prefix='relay_fin_', suffix='.jsonl')
    s = socket.socket(); s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, RELAY_PEERS='', RELAY_STATS_EVERY='0', RELAY_LOG=logf, RELAY_RECONNECT_GRACE=grace, RELAY_FIN_GRACE=val)
    srv = subprocess.Popen([sys.executable, RELAY, str(port), '127.0.0.1'], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    time.sleep(1.0)
    try: return asyncio.run(fin_run(port)), events(logf)
    finally: srv.terminate(); srv.communicate(timeout=5)


if __name__ == '__main__':
    print('== the m19 race, new numbering (RELAY_NUMBER_AT=announce)')
    right, num, mism, ml = order_case('announce')
    check('every guest told its own number, its turns under the host\'s number for it', right)
    check('the host numbered the chained G2 first (its announce came first)', num.get(b'G2') == 2 and num.get(b'G1') == 3, num)
    check('ev=order_mismatch logged (G2 overtook G1\'s hello)', len(mism) == 1 and mism[0].get('swapped') is False, mism)
    check('match_log: numbering announce, order_mismatch kept, swapped false',
          bool(ml) and ml[-1].get('numbering') == 'announce' and ml[-1].get('order_mismatch') and ml[-1].get('swapped') is False, ml[-1:] and {k: ml[-1].get(k) for k in ('numbering', 'order_mismatch', 'swapped')})
    print('== the same race, the old numbering (RELAY_NUMBER_AT=hello): the bug of 19.11')
    right, num, mism, ml = order_case('hello')
    check('the guests come out SWAPPED (each told the other\'s number)', not right)
    check('ev=order_mismatch logged with swapped=true', len(mism) == 1 and mism[0].get('swapped') is True, mism)
    check('match_log swapped true (the ladder leaves the match unrated: peer_order)', bool(ml) and ml[-1].get('swapped') is True, ml[-1:])
    print('== FIN grace')
    (still, any_t), ev = fin_case('-1')
    check('RELAY_FIN_GRACE off: B (closed with FIN) stays in the ticks as silent', any_t and still)
    (still, any_t), ev = fin_case('0')
    check('RELAY_FIN_GRACE=0: B is out of the ticks at once', any_t and not still)
    check('ev=fin_drop logged', any(e.get('ev') == 'fin_drop' for e in ev))
    print('ALL OK' if not fails else 'FAILED: %s' % fails)
    sys.exit(1 if fails else 0)
