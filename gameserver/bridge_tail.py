#!/usr/bin/env python3
"""bridge_tail.py - read the last frames a Relic bridge kept (battle_relay.py "Bridge tail", 26.11.2026: the RLink fatal "We've
received data from the server in our name that we never sent", session.cpp 3383).

  bridge_tail.py <file.jsonl.gz>             the check again, and the ticks around the entry the game died of: per tick its
                                             entries (number, length, first bytes; ours marked) and our turns waiting then
  bridge_tail.py <file A> <file B>           the same connection seen on two nodes (a Moscow player: the node he plays on and
                                             iggy, where the bridge leaves for Relic): are the frames the same, both ways?

A file: line 1 = {"ev": "bridge_tail", node, peer, dest, closed_by, crash, silent_s, dropped, frames, check}, then one line per
frame [wall time, "u" game -> Relic | "d" Relic -> game, length, hex (whole for turns / ticks / hellos, else the first 64 bytes)].
"""
import gzip, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.argv, ARGS = sys.argv[:1], sys.argv[1:]           # battle_relay reads its port from argv at import
os.environ.setdefault('RELAY_PEERS', '')
import battle_relay as br


def load(path):
    with gzip.open(path, 'rt') as f:
        head = json.loads(f.readline())
        frames = [(t, d, n, bytes.fromhex(h)) for t, d, n, h in map(json.loads, f)]
    return head, frames


def show(path):
    head, frames = load(path)
    v = br.tail_check(frames, head.get('dropped', 0) > 0)
    print(f"{os.path.basename(path)}: node {head.get('node')} peer {head.get('peer')} -> {head.get('dest')}, closed by "
          f"{head.get('closed_by')}, crash {head.get('crash')} (silent {head.get('silent_s')} s), {len(frames)} frames, "
          f"{head.get('dropped')} older ones dropped")
    print(f"our number {v['our_idx']}, turns sent {v['sent']}, ticks {v['ticks']}, turns brought back {v['echoed']}")
    f1 = v['first']
    if not f1: print('no tick entry the game would die of'); return v
    print(f"FATAL entry: tick #{f1['tick']} at {f1['t']}, kind {f1['kind']}, {f1['waiting']} of our turns waiting"
          + (f", the same bytes came back {f1['sent_ago_s']} s after we sent them already" if f1['sent_ago_s'] is not None else ''))
    print(f"  bytes {f1['bytes']}")
    n = 0
    for t, d, ln, m in frames:                          # the ticks around it and our turns among them
        if d == 'd' and m[:1] == b'\x0a': n += 1
        if not f1['tick'] - 6 <= n <= f1['tick'] + 2: continue
        if d == 'u' and br.turn_key(m) is not None: print(f"  {t:.3f} up   turn {br.turn_key(m)[:24].hex()}")
        elif d == 'd' and m[:1] == b'\x0a':
            es = br.tick_entries(m) or []
            marks = ', '.join(f"{'*' if i == v['our_idx'] else ''}{i}:{len(k)}:{k[:12].hex()}" for i, k in es)
            o = 3 + sum(1 + len(k) for _, k in es)          # after the entries: <m> m*idx of the silent ones
            silent = list(m[o + 1:o + 1 + m[o]]) if o < len(m) else []
            print(f"  {t:.3f} tick #{n}{' <-- FATAL' if n == f1['tick'] else ''} [{marks}] silent {silent}")
    return v


def compare(a, b):
    (ha, fa), (hb, fb) = load(a), load(b)
    for d in 'ud':
        xa = [m for _, dd, _, m in fa if dd == d]; xb = [m for _, dd, _, m in fb if dd == d]
        n = min(len(xa), len(xb)); off = 0
        # the two files may start at different frames (different ages): align on the first frame of the shorter one
        if xa and xb:
            try: off = xa.index(xb[0]) if len(xa) >= len(xb) else -xb.index(xa[0])
            except ValueError: off = None
        if off is None: print(f"{d}: no common start"); continue
        sa, sb = (xa[off:], xb) if off >= 0 else (xa, xb[-off:])
        n = min(len(sa), len(sb)); diff = next((i for i in range(n) if sa[i] != sb[i]), None)
        print(f"{'game -> Relic' if d == 'u' else 'Relic -> game'}: {n} frames compared, "
              + ('identical' if diff is None else f'first difference at frame {diff}: {sa[diff][:24].hex()} / {sb[diff][:24].hex()}'))


if __name__ == '__main__':
    if len(ARGS) == 1: show(ARGS[0])
    elif len(ARGS) == 2: compare(*ARGS)
    else: print(__doc__); sys.exit(2)
