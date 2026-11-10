# Admin inbox (10.11.2026): every conversation of the feedback chat (data/feedback.sqlite, table fb) as a mail client,
# for the owner and whoever he invites. Part of the ladder service: ladder.py routes /ladder/inbox and /ladder/api/inbox/* here.
#
# Access: a Steam sign-in of the site (community.py, cookie csess) whose Steam id is in data/admins.json. An admin is added
# with a one-time invite link (data/admin_invites.json, 7 days): /ladder/inbox?inv=K keeps K in a cookie, the page asks to
# sign in with Steam (same OpenID as the web chat) if needed, then binds that Steam id. The invite alone gives nothing.
# The old fb-admin token (data/fb_admin_token) still works in the X-Admin-Token header (compatibility).
# POSTs from a Steam session need X-CSRF (HMAC of the session, from /api/inbox/me; only same-origin pages can read it).
#
# GET  /ladder/inbox[?inv=K]          -> the page (with inv: keep the invite in a cookie, redirect to the bare address)
# GET  api/inbox/me                   -> {signed_in, admin, invite, steam?, name?, avatar?, csrf?}  (no inbox data)
# GET  api/inbox/threads?q=&unread=1  -> {threads: [...], mod}                         (admin)
# GET  api/inbox/thread?uid=&seen=0   -> {thread, messages: [... with meta, seen, logs]} (admin; marks it read unless seen=0)
# POST api/inbox/bind                 -> binds the signed-in Steam id with the invite cookie
# POST api/inbox/invite -> {url} (admin: a new one-time invite)
# POST api/inbox/reply {uid, text, images?}   POST api/inbox/mod {set: premod|all_muted|mute_uid, on, uid?}   (admin)
# CLI: python3 inbox.py mint  -> a new invite link (run as the ladder user)
import hashlib, hmac, json, os, re, secrets, sys, threading, time, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADMINS = ROOT + '/data/admins.json'
INVITES = ROOT + '/data/admin_invites.json'
SECRET = ROOT + '/data/inbox_secret'
PAGE = os.path.dirname(os.path.abspath(__file__)) + '/inbox.html'
BASE = 'https://dow2.fintebtc.de'
INVITE_TTL = 7 * 86400
INV_COOKIE = 'ainv'
LOCK = threading.Lock()
L = None                       # the ladder module (fb_db, fb_send, fb_mod_load/save, _fb_token_ok, _fb_uid)
LOGS_RE = re.compile(r'\b(\d{8}-\d{6}-[0-9a-f]{6})\b')

def _jload(p, dflt):
    try:
        with open(p) as f: return json.load(f)
    except Exception: return dflt
def _jsave(p, d):
    tmp = p + '.tmp'
    with open(tmp, 'w') as f: json.dump(d, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o640); os.replace(tmp, p)

def admins():
    d = _jload(ADMINS, {})
    return d.get('admins', {}) if isinstance(d, dict) else {}
def is_admin_steam(steam):
    return bool(steam) and str(steam) in admins()

def _secret():
    with LOCK:
        try: return open(SECRET, 'rb').read()
        except FileNotFoundError:
            s = secrets.token_bytes(32)
            fd = os.open(SECRET, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as f: f.write(s)
            return s
def csrf_of(sess):
    return hmac.new(_secret(), b'csrf:' + sess.encode(), hashlib.sha256).hexdigest()[:40]

# ---------- invites ----------
def _invites():
    d = _jload(INVITES, {}); now = int(time.time())
    return {k: v for k, v in d.items() if isinstance(v, int) and v > now} if isinstance(d, dict) else {}
def mint(ttl=INVITE_TTL):
    with LOCK:
        d = _invites(); k = secrets.token_hex(24); d[k] = int(time.time()) + ttl; _jsave(INVITES, d)
    return k
def invite_ok(k):
    return bool(k) and re.fullmatch(r'[0-9a-f]{48}', k) is not None and k in _invites()
def _consume(k):
    with LOCK:
        d = _invites()
        if k not in d: return False
        del d[k]; _jsave(INVITES, d)
    return True

# ---------- who is asking ----------
def _cookie(h, name):
    for part in (h.headers.get('Cookie') or '').split(';'):
        k, _, v = part.strip().partition('=')
        if k == name: return v
    return ''
def _session(h):
    import community
    tok = _cookie(h, 'csess')
    steam = community._session(tok) if tok else None
    return (str(steam), tok) if steam else (None, None)
def auth(h):
    """('steam', steam, sess) | ('token', None, None) | None"""
    steam, tok = _session(h)
    if steam and is_admin_steam(steam): return ('steam', steam, tok)
    t = h.headers.get('X-Admin-Token') or ''
    if t and L._fb_token_ok(t): return ('token', None, None)
    return None
def is_admin(h):
    try: return auth(h) is not None
    except Exception: return False

# ---------- data ----------
def _s(v): return L._fb_s(v)
def _meta(v):
    try:
        m = json.loads(_s(v) or '{}'); return m if isinstance(m, dict) else {}
    except Exception: return {}
def _user(steam):
    try:
        import users
        u = users.get(steam); return {'name': u['name'], 'avatar': u['avatar']}
    except Exception: return {'name': '', 'avatar': ''}

def _rows(c, uid=None):
    q = 'SELECT id, uid, name, author, text, images, ts, seen, meta FROM fb'
    return c.execute(q + (' WHERE uid=? ORDER BY id' if uid else ' ORDER BY id'), ((uid,) if uid else ())).fetchall()

def _msg(r, player):
    text = _s(r[4]) or ''
    try: imgs = json.loads(_s(r[5]) or '[]')
    except Exception: imgs = []
    return {'id': r[0], 'author': _s(r[3]), 'name': _s(r[2]) or '', 'text': text, 'images': imgs if isinstance(imgs, list) else [],
            'ts': r[6], 'seen': bool(r[7]), 'meta': _meta(r[8]),
            'to': 'Elite dev' if _s(r[3]) == 'player' else (player or ''),
            'logs': LOGS_RE.findall(text) if '📋' in text or 'logs' in text else []}

def _summary(uid, rows, muted):
    player = ''; meta = {}; steam = ''
    for r in rows:
        if _s(r[3]) == 'player':
            if _s(r[2]): player = _s(r[2])
            m = _meta(r[8])
            if m: meta = m
            if m.get('steam') and re.fullmatch(r'\d{17}', str(m['steam'])): steam = str(m['steam'])
    last = rows[-1]
    last_dev = max([r[0] for r in rows if _s(r[3]) == 'dev'] or [0])
    t = {'uid': uid, 'name': player, 'steam': steam, 'count': len(rows),
         # unread = player messages not opened AND after the last dev answer (an answered one was read by whoever answered,
         # e.g. another session through the API, which never set the seen flag)
         'unseen': sum(1 for r in rows if _s(r[3]) == 'player' and not r[7] and r[0] > last_dev),
         'ts': last[6], 'first_ts': rows[0][6], 'meta': meta, 'muted': uid in muted,
         'last': {'author': _s(last[3]), 'text': (_s(last[4]) or '')[:200], 'images': bool(_s(last[5]) not in (None, '', '[]'))},
         'dev_count': sum(1 for r in rows if _s(r[3]) == 'dev')}
    if steam: t['avatar'] = _user(steam)['avatar']
    return t

def threads(q='', unread=False):
    mod = L.fb_mod_load(); c = L.fb_db()
    try: rows = _rows(c)
    finally: c.close()
    by = {}
    for r in rows: by.setdefault(_s(r[1]), []).append(r)
    q = (q or '').strip().lower()[:100]
    out = []
    for uid, rs in by.items():
        t = _summary(uid, rs, mod.get('muted', []))
        if unread and not t['unseen']: continue
        if q:
            hay = ' '.join([uid, t['name'], t['steam']] + [(_s(r[4]) or '') + ' ' + (_s(r[2]) or '') for r in rs]).lower()
            if q not in hay: continue
            t['hits'] = sum(1 for r in rs if q in (_s(r[4]) or '').lower())
        out.append(t)
    out.sort(key=lambda t: t['ts'] or 0, reverse=True)
    return {'threads': out, 'total_unseen': sum(t['unseen'] for t in out),
            'mod': {'premod': bool(mod.get('premod')), 'all_muted': bool(mod.get('all_muted'))}}

def thread(uid, mark=True):
    uid = L._fb_uid(uid)
    if not uid: return {'error': 'uid'}
    mod = L.fb_mod_load(); c = L.fb_db()
    try:
        rows = _rows(c, uid)
        if not rows: return {'error': 'not found'}
        if mark:
            with L.FB_LOCK: c.execute('UPDATE fb SET seen=1 WHERE uid=? AND seen=0', (uid,)); c.commit()
    finally: c.close()
    t = _summary(uid, rows, mod.get('muted', []))
    return {'thread': t, 'messages': [_msg(r, t['name'] or uid) for r in rows]}

# ---------- HTTP ----------
def _no(h, code=403, err='auth'): return h.send(code, {'error': err}, cache=0)
def handle_get(h, u, qs):
    p = u.path
    if p == '/ladder/inbox':
        inv = qs.get('inv', [''])[0]
        if inv:                              # keep the invite in a cookie (not in the address bar / history), then the bare page
            h.send_response(302)
            if invite_ok(inv):
                h.send_header('Set-Cookie', '%s=%s; Path=/ladder/; Max-Age=86400; Secure; HttpOnly; SameSite=Lax' % (INV_COOKIE, inv))
                h.send_header('Location', '/ladder/inbox')
            else: h.send_header('Location', '/ladder/inbox?bad=1')
            h.send_header('Cache-Control', 'no-store'); h.send_header('Content-Length', '0'); h.end_headers(); return
        with open(PAGE, 'rb') as f: b = f.read()
        h.send_response(200); h.send_header('Content-Type', 'text/html; charset=utf-8'); h.send_header('Content-Length', str(len(b)))
        h.send_header('Cache-Control', 'no-store'); h.send_header('X-Frame-Options', 'DENY'); h.send_header('Referrer-Policy', 'no-referrer')
        h.end_headers(); h.wfile.write(b); return
    a = p[len('/ladder/api/inbox/'):]
    if a == 'me':
        steam, tok = _session(h)
        inv = invite_ok(_cookie(h, INV_COOKIE))
        r = {'signed_in': bool(steam), 'admin': bool(steam and is_admin_steam(steam)), 'invite': inv}
        if not steam and h.headers.get('X-Admin-Token') and L._fb_token_ok(h.headers.get('X-Admin-Token')): r['admin'] = True; r['via'] = 'token'
        if steam:
            r.update(steam=steam, **_user(steam))
            if r['admin'] or inv: r['csrf'] = csrf_of(tok)
        return h.send(200, r, cache=0)
    who = auth(h)
    if not who: return _no(h)
    if a == 'threads': return h.send(200, threads(qs.get('q', [''])[0], qs.get('unread', [''])[0] in ('1', 'true')), cache=0)
    if a == 'thread': return h.send(200, thread(qs.get('uid', [''])[0], qs.get('seen', ['1'])[0] != '0'), cache=0)
    return h.send(404, {'error': 'not found'}, cache=0)

def _csrf_ok(h, sess):
    return hmac.compare_digest(h.headers.get('X-CSRF') or '', csrf_of(sess))

def handle_post(h, u):
    a = u.path[len('/ladder/api/inbox/'):]
    n = int(h.headers.get('Content-Length') or 0)
    if n < 0 or n > 24 << 20: return h.send(413, {'error': 'size'}, cache=0)
    try: d = json.loads(h.rfile.read(n).decode('utf-8')) if n else {}
    except Exception: return h.send(400, {'error': 'json'}, cache=0)
    d = d if isinstance(d, dict) else {}
    if a == 'bind':
        steam, tok = _session(h)
        if not steam: return _no(h, 403, 'signin')
        if not _csrf_ok(h, tok): return _no(h, 403, 'csrf')
        k = _cookie(h, INV_COOKIE)
        if is_admin_steam(steam): r = {'ok': True, 'already': True}
        elif not invite_ok(k) or not _consume(k): return _no(h, 403, 'invite')
        else:
            with LOCK:
                doc = _jload(ADMINS, {}); doc = doc if isinstance(doc, dict) else {}
                doc.setdefault('admins', {})[steam] = {'added': int(time.time()), 'via': 'invite', 'name': _user(steam)['name']}
                _jsave(ADMINS, doc)
            print('inbox: admin bound steam=%s' % steam, flush=True); r = {'ok': True}
        b = json.dumps(r).encode()
        h.send_response(200); h.send_header('Content-Type', 'application/json'); h.send_header('Content-Length', str(len(b)))
        h.send_header('Set-Cookie', '%s=; Path=/ladder/; Max-Age=0; Secure; HttpOnly; SameSite=Lax' % INV_COOKIE)
        h.send_header('Cache-Control', 'no-store'); h.end_headers(); h.wfile.write(b); return
    who = auth(h)
    if not who: return _no(h)
    if who[0] == 'steam' and not _csrf_ok(h, who[2]): return _no(h, 403, 'csrf')
    if a == 'reply':
        uid = L._fb_uid(d.get('uid'))
        if not uid: return h.send(200, {'error': 'uid'}, cache=0)
        r = L.fb_send({'uid': uid, 'text': d.get('text'), 'images': d.get('images') or [], 'name': 'Elite dev'}, 'dev')
        print('inbox: reply uid=%s by=%s ok=%s' % (uid[:8], who[1] or 'token', r.get('ok')), flush=True)
        return h.send(200, r, cache=0)
    if a == 'invite':                    # an admin invites another one: a one-time link, 7 days
        host = h.headers.get('Host') or ''
        base = BASE if host.endswith('fintebtc.de') or not host else 'http://' + host
        print('inbox: invite minted by=%s' % (who[1] or 'token'), flush=True)
        return h.send(200, {'ok': True, 'url': base + '/ladder/inbox?inv=' + mint(), 'days': INVITE_TTL // 86400}, cache=0)
    if a == 'mod':
        m = L.fb_mod_load(); st = d.get('set'); on = bool(d.get('on'))
        if st == 'all_muted': m['all_muted'] = on
        elif st == 'premod': m['premod'] = on
        elif st == 'mute_uid':
            uu = L._fb_uid(d.get('uid'))
            if uu: m['muted'] = [x for x in m['muted'] if x != uu] + ([uu] if on else [])
        else: return h.send(400, {'error': 'set'}, cache=0)
        L.fb_mod_save(m); return h.send(200, {'ok': True, 'mod': m}, cache=0)
    return h.send(404, {'error': 'not found'}, cache=0)

if __name__ == '__main__' and sys.argv[1:2] == ['mint']:
    base = sys.argv[2] if len(sys.argv) > 2 else BASE
    print(base + '/ladder/inbox?inv=' + mint())
