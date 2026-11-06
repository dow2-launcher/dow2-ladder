#!/usr/bin/env python3
"""own_lobby.py - our lobby server for DoW2 Retribution (EXPERIMENT, owner 02.11.2026: the automatch fully on our own servers).

The game's lobby service (RLink inside DOW2.exe 3.19) is plain HTTPS to dow2r-lobby.reliclink.com: GET /game/<service>/<call>?<params>,
the answers are JSON arrays. Players with the launcher add-on "own lobby server" (OwnLobby.dll in Dow2-patches) trust our CA next to
Relic's and send those connections here (rts.fintebtc.de:47443). This server:
- passes everything on to Relic as it is - login, news, chat, friends, Relic's custom games and its automatch: one TLS connection to
  Relic per game connection, Relic's certificate checked against Relic's own root (relic_ca.pem, the one pinned in DOW2.exe);
- strips Relic's telemetry credentials (RL_TELEMKINESIS*) from the login answer: never logged, never stored, never passed on;
- v2 (03.11.2026, owner: "the automatch fully on OUR servers, fast and without friends" - no private rooms any more): with
  data/own_mm.on the AUTOMATCH rooms live here. MMFind's host makes an ordinary Custom Games room named MM-<match>-<random>; when
  the ladder's match <match> exists and every one of its players and watchers is signed in through this server (OwnLobby.dll),
  the room is hosted here: ids from our own range (2 000 000 000+), the room's relay is our game server (the one the ladder picked
  for the match if it is one of ours, battle_relay.py native connection on :47100), joins, peers, start and the result, which goes
  into the ladder's database as a match of its own (source "ownlobby") - Relic never hears of it. The room is shown in the Custom
  Games list (findAdvertisements, Relic's answer + ours) only to the players and watchers of that match (data/list_all.on: to
  everyone signed in here), so nobody else can see or join it - and nobody needs to be anybody's friend.
  Anything else (other names, a match with a player who is not here, the ladder not answering) goes to Relic as it is: the
  automatch then runs on Relic's rooms exactly as without this server.
  NOTE: the game hosts EVERY room with visible=0 and opens it with advertisement/update visible=1 a moment later, so visible=0 at
  host time does not mean "private". The old v1 rule (data/own_rooms.on: every visible=0 host kept here) hid ordinary custom
  games and automatch rooms of OwnLobby players from Relic (02.11.2026 evening: matches m1-m3 cancelled) - it is gone;
- hot reload (03.11.2026, owner: open rooms must not hold an update back): `systemctl reload dow2-ownlobby` (SIGHUP) puts the new
  code in place WITHOUT losing anything: the rooms, the sessions and the counters go to the new code through a memfd (memory only -
  session ids never touch the disk), the listening socket is kept (no refused connections), the process re-executes itself with the
  same PID. Open game connections are cut once; the game reconnects (its readSession long poll starts again) and finds its session
  and its room as they were. A file that does not compile is refused before anything is touched;
- with data/trace.on writes a protocol trace (data/trace.jsonl, 600) with session ids, tickets and keys masked.
Session ids and Steam tickets pass through memory only. Usage: own_lobby.py   (env LOBBY_DATA, LOBBY_PORT, LOBBY_RELAYS, LADDER_DB)
"""
import asyncio, json, os, re, signal, socket, sqlite3, ssl, sys, time, urllib.parse

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
                'inj': 0, 'pending': [], 'pend_seq': None, 'pend_n': 0, 'wake': asyncio.Event(), 'conns': set()}
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


# ---------------- v2: which automatch rooms live here ----------------
LADDER_LIVE = os.environ.get('LADDER_LIVE', 'http://127.0.0.1:8217/ladder/api/mm/live?debug=1')   # the ladder's matches (same host)
MM_NAME = re.compile(r'^MM-(m\d+)-')            # MMFind names its room MM-<ladder match>-<random>
SESSION_FRESH = 150                              # a session that polled readSession this recently is "signed in here"


def fetch_live():
    import urllib.request
    with urllib.request.urlopen(LADDER_LIVE, timeout=3) as f: return json.load(f)


async def mm_decision(p, sess):
    """the automatch room being hosted (p) lives here when: own_mm.on, its name is MM-<match>-..., the ladder has that match with
    the host in it, and every player and watcher of the match is signed in through this server. Returns {match, steams, relay}
    or None (= the room goes to Relic as it is, the automatch then runs there as without us)"""
    if not flag('own_mm.on') or not sess: return None
    m = MM_NAME.match(p.get('description') or '')
    if not m: return None
    t0 = time.time()
    try: live = await asyncio.get_running_loop().run_in_executor(None, fetch_live)
    except Exception as e:
        log('room %s: the ladder does not answer (%r) - Relic' % (p.get('description'), e)); return None
    match = next((x for x in live.get('matches', []) if x.get('id') == m.group(1)), None)
    if not match:
        log('room %s: no such match at the ladder - Relic' % p.get('description')); return None
    steams = [str(x.get('steam')) for x in match.get('team1', []) + match.get('team2', []) + match.get('watchers', []) if x.get('steam')]
    if str(sess['steam']) not in steams:
        log('room %s: its host is not a player of the match - Relic' % p.get('description')); return None
    # signed in here = the game holds a connection to us right now (its readSession long poll never lets go while it runs) and
    # spoke recently; a session of a game that was closed stays in SESSIONS for hours, so 'seen' alone is not enough (03.11 test)
    now = time.time(); here = {str(s['steam']) for s in SESSIONS.values() if s['conns'] and now - s['seen'] < SESSION_FRESH}
    missing = [s for s in steams if s not in here]
    if missing:
        log('room %s: %d of %d people of the match are not signed in here - Relic' % (p.get('description'), len(missing), len(steams))); return None
    log('room %s: all %d people of the match are here - our room (ladder %d ms)' % (p.get('description'), len(steams), (time.time() - t0) * 1000))
    return {'match': m.group(1), 'steams': set(steams), 'relay': match.get('relay') or ''}


def relay_for(ip):
    """the ladder's game server for the match (picked by the players' pings) when it is one of ours, else the first one alive"""
    for hp in RELAYS:
        if hp[0] == ip and RELAY_UP.get(hp, True): return hp
    return pick_relay()


def ad_of(r):
    """our room as an entry of findAdvertisements, in Relic's shape (captured 03.11.2026):
    [mid, "<steam lobby id>", host, owner, map, 0, description, 1, map, options, passworded, maxplayers, 1, slotinfo, 1, 0, 1, [[mid, pid, -1, sg, 0, 0], ...]]"""
    p = r['params']
    rows = [[r['mid'], pid, -1, m.get('sg', 0), 0, 0] for pid, m in r['members'].items()]
    try: mx = int(p.get('maxplayers') or 8)
    except ValueError: mx = 8
    return [r['mid'], str(r.get('lobby_id') or '0'), r['host'], r['host'], p.get('mapname', ''), 0, p.get('description', ''), 1,
            p.get('mapname', ''), p.get('options', ''), 1 if p.get('passworded') == '1' else 0, mx, 1, p.get('slotinfo', ''), 1, 0, 1, rows]


def inject_ads(body, sess, params):
    """Relic's Custom Games list + our automatch rooms for the people of their match (list_all.on: for everyone signed in here)"""
    if not sess: return body
    mine = [r for r in ROOMS.values() if r.get('kind') == 'mm' and r['state'] == 'lobby'
            and (str(sess['steam']) in r['steams'] or flag('list_all.on'))
            and (r['params'].get('modname') or '').lower() == (params.get('modName') or '').lower()]
    if not mine: return body
    try: j = json.loads(body)
    except Exception: return body
    if not (isinstance(j, list) and len(j) >= 2 and j[0] == 0 and isinstance(j[1], list)): return body
    have = {a[0] for a in j[1] if isinstance(a, list) and a}
    add = [ad_of(r) for r in mine if r['mid'] not in have]
    j[1] = add + j[1]
    return json.dumps(j, separators=(',', ':')).encode()


def own_call(call, p, sess, mm=None):
    """our answer (a JSON value) for a call about one of our rooms, or None = pass it on to Relic"""
    if not sess: return None
    svc, _, fn = call.partition('/')
    if svc not in ('advertisement', 'party'): return None
    mid = p.get('advertisementid') or p.get('matchID') or p.get('match_id') or p.get('matchid')
    if fn == 'host' and str(p.get('advertisementid')) == '-1':
        if not mm: return None                                         # everything but our automatch rooms: Relic
        mid = next_mid(); ip, port = relay_for(mm['relay']); now = time.time()
        r = ROOMS[mid] = {'mid': mid, 'host': sess['pid'], 'host_alias': sess['alias'], 'relay': [ip, port], 'state': 'lobby',
                          'kind': mm.get('kind', 'mm'), 'match': mm['match'], 'steams': mm['steams'], 'pids': mm.get('pids') or set(),
                          'params': {k: v for k, v in p.items() if k.lower() not in SECRET_PARAMS},
                          'members': {sess['pid']: {'sg': sess['sg'], 'steam': sess['steam'], 'alias': sess['alias'], 'race': -1, 'team': 0}},
                          'created': now, 'seen': now, 'reports': {}, 'started': None, 'lobby_id': None,
                          'unrated': bool(mm.get('unrated')), 'lroom': mm.get('lroom') or ''}
        log('room %d (%s, ladder %s) hosted by pid=%d (%s), relay %s:%d' % (mid, p.get('description'), mm['match'], sess['pid'], sess['alias'], ip, port))
        if mm.get('nm'): nm_hosted(mm['nm'], mid, ip)
        return [0, mid, 'authtoken', ip, port, [member_row(r, sess['pid'])]]
    if not ours(mid): return None
    mid = int(mid); r = ROOMS.get(mid)
    if not r:                                                            # ours, but gone (server restart): as Relic would say
        log('call %s for unknown room %d' % (call, mid)); return [2]
    r['seen'] = time.time()
    if fn == 'join':
        refused = nm_check_join(r, p, sess)
        if refused is not None: return refused
        if r.get('kind') == 'nm': ladder_bg('joined', {'steam': str(sess['steam']), 'room': mid})
        r['members'].setdefault(sess['pid'], {'sg': sess['sg'], 'steam': sess['steam'], 'alias': sess['alias'], 'race': -1, 'team': 0})
        ip, port = r['relay']
        log('room %d: pid=%d (%s) joins' % (mid, sess['pid'], sess['alias']))
        return [0, '/' + ip, ip, port, [member_row(r, sess['pid'])]]   # as Relic: code, the relay's address, relay, port, the joiner
    if fn == 'leave':
        r['members'].pop(sess['pid'], None)
        if r.get('kind') == 'nm' and r['state'] == 'lobby':                 # left the native room before the start: he gave up
            ladder_bg('fail', {'room': mid, 'culprits': [str(sess['steam'])], 'why': 'left the room'})
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
    if r.get('kind') == 'nm': ladder_bg('started', {'room': r['mid']})
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
    # the race each one PLAYED: the game's own report (race_ids in the order of profile_ids); the lobby slot has 255 for Random or
    # the race shown before the roll (03.11.2026: Random -> Tau was stored as Imperial Guard)
    played = {}
    try:
        for q, rc in zip(json.loads(rep.get('profile_ids') or '[]'), json.loads(rep.get('race_ids') or '[]')):
            if 0 <= int(rc) < 16: played[int(q)] = int(rc)
    except Exception: played = {}
    start = int(r['started'] or r['created']); end = int(time.time())
    members = [{'profile_id': pid, 'race_id': played.get(pid, m.get('race', -1)), 'teamid': m.get('team', 0), 'statgroup_id': m.get('sg', 0),
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
    if r.get('unrated'): mode = ''                                       # a launcher room's match (agreed): stored and shown, never rated
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


# ---------------- native automatch (03.11.2026): the game's OWN "Find a Game", the match decided by the ladder ----------------
# DOW2.exe still has Relic's whole automatch client (AutomatchInternal / WorldwideAutomatchService). Relic's matcher no longer pairs
# anybody; the protocol (reversed 03.11.2026, research/relic_automatch_reverse.md):
#   automatch/startpolling (matchTypes, raceInfoRaceID, partySessionID, modName/modVersion/CRCs) -> [0, pollID, searches, -1, 0, "", ...]
#   automatch/polling?pollID   -> the same; once matched: [0, pollID, searches, hostPID, mid|0, map, team, 0, race, searchID, url,
#                                 "<teams>", "<team size>", [pids]]
#   readSession push AutomatchGameMessage [hostPID, mid|0, map|url, race, team, 0, searchID, 0, teams, teamSize, [pids]] - instant
# The player whose profile is hostPID hosts an "AUTOMATCH" room (advertisement/host automatchPoll_id=<his poll>, the map from us,
# teams x team size slots), the others join it by id as soon as we know the id; slots / ready / countdown / start are the game's own.
# WHO plays with whom is the LADDER's decision (ladder.py nm/*, 127.0.0.1, token data/nm_token of the ladder): rating, groups, map
# wishes, the longest waiting first, the game server by the players' pings, timeouts (host never hosts, a guest never joins).
# This server: every search -> nm/join; while searches are on, nm/sync every 0.5 s -> answers and pushes; the room's id -> nm/room;
# joins -> nm/joined (checksums checked here first); the start -> nm/started; Stop Searching -> nm/leave.
LADDER_URL = os.environ.get('LADDER_URL', 'http://127.0.0.1:8217')
NM_TOKEN_FILE = os.environ.get('NM_TOKEN_FILE', '/srv/ladder/data/nm_token')
NM_POLLS = {}                     # pollID -> our record of one search of one game
NM_WAKE = asyncio.Event()         # nm_syncer: sync at once (a search was just matched)
NM_SEQ = [int(time.time()) % 100000 * 100]
NM_MODE = {1: '1v1', 2: '2v2', 3: '3v3'}            # match types: 1 head to head, 2 two on two, 3 team battle
NM_DEAD = 35                      # s without automatch/polling (the game polls every ~11 s while searching): his game is gone
CRC_KEYS = ('modname', 'modversion', 'appbinarychecksum', 'datachecksum', 'moddllchecksum')


def nm_token():
    try:
        with open(NM_TOKEN_FILE) as f: return f.read().strip()
    except Exception: return ''


def ladder_call(fn, body):
    import urllib.request
    req = urllib.request.Request(LADDER_URL + '/ladder/api/nm/' + fn, data=json.dumps(body).encode(), method='POST',
                                 headers={'Content-Type': 'application/json', 'X-NM-Token': nm_token()})
    with urllib.request.urlopen(req, timeout=4) as f: return json.load(f)


async def ladder(fn, body):
    return await asyncio.get_running_loop().run_in_executor(None, ladder_call, fn, body)


def ladder_bg(fn, body):
    """fire and forget (the answer only logged when it failed)"""
    async def go():
        try: await ladder(fn, body)
        except Exception as e: log('ladder nm/%s failed: %r' % (fn, e))
    asyncio.ensure_future(go())


def nm_game(p):
    mod = (p.get('modName') or '').strip()
    return 'vanilla' if mod.lower() in ('', 'dow2') else ('%s-%s' % (mod, p.get('modVersion') or '')).lower()


def nm_members(x):
    """the players of one search: the party leader (who sent startpolling) first, then his party (one search, one team)"""
    return x.get('members') or [{'pid': x['pid'], 'steam': x['steam'], 'race': x['race']}]


def nm_answer(x, pid=None):
    """the answer to startpolling / polling for one player of the search (party members poll with the leader's pollID)"""
    v = x.get('view') or {}; pid = pid or x['pid']
    me = next((m for m in nm_members(x) if m['pid'] == pid), nm_members(x)[0])
    rows = [[str(x['sid']), str(x['mt']), max(1, int(v.get('in_pool') or 1)), 1, [[i, 1 if i == me['race'] else 0] for i in range(7)]]]
    if v.get('state') != 'matched': return [0, x['poll'], rows, -1, 0, '', -1, -1, -1, -1, '', '0', '0', []]
    me_host = v['host_pid'] == pid; mid = int(v['room']) if str(v.get('room') or '').isdigit() else 0
    url = ''
    if not me_host and mid: url = '/' + ((ROOMS.get(mid) or {}).get('relay') or [v.get('relay') or 'relay'])[0]
    return [0, x['poll'], rows, v['host_pid'], mid, v['map'] if me_host else '', v['team'], 0, me['race'], x['sid'],
            url, str(v['teams']), str(v['size']), sorted(v['pids'])]
    # the pid list ASCENDING (stands 03.11.2026): OnHostAutomatch 0x5fc4d0 sorts its stored list of the match in place and compares
    # it (0x5ff070) with the list of every later answer / push as sent - any other order = "already in a game as the host,
    # disconnecting now" the moment a poll answer reaches the host after the guest is in the room (with the stock 11 s poll: at
    # random, in about 8 s of every 11; with MMFind 0.39's 1 s poll: every time)


def nm_push(x, pid):
    a = nm_answer(x, pid)
    n = push(pid, [0, 'AutomatchGameMessage', pid, [a[3], a[4], a[5] if a[3] == pid else a[10], a[8], a[6], a[7], a[9], 0, int(a[11]), int(a[12]), a[13]]])
    x.setdefault('pushed', {})[str(pid)] = [x['view'].get('match'), 'host' if a[3] == pid else a[4]]
    log('native automatch %s: push to pid=%d (%s, mid %s) - %d session(s)' % (x['view'].get('match'), pid, 'host' if a[3] == pid else 'guest', a[4], n))


LROOM_PUSHED = {}                 # (match, steam) -> when that launcher-room guest got the room's id
LROOM_GAP = 4.0                   # s: a launcher room's guests go in one after another (their seats), the next one at the latest this long after


def lroom_turn(x, v, steam):
    """a launcher room's match (06.11.2026): a guest takes the first free slot of his team in the host's room (RequestCorrectSlot), so
    the seats of the room come out right only when the guests join in the room's order (v['steams']: the host, his team, the other
    team, each in seat order) - a guest gets the room's id once every guest before him is in, or LROOM_GAP s after the one before"""
    order = [s_ for s_ in v.get('steams') or [] if s_ != v.get('host_steam')]
    if steam not in order: return True
    k = order.index(steam); joined = set(v.get('joined') or [])
    if all(s_ in joined for s_ in order[:k]): return True
    now = time.time()
    t0 = LROOM_PUSHED.get((v.get('match'), order[k - 1]))
    return bool(t0 and now - t0 >= LROOM_GAP)


def nm_push_news(x):
    """AutomatchGameMessage to every player of this search who has news: the host at once, a guest once the room id is known
    (a launcher room's guests in its seat order, lroom_turn)"""
    v = x['view']; mid = int(v['room']) if str(v.get('room') or '').isdigit() else 0
    if not isinstance(x.get('pushed'), dict): x['pushed'] = {}
    for m in nm_members(x):
        me_host = v['host_pid'] == m['pid']
        if (me_host or mid) and x['pushed'].get(str(m['pid'])) != [v['match'], 'host' if me_host else mid]:
            if not me_host and v.get('lroom') and not lroom_turn(x, v, str(m['steam'])): continue
            nm_push(x, m['pid'])
            if not me_host and v.get('lroom'): LROOM_PUSHED[(v['match'], str(m['steam']))] = time.time()


def nm_apply(x, v):
    """the ladder's view of this search -> our record, pushes on news"""
    if not isinstance(v, dict) or x['state'] in ('gone', 'done'): return
    old = x.get('view') or {}; st = v.get('state')
    if st == 'matched':
        x['view'] = v; x['state'] = 'matched'
        if old.get('match') != v['match']:
            log('native automatch %s: pid=%d (%s%s) matched, %s, host pid=%s, team %s, map %s' % (v['match'], x['pid'], x['alias'],
                ' + party %s' % [m['pid'] for m in nm_members(x)[1:]] if len(nm_members(x)) > 1 else '', v['mode'], v['host_pid'], v['team'], v['map']))
        nm_push_news(x)
    elif st == 'searching':
        if old.get('state') == 'matched':                   # not in the room yet (the ladder cancels those who are): the game takes
            log('native automatch %s: pid=%d back to searching (the match failed)' % (old.get('match'), x['pid']))   # the next match as it comes
            x['pushed'] = {}
        x['view'] = v; x['state'] = 'searching'
    elif st == 'playing':
        x['state'] = 'done'
    else:                                                     # cancelled (he was the culprit / he left / in the failed room), idle
        log('native automatch: pid=%d search ends - %s %s' % (x['pid'], st, v.get('by') or ''))
        nm_cancelled(x, v)
        x['state'] = 'gone'


def nm_cancelled(x, v):
    """his search is over without a match (his game was the reason the match failed, or it was already in the failed room, or the
    ladder lost him): the push AutomatchStopPollingMessage stops the game's search at once - out of any room, back to the Find a Game
    screen (reverse + stands 03.11.2026); to every player of a party (only the leader can stop it himself)"""
    x['view'] = {'state': 'searching'}
    for m in nm_members(x): push(m['pid'], [0, 'AutomatchStopPollingMessage', m['pid'], [x['poll'], x.get('party') or 0]])


async def nm_syncer():
    while True:
        try: await asyncio.wait_for(NM_WAKE.wait(), 0.5)            # 0.5 s, or at once when a search was just matched
        except asyncio.TimeoutError: pass
        NM_WAKE.clear()
        now = time.time()
        for x in NM_POLLS.values():                                           # the game polls every ~11 s in every state, even in the room
            if x['state'] in ('searching', 'matched') and now - x['polled'] > NM_DEAD:
                x['state'] = 'gone'; log('native automatch: pid=%d stopped polling - his game is gone' % x['pid']); ladder_bg('leave', {'steam': x['steam'], 'why': 'game gone'})
        for k in [k for k, x in NM_POLLS.items() if x['state'] in ('gone', 'done') and now - x['t'] > 3600]: NM_POLLS.pop(k, None)
        act = {x['steam']: x for x in NM_POLLS.values() if x['state'] in ('searching', 'matched') and x.get('joined')}
        if not act: continue
        try: vs = await ladder('sync', {'steams': list(act)})
        except Exception as e:
            if now - STATS.get('nm_sync_err_t', 0) > 30: log('native automatch: ladder sync failed: %r' % e); STATS['nm_sync_err_t'] = now
            continue
        for steam, x in act.items():
            try: nm_apply(x, vs.get(steam))
            except Exception as e: log('native automatch: apply for pid=%d failed: %r' % (x['pid'], e))


def nm_search(p):
    try: x = NM_POLLS.get(int(p.get('pollID') or p.get('myPollID') or 0))
    except ValueError: x = None
    return x


async def nm_call(fn, p, sess):
    """our answer to automatch/<fn>, or None = pass it on to Relic (native_mm.on off, not signed in here)"""
    if not flag('native_mm.on') or not sess: return None
    if fn == 'startpolling':
        def first(k, d):
            try: return json.loads(p.get(k) or '[]')[0]
            except Exception: return d
        NM_SEQ[0] += 1
        mt = int(first('matchTypes', 1))
        # a party (friends who searched together, Find a Game's "Your Party"): only the leader sends startpolling, one entry per
        # member in raceInfoProfileID / raceInfoRaceID; the members learn it from the push AutomatchStartPollingMessage [pollID,
        # partySessionID], then poll with the leader's pollID and take the same team (reverse 03.11.2026)
        try: pids = [int(q) for q in json.loads(p.get('raceInfoProfileID') or '[]')]; races = [int(q) for q in json.loads(p.get('raceInfoRaceID') or '[]')]
        except Exception: pids, races = [], []
        members = [{'pid': sess['pid'], 'steam': str(sess['steam']), 'race': races[pids.index(sess['pid'])] if sess['pid'] in pids and len(races) == len(pids) else int(first('raceInfoRaceID', 0))}]
        now = time.time()
        for i, q in enumerate(pids):
            if q == sess['pid']: continue
            s2 = next((s for s in SESSIONS.values() if s['pid'] == q and s['conns'] and now - s['seen'] < SESSION_FRESH), None)
            if not s2:                                                       # a friend not signed in here could never enter our room
                log('native automatch: pid=%d searches with party member pid=%d who is not on this server - refused' % (sess['pid'], q))
                return NM_REFUSED
            members.append({'pid': q, 'steam': str(s2['steam']), 'race': races[i] if i < len(races) else 0, 'alias': s2['alias']})
        if len(members) > {1: 1, 2: 2, 3: 3}.get(mt, 1):
            log('native automatch: pid=%d party of %d for match type %d - refused' % (sess['pid'], len(members), mt)); return NM_REFUSED
        x = {'poll': 900000000 + NM_SEQ[0], 'sid': 800000000 + NM_SEQ[0], 'pid': sess['pid'], 'steam': str(sess['steam']), 'alias': sess['alias'],
             'mt': mt, 'mode': NM_MODE.get(mt, '1v1'), 'race': int(first('raceInfoRaceID', 0)), 'game': nm_game(p),
             'key': '|'.join(p.get(k, '') for k in ('modName', 'modVersion', 'dataCRC', 'appBinCRC', 'modDllCRC')),
             'state': 'searching', 't': time.time(), 'polled': time.time(), 'view': {'state': 'searching'}, 'pushed': {}, 'joined': False,
             'members': members}
        try: x['party'] = int(p.get('partySessionID') or 0)
        except ValueError: x['party'] = 0
        mine = {m['steam'] for m in members}
        for y in NM_POLLS.values():                                          # one search per player
            if y['state'] in ('searching', 'matched') and mine & {m['steam'] for m in nm_members(y)}: y['state'] = 'gone'
        NM_POLLS[x['poll']] = x
        log('native automatch: pid=%d (%s) searches %s, %s%s' % (x['pid'], x['alias'], x['mode'], x['key'], ', party %s' % [m['pid'] for m in members[1:]] if members[1:] else ''))
        for m in members[1:]: push(m['pid'], [0, 'AutomatchStartPollingMessage', m['pid'], [x['poll'], x['party']]])
        try:
            v = await ladder('join', {'steam': x['steam'], 'pid': x['pid'], 'name': x['alias'], 'mode': x['mode'], 'race': x['race'],
                                      'key': x['key'], 'game': x['game'],
                                      'party': [{'steam': m['steam'], 'pid': m['pid'], 'race': m['race'], 'name': m.get('alias')} for m in members[1:]]})
        except Exception as e:
            log('native automatch: the ladder does not answer (%r) - search refused' % e); x['state'] = 'gone'
            for m in members[1:]: push(m['pid'], [0, 'AutomatchStopPollingMessage', m['pid'], [x['poll'], x['party']]])
            return NM_REFUSED
        if v.get('ok') is False:
            log('native automatch: the ladder refused the search (%s)' % v.get('error')); x['state'] = 'gone'
            for m in members[1:]: push(m['pid'], [0, 'AutomatchStopPollingMessage', m['pid'], [x['poll'], x['party']]])
            return NM_REFUSED
        x['joined'] = True                                                   # from now on nm/sync keeps it up to date
        nm_apply(x, v)
        if v.get('state') == 'matched': NM_WAKE.set()                       # the others of this match (the host first) get theirs now, not in 0.5 s
        return nm_answer(x)
    x = nm_search(p)
    if fn == 'polling':
        if not x: return [2]
        x['polled'] = time.time()
        return nm_answer(x, sess['pid'])
    if fn == 'stoppolling':
        if x and x['state'] in ('searching', 'matched') and sess['pid'] == x['pid']:
            x['state'] = 'gone'; log('native automatch: pid=%d stops searching' % x['pid'])
            ladder_bg('leave', {'steam': x['steam'], 'why': 'Stop Searching'})
            for m in nm_members(x)[1:]: push(m['pid'], [0, 'AutomatchStopPollingMessage', m['pid'], [x['poll'], x['party']]])
        return [0]
    if fn == 'updateStatus':
        log('native automatch: pid=%d status poll=%s match=%s result=%s' % (sess['pid'], p.get('myPollID'), p.get('matchID'), p.get('result')))
        # result 0 = his host / join failed (the client reports it and keeps searching). Stands 03.11.2026: after a guest's failed join
        # the host's game soon leaves its room by itself - so the match is over at once: he is out, the host gets a clean cancel
        if p.get('result') == '0' and x and x['state'] == 'matched':
            ladder_bg('fail', {'match': x['view'].get('match'), 'culprits': [str(sess['steam'])], 'why': 'could not ' + ('host' if x['view'].get('host_pid') == sess['pid'] else 'join')})
        return [0]
    return None                                                              # getAutomatchMap etc.: Relic


NM_REFUSED = [1]                  # startpolling refused (the ladder is away): the game resets its search quietly, no message box (reverse)


def nm_room(p, sess):
    """advertisement/host of an AUTOMATCH room by the host of one of our native matches -> the room lives here"""
    if not flag('native_mm.on') or not sess: return None
    try: x = NM_POLLS.get(int(p.get('automatchPoll_id') or -1))
    except ValueError: return None
    if not x or x['state'] != 'matched' or x['view'].get('host_pid') != sess['pid'] or sess['pid'] not in [m['pid'] for m in nm_members(x)]: return None
    v = x['view']
    return {'match': v['match'], 'steams': set(v['steams']), 'pids': set(v['pids']), 'relay': v.get('relay') or '', 'kind': 'nm', 'nm': x,
            'unrated': bool(v.get('unrated')), 'lroom': v.get('lroom') or ''}   # 05.11.2026: a launcher room's match - agreed, never rated


def nm_hosted(x, mid, relay_ip):
    v = x['view']; v['room'] = mid
    log('native automatch %s: room %d is up (relay %s) - the others join' % (v['match'], mid, relay_ip))
    ladder_bg('room', {'steam': v['host_steam'], 'room': mid, 'relay': relay_ip})
    for y in NM_POLLS.values():                                              # the guests at once (the ladder's sync would take 0.5 s)
        if y['state'] == 'matched' and y['view'].get('match') == v['match']:
            y['view']['room'] = mid; nm_push_news(y)


def nm_check_join(r, p, sess):
    """a join into one of our native rooms: only the players of that match, only the very same game (checksums, as Relic checked)"""
    if r.get('kind') != 'nm': return None
    if sess['pid'] not in r.get('pids', ()):
        log('room %d: pid=%d (%s) is not a player of this match - refused' % (r['mid'], sess['pid'], sess['alias'])); return NM_JOIN_FULL
    hp = r['params']
    bad = [k for k in CRC_KEYS if (p.get(k) or '').lower() != (hp.get(k) or '').lower()]
    if bad:
        log('room %d: pid=%d (%s) has another game (%s) - refused' % (r['mid'], sess['pid'], sess['alias'], ', '.join(bad)))
        return NM_JOIN_CRC.get(bad[0], NM_JOIN_CRC['datachecksum'])
    return None


# join refusals: the client maps every code we tried (12, 16, ...) to R_ServerCallFailed - "join failed", the search goes on (stands
# 03.11.2026); the codes below are Relic's names for the reason, kept for the trace
NM_JOIN_FULL = [1]                # not a player of this match
NM_JOIN_CRC = {'modname': [14], 'modversion': [15], 'appbinarychecksum': [16], 'datachecksum': [16], 'moddllchecksum': [16]}   # Relic's join result range is -1..16


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
    conn_key = object(); my_sessions = []
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
            if sess is not None and conn_key not in sess['conns']: sess['conns'].add(conn_key); my_sessions.append(sess)
            t0 = time.time()
            if call == 'login/readSession' and sess is not None:
                try: status, rlines, rbody = await read_session(sess, params, first, lines, body, up)
                except Exception as e:
                    STATS['relic_err'] += 1; log('readSession pid=%d: %r' % (sess['pid'], e)); break
                w.write(response(status, rlines, rbody)); await w.drain()
                if rbody[:1].isdigit() and not rbody.endswith(b',[[]]'): trace(ip=ip, pid=sess['pid'], call=call, p=mask_params(params), a=rbody.decode('utf-8', 'replace')[:3000])
                continue
            if call.startswith('automatch/') and sess is not None:
                try: ans = await nm_call(call[10:], params, sess)
                except Exception as e:
                    log('nm_call %s failed: %r' % (call, e)); ans = None
                if ans is not None:
                    STATS['own'] += 1
                    b = json.dumps(ans, separators=(',', ':')).encode()
                    w.write(response('HTTP/1.1 200 OK', OWN_HDRS + ['Request-Path: ' + path], b)); await w.drain()
                    trace(ip=ip, pid=sess['pid'], call=call, p=mask_params(params), own=1, a=b.decode()[:3000])
                    if hdrs.get('connection', '').lower() == 'close': break
                    continue
            mm = None
            if call == 'advertisement/host' and str(params.get('advertisementid')) == '-1':
                try: mm = nm_room(params, sess) or await mm_decision(params, sess)
                except Exception as e: log('mm_decision failed: %r' % e)
            try: ans = own_call(call, params, sess, mm)
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
                if call == 'advertisement/update' and rbody.startswith(b'[4') and params.get('state') == '0' and params.get('matchtype') == '1':
                    try: status, rlines, rbody = await reopen(up, first, lines, body, params, raw, ip, sess) or (status, rlines, rbody)
                    except Exception as e: log('reopen %s: %r' % (params.get('advertisementid'), e))
                if call.startswith('login/'):
                    rbody = TELEM_RE.sub(rb'\1\2', rbody)
                    rbody = rbody.replace(b'["RL_TELEMSERVICE","1"]', b'["RL_TELEMSERVICE","0"]')
                    if call in ('login/platformlogin', 'login/login'): sess = remember_login(rbody, ip) or sess
                if call == 'advertisement/findAdvertisements' and status[9:12] == '200':
                    try: rbody = inject_ads(rbody, sess, params)
                    except Exception as e: log('inject_ads failed: %r' % e)
                w.write(response(status, rlines, rbody))
                trace(ip=ip, pid=sess and sess['pid'], call=call, p=mask_params(params), st=status[9:12], ms=round((time.time() - t0) * 1000),
                      a=mask_body(call, rbody))
            await w.drain()
            if hdrs.get('connection', '').lower() == 'close': break
    except Exception as e:
        log('connection from %s: %r' % (ip, e))
    finally:
        for x in my_sessions: x['conns'].discard(conn_key)
        up.close()
        try: w.close()
        except Exception: pass


# Continue after a match (03.11.2026, owner: "the game's own Continue - the host presses it and everyone is back in the room"):
# the host's game puts the room back in the lobby (advertisement/update state=0 visible=1), but Relic keeps a started custom game
# (matchtype 1) started and answers [4], so the room stays out of the Custom Games list. On that answer only, we tell Relic the
# room is in the lobby again (advertisement/updateState state=0 with the player's own session) and send his update once more.
def relic_request(first, lines, body, path, params):
    method = first.split(' ', 1)[0]; q = urllib.parse.urlencode(params)
    keep = [h for h in lines if h and h.split(':', 1)[0].strip().lower() not in ('content-length', 'transfer-encoding')]
    if body:
        return ('%s %s HTTP/1.1\r\n' % (method, path) + ''.join(h + '\r\n' for h in keep) + 'Content-Length: %d\r\n\r\n' % len(q)).encode('latin-1') + q.encode('latin-1')
    return ('%s %s?%s HTTP/1.1\r\n' % (method, path, q) + ''.join(h + '\r\n' for h in keep) + '\r\n').encode('latin-1')


async def reopen(up, first, lines, body, params, raw, ip, sess):
    aid = params.get('advertisementid')
    sp = {'advertisementid': aid, 'state': '0'}
    if 'sessionID' in params: sp['sessionID'] = params['sessionID']
    st, rl, rh, rb = await up.request(relic_request(first, lines, body, '/game/advertisement/updateState', sp))
    trace(ip=ip, pid=sess and sess['pid'], call='advertisement/updateState', p=mask_params(sp), st=st[9:12], own='reopen', a=mask_body('advertisement/updateState', rb))
    if not rb.startswith(b'[0'):
        log('room %s back in the lobby (Continue): Relic refused updateState 0 -> %r' % (aid, rb[:40])); return None
    st, rl, rh, rb = await up.request(raw)
    log('room %s back in the lobby (Continue): updateState 0 ok, update -> %r' % (aid, rb[:40]))
    STATS['reopen'] = STATS.get('reopen', 0) + 1
    return st, rl, rb


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
        head = (await r.readuntil(b'\r\n\r\n')).decode('latin-1')
        target = head.split(' ', 2)[1] if head.count(' ') >= 2 else '/'
        if target.startswith('/nm?'):                                    # the ladder asks for MMFind 0.38: is this player here, native on?
            steam = urllib.parse.parse_qs(target[4:]).get('steam', [''])[0]; now = time.time()
            here = any(str(s['steam']) == steam and s['conns'] and now - s['seen'] < SESSION_FRESH for s in SESSIONS.values())
            b = json.dumps({'native': flag('native_mm.on'), 'here': here}).encode()
            w.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: %d\r\n\r\n' % len(b) + b)
            await w.drain(); w.close(); return
        rooms = [{'mid': x['mid'], 'match': x.get('match'), 'name': x['params'].get('description'), 'host': x['host'], 'state': x['state'], 'relay': '%s:%d' % tuple(x['relay']), 'map': x['params'].get('mapname'),
                  'members': {str(k): {kk: vv for kk, vv in v.items() if kk != 'steam'} for k, v in x['members'].items()},
                  'reports': len(x['reports']), 'stored': bool(x.get('stored'))} for x in ROOMS.values()]
        nm = [{'poll': x['poll'], 'pid': x['pid'], 'mode': x['mode'], 'state': x['state'], 'match': (x.get('view') or {}).get('match'),
               'room': (x.get('view') or {}).get('room'), 'since': int(time.time() - x['t'])} for x in NM_POLLS.values() if x['state'] in ('searching', 'matched')]
        b = json.dumps({'own_mm': flag('own_mm.on'), 'native_mm': flag('native_mm.on'), 'native': nm, 'list_all': flag('list_all.on'), 'trace': flag('trace.on'), 'sessions': len(SESSIONS), 'stats': STATS,
                        'relays': {'%s:%d' % k: v for k, v in RELAY_UP.items()}, 'rooms': rooms}).encode()
        w.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: %d\r\n\r\n' % len(b) + b)
        await w.drain()
    except Exception: pass
    w.close()


# ---------------- hot reload (see the top) ----------------
def state_out():
    rooms = {}
    for mid, r in ROOMS.items():
        x = dict(r); x['steams'] = sorted(r.get('steams') or []); x['pids'] = sorted(r.get('pids') or [])
        x['members'] = {str(k): v for k, v in r['members'].items()}; x['reports'] = {str(k): v for k, v in r['reports'].items()}
        rooms[str(mid)] = x
    sess = {k: {kk: vv for kk, vv in v.items() if kk not in ('wake', 'conns')} for k, v in SESSIONS.items()}
    return json.dumps({'v': 1, 'rooms': rooms, 'sessions': sess, 'nm_polls': {str(k): v for k, v in NM_POLLS.items()}, 'nm_seq': NM_SEQ[0], 'stats': STATS, 'relay_up': [[a, b, c] for (a, b), c in RELAY_UP.items()]})


def state_in(blob):
    d = json.loads(blob)
    for mid, x in d.get('rooms', {}).items():
        x['steams'] = set(x.get('steams') or []); x['pids'] = set(x.get('pids') or [])
        x['members'] = {int(k): v for k, v in x['members'].items()}; x['reports'] = {int(k): v for k, v in x['reports'].items()}
        if x.get('order'): x['order'] = [int(q) for q in x['order']]
        ROOMS[int(mid)] = x
    for k, v in d.get('sessions', {}).items():
        v['wake'] = asyncio.Event(); v['conns'] = set()
        if v.get('pending'): v['wake'].set()
        SESSIONS[k] = v
    STATS.update(d.get('stats', {}))
    for k, v in d.get('nm_polls', {}).items():
        if not isinstance(v.get('pushed'), dict): v['pushed'] = {}
        NM_POLLS[int(k)] = v
    NM_SEQ[0] = max(NM_SEQ[0], int(d.get('nm_seq') or 0))
    for a, b, c in d.get('relay_up', []): RELAY_UP[(a, b)] = c
    return len(ROOMS), len(SESSIONS)


def hot_reload(srv_sock, st_sock):
    try:                                                                 # the new code must at least compile, or we keep running
        compile(open(os.path.abspath(__file__), encoding='utf-8').read(), __file__, 'exec')
    except Exception as e:
        log('reload refused, the new own_lobby.py does not compile: %r' % e); return
    fd = os.memfd_create('ownlobby-state', 0)
    os.write(fd, state_out().encode()); os.lseek(fd, 0, 0)
    for x in (fd, srv_sock.fileno(), st_sock.fileno()): os.set_inheritable(x, True)
    os.environ['OWNLOBBY_STATE_FD'] = str(fd)
    os.environ['OWNLOBBY_LISTEN_FDS'] = '%d,%d' % (srv_sock.fileno(), st_sock.fileno())
    log('reload: %d room(s), %d session(s) handed over - re-executing' % (len(ROOMS), len(SESSIONS)))
    os.execv(sys.executable, [sys.executable, '-u', os.path.abspath(__file__)])


def inherited():
    fds = os.environ.pop('OWNLOBBY_LISTEN_FDS', ''); sfd = os.environ.pop('OWNLOBBY_STATE_FD', '')
    if sfd:
        try:
            with os.fdopen(int(sfd), 'rb') as f: n = state_in(f.read())
            log('reload: %d room(s), %d session(s) taken over' % n)
        except Exception as e: log('reload: state not taken over: %r' % e)
    if not fds: return None, None
    a, b = (int(x) for x in fds.split(','))
    return socket.socket(fileno=a), socket.socket(fileno=b)


async def main():
    os.makedirs(DATA, exist_ok=True)
    ls, lst = inherited()
    if ls is None:
        ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM); ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); ls.bind((os.environ.get('LOBBY_BIND', '0.0.0.0'), PORT)); ls.listen(128)
        lst = socket.socket(socket.AF_INET, socket.SOCK_STREAM); lst.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); lst.bind(('127.0.0.1', STATUS_PORT)); lst.listen(16)
    srv = await asyncio.start_server(handle, sock=ls, ssl=server_ctx(), limit=4 << 20)
    st = await asyncio.start_server(status, sock=lst)
    asyncio.get_running_loop().add_signal_handler(signal.SIGHUP, hot_reload, ls, lst)
    asyncio.ensure_future(relay_prober()); asyncio.ensure_future(nm_syncer())
    log('own lobby on :%d (automatch rooms %s, native automatch %s, trace %s), relays %s' % (PORT, 'ON' if flag('own_mm.on') else 'off', 'ON' if flag('native_mm.on') else 'off', 'on' if flag('trace.on') else 'off',
                                                                 ', '.join('%s:%d' % x for x in RELAYS)))
    async with srv, st: await asyncio.gather(srv.serve_forever(), st.serve_forever())

if __name__ == '__main__':
    asyncio.run(main())
