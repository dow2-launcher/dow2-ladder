#!/usr/bin/env python3
# 17.11.2026 (SirItos, PR #28 and its review): (1) the countdown of a launcher room is 5 s (CD, the view's cd_end); (2) a room is
# closed only once its match has really started: ladder nm_started (the start message to every game) AND every seated player's game
# loading it - MMFind's "loading" through his launcher (verb game) or its mm/alive to the match; then it is gone from ROOMS / the
# list / c/live "lrooms", "lroom_gone" with why "started", its players and observers free (BY) - each may make or join another room
# at once; the running match keeps its "lroom" for the launcher's Running matches (c/live "ingame"); its end changes nothing;
# (3) anything that goes wrong before that - before or after nm_started - puts everybody back in the room's lobby, as before.
# usage: python3 ladder/tests/test_lroom_close_on_start.py [<repo dir>]   (temp copies, empty data dirs; nothing live)
import os, shutil, sys, tempfile, time
REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
T = tempfile.mkdtemp(prefix='ladder_lrclose_')
shutil.copytree(REPO + '/ladder', T + '/app', ignore=shutil.ignore_patterns('__pycache__', '*.bak*', 'tests'))
os.makedirs(T + '/data'); sys.path.insert(0, T + '/app'); os.environ['LADDER_NO_CRAWL'] = '1'
import ladder as L
R = L.lroom
fails = []
def check(name, got, want):
    ok = got == want
    print('  %-84s %s' % (name, 'ok' if ok else 'FAIL: got %r, want %r' % (got, want)))
    if not ok: fails.append(name)
A, B, C = '76561190000000401', '76561190000000402', '76561190000000409'
pub = []
R._pub = lambda r: None
L.stream.publish = lambda ev, d, to=None: pub.append((ev, d))
L.live.register = lambda m: None


def room(obs=True):
    R.ROOMS.clear(); R.BY.clear(); L.MM.clear(); L.MM_MATCHES.clear(); L.MM_PLAYING.clear(); L.MM_CANCELLED.clear(); pub.clear()
    v = R.api('create', A, {'game': 'elite', 'ver': '3.2', 'mode': '1v1', 'map': '2p_calderisdunes', 'name': 'close test'}); rid = v['room']['id']
    R.api('join', B, {'id': rid})
    if obs: R.api('join', C, {'id': rid, 'as': 'obs'})
    R.api('army', A, {'race': 'orks', 'hero': 1}); R.api('army', B, {'race': 'eldar', 'hero': 0})
    R.api('ready', A, {'on': True}); R.api('ready', B, {'on': True})
    r = R.ROOMS[rid]
    if r['state'] == 'lobby': R.api('start', A, {})
    return rid, r


def launched(obs=True, game_room='2000000501'):
    rid, r = room(obs)
    R.tick(r['cd'] + 0.1)
    host = r['launch']['host']
    for s, pid, race in ((A, 41, L.RACE_KEYS.index('orks')), (B, 42, L.RACE_KEYS.index('eldar'))):
        L.NM_HINTS[s] = {'t': time.time(), 'd': {'room': rid}}
        L.nm_join({'steam': s, 'mode': '1v1', 'race': race, 'pid': pid, 'key': 'k', 'game': 'elite'})
    mid = r['launch']['match']
    L.nm_room({'steam': host, 'room': game_room}); L.nm_joined({'steam': A if host == B else B, 'room': game_room})
    return rid, r, host, mid


print('(1) the countdown: 5 s')
check('CD', R.CD, 5)
rid, r = room()
check('the room counts down', r['state'], 'countdown')
check('its end 5 s on (the view\'s cd_end too)', (round(r['cd'] - time.time()), R.view(r)['cd_end'] == int(r['cd'] * 1000)), (5, True))
R.tick(r['cd'] - 1)
check('1 s before its end: still the countdown', r['state'], 'countdown')
R.tick(r['cd'] + 0.1)
check('at its end: the launch', r['state'], 'launching')

print('(2) the start: closed only when every game loads the match')
rid, r, host, mid = launched()
check('the match is made from the room', (bool(mid), L.MM_MATCHES[mid]['lroom']), (True, rid))
pub.clear()
L.nm_started({'room': '2000000501'})
check('nm_started alone: the room stays, launching, in the list', (rid in R.ROOMS, r['state'], [x['id'] for x in R.listing()['rooms']]), (True, 'launching', [rid]))
check('  ... the launch says it started', bool(r['launch'].get('started')) and R.view(r)['launch']['started'] > 0, True)
check('  ... no "lroom_gone" yet', [d for ev, d in pub if ev == 'lroom_gone'], [])
R.api('game', A, {'ev': 'loading'})
check('one game loading: still open', (rid in R.ROOMS, r['state']), (True, 'launching'))
R.api('game', B, {'ev': 'loading'})
check('every game loading: the room is gone', rid in R.ROOMS, False)
check('the list is empty', R.listing()['rooms'], [])
check('c/live: no launcher rooms', L.live_view()['lrooms'], [])
check('"lroom_gone" with why "started"', [d for ev, d in pub if ev == 'lroom_gone'], [{'id': rid, 'why': 'started'}])
check('nobody is in a room any more (players and the observer)', [s for s in (A, B, C) if s in R.BY], [])
check('the room\'s calls say no_room (his launcher drops it)', (R.api('get', A, {}), R.api('here', C, {})), ({'ok': False, 'error': 'no_room'},) * 2)
check('a game\'s later event changes nothing', R.api('game', B, {'ev': 'loading'}), {'ok': False, 'error': 'no_room'})
check('the match runs on, it still says its room (Running matches)', (mid in L.MM_PLAYING, L.MM_PLAYING[mid].get('lroom')), (True, rid))
check('c/live ingame: the match with "lroom"', [m.get('lroom') for m in L.live_view()['ingame']], [rid])
v = R.api('create', A, {'game': 'elite', 'ver': '3.2', 'mode': '1v1', 'map': '2p_calderisdunes', 'name': 'next'})
check('a player makes another room at once', (v['ok'], v['room']['state']), (True, 'lobby'))
check('the other one joins it at once', R.api('join', B, {'id': v['room']['id']})['ok'], True)
check('the observer joins it at once', R.api('join', C, {'id': v['room']['id'], 'as': 'obs'})['ok'], True)
nid = v['room']['id']
L.mm_ended(A)
check('the match\'s end: the old room is not back', (rid in R.ROOMS, mid in L.MM_PLAYING), (False, False))
check('  ... the new room as it was', (R.ROOMS[nid]['state'], R.ROOMS[nid]['note'] and R.ROOMS[nid]['note'].get('k')), ('lobby', 'joined_obs'))

print('   "loading" before nm_started (own_lobby tells the ladder in the background): closed at nm_started')
rid, r, host, mid = launched(obs=False, game_room='2000000502')
R.api('game', A, {'ev': 'loading'}); R.api('game', B, {'ev': 'loading'})
check('loading before the start: still launching', (rid in R.ROOMS, r['state']), (True, 'launching'))
L.nm_started({'room': '2000000502'})
check('nm_started: closed, both free', (rid in R.ROOMS, A in R.BY, B in R.BY), (False, False, False))

print('   the games\' own mm/alive counts (no launcher report)')
rid, r, host, mid = launched(game_room='2000000504')
L.nm_started({'room': '2000000504'})
L.mm_alive(A); R.tick(time.time())
check('one alive: still open', (rid in R.ROOMS, r['state']), (True, 'launching'))
L.mm_alive(B); R.tick(time.time())
check('both alive: closed on the tick', rid in R.ROOMS, False)

print('(3) wrong before the start is confirmed: everybody back in the room\'s lobby')
rid, r, host, mid = launched(game_room='2000000503')
L.nm_fail({'match': mid, 'culprits': [B], 'why': 'guest never joined'})
check('the match failed before nm_started: back to its lobby, kept', (rid in R.ROOMS, r['state'], (r['note'] or {}).get('k')), (True, 'lobby', 'match'))
check('everybody still in it', [s for s in (A, B, C) if R.BY.get(s) == rid], [A, B, C])
rid, r = room()
R.tick(r['cd'] + 0.1); R.api('cancel', B, {})
check('a player\'s Cancel while launching: back to its lobby', (rid in R.ROOMS, r['state']), (True, 'lobby'))

def started(game_room):
    rid, r, host, mid = launched(game_room=game_room); L.nm_started({'room': game_room}); return rid, r, host, mid
rid, r, host, mid = started('2000000505'); R.api('game', A, {'ev': 'loading'})
R.api('game', B, {'ev': 'failed', 'reason': 'busy_match'})
check('after nm_started, a game fails: lobby, kept, all in it', (rid in R.ROOMS, r['state'], (r['note'] or {}).get('k'), [s for s in (A, B, C) if R.BY.get(s) == rid]), (True, 'lobby', 'game_failed', [A, B, C]))
rid, r, host, mid = started('2000000506'); R.api('cancel', A, {})
check('after nm_started, a Cancel: lobby, kept', (rid in R.ROOMS, r['state'], (r['note'] or {}).get('k')), (True, 'lobby', 'cancel'))
rid, r, host, mid = started('2000000507'); R.api('game', A, {'ev': 'loading'})
R.tick(r['launch']['started'] + R.START_CONFIRM - 1)
check('after nm_started, %d s without B loading: still waiting' % (R.START_CONFIRM - 1), (rid in R.ROOMS, r['state']), (True, 'launching'))
R.tick(r['launch']['started'] + R.START_CONFIRM + 1)
check('  ... past START_CONFIRM: lobby, kept, B named', (rid in R.ROOMS, r['state'], (r['note'] or {}).get('k'), len(r['note']['who'])), (True, 'lobby', 'match', 1))
check('  ... all still in it, nobody ready', ([s for s in (A, B, C) if R.BY.get(s) == rid], any(s['ready'] for s in r['slots'])), ([A, B, C], False))
rid, r, host, mid = started('2000000508'); R.api('game', A, {'ev': 'loading'})
L.mm_ended(B)
check('after nm_started, the match over before B loaded: lobby, kept', (rid in R.ROOMS, r['state'], (r['note'] or {}).get('k')), (True, 'lobby', 'match'))
rid, r, host, mid = started('2000000509'); L.MM_PLAYING.pop(mid, None); R.tick(time.time())
check('after nm_started, the match gone from the ladder: lobby, kept', (rid in R.ROOMS, r['state']), (True, 'lobby'))
rid, r, host, mid = started('2000000510'); R.api('leave', B, {})
check('after nm_started, a player leaves: lobby, the room kept for the others', (rid in R.ROOMS, r['state'], R.BY.get(A) == rid), (True, 'lobby', True))
v = R.api('ready', A, {'on': True})
check('the room works on: ready again', v['ok'], True)

print('FAILED: %s' % fails if fails else 'all ok'); shutil.rmtree(T, ignore_errors=True); sys.exit(1 if fails else 0)
