# Launcher match rooms (owner 05.11.2026: "a lobby in the launcher like the game's own: the map, who plays where and with
# which army, everybody presses Ready, 10 s countdown, then the game starts for everyone and they all land in one match;
# show who reaches which of our servers, everybody's pings and the server the match will use").
#
# A room lives here, in the ladder's memory (a restart loses the rooms that are open: the launchers see "gone" and the
# players make a new one). The launcher talks to it over HTTPS (/ladder/api/lroom/*, the community session token) and
# hears every change on its live stream (/ladder/api/c/stream, event "lroom" with the room's whole view, "lroom_gone").
#
# The match itself goes the way of the native automatch (research launcher_match_assembly_research.md, path A): at the
# end of the countdown every launcher starts its game (or uses the one in the menu) and tells MMFind over its pipe to
# search with this room's ticket; MMFind sets mode / race / hero on Find a Game and presses Start Searching; own_lobby
# puts the search into the ladder (nm/join) and the ladder, seeing a player of a room that launches, keeps him in that
# room's own pool ('lroom:<id>|...', never matched with anybody else) until every player of the room is in. Then the
# match is made from the room - its host, map, teams - and own_lobby / the games do the rest as for any native match.
# A failure anywhere (a game that never got to the search, another version, the host's room not up, a guest not in)
# calls the whole launch off for everybody and the room is back to its lobby with the reason.
#
# Matches from rooms are never rated (agreed games: own_lobby stores them without a mode); mm_history has kind 'room'.
#
# 10.11.2026 (owner, launcher 1.5.3): observers - a room keeps up to 8 - 2 x its team of them (as the automatch's watch: 3v3 2,
# 2v2 4, 1v1 6); at the launch their MMFind searches in its Watch mode with the room's id ("lroom") and goes into the room's
# match as a watcher (an observer never blocks or calls off the start). Invitations (verb invite -> "lroom_invite" on the
# invited player's stream) and pings (verb ping: the owner's ready check to who is not ready, a player's call of the owner
# when all are ready -> "lroom_ping"). The list's summary carries the seats and the observers (the launcher draws the teams).
# 1.5.8 (owner 12.11.2026): a player calls the owner as soon as every OTHER seat is taken and ready; the room's view carries the
# ping ("ping": who called whom, when the 30 s pause ends, the answers - every player's button shows the pause, the pinged
# player's answer shows next to his name); verb ping_answer (yes / no); the owner's Start marks him ready; a kick keeps nobody
# out (KICK_BAN) and an invitation into a room can be sent again once the player came in or left it.
import json, random, re, secrets, string, threading, time

L = None                    # the ladder module (ladder.py sets it right after the import)
ROOMS = {}                  # id -> room
BY = {}                     # steam -> room id (one room per player)
KICKED = {}                 # (room id, steam) -> until when he can't come back (KICK_BAN s after a kick; 0 = never kept out)
KICK_BAN = 0                # 1.5.8 (owner 12.11.2026): a removed player may come back at once - a kick by mistake is fixed by Join or an invitation
INVITED = {}                # (room id, steam) -> until when he is not invited into that room again
INVITE_GAP = 30             # s between two invitations of one player into one room
INVITE_MAX = 10             # invitations one player may send in a minute (into any rooms)
INV_SENT = {}               # steam -> the times of his invitations of the last minute
PING_GAP = 30               # s between two pings of one kind in one room
PING_TTL = 30               # s the pinged player has to answer (the launcher's window)
INVITE_TTL = 180            # s an invitation stays on the invited player's screen
CD = 10                     # s of the countdown once everybody is ready (as the game's lobby)
HERE_GONE = 45              # s without a heartbeat from his launcher: out of the room (only while it is in its lobby)
LAUNCH_WAIT = int(__import__('os').environ.get('LROOM_LAUNCH_WAIT', '150'))   # s from the end of the countdown to every game in the search
PLAY_KEEP = 3 * 3600        # s a room stays "playing" without a word of the match's end
MAX_ROOMS = 300
SPOIL_KINDS = ('late', 'version', 'race', 'left_search', 'game_failed', 'match', 'left')   # a start called off because of these players
NAME_MAX = 48
ELITE_ORDER = ['space_marines', 'chaos_marines', 'eldar', 'orks', 'tyranids', 'imperial_guard', 't_tau', 'ordo_malleus']
VAN_RACES = ['chaos_marines', 'eldar', 'imperial_guard', 'orks', 'space_marines', 'tyranids']   # the vanilla drop-down order (its UI index)


def log(*a): print('lroom:', *a, flush=True)


def _races(game):
    """{race key: {'ui': index in the game's race drop-down, 'heroes': how many}} of the game's playable races"""
    elite = None if game == 'vanilla' else 1
    try:
        with open(__import__('os').path.dirname(__import__('os').path.abspath(__file__)) + '/assets_index.json', encoding='utf-8') as f:
            rs = json.load(f).get('races') or {}
    except Exception: rs = {}
    out = {k: {'ui': v.get('ui_index'), 'heroes': len(v.get('heroes') or []), 'names': [h.get('name') or '' for h in v.get('heroes') or []]}
           for k, v in rs.items() if v.get('playable') and v.get('heroes')}
    if not elite:   # vanilla: its six races, their drop-down order; the heroes as Elite's (the same hero_list in both, 06.11.2026)
        return {k: {'ui': i, 'heroes': (out.get(k) or {}).get('heroes', 3), 'names': (out.get(k) or {}).get('names') or []} for i, k in enumerate(VAN_RACES)}
    return out or {k: {'ui': i, 'heroes': 3} for i, k in enumerate(L.RACE_KEYS[:8])}


def _maps(game, mode):
    n = 2 * L.TEAM_N[mode]; cat = L._catalog()
    keys = [k for k, v in cat.items() if v.get('maxplayers') == n and (game != 'vanilla' or k in L.VAN_MAPS)]
    return sorted(keys, key=lambda k: (cat[k].get('name') or k).lower()) or L._nm_maps(game, mode)


def _clean(v, n): return L._clean(v, n)


# ---------- the match options (the host's game writes them: MMFind 0.47 rewrites the options string of the room's match) ----------
# Stand 1, 06.11.2026 (lroom/runs/op1, the Private Match lobby's drop-downs against the string the game wrote): the victory condition
# is the item number of its drop-down (Elite 3.2: 0 Annihilate, 1 Free For All, 2 Team FFA, 3 Victory Point Control, 4 Annihilate -
# Hero Assault, 5 Massive Battles - Annihilate, 6 VPC - Hero Assault (500), ...); with VPC the tickets 250 / 500 / 1000 = VPTK 0 / 1 / 2;
# Starting Location Random / Fixed = SLOC 0 / 1; Starting resources Standard / High Resources = RSST 0 / 1. The native automatch's
# defaults: VPC, 500, Fixed, Standard.
OPT_WIN = {'vpc': 3, 'annihilate': 0, 'annihilate_hero': 4, 'vpc_hero': 6}
OPT_VP = {250: 0, 500: 1, 1000: 2}
OPT_DEFAULT = {'win': 'vpc', 'vp': 500, 'start': 'fixed', 'res': 'standard'}
def _opts_clean(o, game='elite'):
    out = dict(OPT_DEFAULT)
    if o.get('win') in OPT_WIN and (game != 'vanilla' or o['win'] in ('vpc', 'annihilate')): out['win'] = o['win']
    try:
        if int(o.get('vp')) in OPT_VP: out['vp'] = int(o['vp'])
    except Exception: pass
    if o.get('start') in ('fixed', 'random'): out['start'] = o['start']
    if o.get('res') in ('standard', 'high'): out['res'] = o['res']
    return out
def _opt_values(r):
    """for MMFind (the host): the numbers of the options string; the defaults are sent too (the game's own may differ by version)"""
    o = r['opts']
    return {'win': OPT_WIN[o['win']], 'vptk': OPT_VP[o['vp']], 'sloc': 1 if o['start'] == 'fixed' else 0, 'rsst': 1 if o['res'] == 'high' else 0}


def _new_id():
    while True:
        i = ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))
        if i not in ROOMS: return i


def _size(r): return L.TEAM_N[r['mode']]


def _members(r): return [s['steam'] for s in r['slots'] if s]


def _slot(r, steam): return next((s for s in r['slots'] if s and s['steam'] == steam), None)


def _obs_cap(r): return max(0, 8 - 2 * _size(r))      # the observer seats of the match (the automatch's watch, ladder.py)


def _obs(r, steam): return next((o for o in r.setdefault('obs', []) if o['steam'] == steam), None)


def _everyone(r): return _members(r) + [o['steam'] for o in r.setdefault('obs', [])]


def _name(steam):
    try: return L.users.get(steam)['name'] or 'Player'
    except Exception: return 'Player'


def _note(r, k, who=(), **kw):
    r['note'] = dict(kw, k=k, who=[_name(s) for s in who], t=int(time.time()))


# ---------- the network: who reaches which of our servers, and the one the match takes ----------
def _nodes():
    doc = (L._relays().get('doc') or {})
    names = {x.get('ip'): x.get('name') or x.get('ip') for x in doc.get('relays') or []}
    return [{'ip': ip, 'name': names.get(ip, ip)} for ip in L.relay_order()]


def _pings_of(r, steam):
    """the pings his launcher measured, in the shape Relay.dll sends them (ip -> ms, -1 = no answer or no stream; the chain
    key when his Relay.dll passes a match on through its own nearest node)"""
    x = (r['pings'].get(steam) or {})
    p = dict(x.get('p') or {})
    if p and x.get('chain'): p[L.CHAIN_V] = 1
    return p


def _net(r):
    """the table of the room: every player against every node (ms / -1), his delay to each node through a chain when he has
    one, the node the match would use now (the same rule as the native automatch: of the nodes every player reaches - straight
    or through his nearest node - the one with the lowest worst delay; a tie goes by relays.json) and why"""
    ro = L.relay_order(); links = L._relay_links(); steams = _members(r)
    av = L._avoid_of(steams)                     # 06.11.2026 node quality: the nodes bad for a player (nodeq.py) - not for him
    nq = {}
    for s in steams:
        try: nq[s] = L.nodeq.public(s)
        except Exception: nq[s] = {}
    rows, all_have = [], True
    for s in steams:
        p = _pings_of(r, s)
        if not p: all_have = False
        cost = {h: L._relay_cost(p, h, ro, links) if p else (None, None) for h in ro}
        qcost = {h: L._relay_cost(p, h, ro, links, av.get(s) or frozenset()) if p else (None, None) for h in ro}
        rows.append({'steam': s, 'ping': {h: (r['pings'].get(s) or {}).get('p', {}).get(h) for h in ro},
                     'raw': (r['pings'].get(s) or {}).get('raw') or {},
                     'chain': bool((r['pings'].get(s) or {}).get('chain')), 'age': int(time.time() - (r['pings'].get(s) or {}).get('t', 0)) if r['pings'].get(s) else None,
                     'cost': {h: (round(c) if c is not None else None) for h, (c, v) in cost.items()},
                     'qcost': {h: (round(c) if c is not None else None) for h, (c, v) in qcost.items()},
                     'via': {h: v for h, (c, v) in cost.items() if v},
                     'nq': {h: m for h, m in (nq.get(s) or {}).items() if h in ro}})
    pick, worst, ignored = '', None, False
    if steams and all_have:
        def best_of(key):
            best = None
            for h in ro:
                cs = [row[key][h] for row in rows]
                if any(c is None for c in cs): continue
                k = (max(cs), ro.index(h))
                if best is None or k < best[0]: best = (k, h)
            return best
        best = best_of('qcost')
        if not best and any(av.values()):        # nothing fits without the bad nodes: the marks are ignored for this match
            best = best_of('cost'); ignored = bool(best)
        if best: pick, worst = best[1], best[0][0]
    why = 'measuring' if steams and not all_have else 'ok' if pick else 'none' if steams else ''
    return {'nodes': _nodes(), 'rows': rows, 'pick': pick, 'worst': worst, 'why': why, 'nq_ignored': ignored}


# ---------- the view everybody gets (stream event "lroom") ----------
def view(r):
    n = _size(r); cat = L._catalog(); now = time.time()
    slots = []
    for i, s in enumerate(r['slots']):
        if not s: slots.append(None); continue
        u = L.users.get(s['steam'])
        slots.append({'steam': s['steam'], 'name': u['name'] or 'Player', 'avatar': u['avatar'], 'rating': u.get('rating'),
                      'team': 0 if i < n else 1, 'race': s['race'], 'hero': s['hero'], 'ready': s['ready'], 'game': s.get('gst') or '',
                      'game_t': int(s.get('gst_t') or 0), 'here': now - s['seen'] < HERE_GONE, 'owner': s['steam'] == r['owner'],
                      'spoil': (r.get('spoil') or {}).get(s['steam'], 0)})
    obs = []
    for o in r.setdefault('obs', []):
        u = L.users.get(o['steam'])
        obs.append({'steam': o['steam'], 'name': u['name'] or 'Player', 'avatar': u['avatar'], 'here': now - o['seen'] < HERE_GONE, 'game': o.get('gst') or ''})
    la = r.get('launch') or {}
    return {'id': r['id'], 'name': r['name'], 'game': r['game'], 'ver': r['ver'], 'mode': r['mode'], 'size': n,
            'map': r['map'], 'map_name': (cat.get(r['map']) or {}).get('name') or r['map'], 'owner': r['owner'],
            'maps': [{'key': k, 'name': (cat.get(k) or {}).get('name') or k} for k in r['maps']], 'opts': dict(r['opts']),
            'state': r['state'], 'cd_end': int(r['cd'] * 1000) if r['state'] == 'countdown' else 0, 'now': int(now * 1000),
            'slots': slots, 'obs': obs, 'obs_cap': _obs_cap(r), 'net': _net(r), 'note': r.get('note'), 'seq': r['seq'],
            'hs': bool(r.get('hs')), 'all_ready': _all_ready(r, now), 'ping': _ping_view(r, now),
            'launch': {'t': int(la.get('t', 0)), 'deadline': int(la.get('deadline', 0)), 'host': la.get('host'), 'relay': la.get('relay'),
                       'match': la.get('match'), 'room': la.get('room'), 'map': la.get('map'),
                       'map_name': (cat.get(la.get('map')) or {}).get('name') or la.get('map')} if la else None}


def _ping_view(r, now):
    """1.5.8: the room's pings for the launchers (times in ms): who called whom, the pause's end, the answers. Kept 60 s."""
    out = {}
    for k, p in (r.get('ping') or {}).items():
        if now - p['t'] > 60: continue
        out[k] = {'t': int(p['t'] * 1000), 'until': int(p['until'] * 1000), 'ttl': PING_TTL, 'from': p['from'], 'from_name': _name(p['from']),
                  'to': list(p['to']), 'ans': {s: {'a': a['a'], 't': int(a['t'] * 1000)} for s, a in p['ans'].items()}}
    return out or None


def summary(r):
    cat = L._catalog()
    return {'id': r['id'], 'name': r['name'], 'game': r['game'], 'ver': r['ver'], 'mode': r['mode'], 'map': r['map'],
            'map_name': (cat.get(r['map']) or {}).get('name') or r['map'], 'state': r['state'],
            'players': len(_members(r)), 'cap': 2 * _size(r), 'owner_name': _name(r['owner']), 'owner': r['owner'],
            'names': [_name(s) for s in _members(r)],
            'slots': [{'steam': s['steam'], 'name': _name(s['steam']), 'race': s['race'], 'hero': s['hero'], 'ready': s['ready'],
                       'rating': (L.users.get(s['steam']) or {}).get('rating')} if s else None for s in r['slots']],
            'obs': [{'steam': o['steam'], 'name': _name(o['steam'])} for o in r.setdefault('obs', [])], 'obs_cap': _obs_cap(r)}


def _pub(r):
    r['seq'] += 1
    try: L.stream.publish('lroom', view(r))
    except Exception as e: log('publish %s: %r' % (r['id'], e))


def _close(r, why):
    ROOMS.pop(r['id'], None)
    for s in _everyone(r):
        if BY.get(s) == r['id']: BY.pop(s, None)
    log('room %s closed (%s)' % (r['id'], why))
    try: L.stream.publish('lroom_gone', {'id': r['id'], 'why': why})
    except Exception: pass


# ---------- the countdown and the launch ----------
def _unready(r, k=None, who=()):
    for s in r['slots']:
        if s: s['ready'] = False
    if r['state'] == 'countdown': r['state'] = 'lobby'; _note(r, k or 'cd_stop', who)


def _all_ready(r, now):
    return all(r['slots']) and all(s['ready'] and now - s['seen'] < HERE_GONE for s in r['slots'])


def _others_ready(r, now):
    """1.5.8: every seat taken, every player but the owner ready and here - a player may call the owner"""
    return all(r['slots']) and all((s['ready'] and now - s['seen'] < HERE_GONE) for s in r['slots'] if s['steam'] != r['owner'])


def _check_ready(r, now):
    """everybody in, everybody ready, every launcher here: the countdown; anything else stops it. A room of a launcher 1.5+
    ('hs', the launcher's redesign 09.11.2026) waits for its owner's Play (verb start) instead of starting by itself."""
    ok = _all_ready(r, now)
    if r['state'] == 'lobby' and ok and not r.get('hs'):
        r['state'] = 'countdown'; r['cd'] = now + CD; r['note'] = None; log('room %s: countdown' % r['id']); return True
    if r['state'] == 'countdown' and not ok:
        r['state'] = 'lobby'
        if not r.get('note'): _note(r, 'cd_stop')
        return True
    return False


def _launch(r, now):
    """the countdown is over: the server the match takes, its host, the teams, a ticket per player"""
    net = _net(r); n = _size(r); ro = L.relay_order(); links = L._relay_links()
    pick = net['pick']
    av = {} if net.get('nq_ignored') else L._avoid_of(_members(r))
    def cost(s):
        if not pick: return 0
        c, _ = L._relay_cost(_pings_of(r, s), pick, ro, links, av.get(s) or frozenset())
        return c if c is not None else 99999
    order = _members(r)
    host = min(order, key=lambda s: (cost(s), s != r['owner'], order.index(s)))
    races = _races(r['game']); heroes = {}
    for s in r['slots']:
        if s['race'] == 'random': heroes[s['steam']] = -1                      # the game rolls race and hero (Random on Find a Game)
        elif s['hero'] is None or s['hero'] < 0: heroes[s['steam']] = random.randrange(max(1, races.get(s['race'], {}).get('heroes', 3)))
        else: heroes[s['steam']] = s['hero']
    mp = random.choice(r['maps']) if r['maps'] else r['map']                  # one of the room's maps, at random
    r['launch'] = {'t': now, 'deadline': now + LAUNCH_WAIT, 'relay': pick, 'host': host, 'heroes': heroes, 'map': mp,
                   'teams': [[s['steam'] for s in r['slots'][:n]], [s['steam'] for s in r['slots'][n:]]], 'match': None, 'room': None}
    r['state'] = 'launching'; r['note'] = None
    for s in r['slots'] + r.setdefault('obs', []): s['gst'] = 'starting'; s['gst_t'] = now
    log('room %s: launch - %s %s (of %s), host %s, relay %r (worst %s ms), teams %s' % (r['id'], r['mode'], mp, r['maps'], host, pick, net['worst'], r['launch']['teams']))


def _cancel_launch(r, k, who=(), **kw):
    """under the ladder's MM_LOCK: the launch is off for everybody - their searches stopped (own_lobby pushes the stop to every
    game that searches), the match being set up dropped, the room back to its lobby with the reason"""
    la = r.get('launch') or {}; now = time.time()
    mid = la.get('match')
    m = L.MM_MATCHES.pop(mid, None) if mid else None
    for s in _everyone(r):
        p = L.MM.get(s)
        if p and (p.get('lroom') == r['id'] or (mid and p.get('match') == mid)):
            L.MM.pop(s, None)
            L.MM_CANCELLED[s] = {'by': 'launcher room: ' + k, 'match': mid or ('lroom-' + r['id']), 't': now, 'again': False, 'native': True}
    r['state'] = 'lobby'; r['launch'] = None
    for s in r['slots']:
        if s: s['ready'] = False; s['gst'] = ''
    for o in r.setdefault('obs', []): o['gst'] = ''
    if k in SPOIL_KINDS:                                                    # "spoiled the start x2" next to his name; the owner may kick
        for s in who: r.setdefault('spoil', {})[s] = r.setdefault('spoil', {}).get(s, 0) + 1
    _note(r, k, who, **kw)
    log('room %s: launch cancelled (%s%s)%s' % (r['id'], k, ' ' + ','.join(who) if who else '', ' - match %s dropped' % mid if m else ''))


# ---------- the ladder's hooks (called by ladder.py, under MM_LOCK) ----------
def on_nm_join(steam, p, hint, d):
    """a native search came in (own_lobby nm/join): a player of a room that launches goes into that room's pool. True = taken"""
    r = ROOMS.get(BY.get(steam) or '')
    if not r or r['state'] != 'launching' or (r.get('launch') or {}).get('match'): return False
    hr = str((hint or {}).get('room') or '')
    if hr and hr != r['id']: return False                                    # MMFind searches for another room: not this one
    if not _slot(r, steam):                                                  # an observer's game searching as a player: dropped
        L.MM.pop(steam, None)
        L.MM_CANCELLED[steam] = {'by': 'launcher room: an observer watches, he does not play', 'match': 'lroom-' + r['id'], 't': time.time(), 'again': False, 'native': True}
        log('room %s: observer %s searched as a player - dropped (his MMFind has no room watch)' % (r['id'], steam))
        return True
    p['lroom'] = r['id']; p['pool'] = 'lroom:%s|%s' % (r['id'], p.get('pool') or ''); p['party'] = ''; p['party_of'] = []
    if not p.get('ping'): p['ping'] = _pings_of(r, steam) or None           # MMFind sends Relay.dll's pings; else his launcher's
    hero = (r['launch'].get('heroes') or {}).get(steam)
    if hero is not None and hero >= 0: p['hero'] = str(hero)
    sl = _slot(r, steam)
    try: rid = int(d.get('race'))
    except Exception: rid = None
    if sl and sl['race'] != 'random' and rid is not None:
        got = (VAN_RACES[rid] if r['game'] == 'vanilla' and 0 <= rid < len(VAN_RACES) else L.RACE_KEYS[rid] if 0 <= rid < len(L.RACE_KEYS) else None)
        if got and got != sl['race']:
            # 06.11.2026 (live, room d59lrf): the game searched with the army it had on Find a Game, not the room's - never a match with
            # another race: the start is off for all, the room says whose game had which race (MMFind 0.48 checks before it searches)
            log('room %s: %s searches as %s, the room says %s - the start is off' % (r['id'], steam, got, sl['race']))
            L.MM.pop(steam, None)
            _cancel_launch(r, 'race', [steam], why=got, want=sl['race']); _pub(r)
            return True
        if got: p['race'] = got
    if sl: sl['gst'] = 'searching'; sl['gst_t'] = time.time()
    log('room %s: %s is in the search (%s)' % (r['id'], steam, p['pool']))
    _assemble(r)
    _pub(r)
    return True


def _assemble(r):
    """every player of the room in its pool: the match, as the room has it (under MM_LOCK)"""
    la = r['launch']; steams = _members(r)
    ps = [L.MM.get(s) for s in steams]
    if not all(p and p.get('lroom') == r['id'] and p['state'] == 'searching' for p in ps): return
    pools = {}
    for p in ps: pools.setdefault(p['pool'], []).append(p['steam'])
    if len(pools) > 1:                                                        # another version / other data: they would never meet
        host_pool = L.MM[la['host']]['pool']
        odd = [s for pool, ss in pools.items() if pool != host_pool for s in ss]
        return _cancel_launch(r, 'version', odd)
    host = la['host']; t0, t1 = la['teams']
    host_team, guest_team = (list(t0), list(t1)) if host in t0 else (list(t1), list(t0))
    host_team.remove(host); host_team.insert(0, host)
    L.MM_SEQ[0] += 1; mid = 'm%d' % L.MM_SEQ[0]
    for p in ps: p.update(state='matched', match=mid, role='host' if p['steam'] == host else 'guest')
    slots = {s: i for i, s in enumerate(host_team)}; slots.update({s: 4 + i for i, s in enumerate(guest_team)})
    L.MM_MATCHES[mid] = {'id': mid, 'mode': r['mode'], 'host': host_team, 'guest': guest_team, 'slots': slots, 'watchers': [],
                         'pool': ps[0]['pool'], 'host_steam': host, 'lobby': None, 'created': time.time(), 'map': la.get('map') or r['map'], 'room': None,
                         'native': True, 'state': 'creating', 'started': None, 'relay': la.get('relay') or '', 'lroom': r['id'], 'unrated': True,
                         'players': {p['steam']: {'name': p.get('name') or 'Player', 'rating': round(p['rating']), 'rsrc': p.get('rsrc', 'ladder'),
                                                  'race': p.get('race'), 'hero': p.get('hero')} for p in ps}}
    la['match'] = mid
    for s in r['slots']: s['gst'] = 'matched'; s['gst_t'] = time.time()
    _watch_in(r)
    log('room %s: match %s made - host %s, %s vs %s, map %s, relay %r' % (r['id'], mid, host, host_team, guest_team, la.get('map'), la.get('relay')))


def _watch_in(r):
    """the room's observers who are in their watch search go into its match (made, not playing yet), as many as it has seats"""
    mid = (r.get('launch') or {}).get('match'); m = L.MM_MATCHES.get(mid) if mid else None
    if not m or m.get('state') == 'playing': return
    for o in r.setdefault('obs', []):
        p = L.MM.get(o['steam'])
        if not p or p.get('lroom') != r['id'] or p['state'] != 'searching' or p['mode'] != L.WATCH: continue
        if len(m['watchers']) >= _obs_cap(r): break
        m['watchers'].append(o['steam']); p.update(state='matched', match=mid, role='watcher')
        m['players'][o['steam']] = {'name': p.get('name') or 'Player', 'watcher': True}
        o['gst'] = 'matched'; o['gst_t'] = time.time()
        log('room %s: observer %s in the match %s' % (r['id'], o['steam'], mid))


def on_watch_join(steam, p, d):
    """a watch search came in (ladder mm/join, mode watch) with "lroom" = a room's id: an observer of that room while it
    launches waits for its match (or goes into it at once). True = taken (the ladder's own watchers do not get him)"""
    rid = str((d or {}).get('lroom') or '')
    if not rid: return False
    r = ROOMS.get(BY.get(steam) or '')
    if not r or r['id'] != rid or not _obs(r, steam) or r['state'] != 'launching':
        L.MM.pop(steam, None)
        L.MM_CANCELLED[steam] = {'by': 'launcher room: not starting a match with this observer', 'match': 'lroom-' + rid, 't': time.time(), 'again': False}
        return True
    p['lroom'] = r['id']; p['pool'] = 'lroom:%s|%s' % (r['id'], p.get('pool') or '')
    o = _obs(r, steam); o['gst'] = 'searching'; o['gst_t'] = time.time()
    log('room %s: observer %s is in the watch search' % (r['id'], steam))
    _watch_in(r); _pub(r)
    return True


def on_match_failed(m, culprits, why):
    """a native match of a room did not come together (the host's room never up, a guest never in, a game gone): no search
    goes on - everybody's is stopped, the room is back to its lobby"""
    r = ROOMS.get(m.get('lroom') or '')
    if r and (r.get('launch') or {}).get('match') == m['id']:
        pl = [s for s in culprits if s in _members(r)]
        if culprits and not pl:                                               # only observers failed: they are out, the match goes on
            for s in culprits:
                if s in m.get('watchers', []): m['watchers'].remove(s)
                m.get('players', {}).pop(s, None); L.MM.pop(s, None)
                o = _obs(r, s)
                if o: o['gst'] = ''
            log('room %s: observers %s not in the match %s (%s) - the players go on' % (r['id'], culprits, m['id'], why)); _pub(r)
            return
        _cancel_launch(r, 'match', pl, why=why); _pub(r)
        return
    L.MM_MATCHES.pop(m['id'], None)                                          # the room is gone meanwhile: just end the searches
    now = time.time()
    for s in m['host'] + m['guest']:
        if L.MM.pop(s, None): L.MM_CANCELLED[s] = {'by': why, 'match': m['id'], 't': now, 'again': False, 'native': True}


def on_search_left(steam, why):
    """a player of a launching room stopped his search (Stop Searching, his game is gone) before the match was made"""
    r = ROOMS.get(BY.get(steam) or '')
    if r and _obs(r, steam):                                                  # an observer: only he is out of this start
        L.MM.pop(steam, None); _obs(r, steam)['gst'] = ''
        log('room %s: observer %s left his watch search (%s)' % (r['id'], steam, why)); _pub(r)
        return
    if r and r['state'] == 'launching':
        _cancel_launch(r, 'left_search', [steam], why=why); _pub(r)


def on_match_room(m, room):
    r = ROOMS.get(m.get('lroom') or '')
    if r and r.get('launch'):
        r['launch']['room'] = room
        for s in r['slots']: s['gst'] = 'room'; s['gst_t'] = time.time()
        _pub(r)


def on_match_started(m):
    r = ROOMS.get(m.get('lroom') or '')
    if r and r.get('launch'):
        r['state'] = 'playing'; r['launch']['started'] = time.time(); r['note'] = None
        for s in r['slots']: s['gst'] = 'playing'; s['gst_t'] = time.time(); s['ready'] = False
        for o in r.setdefault('obs', []): o['gst'] = 'playing' if o['steam'] in m.get('watchers', []) else ''
        log('room %s: match %s started' % (r['id'], m['id'])); _pub(r)


def on_match_over(m):
    r = ROOMS.get(m.get('lroom') or '')
    if r and r['state'] == 'playing' and (r.get('launch') or {}).get('match') == m['id']:
        r['state'] = 'lobby'; r['launch'] = None
        for s in r['slots']:
            if s: s['ready'] = False; s['gst'] = ''
        for o in r.setdefault('obs', []): o['gst'] = ''
        _note(r, 'played'); log('room %s: match %s over - back in the room' % (r['id'], m['id'])); _pub(r)


# ---------- the clock: countdowns, launches that take too long, launchers that are gone ----------
def ticker():
    while True:
        time.sleep(0.5)
        try:
            with L.MM_LOCK: tick(time.time())
        except Exception as e: log('tick: %r' % e)


def tick(now):
    for r in list(ROOMS.values()):
        ch = False
        if r['state'] in ('lobby', 'countdown'):
            gone = [s['steam'] for s in r['slots'] if s and now - s['seen'] > HERE_GONE] + [o['steam'] for o in r.setdefault('obs', []) if now - o['seen'] > HERE_GONE]
            for st in gone: _leave(r, st); _note(r, 'gone', [st]); ch = True
            if r['id'] not in ROOMS: continue
            ch |= _check_ready(r, now)
            if r['state'] == 'countdown' and now >= r['cd']: _launch(r, now); ch = True
        elif r['state'] == 'launching' and not r['launch'].get('match') and now > r['launch']['deadline']:
            late = [s for s in _members(r) if not (L.MM.get(s) or {}).get('lroom') == r['id']]
            _cancel_launch(r, 'late', late, secs=LAUNCH_WAIT); ch = True
        elif r['state'] == 'launching' and r['launch'].get('match') and r['launch']['match'] not in L.MM_MATCHES and r['launch']['match'] not in L.MM_PLAYING:
            _cancel_launch(r, 'match'); ch = True                                # dropped by the ladder some other way
        elif r['state'] == 'playing' and all(now - s['seen'] > 900 for s in r['slots'] if s):   # every launcher gone for 15 min
            _close(r, 'gone while playing'); continue
        elif r['state'] == 'playing' and now - r['launch'].get('started', now) > PLAY_KEEP:
            r['state'] = 'lobby'; r['launch'] = None; _note(r, 'played'); ch = True
        if not _members(r) and r['id'] in ROOMS: _close(r, 'empty'); continue
        if ch: _pub(r)
    for k in [k for k, t in KICKED.items() if t < now]: KICKED.pop(k, None)
    for k in [k for k, t in INVITED.items() if t < now]: INVITED.pop(k, None)
    for k in [k for k, ts in INV_SENT.items() if not ts or now - ts[-1] > 60]: INV_SENT.pop(k, None)


# ---------- the launcher's calls ----------
def _leave(r, steam):
    for i, s in enumerate(r['slots']):
        if s and s['steam'] == steam: r['slots'][i] = None
    r['obs'] = [o for o in r.setdefault('obs', []) if o['steam'] != steam]
    r['pings'].pop(steam, None)
    INVITED.pop((r['id'], steam), None)                                   # 1.5.8: left or removed - he can be invited again at once
    if BY.get(steam) == r['id']: BY.pop(steam, None)
    if r['owner'] == steam and _members(r): r['owner'] = _members(r)[0]
    if r['state'] == 'countdown': r['state'] = 'lobby'


def _seat(r, steam, slot=None):
    free = [i for i, s in enumerate(r['slots']) if not s]
    if slot is not None and slot in free: i = slot
    else:                                                                       # the team with fewer players first
        n = _size(r); a = sum(1 for s in r['slots'][:n] if s); b = sum(1 for s in r['slots'][n:] if s)
        free.sort(key=lambda i: ((a if i < n else b), i)); i = free[0]
    r['slots'][i] = {'steam': steam, 'race': 'random', 'hero': -1, 'ready': False, 'seen': time.time(), 'gst': ''}
    BY[steam] = r['id']
    return i


def _army(r, d):
    races = _races(r['game'])
    race = str(d.get('race') or 'random')
    if race != 'random' and race not in races: return None
    try: hero = int(d.get('hero', -1))
    except Exception: hero = -1
    if race == 'random': hero = -1
    elif not -1 <= hero < races[race]['heroes']: hero = -1
    return race, hero


def _resize(r, mode):
    """another mode: the slots for it, the players kept in their teams as far as they fit"""
    n = L.TEAM_N[mode]; old_n = _size(r)
    t0 = [s for s in r['slots'][:old_n] if s]; t1 = [s for s in r['slots'][old_n:] if s]
    if len(t0) + len(t1) > 2 * n: return False
    while len(t0) > n: t1.append(t0.pop())
    while len(t1) > n: t0.append(t1.pop())
    r['slots'] = t0 + [None] * (n - len(t0)) + t1 + [None] * (n - len(t1)); r['mode'] = mode
    return True


def api(verb, steam, d):
    """one call of a signed-in launcher; returns the answer (the room's view when it changed). Under MM_LOCK."""
    now = time.time(); rid = BY.get(steam); r = ROOMS.get(rid or '')
    if verb == 'create':
        game = 'vanilla' if d.get('game') == 'vanilla' else 'elite'
        mode = d.get('mode') if d.get('mode') in L.MODES else '1v1'
        if r and r['state'] not in ('lobby', 'countdown'): return {'ok': False, 'error': 'busy'}
        if r: _leave(r, steam); _note(r, 'left', [steam]); (_pub(r) if _members(r) else _close(r, 'empty'))
        if len(ROOMS) >= MAX_ROOMS: return {'ok': False, 'error': 'too_many'}
        maps = _maps(game, mode); mp = d.get('map') if d.get('map') in maps else (maps[0] if maps else '')
        name = _clean(d.get('name'), NAME_MAX) or ('%s: %s' % (_name(steam), mode))
        r = {'id': _new_id(), 'name': name, 'game': game, 'ver': _clean(d.get('ver'), 24) or '', 'mode': mode, 'map': mp, 'owner': steam,
             'state': 'lobby', 'slots': [None] * (2 * L.TEAM_N[mode]), 'cd': 0, 'launch': None, 'note': None, 'pings': {}, 'seq': 0, 'created': now,
             'maps': [mp] if mp else [], 'opts': _opts_clean(d.get('opts') or {}, game), 'hs': d.get('start') == 'host', 'obs': []}
        ROOMS[r['id']] = r; _seat(r, steam, 0)
        log('room %s made by %s (%s %s %s, %s)' % (r['id'], steam, game, r['ver'], mode, mp))
        _pub(r); return {'ok': True, 'room': view(r)}
    if verb == 'join':                                                      # 'as': 'obs' - an observer seat (1.5.3)
        t = ROOMS.get(str(d.get('id') or ''))
        if not t: return {'ok': False, 'error': 'no_room'}
        if r is t: (_slot(t, steam) or _obs(t, steam))['seen'] = now; return {'ok': True, 'room': view(t)}
        if r and r['state'] not in ('lobby', 'countdown'): return {'ok': False, 'error': 'busy'}
        if KICKED.get((t['id'], steam), 0) > now: return {'ok': False, 'error': 'kicked', 'left': int(KICKED[(t['id'], steam)] - now)}
        if t['state'] not in ('lobby', 'countdown'): return {'ok': False, 'error': 'state'}
        if d.get('as') == 'obs':
            if len(t.setdefault('obs', [])) >= _obs_cap(t): return {'ok': False, 'error': 'obs_full'}
            if r: _leave(r, steam); _note(r, 'left', [steam]); (_pub(r) if _members(r) else _close(r, 'empty'))
            t['obs'].append({'steam': steam, 'seen': now, 'gst': ''}); BY[steam] = t['id']; _note(t, 'joined_obs', [steam]); INVITED.pop((t['id'], steam), None)
            _pub(t); return {'ok': True, 'room': view(t)}
        if all(t['slots']): return {'ok': False, 'error': 'full'}
        if r: _leave(r, steam); _note(r, 'left', [steam]); (_pub(r) if _members(r) else _close(r, 'empty'))
        _seat(t, steam); _unready(t, 'joined', [steam]); _note(t, 'joined', [steam]); INVITED.pop((t['id'], steam), None)
        _pub(t); return {'ok': True, 'room': view(t)}
    if not r: return {'ok': False, 'error': 'no_room'}
    me = _slot(r, steam); ob = None if me else _obs(r, steam)
    if not me and not ob: BY.pop(steam, None); return {'ok': False, 'error': 'no_room'}
    (me or ob)['seen'] = now
    if verb == 'here':                                                      # the launcher's heartbeat (every 15 s while in the room)
        return {'ok': True, 'seq': r['seq']}
    if verb == 'get': return {'ok': True, 'room': view(r)}
    if verb == 'ticket':                                                    # what MMFind needs, only for the player himself
        la = r.get('launch')
        if r['state'] != 'launching' or not la: return {'ok': False, 'error': 'state'}
        if ob:                                                              # an observer: MMFind's Watch with the room's id
            return {'ok': True, 'ticket': {'room': r['id'], 'game': r['game'], 'ver': r['ver'], 'mode': r['mode'], 'map': la.get('map') or r['map'],
                                           'watch': True, 'deadline': int(la['deadline']), 'relay': la.get('relay') or '', 'ttl': max(0, int(la['deadline'] - now))}}
        races = _races(r['game']); hero = la['heroes'].get(steam, -1)
        return {'ok': True, 'ticket': {'room': r['id'], 'game': r['game'], 'ver': r['ver'], 'mode': r['mode'], 'map': la.get('map') or r['map'],
                                       'opts': _opt_values(r) if la['host'] == steam else {},
                                       'race': me['race'], 'race_ui': -1 if me['race'] == 'random' else races.get(me['race'], {}).get('ui', -1),
                                       'hero': hero, 'host': la['host'] == steam, 'deadline': int(la['deadline']), 'relay': la.get('relay') or '',
                                       'ttl': max(0, int(la['deadline'] - now))}}     # 0.48: how long the game may still take to search
    if verb == 'game':                                                      # what his game does now (the launcher hears it from MMFind)
        ev = _clean(d.get('ev'), 24) or ''
        if ob:                                                              # an observer's game: told, never calls the start off
            if r['state'] == 'launching': ob['gst'] = ev; ob['gst_t'] = now; _pub(r)
            return {'ok': True}
        if r['state'] == 'launching':
            me['gst'] = ev; me['gst_t'] = now
            if ev == 'failed':
                why = _clean(d.get('reason'), 40) or 'error'
                _cancel_launch(r, 'game_failed', [steam], why=why)
        _pub(r); return {'ok': True}
    if verb == 'pings':                                                     # his launcher's measurements of our servers
        p = {}
        for ip, ms in list((d.get('pings') or {}).items())[:8]:
            try: ms = int(ms)
            except Exception: continue
            if ip in L.relay_order(): p[ip] = max(-1, min(5000, ms))
        raw = {}
        for ip, x in list((d.get('raw') or {}).items())[:8]:
            if ip in L.relay_order() and isinstance(x, dict):
                try: ms = int(x.get('ms')) if x.get('ms') is not None else None
                except Exception: ms = None
                raw[ip] = {'ms': ms, 'ok': bool(x.get('ok'))}
        r['pings'][steam] = {'p': p, 'raw': raw, 'chain': bool(d.get('chain')), 't': now}
        _pub(r); return {'ok': True}
    if verb == 'leave':
        if ob:                                                              # an observer: the room goes on as it is
            if (L.MM.get(steam) or {}).get('lroom') == r['id']: L.MM.pop(steam, None)
            m = L.MM_MATCHES.get((r.get('launch') or {}).get('match') or '')
            if m and steam in m.get('watchers', []): m['watchers'].remove(steam); m.get('players', {}).pop(steam, None)
            _leave(r, steam); _note(r, 'left', [steam]); _pub(r); return {'ok': True}
        if r['state'] == 'launching': _cancel_launch(r, 'left', [steam])
        elif r['state'] == 'playing': pass                                  # the match goes on; he just leaves the room
        _leave(r, steam); _note(r, 'left', [steam])
        if _members(r): _pub(r)
        else: _close(r, 'empty')
        return {'ok': True}
    if verb == 'invite':                                                    # 1.5.3: anybody in the room invites a player (his stream)
        t = str(d.get('steam') or '')
        if not re.fullmatch(r'\d{1,20}', t) or t == steam or t in _everyone(r): return {'ok': False, 'error': 'bad'}   # a SteamID only
        if r['state'] not in ('lobby', 'countdown'): return {'ok': False, 'error': 'state'}
        if INVITED.get((r['id'], t), 0) > now: return {'ok': True, 'again': True}   # invited a moment ago: once is enough
        sent = [x for x in INV_SENT.get(steam, []) if now - x < 60]
        if len(sent) >= INVITE_MAX: INV_SENT[steam] = sent; return {'ok': False, 'error': 'too_soon'}   # no flood of invitations
        INV_SENT[steam] = sent + [now]; INVITED[(r['id'], t)] = now + INVITE_GAP
        cat = L._catalog()
        try: L.stream.publish('lroom_invite', {'id': r['id'], 'name': r['name'], 'mode': r['mode'], 'map': r['map'],
                                               'map_name': (cat.get(r['map']) or {}).get('name') or r['map'], 'game': r['game'], 'ver': r['ver'],
                                               'from': steam, 'from_name': _name(steam), 'players': len(_members(r)), 'cap': len(r['slots']),
                                               'ttl': INVITE_TTL}, to=t)
        except Exception as e: log('invite %s -> %s: %r' % (r['id'], t, e))
        log('room %s: %s invites %s' % (r['id'], steam, t)); return {'ok': True}
    if verb == 'ping':                                                      # 1.5.3: the owner's ready check / a player calls the owner
        kind = d.get('kind')
        if r['state'] != 'lobby': return {'ok': False, 'error': 'state'}
        if kind == 'ready':
            if steam != r['owner']: return {'ok': False, 'error': 'owner'}
            to = [s['steam'] for s in r['slots'] if s and s['steam'] != steam and not s['ready']]
        elif kind == 'start':
            if not me or steam == r['owner']: return {'ok': False, 'error': 'bad'}
            if not (r.get('hs') and _others_ready(r, now)): return {'ok': False, 'error': 'not_ready'}   # 1.5.8: the owner's own tick does not matter
            to = [r['owner']]
        else: return {'ok': False, 'error': 'bad'}
        if not to: return {'ok': False, 'error': 'bad'}
        pg = r.setdefault('ping', {})
        if (pg.get(kind) or {}).get('until', 0) > now: return {'ok': False, 'error': 'too_soon', 'room': view(r)}   # another player was first
        pg[kind] = {'t': now, 'until': now + PING_GAP, 'from': steam, 'to': to, 'ans': {}}
        for t in to:
            try: L.stream.publish('lroom_ping', {'kind': kind, 'id': r['id'], 'name': r['name'], 'from': steam, 'from_name': _name(steam), 'ttl': PING_TTL}, to=t)
            except Exception as e: log('ping %s -> %s: %r' % (r['id'], t, e))
        log('room %s: %s pings %s (%s)' % (r['id'], steam, ','.join(to), kind))
        _pub(r); return {'ok': True, 'n': len(to), 'room': view(r)}
    if verb == 'ping_answer':                                               # 1.5.8: the pinged player's yes / no, shown to the room
        kind, ans = d.get('kind'), d.get('ans')
        p = (r.get('ping') or {}).get(kind)
        if ans not in ('yes', 'no') or not p or steam not in p['to'] or now - p['t'] > PING_TTL + 5: return {'ok': False, 'error': 'bad'}
        if steam in p['ans']: return {'ok': True}
        p['ans'][steam] = {'a': ans, 't': now}
        log('room %s: %s answers %s (%s)' % (r['id'], steam, ans, kind)); _pub(r); return {'ok': True}
    if ob and verb in ('cancel', 'ready', 'army'): return {'ok': False, 'error': 'obs'}   # an observer has no army and no say in the start
    if verb == 'cancel':                                                    # stop the launch (any player, as Cancel on the game's countdown)
        if r['state'] == 'countdown': me['ready'] = False; r['state'] = 'lobby'; _note(r, 'unready', [steam])
        elif r['state'] == 'launching': _cancel_launch(r, 'cancel', [steam])
        else: return {'ok': False, 'error': 'state'}
        _pub(r); return {'ok': True, 'room': view(r)}
    if r['state'] not in ('lobby', 'countdown'): return {'ok': False, 'error': 'state'}
    if verb == 'ready':
        on = bool(d.get('on'))
        if me['ready'] == on: return {'ok': True, 'room': view(r)}
        me['ready'] = on
        if not on and r['state'] == 'countdown': r['state'] = 'lobby'; _note(r, 'unready', [steam])
        _check_ready(r, now); _pub(r); return {'ok': True, 'room': view(r)}
    if verb == 'army':
        a = _army(r, d)
        if not a: return {'ok': False, 'error': 'bad'}
        if (me['race'], me['hero']) != a:
            me['race'], me['hero'] = a; me['ready'] = False
            if r['state'] == 'countdown': r['state'] = 'lobby'; _note(r, 'changed', [steam])
            _pub(r)
        return {'ok': True, 'room': view(r)}
    if verb == 'seat':
        try: i = int(d.get('slot'))
        except Exception: return {'ok': False, 'error': 'bad'}
        if not 0 <= i < len(r['slots']) or r['slots'][i]: return {'ok': False, 'error': 'taken'}
        if ob:                                                              # an observer sits down: a player now
            r['obs'] = [o for o in r['obs'] if o['steam'] != steam]
            r['slots'][i] = {'steam': steam, 'race': 'random', 'hero': -1, 'ready': False, 'seen': now, 'gst': ''}
            _unready(r, 'joined', [steam]); _note(r, 'joined', [steam]); _pub(r); return {'ok': True, 'room': view(r)}
        j = r['slots'].index(me); r['slots'][i], r['slots'][j] = me, None; me['ready'] = False
        if r['state'] == 'countdown': r['state'] = 'lobby'; _note(r, 'changed', [steam])
        _pub(r); return {'ok': True, 'room': view(r)}
    # the owner's settings: any change of them makes everybody ready again by hand (as the game's lobby)
    if steam != r['owner']: return {'ok': False, 'error': 'owner'}
    if verb == 'start':                                                     # the owner's Play: everybody ready - the countdown
        if r['state'] == 'countdown': return {'ok': True, 'room': view(r)}
        if _others_ready(r, now): me['ready'] = True                       # 1.5.8: his Start is his "ready" too
        if not _all_ready(r, now): return {'ok': False, 'error': 'not_ready'}
        r['state'] = 'countdown'; r['cd'] = now + CD; r['note'] = None; log('room %s: countdown (owner)' % r['id'])
        _pub(r); return {'ok': True, 'room': view(r)}
    if verb == 'stop':                                                      # the owner's Play again during the countdown
        if r['state'] != 'countdown': return {'ok': False, 'error': 'state'}
        r['state'] = 'lobby'; _note(r, 'cd_stop', [steam]); _pub(r); return {'ok': True, 'room': view(r)}
    if verb == 'kick':
        t = str(d.get('steam') or '')
        if t == steam or not (_slot(r, t) or _obs(r, t)): return {'ok': False, 'error': 'bad'}
        was_obs = not _slot(r, t)
        _leave(r, t)
        if KICK_BAN > 0: KICKED[(r['id'], t)] = now + KICK_BAN
        if not was_obs: _unready(r)
        _note(r, 'kicked', [t])
        try: L.stream.publish('lroom_kicked', {'id': r['id'], 'steam': t, 'name': r['name'], 'left': KICK_BAN}, to=t)
        except Exception: pass
        _pub(r); return {'ok': True, 'room': view(r)}
    if verb == 'conf':
        changed = False
        if d.get('mode') in L.MODES and d['mode'] != r['mode']:
            if not _resize(r, d['mode']): return {'ok': False, 'error': 'too_many_players'}
            maps = _maps(r['game'], r['mode'])
            r['maps'] = [k for k in r['maps'] if k in maps]
            if not r['maps']: r['maps'] = [random.choice(maps)] if maps else []
            r['map'] = r['maps'][0] if r['maps'] else ''
            changed = True
        if d.get('map') and d['map'] != r['map'] and not d.get('maps'):        # one map
            if d['map'] not in _maps(r['game'], r['mode']): return {'ok': False, 'error': 'bad_map'}
            r['map'] = d['map']; r['maps'] = [d['map']]; changed = True
        if isinstance(d.get('maps'), list):                                    # one or more: the match takes one at random
            ok = set(_maps(r['game'], r['mode'])); ms = []
            for k in d['maps'][:200]:
                if k in ok and k not in ms: ms.append(k)
            if not ms: return {'ok': False, 'error': 'bad_map'}
            if ms != r['maps']: r['maps'] = ms; r['map'] = d['map'] if d.get('map') in ms else ms[0]; changed = True
        if isinstance(d.get('opts'), dict):
            o = _opts_clean(dict(r['opts'], **d['opts']), r['game'])
            if o != r['opts']: r['opts'] = o; changed = True
        nm = _clean(d.get('name'), NAME_MAX)
        if nm and nm != r['name']: r['name'] = nm; changed = True
        v = _clean(d.get('ver'), 24)
        if v and r['game'] == 'elite' and v != r['ver']: r['ver'] = v; changed = True
        if changed: _unready(r, 'conf'); _note(r, 'conf', [steam]); _pub(r)
        return {'ok': True, 'room': view(r)}
    return {'ok': False, 'error': 'unknown'}


def listing():
    return {'rooms': [summary(r) for r in sorted(ROOMS.values(), key=lambda r: r['created'])], 'now': int(time.time())}


def catalog(game, mode):
    """what a room of this game and mode may have: the maps (key, name, players) and the races with their heroes"""
    cat = L._catalog(); game = 'vanilla' if game == 'vanilla' else 'elite'
    out = {}
    for md in L.MODES:
        out[md] = [{'key': k, 'name': (cat.get(k) or {}).get('name') or k} for k in _maps(game, md)]
    return {'game': game, 'maps': out, 'races': {k: v['heroes'] for k, v in _races(game).items()},
            'heroes': {k: v.get('names') or [] for k, v in _races(game).items()},
            'race_order': [k for k in (VAN_RACES if game == 'vanilla' else ELITE_ORDER) if k in _races(game)],
            'opts': {'win': [k for k in OPT_WIN if game != 'vanilla' or k in ('vpc', 'annihilate')], 'vp': sorted(OPT_VP), 'start': ['fixed', 'random'],
                     'res': ['standard', 'high'], 'default': OPT_DEFAULT}}


def launching_member(room, steam, watch=False):
    """MMFind asks before it searches for a room (mm/native with "room"): is that room starting a match with him in it now.
    An observer only for a watch search ("watch": true - an older MMFind would search as a player with his ticket)"""
    r = ROOMS.get(str(room))
    if not r or r['state'] != 'launching': return False
    if watch: return bool(_obs(r, steam))
    return steam in _members(r) and not (r.get('launch') or {}).get('match')
