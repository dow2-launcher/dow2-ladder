#!/usr/bin/env python3
"""battle_relay "Bridge tail" (26.11.2026, the RLink fatal "data from the server in our name that we never sent"):
python3 gameserver/tests/test_bridge_tail.py
1. tail_check replays the game's own check: turns (17 .. 09 fe <len + data>) wait until a tick (0a) brings the same bytes back
   under the game's number; a clean match gives nothing, a tick that comes twice gives "again", bytes the game never sent under
   its number give "never_sent", two of its turns in the wrong order give "again"; an entry from before the frames kept (the
   first 3 s of a trimmed tail) is not counted.
2. A real bridge (DWR3 through battle_relay's handle to a fake Relic relay on 127.0.0.1): a game that sends turns and then
   goes silent while Relic repeats a tick leaves a file and an ev=bridge_tail line with fatal=again; a game that just leaves
   (closes at once) leaves nothing; bridge_tail.py reads the file and finds the same, and a file compared with itself is
   identical both ways."""
import asyncio, glob, gzip, json, os, shutil, socket, subprocess, sys, tempfile
TMP = tempfile.mkdtemp(prefix='bridge_tail_')
os.environ.update(RELAY_PEERS='', RELAY_LOG=os.path.join(TMP, 'br.jsonl'), RELAY_BRIDGE_TAIL_DIR=os.path.join(TMP, 'tail'),
                  RELAY_BRIDGE_TAIL_SILENT='0.5')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..')); sys.argv = sys.argv[:1]
import battle_relay as br


def turn(i, who=1):
    data = bytes([who]) * 4 + i.to_bytes(4, 'little') + b'\0' * 6               # a turn: frame number inside, as the real ones
    return b'\x17\x01' + b'\xaa' * 4 + i.to_bytes(4, 'little') + b'\x09\xfe' + len(data).to_bytes(2, 'little') + data


def tick(entries, silent=()):
    m = b'\x0a\xfe' + bytes([len(entries)])
    for i, k in entries: m += bytes([i]) + k
    return m + bytes([len(silent)]) + bytes(silent)


def game(n, t0=100.0):
    """a 1v1 seen from player 1: its turn i, then the tick with its and player 2's turn i"""
    fr = []
    for i in range(n):
        u = turn(i); fr.append((t0 + i * 0.1, 'u', len(u), u))
        d = tick([(1, br.turn_key(u)), (2, br.turn_key(turn(i, 2)))]); fr.append((t0 + i * 0.1 + 0.05, 'd', len(d), d))
    return fr


# ---- 1. the check
fr = game(40)
v = br.tail_check(fr)
assert v['our_idx'] == 1 and v['sent'] == 40 and v['ticks'] == 40 and v['echoed'] == 40 and v['first'] is None, v
assert br.tick_entries(tick([(1, b'\x02\x00ab')], [3])) == [(1, b'\x02\x00ab')]
assert br.tick_entries(tick([(1, b'\x02\x00ab')], [3]) + b'x') is None                     # not the layout: not a tick
dup = fr[:21] + [(fr[19][0] + 0.06, 'd', fr[19][2], fr[19][3])] + fr[21:]                   # tick #10 comes twice
v = br.tail_check(dup)
assert v['first'] and v['first']['kind'] == 'again' and v['first']['tick'] == 11 and v['echoed'] == 10, v
k = b'\x05\x00hello'                                                                        # bytes nobody of ours sent, under our number
fo = fr[:21] + [(fr[20][0] + 0.01, 'd', 0, b'')] + fr[21:]
fo[21] = (fo[21][0], 'd', len(tick([(1, k)])), tick([(1, k)]))
v = br.tail_check(fo)
assert v['first'] and v['first']['kind'] == 'never_sent' and v['first']['waiting'] == 1, v   # turn 10 waits (its tick comes later): the game drops it too, then dies
ro = [x for x in fr if not (x[1] == 'd' and x[0] in (101.25, 101.35))]                  # turns 12 and 13 come back the wrong way round:
t13, t12 = tick([(1, br.turn_key(turn(13)))]), tick([(1, br.turn_key(turn(12)))])          # the ticks of both after both were sent
ro += [(101.36, 'd', len(t13), t13), (101.37, 'd', len(t12), t12)]
ro.sort(key=lambda x: x[0])
v = br.tail_check(ro)
assert v['first'] and v['first']['kind'] == 'again', v
tr = fr[4:]                                                                                 # trimmed: starts with an echo of a turn not kept
tr = [x for x in tr if not (x[1] == 'u' and x[0] < 100.25)]
assert br.tail_check(tr, trimmed=True)['first'] is None
assert br.tail_check(tr, trimmed=False)['first'] is not None
print('tail_check ok')


# ---- 2. a real bridge
def free_relic_port():
    for p in range(27090, 27000, -1):
        s = socket.socket()
        try: s.bind(('127.0.0.1', p)); s.close(); return p
        except OSError: s.close()
    raise SystemExit('no free port in 27000-27099')


async def relic(r, w, repeat_at):
    """a fake Relic relay: hello echoed, a tick every 50 ms with the turns that came (number 1) and player 2's; tick #repeat_at
    goes out twice"""
    turns, n, sent, stop = [], [0], [], asyncio.Event()

    async def ticker():
        i = 0
        while not stop.is_set():
            await asyncio.sleep(0.05)
            q, turns[:] = turns[:], []
            m = tick([(1, k) for k in q] + [(2, br.turn_key(turn(i, 2)))]); i += 1
            w.write(len(m).to_bytes(2, 'big') + m); n[0] += 1; sent.append(m)
            if repeat_at and n[0] == repeat_at: w.write(len(m).to_bytes(2, 'big') + m)
            try: await w.drain()
            except Exception: break
    t = asyncio.ensure_future(ticker())
    try:
        while True:
            ln = int.from_bytes(await r.readexactly(2), 'big'); m = await r.readexactly(ln)
            if m[:1] == b'\x15': w.write(ln.to_bytes(2, 'big') + m)
            k = br.turn_key(m)
            if k is not None: turns.append(k)
    except Exception: pass
    stop.set(); t.cancel(); w.close()


async def play(port, rport, silent_end):
    r, w = await asyncio.open_connection('127.0.0.1', port)
    hello = b'\x15' + (777).to_bytes(4, 'little') + b'\0' * 4 + b'P' * 8 + b'\x00'
    w.write(b'DWR3' + socket.inet_aton('127.0.0.1') + rport.to_bytes(2, 'big') + len(hello).to_bytes(2, 'big') + hello)
    got = []

    async def rd():
        try:
            while True:
                ln = int.from_bytes(await r.readexactly(2), 'big'); got.append(await r.readexactly(ln))
        except Exception: pass
    t = asyncio.ensure_future(rd())
    for i in range(20):
        m = turn(i); w.write(len(m).to_bytes(2, 'big') + m); await w.drain(); await asyncio.sleep(0.05)
    if silent_end: await asyncio.sleep(1.2)                    # the game "crashed": nothing more from it, then its connection ends
    w.close(); await asyncio.sleep(0.8); t.cancel()
    return got


async def main():
    class _IP:                                                  # the bridge takes only public Relic addresses: let 127.0.0.1 pass here
        is_global = True
    br.ipaddress = type('ipaddress', (), {'ip_address': staticmethod(lambda s: _IP())})
    rport = free_relic_port()
    mode = {'repeat': 0}
    rs = await asyncio.start_server(lambda r, w: relic(r, w, mode['repeat']), '127.0.0.1', rport)
    bs = await asyncio.start_server(br.handle, '127.0.0.1', 0); port = bs.sockets[0].getsockname()[1]
    mode['repeat'] = 0; await play(port, rport, silent_end=False)              # leaves normally: no file
    assert not glob.glob(os.path.join(TMP, 'tail', '*.jsonl.gz')), 'a game that just leaves must leave no file'
    mode['repeat'] = 8; got = await play(port, rport, silent_end=True)        # a tick twice, then silence
    assert sum(1 for m in got if m[:1] == b'\x0a') > 10
    files = glob.glob(os.path.join(TMP, 'tail', '*.jsonl.gz'))
    assert len(files) == 1, files
    lines = [json.loads(l) for l in open(os.environ['RELAY_LOG'])]
    bt = [l for l in lines if l.get('ev') == 'bridge_tail']
    assert len(bt) == 1 and bt[0]['crash'] == 1 and bt[0]['fatal'] == 'again' and bt[0]['our_idx'] == 1, bt
    head = json.loads(gzip.open(files[0], 'rt').readline())
    assert head['check']['first']['kind'] == 'again' and head['closed_by'] == 'game', head
    rs.close(); bs.close()
    return files[0]

f = asyncio.run(main())
out = subprocess.run([sys.executable, os.path.join(HERE, '..', 'bridge_tail.py'), f], capture_output=True, text=True)
assert out.returncode == 0 and 'kind again' in out.stdout and '<-- FATAL' in out.stdout, out.stdout + out.stderr
out = subprocess.run([sys.executable, os.path.join(HERE, '..', 'bridge_tail.py'), f, f], capture_output=True, text=True)
assert out.returncode == 0 and out.stdout.count('identical') == 2, out.stdout + out.stderr
print('bridge tail ok:', os.path.basename(f))
shutil.rmtree(TMP, ignore_errors=True)
