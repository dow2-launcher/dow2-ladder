#!/usr/bin/env python3
"""live_maps.py <out.json> <glob>... - the map part of a DoW2 replay header (chunk DATASDSC: the map's file date, path, name id,
player count, size) for every map found in the given .rec files; the live replay builds its header from it (live_rec.py)."""
import collections, glob, json, struct, sys
def sdsc(d):
    c = d.find(b'Relic Chunky\r\n\x1a\x00', 20); c = d.find(b'Relic Chunky\r\n\x1a\x00', c + 16)
    if c < 0: return None
    p = c + struct.unpack_from('<I', d, c + 24)[0]
    while p + 28 <= len(d) and d[p:p + 4] in (b'FOLD', b'DATA'):
        ver, size, nlen = struct.unpack_from('<III', d, p + 8); po = p + 28 + nlen
        if d[p:p + 8] == b'DATASDSC': return ver, d[po:po + size]
        p = po + size
    return None
def map_of(b):
    i = b.find(b'DATA:maps')
    if i < 4: return None
    n = struct.unpack_from('<I', b, i - 4)[0]
    return b[i:i + n].decode('latin-1').lower()
seen = collections.defaultdict(collections.Counter)
for g in sys.argv[2:]:
    for f in glob.glob(g, recursive=True):
        try:
            d = open(f, 'rb').read()
            if d[12:20] != b'DOW2_REC': continue
            r = sdsc(d)
            if r and r[0] == 2008:
                m = map_of(r[1])
                if m: seen[m][r[1].hex()] += 1
        except Exception: pass
out = {m: c.most_common(1)[0][0] for m, c in sorted(seen.items())}
json.dump({'v': 1, 'maps': out}, open(sys.argv[1], 'w'), indent=0)
print(len(out), 'maps;', sum(1 for c in seen.values() if len(c) > 1), 'with variants')
