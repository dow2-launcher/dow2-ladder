"""live.py - the live replay on the ladder (06.11.2026): watch a running match of our battle servers as a replay that keeps
growing, LIVE_DELAY s behind (owner: "для честности", the server's setting; the battle server has its own floor too).

The match is on one of our nodes (battle_relay.py; the room id of our lobby server is the relay session id). The node builds
the replay itself (gameserver/live_rec.py) from the ticks and the host's lobby state; the ladder only knows which match is where,
asks the node ("DWRL", see battle_relay.py) and hands the answer to any number of spectators - one request per match and
position every LIVE_CACHE s, whatever the number of them.
  GET /ladder/api/live/<match>            -> {ok, game, map, mode, started, delay, teams}  (404: not ours / unknown)
  GET /ladder/api/live/<match>/rec?from=N -> the node's envelope as it is (application/octet-stream): "DWLR" ver flags
     available ticks header(len + bytes, only for from=0) records(len + bytes) meta(len + JSON). LiveReplay.dll reads it.
Only native matches of our lobby server (automatch v2, launcher rooms) - a Relic match has no node of ours."""
import json, os, socket, struct, threading, time

DELAY = int(os.environ.get('LIVE_DELAY', '120'))           # s behind the match (the node never gives less than its own floor)
PORT = int(os.environ.get('LIVE_NODE_PORT', '47100'))      # battle_relay on our nodes
NODES = dict(x.split('=', 1) for x in os.environ.get('LIVE_NODES', '').split(',') if '=' in x)   # test: "ip=host:port"
KEEP = 3 * 3600                                            # s a match stays watchable after its start (the node says when it is over)
CACHE = 2.0                                                # s an answer of a node is reused
LOCK = threading.Lock()
LIVE = {}                                                  # match id -> {node, room, game, map, mode, started, teams}
_cache = {}                                                # (match, from) -> (time, bytes)


def register(m, names=None):
    """a native match of ours started (ladder nm_started): it can be watched"""
    node = m.get('relay_used') or m.get('relay') or ''
    room = str(m.get('room') or '')
    if not (m.get('native') and node and room.isdigit()): return False
    pool = m.get('pool') or ''
    if pool.startswith('lroom:'): pool = pool.split('|', 1)[1] if '|' in pool else ''   # a launcher room: <group>|<game>|... after it
    pool = pool.split('|')
    game = 'vanilla' if len(pool) > 1 and pool[1].startswith('vanilla') else 'elite'      # <group>|vanilla|nm|... / elite-<ver>
    team = lambda ss: [{'steam': s, 'name': (m.get('players', {}).get(s) or {}).get('name') or 'Player',
                        'race': (m.get('players', {}).get(s) or {}).get('race')} for s in ss]
    with LOCK:
        LIVE[m['id']] = {'node': node, 'room': room, 'game': game, 'map': m.get('map') or '', 'mode': m.get('mode') or '',
                         'started': int(m.get('started') or time.time()), 'teams': [team(m.get('host') or []), team(m.get('guest') or [])]}
        now = time.time()
        for k in [k for k, v in LIVE.items() if now - v['started'] > KEEP]: LIVE.pop(k, None)
    print('live: match %s watchable (node %s, room %s, %s)' % (m['id'], node, room, game), flush=True)
    return True


def watchable(mid):
    with LOCK: return mid in LIVE


def info(mid):
    with LOCK: v = LIVE.get(mid)
    if not v: return None
    return {'ok': True, 'match': mid, 'game': v['game'], 'map': v['map'], 'mode': v['mode'], 'started': v['started'],
            'delay': DELAY, 'teams': v['teams']}


def fetch(mid, frm):
    """-> the node's envelope for this match from record frm, None = not a match we know"""
    with LOCK: v = LIVE.get(mid)
    if not v: return None
    key = (mid, frm); now = time.time()
    with LOCK:
        c = _cache.get(key)
        if c and now - c[0] < CACHE: return c[1]
    hp = NODES.get(v['node'], '%s:%d' % (v['node'], PORT)); host, port = hp.rsplit(':', 1)
    s = socket.create_connection((host, int(port)), timeout=8)
    try:
        s.settimeout(20)
        s.sendall(b'DWRL' + struct.pack('<III', int(v['room']), max(0, frm), DELAY) + bytes([1 if v['game'] == 'vanilla' else 0]))
        chunks = []
        while True:
            b = s.recv(65536)
            if not b: break
            chunks.append(b)
            if sum(map(len, chunks)) > 16 << 20: break
    finally: s.close()
    data = b''.join(chunks)
    if data[:4] != b'DWLR': raise IOError('bad answer from %s' % hp)
    with LOCK:
        _cache[key] = (now, data)
        for k in [k for k, c in _cache.items() if now - c[0] > 30]: _cache.pop(k, None)
    return data
