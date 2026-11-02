#!/usr/bin/env python3
"""own_lobby.py - our lobby server for DoW2 Retribution (EXPERIMENT, owner 02.11.2026: the automatch fully on our own servers).

The game's lobby service (RLink inside DOW2.exe 3.19) is plain HTTPS to dow2r-lobby.reliclink.com: GET /game/<service>/<call>?<params>,
the answers are JSON arrays. Players with the launcher add-on "own lobby server" (OwnLobby.dll in Dow2-patches) trust our CA next to
Relic's and send those connections here (rts.fintebtc.de:47443). This server:
- passes everything on to Relic as it is - login, news, chat, friends, Relic's custom games and its automatch: one TLS connection to
  Relic per game connection, Relic's certificate checked against Relic's own root (relic_ca.pem, the one pinned in DOW2.exe);
- strips Relic's telemetry credentials (RL_TELEMKINESIS*) from the login answer: never logged, never stored, never passed on;
- when OWN_ROOMS is on (data/own_rooms.on) hosts the PRIVATE rooms itself (the fast automatch makes those): ids from our own range
  (2 000 000 000+), the room's relay is our game server (battle_relay.py, native connection on :47100), joins, peers, start and
  the match result, which goes into the ladder's database as a match of its own (source "ownlobby") - Relic does not know our ids,
  so its reportMatch is not called for them. Public rooms (the Custom Games list) stay on Relic: everybody can see and join them;
- with data/trace.on writes a protocol trace (data/trace.jsonl, 600) with session ids, tickets and keys masked.
Session ids and Steam tickets pass through memory only. Usage: own_lobby.py   (env LOBBY_DATA, LOBBY_PORT, LOBBY_RELAYS, LADDER_DB)
"""
import asyncio, json, os, re, socket, sqlite3, ssl, sys, time, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get('LOBBY_DATA', '/srv/ownlobby/data')
PORT = int(os.environ.get('LOBBY_PORT', '47443'))
STATUS_PORT = int(os.environ.get('LOBBY_STATUS_PORT', '47444'))          # 127.0.0.1 only: rooms and counters, no session ids
RELIC = 'dow2r-lobby.reliclink.com'
LADDER_DB = os.environ.get('LADDER_DB', '/srv/ladder/data/ladder.sqlite')
RELAYS = [(h.rsplit(':', 1)[0], int(h.rsplit(':', 1)[1])) for h in
          os.environ.get('LOBBY_RELAYS', '15.220.68.107:47100,116.202.106.150:47100').split(',') if ':' in h]
MID_BASE, MID_TOP = 2_000_000_000, 2_100_000_000
SECRET_PARAMS = {'sessionid', 'auth', 'authticket', 'platformuserid', 'password', 'steamticket', 'ticket', 'token'}
TELEM_RE = re.compile(rb'(\["RL_TELEMKINESIS[A-Z_]*",\s*")[^"]*(")')


def flag(name): return os.path.exists(os.path.join(DATA, name))


def log(*a): print(time.strftime('%T'), *a, flush=True)


# ---------------- trace (masked) ----------------
def mask_params(p):
    out = {}
    for k, v in p.items():
        if k.lower() in SECRET_PARAMS: out[k] = '<x>' if v else ''
        elif len(v) > 1500: out[k] = v[:1500] + '...<%d>' % len(v)
        else: out[k] = v
    return out


def mask_body(call, b):
    s = b.decode('utf-8', 'replace')
    if call.startswith('login/'):
        s = re.sub(r'^\[0,"[^"]*"', '[0,"<sid>"', s)
    s = re.sub(r'"(RL_TELEMKINESIS[A-Z_]*|RL_TITLEID|RL_CLOUD_CREDENTIAL_PROVIDER)",\s*"[^"]*"', r'"\1","<x>"', s)
    return s[:6000]


def trace(**k):
    if not flag('trace.on'): return
    k['t'] = round(time.time(), 3)
    p = os.path.join(DATA, 'trace.jsonl')
    with open(p, 'a') as f: f.write(json.dumps(k, ensure_ascii=False) + '\n')
    try: os.chmod(p, 0o600)
    except OSError: pass


# ---------------- sessions (memory only) ----------------
SESSIONS = {}                     # session id -> {pid, steam, alias, sg, ip, seen}


def remember_login(body, ip):
    try: j = json.loads(body)
    except Exception: return
    if not (isinstance(j, list) and len(j) > 3 and j[0] == 0 and isinstance(j[1], str)): return
    try:
        me = j[3][0]
        info = {'pid': int(me[1]), 'steam': str(me[2]).replace('/steam/', ''), 'alias': str(me[4]), 'sg': int(me[6]), 'ip': ip, 'seen': time.time(),
                'inj': 0, 'pending': [], 'pend_seq': None, 'pend_n': 0, 'wake': asyncio.Event()}
    except Exception:
        return
    SESSIONS[j[1]] = info
    log('login pid=%d alias=%r from %s' % (info['pid'], info['alias'], ip))
    return info


def session_of(params):
    s = SESSIONS.get(params.get('sessionID') or '')
    if s: s['seen'] = time.time()
    return s


def reap_sessions():
    now = time.time()
    for k in [k for k, v in SESSIONS.items() if now - v['seen'] > 6 * 3600]: SESSIONS.pop(k, None)


# ---------------- push: our messages inside Relic's readSession stream ----------------
# readSession?ack=N is a long poll; the answer is "<seq>,[[msg, ...]]" where seq counts messages. Our messages (MatchStartMessage of
# our rooms) go out in answers of their own; the player's count then runs ahead of Relic's by what he has confirmed of ours
# ('inj'), so his ack is turned back into Relic's (ack - inj) and Relic's seq into his (seq + inj). A poll waiting at Relic is
# dropped when one of ours comes (Relic keeps what it has not had confirmed and gives it again on the next poll).
def push(pid, msg):
    n = 0
    for s in SESSIONS.values():
        if s['pid'] == pid and time.time() - s['seen'] < 120:
            s['pending'].append(msg); s['wake'].set(); n += 1
    return n


def push_answer(s, ack):
    s['pend_seq'] = ack + len(s['pending']); s['pend_n'] = len(s['pending'])
    return ('%d,[%s]' % (s['pend_seq'], json.dumps(s['pending'], separators=(',', ':')))).encode()


# ---------------- our rooms ----------------
ROOMS = {}                        # mid -> room
STATS = {'conn': 0, 'req': 0, 'own': 0, 'relic': 0, 'relic_err': 0}


def next_mid():
    p = os.path.join(DATA, 'next_mid')
    try: mid = int(open(p).read().strip())
    except Exception: mid = MID_BASE + int(time.time()) % 1_000_000 * 10
    if not MID_BASE <= mid < MID_TOP: mid = MID_BASE
    with open(p + '.tmp', 'w') as f: f.write(str(mid + 1))
    os.replace(p + '.tmp', p)
    return mid


def ours(v):
    try: return MID_BASE <= int(v) < MID_TOP
    except Exception: return False


RELAY_UP = {}                     # (ip, port) -> True/False, probed every 30 s


async def relay_prober():
    while True:
        for hp in RELAYS:
            try:
                _, w = await asyncio.wait_for(asyncio.open_connection(*hp), 3)
                w.close(); RELAY_UP[hp] = True
            except Exception:
                RELAY_UP[hp] = False
        reap_sessions(); reap_rooms()
        await asyncio.sleep(30)


def pick_relay():
    for hp in RELAYS:
        if RELAY_UP.get(hp, True): return hp
    return RELAYS[0]


def reap_rooms():
    now = time.time()
    for mid, r in list(ROOMS.items()):
        if r['reports'] and not r.get('stored') and now - r.get('first_report', now) > 90: to_ladder(r)   # someone never reported (left)
        if (r['state'] != 'playing' and now - r['seen'] > 3600) or now - r['created'] > 6 * 3600:
            ROOMS.pop(mid, None); log('room %d dropped (idle)' % mid)


def member_row(r, pid):
    m = r['members'].get(pid) or {}
    return [r['mid'], pid, m.get('race', -1), m.get('sg', 0), m.get('team', 0), -1]


def own_call(call, p, sess):
    """our answer (a JSON value) for a call about one of our rooms, or None = pass it on to Relic"""
    if not flag('own_rooms.on') or not sess: return None
    svc, _, fn = call.partition('/')
    if svc not in ('advertisement', 'party'): return None
    mid = p.get('advertisementid') or p.get('matchID') or p.get('match_id') or p.get('matchid')
    if fn == 'host' and str(p.get('advertisementid')) == '-1':
        if p.get('visible', '1') != '0': return None                   # public rooms stay on Relic: everybody sees them
        if p.get('description') == 'SESSION_MATCH_KEY': return None     # the party of the game's own (Relic) automatch screen
        mid = next_mid(); ip, port = pick_relay(); now = time.time()
        r = ROOMS[mid] = {'mid': mid, 'host': sess['pid'], 'host_alias': sess['alias'], 'relay': [ip, port], 'state': 'lobby',
                          'params': {k: v for k, v in p.items() if k.lower() not in SECRET_PARAMS},
                          'members': {sess['pid']: {'sg': sess['sg'], 'steam': sess['steam'], 'alias': sess['alias'], 'race': -1, 'team': 0}},
                          'created': now, 'seen': now, 'reports': {}, 'started': None, 'lobby_id': None}
        log('room %d hosted by pid=%d (%s), relay %s:%d' % (mid, sess['pid'], sess['alias'], ip, port))
        return [0, mid, 'authtoken', ip, port, [member_row(r, sess['pid'])]]
    if not ours(mid): return None
    mid = int(mid); r = ROOMS.get(mid)
    if not r:                                                            # ours, but gone (server restart): as Relic would say
        log('call %s for unknown room %d' % (call, mid)); return [2]
    r['seen'] = time.time()
    if fn == 'join':
        r['members'].setdefault(sess['pid'], {'sg': sess['sg'], 'steam': sess['steam'], 'alias': sess['alias'], 'race': -1, 'team': 0})
        ip, port = r['relay']
        log('room %d: pid=%d (%s) joins' % (mid, sess['pid'], sess['alias']))
        return [0, '/' + ip, ip, port, [member_row(r, sess['pid'])]]   # as Relic: code, the relay's address, relay, port, the joiner
    if fn == 'leave':
        r['members'].pop(sess['pid'], None)
        if sess['pid'] == r['host'] and r['state'] != 'playing':
            ROOMS.pop(mid, None); log('room %d closed by its host' % mid)
        return [0]
    if fn in ('update', 'updateState'):
        if sess['pid'] == r['host']:
            r['params'].update({k: v for k, v in p.items() if k.lower() not in SECRET_PARAMS})
            if fn == 'updateState' and p.get('state') not in (None, '0', '2') and r['state'] == 'lobby': start_room(r)
        return [0]
    if fn == 'updatePlatformLobbyID':
        r['lobby_id'] = p.get('platformlobbyID'); return [0]
    if fn in ('peerAdd', 'peerUpdate'):
        try:
            pids = json.loads(p.get('profile_ids') or '[]'); sgs = json.loads(p.get('statGroup_ids') or '[]')
            races = json.loads(p.get('race_ids') or '[]'); teams = json.loads(p.get('teamIDs') or '[]')
        except Exception:
            pids = sgs = races = teams = []
        if fn == 'peerUpdate' and pids: r['order'] = [int(x) for x in pids]
        for i, pid in enumerate(pids):
            m = r['members'].setdefault(int(pid), {})
            if i < len(sgs): m['sg'] = sgs[i]
            if i < len(races): m['race'] = races[i]
            if i < len(teams): m['team'] = teams[i]
        return [0]
    if fn == 'updateHost':
        return [0]
    if fn == 'reportMatch':
        return report(r, sess, p)
    log('room %d: %s not handled - answered [0]' % (mid, call))
    return [0]


def start_room(r):
    r['state'] = 'playing'; r['started'] = time.time()
    order = r.get('order') or list(r['members'])
    body = [[[pid, []] for pid in order], [[str(pid), str(r['members'].get(pid, {}).get('race', -1))] for pid in order], int(r['started']),
            [[str(pid), []] for pid in order]]
    got = sum(push(pid, [0, 'MatchStartMessage', pid, body]) for pid in order)
    log('room %d: match started, %d players, start message to %d session(s)' % (r['mid'], len(order), got))


def report(r, sess, p):
    if r['state'] == 'lobby': start_room(r)
    r.setdefault('first_report', time.time())
    r['reports'][sess['pid']] = {k: v for k, v in p.items() if k.lower() not in SECRET_PARAMS}
    log('room %d: result from pid=%d (%d of %d)' % (r['mid'], sess['pid'], len(r['reports']), len(r['members'])))
    if len(r['reports']) >= len(r.get('order') or r['members']):
        to_ladder(r)
    return [0]


def to_ladder(r):
    """the match into the ladder's database in the shape of a Relic match history entry (the ladder rates it like the others)"""
    if r.get('stored'): return
    r['stored'] = True
    rep = next(iter(r['reports'].values()), {})
    outcome = {}
    for pid, x in r['reports'].items():                                  # every player reports his own outcome (see results)
        try: res = json.loads(x.get('results') or '[]')
        except Exception: res = []
        try: ids = json.loads(x.get('profile_ids') or '[]')
        except Exception: ids = []
        for i, q in enumerate(ids):
            if i < len(res): outcome.setdefault(int(q), res[i])
    start = int(r['started'] or r['created']); end = int(time.time())
    members = [{'profile_id': pid, 'race_id': m.get('race', -1), 'teamid': m.get('team', 0), 'statgroup_id': m.get('sg', 0),
                'outcome': outcome.get(pid, -1)} for pid, m in r['members'].items()]
    p = r['params']
    m = {'id': r['mid'], 'source': 'ownlobby', 'mapname': p.get('mapname', ''), 'description': p.get('description', ''),
         'maxplayers': int(p.get('maxplayers') or 0), 'matchtype_id': 0, 'startgametime': start, 'completiontime': end,
         'slotinfo': p.get('slotinfo', ''), 'options': p.get('options', ''), 'modname': p.get('modname', ''),
         'matchhistorymember': members, 'report': {k: v for k, v in rep.items() if k in ('profile_ids', 'results', 'race_ids', 'teamIDs', 'counters')}}
    teams = {}
    for x in members: teams.setdefault(x['teamid'], []).append(x)
    sizes = sorted(len(v) for v in teams.values())
    mode = {(1, 1): '1v1', (2, 2): '2v2', (3, 3): '3v3'}.get(tuple(sizes), '') if len(teams) == 2 else ''
    elite = 1 if 'elite' in (p.get('modname') or '').lower() else 0
    if flag('unrated.on'): mode = ''                                     # tests: stored and shown, not rated
    t = time.gmtime(start); season = '%d-Q%d' % (t.tm_year, (t.tm_mon - 1) // 3 + 1)
    try:
        c = sqlite3.connect(LADDER_DB, timeout=30)
        with c:
            c.execute('INSERT OR IGNORE INTO matches VALUES (?,?,?,?,?,?)', (r['mid'], start, elite, mode, season, json.dumps(m, separators=(',', ':'))))
            for x in members: c.execute('INSERT OR IGNORE INTO members VALUES (?,?,?)', (x['profile_id'], r['mid'], start))
            # the ladder's automatch history: its row of this match (same players, started within 10 min) gets the result
            pids = {x['profile_id'] for x in members}
            for lobby, pl in c.execute('SELECT lobby, players FROM mm_history WHERE result IS NULL AND started BETWEEN ? AND ?', (start - 600, start + 600)).fetchall():
                if {q.get('pid') for q in json.loads(pl)} == pids:
                    try: cn = {pid: json.loads(x) for pid, x in zip(json.loads(rep.get('profile_ids') or '[]'), json.loads(rep.get('counters') or '[]'))}
                    except Exception: cn = {}
                    res = {'own_id': r['mid'], 'mapname': p.get('mapname'), 'start': start, 'duration': end - start,
                           'players': [{'pid': x['profile_id'], 'result': x['outcome'], 'team': x['teamid'], 'race': x['race_id'], 'hero': None,
                                        'counters': cn.get(x['profile_id'])} for x in members]}
                    c.execute('UPDATE mm_history SET result = ?, ended = coalesce(ended, ?) WHERE lobby = ?', (json.dumps(res), end, lobby))
                    log('room %d: result in the ladder history (%s)' % (r['mid'], lobby)); break
        c.close()
        log('room %d: result in the ladder (%s, %s, elite=%d): %s' % (r['mid'], mode or 'no mode', p.get('mapname'), elite,
                                                                     ', '.join('%d:%s' % (x['profile_id'], x['outcome']) for x in members)))
    except Exception as e:
        log('room %d: ladder write failed: %r' % (r['mid'], e))


# ---------------- HTTP over TLS ----------------
RELIC_CTX = ssl.create_default_context(cafile=os.path.join(HERE, 'relic_ca.pem'))
RELIC_CTX.verify_flags &= ~ssl.VERIFY_X509_STRICT                     # Relic's root (2014) has a non-critical basicConstraints


def server_ctx():
    c = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    c.load_cert_chain(os.path.join(DATA, 'lobby.crt'), os.path.join(DATA, 'lobby.key'))
    c.minimum_version = ssl.TLSVersion.TLSv1_2                          # DOW2.exe: OpenSSL 1.0.1e, TLS 1.2 ECDHE-RSA-AES-GCM
    c.set_ciphers('ECDHE+AESGCM:ECDHE+AES:@SECLEVEL=1')
    return c


async def read_message(r, request):
    head = await r.readuntil(b'\r\n\r\n')
    lines = head.decode('latin-1').split('\r\n')
    first = lines[0]; hdrs = {}
    for ln in lines[1:]:
        if ':' in ln: k, v = ln.split(':', 1); hdrs[k.strip().lower()] = v.strip()
    body = b''
    if 'chunked' in hdrs.get('transfer-encoding', '').lower():
        while True:
            n = int((await r.readuntil(b'\r\n')).split(b';')[0].strip() or b'0', 16)
            if n == 0:
                await r.readuntil(b'\r\n'); break
            body += await r.readexactly(n); await r.readexactly(2)
    elif 'content-length' in hdrs:
        body = await r.readexactly(int(hdrs['content-length']))
    elif not request and hdrs.get('connection', '').lower() == 'close':
        body = await r.read()
    return first, lines[1:], hdrs, body


class Upstream:
    def __init__(self): self.r = self.w = None

    def close(self):
        if self.w:
            try: self.w.close()
            except Exception: pass
        self.r = self.w = None

    async def request(self, raw):
        for attempt in (0, 1):
            fresh = self.w is None or self.w.is_closing()
            if fresh:
                self.r, self.w = await asyncio.wait_for(asyncio.open_connection(RELIC, 443, ssl=RELIC_CTX, server_hostname=RELIC, limit=8 << 20), 15)
            try:
                self.w.write(raw); await self.w.drain()
                return await asyncio.wait_for(read_message(self.r, False), 120)
            except (ConnectionError, asyncio.IncompleteReadError, ssl.SSLError, OSError):
                self.close()
                if attempt or fresh: raise                               # a kept connection Relic had closed: once more on a new one


def response(status, hdr_lines, body):
    keep = [h for h in hdr_lines if h and h.split(':', 1)[0].strip().lower() not in ('content-length', 'transfer-encoding')]
    return (status + '\r\n' + ''.join(h + '\r\n' for h in keep) + 'Content-Length: %d\r\n\r\n' % len(body)).encode('latin-1') + body


async def handle(r, w):
    peer = w.get_extra_info('peername'); ip = peer[0] if peer else '?'
    STATS['conn'] += 1; up = Upstream()
    try:
        while True:
            try: first, lines, hdrs, body = await asyncio.wait_for(read_message(r, True), 600)
            except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError, ssl.SSLError): break
            STATS['req'] += 1
            try: method, target, _ = first.split(' ', 2)
            except ValueError: break
            path, _, qs = target.partition('?')
            params = dict(urllib.parse.parse_qsl(qs, keep_blank_values=True))
            if body and 'urlencoded' in hdrs.get('content-type', ''):
                params.update(urllib.parse.parse_qsl(body.decode('latin-1'), keep_blank_values=True))
            call = path[6:] if path.startswith('/game/') else path
            sess = session_of(params)
            t0 = time.time()
            if call == 'login/readSession' and sess is not None:
                try: status, rlines, rbody = await read_session(sess, params, first, lines, body, up)
                except Exception as e:
                    STATS['relic_err'] += 1; log('readSession pid=%d: %r' % (sess['pid'], e)); break
                w.write(response(status, rlines, rbody)); await w.drain()
                if rbody[:1].isdigit() and not rbody.endswith(b',[[]]'): trace(ip=ip, pid=sess['pid'], call=call, p=mask_params(params), a=rbody.decode('utf-8', 'replace')[:3000])
                continue
            try: ans = own_call(call, params, sess)
            except Exception as e:
                log('own_call %s failed: %r' % (call, e)); ans = None
            if ans is not None:
                STATS['own'] += 1
                b = json.dumps(ans, separators=(',', ':')).encode()
                w.write(response('HTTP/1.1 200 OK', ['Content-Type: application/json', 'Connection: keep-alive',
                                                     'Cache-Control: no-store, no-cache, must-revalidate, max-age=0', 'Request-Path: ' + path], b))
                trace(ip=ip, pid=sess and sess['pid'], call=call, p=mask_params(params), own=1, a=b.decode()[:3000])
            else:
                raw = (first + '\r\n' + ''.join(h + '\r\n' for h in lines if h)).encode('latin-1') + b'\r\n' + body
                try: status, rlines, rh, rbody = await up.request(raw)
                except Exception as e:
                    STATS['relic_err'] += 1; log('relic %s: %r' % (call, e)); break
                STATS['relic'] += 1
                if call.startswith('login/'):
                    rbody = TELEM_RE.sub(rb'\1\2', rbody)
                    rbody = rbody.replace(b'["RL_TELEMSERVICE","1"]', b'["RL_TELEMSERVICE","0"]')
                    if call in ('login/platformlogin', 'login/login'): sess = remember_login(rbody, ip) or sess
                w.write(response(status, rlines, rbody))
                trace(ip=ip, pid=sess and sess['pid'], call=call, p=mask_params(params), st=status[9:12], ms=round((time.time() - t0) * 1000),
                      a=mask_body(call, rbody))
            await w.drain()
            if hdrs.get('connection', '').lower() == 'close': break
    except Exception as e:
        log('connection from %s: %r' % (ip, e))
    finally:
        up.close()
        try: w.close()
        except Exception: pass


OWN_HDRS = ['Content-Type: application/json', 'Connection: keep-alive', 'Cache-Control: no-store, no-cache, must-revalidate, max-age=0']


async def read_session(s, params, first, lines, body, up):
    """the long poll: ours first, else Relic's with the numbers moved by what the player confirmed of ours (see push)"""
    try: ack = int(params.get('ack', '0'))
    except ValueError: ack = 0
    s['wake'].clear()
    if s['pend_seq'] is not None and ack >= s['pend_seq']:              # he has ours: from now on Relic's numbers are ahead by them
        s['inj'] += s['pend_n']; del s['pending'][:s['pend_n']]; s['pend_seq'] = None; s['pend_n'] = 0
    if s['pending']:
        STATS['own'] += 1
        return 'HTTP/1.1 200 OK', OWN_HDRS + ['Request-Path: /game/login/readSession'], push_answer(s, ack)
    if s['inj']:
        first = re.sub(r'([?&]ack=)-?\d+', lambda m: m.group(1) + str(ack - s['inj']), first, count=1)
    raw = (first + '\r\n' + ''.join(h + '\r\n' for h in lines if h)).encode('latin-1') + b'\r\n' + body
    task = asyncio.ensure_future(up.request(raw)); wake = asyncio.ensure_future(s['wake'].wait())
    done, _ = await asyncio.wait({task, wake}, return_when=asyncio.FIRST_COMPLETED)
    if task in done:
        wake.cancel()
        status, rlines, _, rbody = task.result(); STATS['relic'] += 1
        m = re.match(rb'(\d+),', rbody)
        if m and s['inj']: rbody = str(int(m.group(1)) + s['inj']).encode() + rbody[m.end() - 1:]
        return status, rlines, rbody
    task.cancel(); up.close()                                            # Relic gives what it had again on the next poll
    STATS['own'] += 1
    return 'HTTP/1.1 200 OK', OWN_HDRS + ['Request-Path: /game/login/readSession'], push_answer(s, ack)


async def status(r, w):
    try:
        await r.readuntil(b'\r\n\r\n')
        rooms = [{'mid': x['mid'], 'host': x['host'], 'state': x['state'], 'relay': '%s:%d' % tuple(x['relay']), 'map': x['params'].get('mapname'),
                  'members': {str(k): {kk: vv for kk, vv in v.items() if kk != 'steam'} for k, v in x['members'].items()},
                  'reports': len(x['reports']), 'stored': bool(x.get('stored'))} for x in ROOMS.values()]
        b = json.dumps({'own_rooms': flag('own_rooms.on'), 'trace': flag('trace.on'), 'sessions': len(SESSIONS), 'stats': STATS,
                        'relays': {'%s:%d' % k: v for k, v in RELAY_UP.items()}, 'rooms': rooms}).encode()
        w.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: %d\r\n\r\n' % len(b) + b)
        await w.drain()
    except Exception: pass
    w.close()


async def main():
    os.makedirs(DATA, exist_ok=True)
    srv = await asyncio.start_server(handle, '0.0.0.0', PORT, ssl=server_ctx(), limit=4 << 20)
    st = await asyncio.start_server(status, '127.0.0.1', STATUS_PORT)
    asyncio.ensure_future(relay_prober())
    log('own lobby on :%d (own rooms %s, trace %s), relays %s' % (PORT, 'ON' if flag('own_rooms.on') else 'off', 'on' if flag('trace.on') else 'off',
                                                                 ', '.join('%s:%d' % x for x in RELAYS)))
    async with srv, st: await asyncio.gather(srv.serve_forever(), st.serve_forever())

if __name__ == '__main__':
    asyncio.run(main())
