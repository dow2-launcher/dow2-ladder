#!/usr/bin/env python3
"""live_rec.py - a DoW2 replay (.rec) of a match on our battle server, built from what the server itself carries (06.11.2026,
the "live replay": a spectator watches a running match as a replay that keeps growing, a fixed delay behind).

Nothing comes from the players' games: the server has every turn of the match (the 0x0a ticks it sends everyone) and the
host's lobby state, which the host sends every other player through the server before the start.

Ticks -> records (checked byte for byte against the players' own temp.rec, stand 06.11.2026: 3131 of 3131 records). The
game's lockstep (P2PNetworkSynchronization::GetSyncCommand, DOW2.exe 0x66D5A0) turns every tick of the server that carries
at least one message into one simulation step, and the recorder writes that step as it is:
  - first 4 steps of the match: empty records (the game's own start-up frames);
  - then one record per server tick with at least one turn that has data (ticks with none, or only data-less messages - the
    first one a game sends, or one after the match - make no step);
  - bundles: the messages of the tick grouped by the sender's number in the session (ascending), each sender's in the order
    they came; a bundle = [len & 0xFF][commands] (len = the commands' length); a message without data (the first one a
    game sends) is no bundle;
  - the record's tick and crc: those of the first entry of the lowest number in the tick - a player in the silent list has one
    empty entry (0 / 0), so does a message without data; the counter: the sum of the messages' command counters.
  - a player who left: one event record (type 1: 0, 8, player id 1000 + k, 0; k = his place among the filled slots) right
    after the second tick he is missing from (neither a message nor in the silent list) - as the game drops a peer.
A turn message (0x09 data): [0 | 1 = zlib of the rest] then 02, turn u32, counter u32, crc u32, len u16, commands.

Header: the file header, FOLDPOST (number of tick records), DATASDSC (the map: from live_maps.json - built from players'
replays by tools/live_maps.py; a stand test showed the game does not check its date / name id), FOLDINFO: DATABASE (seed of
the start message, the options of the lobby, the game's data checksum of a known replay) and 8 x DATAINFO (the slots of the
lobby state: name, team, race, hero, profile, army painter colours and badge).

Usage as a module: LiveRec(game, room_blob, start_blob) -> .header(ticks) / .feed(tick frame, time) -> records.
Run it: live_rec.py capture.jsonl out.rec [conn] - builds a replay from a capture of the stands (capproxy.py) for a test."""
import json, os, re, struct, time, zlib

RACES = {'elite': ['chaos_marines', 'eldar', 'imperial_guard', 'ordo_malleus', 'orks', 'space_marines', 't_tau', 'tyranids', 'z_unecron'],
         'vanilla': ['chaos_marines', 'eldar', 'imperial_guard', 'orks', 'space_marines', 'tyranids']}
SLOTS = 8
START_EMPTY = 4                                  # the game's first steps of a match: records without anything
# DATABASE carries the victory condition as the game's id of its script (the lobby has the drop-down's number): the ids from the
# players' own replays of stand matches, 06.11.2026 (lroom: 0 annihilate, 3 VPC, 4 annihilate - hero assault, 6 VPC - hero assault)
WIN_ID = {'elite': {0: 'a98ab169', 3: '52e203fc', 4: '738f43c8', 6: 'c8d5af1a'},
          'vanilla': {0: '03c98652', 3: '00eb7615'}}
MOD_TAG = {'elite': 0xD6805B7D, 'vanilla': 0x161D19DD}          # the file header's second word: the mod (Elite 3.2 / Retribution)
EMPTY_SLOT = bytes.fromhex('00000000070000000000000000000000ffffffffffffffffffffffff0000000000000000ffffffff00ffffffff'
                           '0000000000000000000000000000000000ffffffff')
_MAPS = None


def maps():
    global _MAPS
    if _MAPS is None:
        try: _MAPS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'live_maps.json')))['maps']
        except Exception: _MAPS = {}
    return _MAPS


# ---------------------------------------------------------------- reading what the server sees
def lobby_payload(m):
    """a 0x10 frame (RLink ProxyMessage: 10 src n(u16) n*dst len(u16) data + n*15) -> (game message type, decompressed body)
    for the zlib-packed game messages: data = 09 <type> len(u16) 01 <zlib>; None otherwise"""
    try:
        n = m[2] | m[3] << 8; o = 4 + n; size = m[o] | m[o + 1] << 8
        data = m[o + 2:o + 2 + size - 15 * n]
        if len(data) < 6 or data[0] != 0x09 or data[4] != 0x01: return None
        return data[1], zlib.decompressobj().decompress(data[5:])
    except Exception: return None


def is_room_state(body, sid):
    return len(body) > 40 and body[0] == 0 and body[1:5] == b'\x0c\0\0\0' and body[5:9] == sid


def is_start(body):
    return len(body) >= 9 and body[0] == 1 and len(body) < 200


def turn(d):
    """a turn message's data -> dict(turn, cnt, crc, cmds) or None (no data)"""
    if not d: return None
    if d[0] == 1: d = b'\x00' + zlib.decompressobj().decompress(d[1:])
    tn, cnt, crc, ln = struct.unpack_from('<IIIH', d, 2)
    return {'turn': tn, 'cnt': cnt, 'crc': crc, 'cmds': d[16:16 + ln]}


def tick_msgs(m):
    """a 0x0a frame -> ([(sender, data)], [silent senders])"""
    cnt = m[2]; o = 3; out = []
    for _ in range(cnt):
        idx = m[o]; ln = m[o + 1] | m[o + 2] << 8; out.append((idx, m[o + 3:o + 3 + ln])); o += 3 + ln
    ns = m[o]; return out, list(m[o + 1:o + 1 + ns])


# ---------------------------------------------------------------- the host's lobby state
class Room:
    """the parts of the lobby state the replay header needs. Layout (stand captures 06.11.2026): 00, 0C000000, sid, 0, 8 x FF,
    host profile, 11 x 00, name (at 0x24) (u32 + UTF-16), map (u32 + UTF-16), max players u32, options (u32 + ASCII: "<win> -1 <n>
    <key> <value>..."), 2 bytes, slots u16, the slots, the stations (machine, profile, /steam/<id>, name, ...)."""
    def __init__(self, b):
        self.b = b; o = 0x24
        self.name, o = self._ws(o)
        self.map, o = self._ws(o)
        self.maxplayers = struct.unpack_from('<I', self.b, o)[0]; o += 4
        n = struct.unpack_from('<I', self.b, o)[0]; self.opts_str = self.b[o + 4:o + 4 + n].decode('latin-1'); o += 4 + n
        v = [int(x) for x in self.opts_str.split()]
        self.win = v[0]; k = v[2]; self.opts = [(v[3 + 2 * i], v[4 + 2 * i]) for i in range(k)]
        o += 2; ns = struct.unpack_from('<H', self.b, o)[0]; o += 2
        self.slots = []
        for _ in range(ns):
            s, o = self._slot(o); self.slots.append(s)
        self.names = self._names()

    def _ws(self, o):
        n = struct.unpack_from('<I', self.b, o)[0]
        return self.b[o + 4:o + 4 + 2 * n].decode('utf-16-le'), o + 4 + 2 * n

    def _slot(self, o):
        b = self.b
        prof, _z, station, _z2, team, hero, race = struct.unpack_from('<IIIIiii', b, o); o += 28
        o += 1 + 4 + 10                                # 00, FF FF FF FF, 5 x u16 (colour indexes)
        clan, o = self._ws(o)
        colour = b[o:o + 4]; o += 4
        n = struct.unpack_from('<I', b, o)[0]; badge = b[o + 4:o + 4 + n]; o += 4 + n
        o += 4 + 1 + 8                                 # 0, 01, 8 x FF
        army = b[o]; o += 1
        return dict(profile=prof, station=station, team=team, hero=hero, race=race, clan=clan, colour=colour, badge=badge, army=army), o

    def _names(self):
        """profile id -> the player's name, from the stations: <profile> 0 <u32 n> "/steam/<id>" (UTF-16) 0 <u32 n> <name>"""
        out = {}
        for s in self.slots:
            p = struct.pack('<II', s['profile'], 0)
            for mt in re.finditer(re.escape(p), self.b):
                o = mt.end()
                try:
                    n = struct.unpack_from('<I', self.b, o)[0]
                    if self.b[o + 4:o + 4 + 14] != '/steam/'.encode('utf-16-le'): continue
                    o += 4 + 2 * n + 4; n = struct.unpack_from('<I', self.b, o)[0]
                    if 0 < n < 64: out[s['profile']] = self.b[o + 4:o + 4 + 2 * n].decode('utf-16-le', 'replace'); break
                except Exception: continue
        return out


# ---------------------------------------------------------------- the replay
def _chunk(tid, ver, payload, fold=False):
    return tid + struct.pack('<III', ver, len(payload), 0) + (b'\0\0\0\0' if fold else b'\xff\xff\xff\xff') + b'\0\0\0\0' + payload


def _u32s(s): b = s.encode('utf-16-le'); return struct.pack('<I', len(s)) + b
def _u32a(s): return struct.pack('<I', len(s)) + s


CHUNKY = b'Relic Chunky\r\n\x1a\x00' + struct.pack('<IIIII', 3, 1, 0x24, 0x1C, 1)


class LiveRec:
    def __init__(self, game, room_blob, start_blob, sid=b''):
        self.game = 'vanilla' if game == 'vanilla' else 'elite'
        self.room = Room(room_blob)
        self.seed = start_blob[1:5]
        # slot positions: each team fills its half of the 8 slots in the lobby's order (host first): 0.. / 4..
        k = {}; self.layout = [None] * SLOTS
        for s in self.room.slots:
            t = s['team'] if s['team'] in (0, 1) else 0
            i = t * 4 + k.get(t, 0); k[t] = k.get(t, 0) + 1
            if i < SLOTS: self.layout[i] = s
        # player ids of the simulation: 1000 + the place among the filled slots; the station (the server's number) -> it
        self.player_id = {}
        for n, s in enumerate(x for x in self.layout if x): self.player_id[s['station']] = 1000 + n
        self.records = [b''.join(self._rec0(0, 0, 0, [])) for _ in range(START_EMPTY)]
        self.ticks = START_EMPTY                      # tick records so far
        self.times = [0.0] * START_EMPTY             # the server's time of each record (the start-up ones: 0 = always old enough)
        self.present = set(); self.missing = {}; self.dropped = set()

    # -- header
    def _datainfo(self, s, first):
        if not s: return EMPTY_SLOT
        race = RACES[self.game][s['race']] if 0 <= s['race'] < len(RACES[self.game]) else 'space_marines'
        name = self.room.names.get(s['profile']) or 'Player'
        b = _u32s(name) + struct.pack('<II', 0 if first else 3, s['team']) + _u32a(race.encode())
        b += struct.pack('<IIIIIi', s['profile'], 0, s['army'], 0, 0, s['hero']) + b'\0' + struct.pack('<I', s['army'])
        b += s['colour'] + b'\x01' + _u32a(s['badge']) + b'\0\0\0\0' + _u32s(s['clan']) + struct.pack('<i', s['race'])
        return b

    def _sdsc(self):
        path = 'DATA:maps\\pvp\\' + self.room.map
        hx = maps().get(path.lower())
        if hx: return bytes.fromhex(hx)
        # a map no replay of ours has shown yet: the fields as a 2-player map has them, the path of this one
        b = _u32s('1/1/2011 12:00 AM') + _u32a(b'DOW2') + _u32a(path.encode()) + _u32s('$0')
        b += bytes.fromhex('0000000000000000') + struct.pack('<I', self.room.maxplayers) + bytes.fromhex('0001000000010000000000000000000000ffffffff')
        return struct.pack('<I', 2) + b + _u32a(path.encode())

    def header(self, nticks=None):
        n = self.ticks if nticks is None else nticks
        date = time.strftime('%m/%d/%Y %I:%M %p').lstrip('0').replace('/0', '/').replace(' 0', ' ')
        h = struct.pack('<III', 10320, MOD_TAG[self.game], 0) + b'DOW2_REC' + date.encode('utf-16-le')[:62].ljust(64, b'\0')
        h += CHUNKY + _chunk(b'FOLDPOST', 1, _chunk(b'DATADATA', 1, struct.pack('<I', n)), True)
        db = struct.pack('<II', 16, 8) + self.seed + struct.pack('<I', len(self._db_opts()))
        for key, val in self._db_opts(): db += struct.pack('<iI', val, key)
        win = WIN_ID[self.game].get(self.room.win) or WIN_ID['elite'].get(self.room.win) or WIN_ID['elite'][3]
        # (DOW2.exe 0x41AD12) u8, name, u32, the victory conditions (count + ids), u32, u8, u32, u8, u8, u8
        db += b'\0' + struct.pack('<III', 0, 0, 1) + bytes.fromhex(win) + struct.pack('<I', 0) + b'\0' + struct.pack('<I', 0) + b'\0\x01\x01'
        info = _chunk(b'DATABASE', 9, db)
        for i, s in enumerate(self.layout):
            info += _chunk(b'FOLDGPLY', 4, _chunk(b'DATAINFO', 7, self._datainfo(s, i == 0)), True)
        h += CHUNKY + _chunk(b'DATASDSC', 2008, self._sdsc()) + _chunk(b'FOLDINFO', 1, info, True)
        return h

    def _db_opts(self):
        keep = {0x5650544B, 0x534C4F43, 0x52535354}           # KTPV, COLS, TSSR - what the game's own replays carry
        return [(k, v) for k, v in self.room.opts if k in keep]

    # -- records
    @staticmethod
    def _rec0(tick, cnt, crc, bundles):
        body = b'\x20' + struct.pack('<IIII', tick, cnt, crc, len(bundles))
        for c in bundles: body += struct.pack('<III', 0, 0, len(c)) + bytes([len(c) & 0xFF]) + c
        yield struct.pack('<II', 0, len(body)) + body

    def feed(self, frame, t):
        """one 0x0a tick of the server -> the records it makes (0, 1 or 2: a step and a player's drop)"""
        msgs, silent = tick_msgs(frame)
        out = []
        here = {i for i, _ in msgs} | set(silent)
        if any(d for _, d in msgs):                                      # a step only for a tick with a turn that has data
            groups = {i: [None] for i in silent}                        # a silent player: an empty entry of his (no bundle)
            for i, d in msgs: groups.setdefault(i, []).append(turn(d))
            hdr = (0, 0); cnt = 0; bundles = []
            first = groups[min(groups)][0]                              # the first entry of the lowest number: the step's header
            if first: hdr = (first['turn'], first['crc'])
            for i in sorted(groups):
                for x in groups[i]:
                    if x: cnt += x['cnt']; bundles.append(x['cmds'])
            out.append(b''.join(self._rec0(hdr[0], cnt & 0xFFFFFFFF, hdr[1], bundles))); self.ticks += 1
        # a player gone from the ticks: dropped by the games right after the second tick without him
        for st in list(self.present):
            if st in here: self.missing.pop(st, None); continue
            if st in self.dropped: continue
            self.missing[st] = self.missing.get(st, 0) + (1 if msgs else 0)
            if self.missing[st] >= 2 and st in self.player_id:
                self.dropped.add(st)
                out.append(struct.pack('<II', 1, 16) + struct.pack('<IIII', 0, 8, self.player_id[st], 0))
        self.present |= here
        for r in out: self.records.append(r); self.times.append(t)
        return out


# ---------------------------------------------------------------- a test from a capture of the stands
if __name__ == '__main__':
    import sys
    cap, out = sys.argv[1], sys.argv[2]; conn = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    game = os.environ.get('GAME', 'elite')
    room = start = None; sid = None; lr = None; frames = []
    for l in open(cap):
        r = json.loads(l)
        if 'hex' not in r: continue
        m = bytes.fromhex(r['hex'])
        if r['d'] == 'up' and m[:1] == b'\x15' and sid is None: sid = m[1:5]
        if m[:1] == b'\x10' and r['d'] == 'up':
            p = lobby_payload(m)
            if p and sid and is_room_state(p[1], sid) and start is None: room = p[1]      # the state at the start
            elif p and p[0] == 0x55 and is_start(p[1]) and start is None: start = p[1]
        if m[:1] == b'\x0a' and r['n'] == conn and r['d'] == 'down': frames.append((m, r['t']))
    lr = LiveRec(game, room, start, sid)
    for m, t in frames: lr.feed(m, t)
    data = lr.header() + b''.join(lr.records)
    open(out, 'wb').write(data)
    print('room', lr.room.name, lr.room.map, lr.room.opts_str, [(s['station'], s['team'], s['race'], s['hero'], lr.room.names.get(s['profile'])) for s in lr.room.slots])
    print('records', len(lr.records), 'ticks', lr.ticks, 'bytes', len(data))
