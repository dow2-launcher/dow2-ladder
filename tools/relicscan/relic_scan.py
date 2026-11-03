#!/usr/bin/env python3
"""relic_scan.py - which game every open Relic room is for, asked at Relic itself with our stand account (owner 03.11.2026).

Relic's public list (dow-api community/advertisement/findAdvertisements) has no mod fields. The game's own findAdvertisements
(dow2r-lobby.reliclink.com, signed in) carries the game's filter - modName, modVersion, dataChecksum, appBinaryChecksum,
modDLLChecksum - and Relic answers only the rooms of that very game. So every SCAN_EVERY s we ask twice with our own session
of the stand account (stand 1, cherpekat): once as vanilla DOW2 3.19, once as Elite 3.2, with exactly the parameters the game
sends (stand trace 03.11.2026). Room id -> the fields of the query that listed it goes to the ladder (ADS_OUT, JSON, no secrets),
which shows it instead of its map/race guess.

Sign-in as the game does it (DOW2.exe 3.19 FUN_00632620 / FUN_006326f0 / FUN_0054d2f0): a Steam Encrypted App Ticket of the
stand account requested with the user data "RLINK" (steamticket.exe under Wine in the stand's prefix next to the game's own
steam_api.dll, through a pipe), base64 -> auth of login/platformlogin -> sessionID; then the readSession long poll as the game keeps it
(answer "<seq>,[...]", next poll with ack=<seq>; Relic drops a session not polled for RL_DISCONNECT 30 s).
The session id and the ticket live in this process's memory only: never logged, never on a command line, never written.

One Relic account = one session. The stand's game comes first:
- no sign-in while DOW2.exe / Elite.exe runs in the stand's prefix, and not until STAND_QUIET s after it is gone;
- the stand checked every 2 s while signed in: a game starting -> login/logout at once, pause;
- the session cut from elsewhere (readSession / findAdvertisements say so) -> pause KICK_PAUSE s, then as above.
Gentle load: two findAdvertisements and one public list per SCAN_EVERY (30 s); sign-ins at most MAX_LOGINS per hour.
"""
import base64, http.client, json, os, re, signal, ssl, subprocess, sys, threading, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RELIC = 'dow2r-lobby.reliclink.com'
CA = os.environ.get('RELIC_CA', os.path.join(HERE, 'relic_ca.pem'))           # "RelicLink Root CA", the one pinned in DOW2.exe
ADS_OUT = os.environ.get('ADS_OUT', '/mnt/rts/srv/ladder/data/ads_exact.json')
PUBLIC = 'https://dow-api.reliclink.com/community/advertisement/findAdvertisements?title=dow2r'
WINE = os.environ.get('STAND_WINE', '/mnt/dow2bench/wine/wine-11.20-staging-amd64-wow64/bin/wine')
PREFIX = os.environ.get('STAND_PREFIX', '/mnt/dow2bench/prefix')                # stand 1 = cherpekat (stand 2 = the owner's Steam)
DISPLAY = os.environ.get('STAND_DISPLAY', ':99')
STAND_STEAM = os.environ.get('STAND_STEAM', '76561198616066720')           # cherpekat: a ticket of any other account is not used
TICKET_EXE = os.path.join(HERE, 'steamticket.exe')
SCAN_EVERY, STAND_QUIET, KICK_PAUSE, MAX_LOGINS = 30, 120, 600, 4
ONCE = int(os.environ.get('RELIC_SCAN_ONCE', '0'))                         # test: this many scans, sign out, exit

# the stand account's login as the game sends it (stand trace 02.11.2026; auth and platformUserID filled in at sign-in)
LOGIN = [('accountType', 'STEAM'), ('flags', '0'), ('country', 'DE'), ('alias', os.environ.get('STAND_ALIAS', 'igor.pechenikin')),
         ('appID', '56400')]
LOGIN_TAIL = [('majorVersion', '0.0.0'), ('minorVersion', '0'), ('installationType', 'client'),
              ('macAddress', os.environ.get('STAND_MAC', '10-7C-61-49-3E-6E')), ('title', 'dow2r'), ('language', 'en'),
              ('clientLibVersion', '18')]
# findAdvertisements as the game sends it (own lobby trace 03.11.2026, Elite 3.2; vanilla differs only in the mod fields):
# profile_ids / statGroup_ids = the signed-in profile, then these
FILTERS = {
    'vanilla': {'modName': 'DOW2', 'modVersion': '3.19', 'modDLLChecksum': '-1151285252', 'dataChecksum': '371005917', 'appBinaryChecksum': '19'},
    'elite':   {'modName': 'Elite', 'modVersion': '3.2', 'modDLLChecksum': '-1151285252', 'dataChecksum': '-696231043', 'appBinaryChecksum': '19'},
}
FIELD_OUT = (('modName', 'modname'), ('modVersion', 'modversion'), ('dataChecksum', 'datachecksum'),
             ('appBinaryChecksum', 'appbinarychecksum'), ('modDLLChecksum', 'moddllchecksum'))


def log(*a): print(time.strftime('%F %T'), *a, flush=True)


def q(v):  # the game's URL encoding: brackets as %5b / %5d, lower case
    return re.sub(r'%[0-9A-F]{2}', lambda m: m.group(0).lower(), urllib.parse.quote(str(v), safe='-_.~'))


def qs(pairs): return '&'.join('%s=%s' % (k, q(v)) for k, v in pairs)


# ---------------- the stand: is its game running? ----------------
def stand_game():
    """pid of a DOW2.exe / Elite.exe (or its launcher) running in the stand's prefix, else None"""
    for d in os.listdir('/proc'):
        if not d.isdigit() or int(d) == os.getpid(): continue
        try:
            cmd = open('/proc/%s/cmdline' % d, 'rb').read().replace(b'\0', b' ').lower()
            if b'dow2.exe' not in cmd and b'elite.exe' not in cmd: continue
            argv0 = cmd.split(b' ', 1)[0]
            if not (argv0.endswith(b'.exe') or b'\\' in argv0 or b'wine' in argv0): continue
            env = open('/proc/%s/environ' % d, 'rb').read().split(b'\0')
            if ('WINEPREFIX=' + PREFIX).encode() in env: return int(d)
        except OSError:
            continue
    return None


# ---------------- Relic connection (keep-alive, Relic's cookies, the game's headers) ----------------
class Relic:
    def __init__(self, cookies):
        self.c = None; self.cookies = cookies
        self.ctx = ssl.create_default_context(cafile=CA)
        self.ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    def close(self):
        try: self.c and self.c.close()
        except Exception: pass
        self.c = None

    def get(self, path, timeout, login=False):
        for attempt in (0, 1):
            if self.c is None: self.c = http.client.HTTPSConnection(RELIC, 443, timeout=timeout, context=self.ctx)
            self.c.timeout = timeout
            if self.c.sock: self.c.sock.settimeout(timeout)
            try:
                self.c.putrequest('GET', path, skip_accept_encoding=True)
                self.c.putheader('Accept', '*/*')
                if self.cookies: self.c.putheader('Cookie', ';'.join('%s=%s' % kv for kv in self.cookies.items()))
                if login:
                    self.c.putheader('Content-Type', 'application/x-www-form-urlencoded; charset=UTF-8')
                    self.c.putheader('Pragma', 'no-cache'); self.c.putheader('Cache-Control', 'no-store')
                self.c.endheaders()
                r = self.c.getresponse(); body = r.read()
                for h, v in r.getheaders():
                    if h.lower() == 'set-cookie' and '=' in v:
                        k, _, val = v.split(';', 1)[0].partition('='); self.cookies[k.strip()] = val.strip()
                return r.status, body
            except (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError, http.client.CannotSendRequest):
                self.close()
                if attempt: raise
            except Exception:
                self.close(); raise


# ---------------- Steam ticket of the stand account ----------------
def steam_ticket():
    """(steamid64, ticket base64, helper process) - the helper is kept until the sign-in is done, then let go"""
    env = dict(os.environ, WINEPREFIX=PREFIX, WINEDEBUG='-all', DISPLAY=DISPLAY, SteamAppId='56400', SteamGameId='56400',
               WINEDLLOVERRIDES='mscoree,mshtml=')
    p = subprocess.Popen([WINE, TICKET_EXE], cwd=HERE, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL)
    out = {}
    t = threading.Thread(target=lambda: out.update(line=p.stdout.readline().decode('ascii', 'replace').strip()), daemon=True)
    t.start(); t.join(90)
    line = out.get('line') or ''
    if not line.startswith('OK '):
        release(p)
        raise RuntimeError('ticket helper: %s' % (line[:60] if line.startswith('ERR') else 'no answer'))
    _, sid64, hexa = line.split(' ', 2)
    if sid64 != STAND_STEAM:
        release(p); raise RuntimeError('ticket helper: the prefix is signed in as another Steam account (%s), not used' % sid64)
    return sid64, base64.b64encode(bytes.fromhex(hexa)).decode(), p


def release(p):
    try: p.stdin.close()
    except Exception: pass
    try: p.wait(20)
    except Exception:
        try: p.kill()
        except Exception: pass


# ---------------- one session ----------------
class Session:
    def __init__(self):
        self.cookies = {}; self.sid = None; self.pid = self.sg = None
        self.lost = threading.Event(); self.why = ''
        self.main = Relic(self.cookies); self.poll = Relic(self.cookies)

    def login(self):
        sid64, hexa, helper = steam_ticket()
        try:
            path = '/game/login/platformlogin?' + qs([('auth', hexa)] + LOGIN + [('platformUserID', sid64)] + LOGIN_TAIL)
            st, body = self.main.get(path, 30, login=True)
        finally:
            release(helper); hexa = path = None
        try: j = json.loads(body)
        except Exception: j = None
        if st != 200 or not (isinstance(j, list) and j and j[0] == 0 and len(j) > 3):
            code = j[0] if isinstance(j, list) and j else None
            raise RuntimeError('platformlogin: HTTP %s, answer code %r' % (st, code))
        self.sid = j[1]; me = j[3][0]; self.pid, self.sg = int(me[1]), int(me[6])
        log('signed in: profile %d, statgroup %d' % (self.pid, self.sg))
        threading.Thread(target=self.read_session, daemon=True).start()

    def read_session(self):
        ack, fails = 0, 0
        while not self.lost.is_set():
            try:
                st, body = self.poll.get('/game/login/readSession?' + qs([('sessionID', self.sid), ('ack', ack)]), 45)
            except Exception as e:
                fails += 1
                if fails >= 3: self.drop('readSession: %s' % type(e).__name__); return
                time.sleep(2); continue
            m = re.match(rb'^(\d+),', body or b'')
            if st != 200 or not m:
                self.drop('readSession: HTTP %s %r' % (st, (body or b'')[:12])); return
            ack, fails = int(m.group(1)), 0

    def drop(self, why):
        if not self.lost.is_set(): self.why = why; self.lost.set()

    def find(self, name):
        f = FILTERS[name]
        pairs = [('profile_ids', '[%d]' % self.pid), ('statGroup_ids', '[%d]' % self.sg), ('race_ids', '[0]'), ('matchType_id', '1'),
                 ('modName', f['modName']), ('modVersion', f['modVersion']), ('modDLLFile', 'INVALID'),
                 ('modDLLChecksum', f['modDLLChecksum']), ('dataChecksum', f['dataChecksum']),
                 ('appBinaryChecksum', f['appBinaryChecksum']), ('cheatsEnabled', '0'), ('sessionID', self.sid)]
        st, body = self.main.get('/game/advertisement/findAdvertisements?' + qs(pairs), 30)
        try: j = json.loads(body)
        except Exception: j = None
        if st != 200 or not isinstance(j, list) or not j:
            raise LookupError('HTTP %s' % st)
        if j[0] != 0 or len(j) < 2 or not isinstance(j[1], list):
            raise LookupError('answer code %r' % j[0])
        return [a[0] for a in j[1] if isinstance(a, list) and a and isinstance(a[0], int)]

    def logout(self):
        self.lost.set()
        if self.sid:
            try: self.main.get('/game/login/logout?' + qs([('sessionID', self.sid)]), 10)
            except Exception: pass
        self.sid = None; self.main.close(); self.poll.close()


# ---------------- output for the ladder ----------------
def public_ids():
    with urllib.request.urlopen(urllib.request.Request(PUBLIC, headers={'User-Agent': 'dow2-ladder relic-scan'}), timeout=15) as r:
        return [m.get('id') for m in (json.load(r).get('matches') or []) if isinstance(m.get('id'), int)]


def write_out(state, ads=None, other=None, public=None, note=''):
    d = {'ts': int(time.time()), 'state': state, 'every': SCAN_EVERY, 'note': note,
         'filters': {n: {o: f[i] for i, o in FIELD_OUT} for n, f in FILTERS.items()}}
    if ads is not None: d.update(scan_ts=int(time.time()), ads=ads, other=other or [], public=public)
    else:
        try:                                         # paused: keep the last scan (the ladder looks at scan_ts)
            old = json.load(open(ADS_OUT))
            d.update({k: old[k] for k in ('scan_ts', 'ads', 'other', 'public') if k in old})
        except Exception: pass
    tmp = ADS_OUT + '.tmp'
    with open(tmp, 'w') as f: json.dump(d, f, separators=(',', ':'))
    os.chmod(tmp, 0o644); os.replace(tmp, ADS_OUT)


def scan(s):
    ads, counts = {}, {}
    for name in ('vanilla', 'elite'):
        ids = s.find(name); counts[name] = len(ids)
        f = FILTERS[name]
        for aid in ids:
            e = dict({o: f[i] for i, o in FIELD_OUT}, src='scan', q=name)
            if str(aid) in ads: ads[str(aid)]['both'] = True          # Relic did not filter it: not exact
            else: ads[str(aid)] = e
    for k in [k for k, v in ads.items() if v.get('both')]: ads.pop(k)
    try: pub = public_ids()
    except Exception: pub = None
    other = sorted(set(pub) - {int(k) for k in ads}) if pub is not None else []
    write_out('ok', ads, other, len(pub) if pub is not None else None)
    return counts, len(other), (len(pub) if pub is not None else -1)


# ---------------- main loop ----------------
ONCE_DONE = []
CURRENT = []                                         # the signed-in session, signed out on SIGTERM (systemctl stop)


def main():
    logins, pause_until, last_seen_game, backoff, last_line, last_write = [], 0, 0, 60, '', 0
    log('relic scan: stand prefix %s, out %s, every %d s' % (PREFIX, ADS_OUT, SCAN_EVERY))
    while True:
        now = time.time(); g = stand_game()
        if g: last_seen_game = now
        why = None
        if g: why = 'the stand\'s game runs (pid %d)' % g
        elif now - last_seen_game < STAND_QUIET: why = 'the stand\'s game ended %d s ago' % (now - last_seen_game)
        elif now < pause_until: why = 'pause %d s more' % (pause_until - now)
        logins = [t for t in logins if now - t < 3600]
        if not why and len(logins) >= MAX_LOGINS: why = '%d sign-ins in the last hour' % len(logins)
        if why:
            line = 'waiting: ' + re.sub(r'\d+ s', 'N s', why)
            if line != last_line: log('waiting: ' + why); last_line = line; last_write = 0
            if now - last_write > 60:
                try: write_out('paused', note=why); last_write = now
                except Exception as e: log('write: %r' % e)
            time.sleep(10); continue
        last_line = ''
        s = Session(); logins.append(now); CURRENT[:] = [s]
        try:
            s.login(); backoff = 60
        except Exception as e:
            log('sign-in failed: %s - next try in %d s' % (e, backoff))
            if ONCE: s.logout(); return
            s.logout(); pause_until = time.time() + backoff; backoff = min(backoff * 2, 3600); continue
        next_scan = 0
        while not s.lost.is_set():
            g = stand_game()
            if g:
                log('the stand\'s game started (pid %d): signing out' % g); s.logout(); last_seen_game = time.time(); break
            if time.time() >= next_scan:
                next_scan = time.time() + SCAN_EVERY
                try:
                    c, no, np = scan(s)
                    log('scan: vanilla %d, elite %d, neither %d, public %d' % (c['vanilla'], c['elite'], no, np))
                    if ONCE:
                        ONCE_DONE.append(1)
                        if len(ONCE_DONE) >= ONCE: log('test done: signing out'); s.logout(); return
                except LookupError as e:
                    s.drop('findAdvertisements: %s' % e)
                except Exception as e:
                    log('scan error: %r' % e)
            s.lost.wait(2)
        if s.why:
            log('session lost (%s): pause %d s' % (s.why, KICK_PAUSE)); s.logout(); pause_until = time.time() + KICK_PAUSE
            try: write_out('paused', note='session lost')
            except Exception: pass


def stop(*_): raise SystemExit(0)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, stop)
    try: main()
    except (KeyboardInterrupt, SystemExit): pass
    finally:
        for s in CURRENT:
            if s.sid: log('stopping: signing out'); s.logout()
