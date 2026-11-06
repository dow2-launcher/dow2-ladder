"""Node quality per player (owner 06.11.2026): "at 30-40 % loss nothing helps - neither copies nor TCP; just keep it and openly
offer not to use that server for that player".

What is kept: for every player (Steam id) and every game node of ours, the recent measurements of the way between them -
  * the launcher's connection test ("Check connection"; launcher 1.4.23+ sends each finished run silently with its session
    token: per node the median ping, losses up / down, "stuck up to N s", the longest pause, a cut stream, a stream stopped on the
    way (DPI));
  * real matches on our nodes (deploy/nodeq_collect.py on rts every few minutes: the node's battle_relay "leave" line of each
    player - his Steam id from his peer announce, the stalls that were his alone - joined with the UDP gateway's "close" line of
    his connection - losses up (holes / copies that filled one) and down (resends), the connection died).
Kept KEEP_DAYS; the newest decide.

A node is BAD for a player when his NEED_BAD newest measurements of it are all bad (one good fresh measurement clears it):
  bad = losses >= LOSS_BAD % (either way), or a stall / pause >= STALL_MS (a match: >= MATCH_STALLS stalls of >= 1 s that were
  his alone), or the stream broke (cut, no game flow, the connection died) or was stopped on the way (DPI).
A node that does not answer at all is not a measurement here (Relay.dll itself does not use a node it can't reach).

The matchmaker (ladder._best_relay, the launcher rooms, the native automatch) does not put a match on a node that is BAD for one
of its players, as if he could not reach it; his chain through a good node of his stays possible (see ladder._relay_cost).
Nothing fits with the marks -> the marks are ignored for that match (a match on a poor node beats no match).
The player sees it in the launcher (Settings -> Online play, the connection test window, the room's ping table) and may press
"use it anyway": the mark is off for him for FORCE_SECS.
Storage: data/nodeq.sqlite (its own file - not community / feedback).
"""
import json, os, sqlite3, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get('NODEQ_DB') or ROOT + '/data/nodeq.sqlite'
KEEP_DAYS = 7
LOSS_BAD = 10.0          # % lost either way
STALL_MS = 1000          # a stall / pause this long (the launcher's test)
MATCH_STALLS = 2         # a match: this many stalls >= 1 s of this player alone
MATCH_MIN_RX = 300       # a match: packets from the player at least (~30 s of turns) to judge it at all
NEED_BAD = 2             # this many newest measurements all bad -> the node is bad for him
FORCE_SECS = 86400       # "use it anyway" lasts this long
_LOCK = threading.Lock()
_CACHE = {}              # steam -> {ip: mark} (built from the db, dropped on every write for that player)
_PRUNED = [0.0]


def db():
    c = sqlite3.connect(DB, timeout=10)
    c.execute('''CREATE TABLE IF NOT EXISTS sample(steam TEXT, ip TEXT, t REAL, src TEXT, ref TEXT UNIQUE, bad INTEGER,
                 why TEXT, loss REAL, stall_ms INTEGER, med REAL, info TEXT)''')
    c.execute('CREATE INDEX IF NOT EXISTS sample_st ON sample(steam, ip, t)')
    c.execute('CREATE INDEX IF NOT EXISTS sample_t ON sample(t)')
    c.execute('CREATE TABLE IF NOT EXISTS force(steam TEXT, ip TEXT, until REAL, PRIMARY KEY(steam, ip))')
    return c


def _f(v, lo=0.0, hi=1e12):
    try: v = float(v)
    except Exception: return None
    return max(lo, min(hi, v)) if v == v else None


def _ip(v):
    v = str(v or '')
    parts = v.split('.')
    return v if len(parts) == 4 and all(p.isdigit() and int(p) < 256 for p in parts) else None


# ---------- judging one measurement ----------
def judge_test(n):
    """one node of the launcher's test -> (bad, why, loss %, stall ms, median ms) or None (no answer / cancelled: no information)"""
    why_in = [str(x) for x in (n.get('why') or [])][:16]
    tr = str(n.get('transport') or '')
    if tr == 'none' or 'no_answer' in why_in or 'cancelled' in why_in: return None
    loss = max(_f(n.get('loss_up')) or 0.0, _f(n.get('loss_down')) or 0.0)
    stall = max(_f(n.get('stall_ms')) or 0.0, _f(n.get('max_gap_ms')) or 0.0)
    why = []
    if loss >= LOSS_BAD: why.append('loss')
    if stall >= STALL_MS: why.append('stall')
    if n.get('cut') or 'cut' in why_in or 'no_flow' in why_in: why.append('cut')
    if 'stream_blocked' in why_in: why.append('dpi')
    return bool(why), why, round(loss, 1), int(stall), _f(n.get('med'))


def judge_match(m):
    """one player's match on a node (nodeq_collect.py) -> (bad, why, loss %, stall ms, None) or None (too short to say)"""
    rx = _f(m.get('rx')) or 0; tx = _f(m.get('tx')) or 0
    if rx < MATCH_MIN_RX: return None
    up = 100.0 * max(_f(m.get('lost_in')) or 0, _f(m.get('filled')) or 0) / max(rx, 1)
    down = 100.0 * (_f(m.get('resent')) or 0) / max(tx, 1)
    loss = min(100.0, max(up, down))
    stalls = int(_f(m.get('solo_stalls')) or 0)
    why = []
    if loss >= LOSS_BAD: why.append('loss')
    if stalls >= MATCH_STALLS: why.append('stall')
    if m.get('dead'): why.append('cut')
    return bool(why), why, round(loss, 1), int(_f(m.get('max_solo_ms')) or 0), None


# ---------- writing ----------
def _add(c, steam, ip, t, src, ref, j, info):
    bad, why, loss, stall, med = j
    c.execute('INSERT OR IGNORE INTO sample(steam, ip, t, src, ref, bad, why, loss, stall_ms, med, info) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
              (steam, ip, t, src, ref, int(bad), ','.join(why), loss, stall, med, json.dumps(info, separators=(',', ':'))[:600]))


def _prune(c, now):
    if now - _PRUNED[0] < 3600: return
    _PRUNED[0] = now
    c.execute('DELETE FROM sample WHERE t < ?', (now - KEEP_DAYS * 86400,))
    c.execute('DELETE FROM force WHERE until < ?', (now,))


def add_test(steam, d, nodes_known, now=None):
    """the launcher's run (POST nq/test): {ts, mode, vpn, launcher, nodes: [{ip, transport, verdict, why, med, loss_up, loss_down,
    stall_ms, max_gap_ms, cut, secs}]} -> how many node measurements were kept"""
    now = now or time.time(); steam = str(steam)
    ts = _f(d.get('ts')) or now
    if ts > now + 300 or ts < now - 3600: ts = now                  # the player's clock: not trusted beyond an hour
    rows = [x for x in (d.get('nodes') or []) if isinstance(x, dict)][:12]
    n = 0
    with _LOCK:
        c = db()
        try:
            for x in rows:
                ip = _ip(x.get('ip'))
                if not ip or ip not in nodes_known: continue
                j = judge_test(x)
                if j is None: continue
                info = {k: x.get(k) for k in ('verdict', 'transport', 'secs') if x.get(k) is not None}
                info.update(mode=str(d.get('mode') or '')[:4], vpn=bool(d.get('vpn')), why_l=[str(w)[:20] for w in (x.get('why') or [])][:8])
                _add(c, steam, ip, ts, 'test', 'test:%s:%s:%d' % (steam, ip, int(ts)), j, info); n += 1
            _prune(c, now); c.commit()
        finally: c.close()
        _CACHE.pop(steam, None)
    return n


def add_matches(samples, nodes_known, now=None):
    """the collector's samples (POST nq/match, loopback only): [{steam, ip, t, ref, rx, tx, lost_in, filled, resent, solo_stalls,
    max_solo_ms, dead, secs, sid}] -> how many were new"""
    now = now or time.time(); n = 0; touched = set()
    with _LOCK:
        c = db()
        try:
            for m in [x for x in (samples or []) if isinstance(x, dict)][:2000]:
                steam = str(m.get('steam') or ''); ip = _ip(m.get('ip'))
                if not steam.isdigit() or not ip or ip not in nodes_known: continue
                j = judge_match(m)
                if j is None: continue
                t = _f(m.get('t')) or now
                info = {k: m.get(k) for k in ('sid', 'secs', 'rx', 'tx', 'lost_in', 'filled', 'resent', 'solo_stalls', 'dead', 'srtt_ms') if m.get(k) is not None}
                before = c.total_changes
                _add(c, steam, ip, t, 'match', 'match:' + str(m.get('ref') or '%s:%s:%d' % (steam, ip, int(t)))[:120], j, info)
                if c.total_changes > before: n += 1; touched.add(steam)
            _prune(c, now); c.commit()
        finally: c.close()
        for s in touched: _CACHE.pop(s, None)
    return n


def force(steam, ip, on, now=None):
    """"use it anyway": the mark is off for this player and node for FORCE_SECS (on=False: back to the marks)"""
    now = now or time.time(); steam = str(steam); ip = _ip(ip)
    if not ip: return False
    with _LOCK:
        c = db()
        try:
            if on: c.execute('INSERT OR REPLACE INTO force(steam, ip, until) VALUES(?,?,?)', (steam, ip, now + FORCE_SECS))
            else: c.execute('DELETE FROM force WHERE steam=? AND ip=?', (steam, ip))
            c.commit()
        finally: c.close()
        _CACHE.pop(steam, None)
    return True


# ---------- reading ----------
def _marks(steam, now):
    """{ip: mark} for every node with measurements of this player: bad (the NEED_BAD newest all bad), the newest bad one's numbers
    and time, forced_until"""
    c = db()
    try:
        rows = c.execute('SELECT ip, t, src, bad, why, loss, stall_ms, med FROM sample WHERE steam=? AND t>=? ORDER BY t DESC',
                         (steam, now - KEEP_DAYS * 86400)).fetchall()
        forced = {ip: u for ip, u in c.execute('SELECT ip, until FROM force WHERE steam=? AND until>?', (steam, now)).fetchall()}
    finally: c.close()
    out = {}
    for ip, t, src, bad, why, loss, stall, med in rows:
        m = out.get(ip)
        if m is None: m = out[ip] = {'run': 0, 'done': False, 'n': 0, 'last': None}
        m['n'] += 1
        if m['done']: continue
        if bad:
            m['run'] += 1
            if m['last'] is None: m['last'] = {'t': int(t), 'src': src, 'why': [w for w in (why or '').split(',') if w], 'loss': loss, 'stall_ms': stall, 'med': med}
        else:
            m['done'] = True
            if m['run'] == 0: m['good_t'] = int(t)
    res = {}
    for ip, m in out.items():
        bad = m['run'] >= NEED_BAD
        r = {'bad': bad, 'n': m['n'], 'bad_run': m['run']}
        if m['last']: r.update(m['last'])
        if ip in forced: r['forced_until'] = int(forced[ip])
        r['avoid'] = bad and ip not in forced
        res[ip] = r
    return res


def marks(steam, now=None):
    steam = str(steam or '')
    if not steam: return {}
    now = now or time.time()
    with _LOCK:
        e = _CACHE.get(steam)
        if e and 0 <= now - e[0] < 60: return e[1]
    try: m = _marks(steam, now)
    except Exception as ex:
        print('nodeq: marks %s: %r' % (steam, ex), flush=True); m = {}
    with _LOCK:
        if len(_CACHE) > 5000: _CACHE.clear()
        _CACHE[steam] = (now, m)
    return m


def avoid(steam, now=None):
    """the nodes the matchmaker does not use for this player now"""
    return frozenset(ip for ip, m in marks(steam, now).items() if m.get('avoid'))


def public(steam, now=None):
    """what the launcher shows: only the nodes that are marked (bad) or forced, with the numbers of the newest bad measurement"""
    return {ip: {k: v for k, v in m.items() if k in ('bad', 'avoid', 't', 'src', 'why', 'loss', 'stall_ms', 'forced_until', 'bad_run')}
            for ip, m in marks(steam, now).items() if m.get('bad')}
