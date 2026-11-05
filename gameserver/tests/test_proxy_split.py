#!/usr/bin/env python3
"""battle_relay.proxy_split (05.11.2026): python3 gameserver/tests/test_proxy_split.py
Real 0x10 frames of a Relic capture (27.10, two stands, m3) must come out unchanged (one dst each), a frame for three peers
must give each peer its own one-dst frame with its own 15-byte info, and anything that does not fit the layout -> None."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
os.environ.setdefault('RELAY_PEERS', '')
import battle_relay as br

REAL = ['10010100010f00100000000000000000000003000000',
        '1002010001210009fd0e000005020000000000000042000000030100000000000000000004000000',
        '10010100022500094f1200000020679e0000000000fa823e3c00000000030b0000000000000000000b000000']
for h in REAL:
    m = bytes.fromhex(h); r = br.proxy_split(m)
    assert r == [(m[4], m)], (h, r)

data = b'D' * 37; infos = [bytes([i]) * 15 for i in (2, 3, 4)]
body = data + b''.join(infos)
m = bytes([0x10, 1]) + (3).to_bytes(2, 'little') + bytes([2, 3, 4]) + len(body).to_bytes(2, 'little') + body
r = br.proxy_split(m)
assert [d for d, _ in r] == [2, 3, 4]
for (d, one), inf in zip(r, infos):
    b = data + inf
    assert one == bytes([0x10, 1, 1, 0, d]) + len(b).to_bytes(2, 'little') + b
    assert br.proxy_split(one) == [(d, one)]                  # a split frame is a valid one-dst frame
for bad in (m[:-1], m + b'x', bytes([0x10, 1, 0, 0, 0, 0]), bytes([0x10, 1, 2, 0, 2, 3, 10, 0]) + b'x' * 10):
    assert br.proxy_split(bad) is None, bad.hex()
print('proxy_split ok')
