#!/usr/bin/env python3
# 14.11.2026 (siritos fb 1062): (1) the pre-ticket of a launcher room's countdown (verb ticket while "countdown": go_at = the
# countdown's end, the hero rolled once and the same in the launch); (2) observers through the native automatch (MMFind 0.51
# RoomObservers=1, data/lroom_obs_native.on): the observer's native search is a watcher of the room's match (team 2, his own pid in
# his list, never in the players'), the host's ticket says "obs"; a failed observer never calls the players' start off; without the
# flag file his search ends ("off on the server"); (3) own_lobby: an observer is refused once every player is in, and sent out
# (AutomatchStopPollingMessage) when every player is in and the room has not started in NM_OBS_GRACE s.
# usage: python3 ladder/tests/test_lroom_goat_obs.py [<repo dir>]   (temp copies, empty data dirs; nothing live)
import os, shutil, sys, tempfile, time
REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
T = tempfile.mkdtemp(prefix='ladder_goat_')
shutil.copytree(REPO + '/ladder', T + '/app', ignore=shutil.ignore_patterns('__pycache__', '*.bak*', 'tests'))
os.makedirs(T + '/data'); sys.path.insert(0, T + '/app'); os.environ['LADDER_NO_CRAWL'] = '1'
import ladder as L
R = L.lroom
fails = []
def check(name, got, want):
    ok = got == want
    print('  %-84s %s' % (name, 'ok' if ok else 'FAIL: got %r, want %r' % (got, want)))
    if not ok: fails.append(name)
A, B, C = '76561190000000301', '76561190000000302', '76561190000000309'
R._pub = lambda r: None
def room_with_obs(hero_a=None):
    R.ROOMS.clear(); R.BY.clear(); L.MM.clear(); L.MM_MATCHES.clear(); L.MM_CANCELLED.clear()
    v = R.api('create', A, {'game': 'elite', 'ver': '3.2', 'mode': '1v1', 'map': '2p_calderisdunes', 'name': 'test'}); rid = v['room']['id']
    R.api('join', B, {'id': rid}); R.api('join', C, {'id': rid, 'as': 'obs'})
    R.api('army', A, {'race': 'orks', 'hero': hero_a}); R.api('army', B, {'race': 'eldar', 'hero': 0})
    R.api('ready', A, {'on': True}); R.api('ready', B, {'on': True})
    r = R.ROOMS[rid]
    if r['state'] == 'lobby': R.api('start', A, {})
    return rid, r

print('(1) the pre-ticket of the countdown')
rid, r = room_with_obs(hero_a=None)
check('the room counts down', r['state'], 'countdown')
ta = R.api('ticket', A, {}); tc = R.api('ticket', C, {})
check('a player gets a pre-ticket', (ta['ok'], ta['ticket'].get('pre'), ta['ticket']['go_at']), (True, True, int(r['cd'] * 1000)))
check('its army (orks = ui 3, a hero rolled 0..2)', (ta['ticket']['race_ui'], ta['ticket']['hero'] in (0, 1, 2)), (R._races('elite')['orks']['ui'], True))
check('no host in it, the room\'s options for everybody (the host not known yet)', ('host' in ta['ticket'], ta['ticket']['opts'] == R._opt_values(r)), (False, True))
check('obs 0 without the flag', ta['ticket']['obs'], 0)
check('an observer gets one too (watch)', (tc['ok'], tc['ticket'].get('watch'), tc['ticket']['go_at']), (True, True, int(r['cd'] * 1000)))
hero = ta['ticket']['hero']
check('asked again: the same hero', R.api('ticket', A, {})['ticket']['hero'], hero)
R.tick(r['cd'] + 0.1)
check('the launch', r['state'], 'launching')
tf = R.api('ticket', A, {})['ticket']
check('the final ticket keeps the pre-ticket hero', tf['hero'], hero)
check('no observer seats in the host ticket without the flag', (tf['host'], tf['obs']) if tf['host'] else (True, R.api('ticket', B, {})['ticket']['obs']), (True, 0))

print('   a game a little early (go_at by its own clock): the launch now, not a refusal')
rid, r = room_with_obs(hero_a=1); r['cd'] = time.time() + 1.0
check('1 s before the countdown ends: A may search for the room', R.launching_member(rid, A), True)
check('  ... the room launched', r['state'], 'launching')
rid, r = room_with_obs(hero_a=1); r['cd'] = time.time() + 5.0
check('5 s before: no', (R.launching_member(rid, A), r['state']), (False, 'countdown'))

print('(2) an observer through the native automatch')
def launch_and_search(flag, seats=2, old=None):
    if flag: open(T + '/data/lroom_obs_native.on', 'w').close()
    elif os.path.exists(T + '/data/lroom_obs_native.on'): os.remove(T + '/data/lroom_obs_native.on')
    rid, r = room_with_obs(hero_a=1); R.tick(r['cd'] + 0.1)
    host = r['launch']['host']
    for s, pid, race in ((A, 31, L.RACE_KEYS.index('orks')), (B, 32, L.RACE_KEYS.index('eldar'))):
        L.NM_HINTS[s] = {'t': time.time(), 'd': dict({'room': rid}, **({'obs_seats': seats} if seats and s != old else {}))}   # MMFind 0.53 (16.11)
        L.nm_join({'steam': s, 'mode': '1v1', 'race': race, 'pid': pid, 'key': 'k', 'game': 'elite'})
    L.NM_HINTS[C] = {'t': time.time(), 'd': dict({'room': rid, 'watch': True}, **({'obs_seats': 2} if seats else {}))}
    v = L.nm_join({'steam': C, 'mode': '1v1', 'race': 0, 'pid': 39, 'key': 'k', 'game': 'elite'})
    return rid, r, host, v
rid, r, host, v = launch_and_search(False)
check('flag off: the observer\'s native search ends', (v.get('state'), 'off on the server' in (v.get('by') or '')), ('cancelled', True))
check('flag off: the players\' match is made all the same', bool(r['launch'].get('match')), True)
rid, r, host, v = launch_and_search(True)
mid = r['launch']['match']; m = L.MM_MATCHES[mid]
check('flag on: the match is made', bool(mid), True)
check('the observer is its watcher', (m['watchers'], L.MM[C]['role']), ([C], 'watcher'))
vc = L._nm_view(L.MM[C]); vh = L._nm_view(L.MM[host])
check('his view: team 2 of 2, size 1, his pid in his list', (vc['team'], vc['teams'], vc['size'], 39 in vc['pids']), (2, 2, 1, True))
check('the host\'s list: players only', sorted(vh['pids']), [31, 32])
check('the host\'s view names the watcher', vh['watchers'], [C])
th = R.api('ticket', host, {})['ticket']
check('the host\'s ticket: obs 1', (th['host'], th['obs']), (True, 1))
rid, r, host, v = launch_and_search(True, seats=0)
mid = r['launch'].get('match')
check('16.11: games without obs_seats (MMFind < 0.53): the players\' match is made', bool(mid), True)
check('16.11: ... the observer is not its watcher, his search ends', (L.MM_MATCHES[mid]['watchers'], C in L.MM, 'cannot have observers' in (L.MM_CANCELLED.get(C) or {}).get('by', '')), ([], False, True))
for old in (A, B):
    rid, r, host, v = launch_and_search(True, old=old)                 # one player's game old (host or guest)
    mid = r['launch']['match']
    check('16.11: %s\'s game old -> the match made, no watcher' % ('the host' if old == host else 'the guest'), (bool(mid), L.MM_MATCHES[mid]['watchers'], C in L.MM), (True, [], False))
rid, r, host, v = launch_and_search(True)
mid = r['launch']['match']; m = L.MM_MATCHES[mid]
print('   a failed observer never calls the start off')
L.nm_room({'steam': host, 'room': '2000000077'})
L.nm_fail({'match': mid, 'culprits': [C], 'why': 'observer could not join'})
check('the match goes on', (mid in L.MM_MATCHES, r['state']), (True, 'launching'))
check('the observer is out of it', (C in L.MM_MATCHES[mid]['watchers'], C in L.MM), (False, False))
check('nm/sync then says idle for him (own_lobby stops his search)', L.nm_sync({'steams': [C]})[C]['state'], 'idle')
rid, r, host, v = launch_and_search(True)
mid = r['launch']['match']; L.nm_room({'steam': host, 'room': '2000000078'})
L.nm_leave({'steam': C, 'why': 'Stop Searching'})
check('an observer\'s Stop Searching: the match goes on', (mid in L.MM_MATCHES, r['state']), (True, 'launching'))
rid, r, host, v = launch_and_search(True)
mid = r['launch']['match']; L.nm_room({'steam': host, 'room': '2000000079'})
L.nm_joined({'steam': A if host == B else B, 'room': '2000000079'})
L.nm_started({'room': '2000000079'})
check('started: the watcher\'s search is over', C in L.MM, False)
check('nm/sync for him: playing (not idle - no stop pushed into a running match)', L.nm_sync({'steams': [C]})[C]['state'], 'playing')

print('(3) own_lobby: late observers, the eject')
sys.path.insert(0, REPO + '/lobby')
os.environ['LOBBY_DATA'] = T + '/lobbydata'; os.makedirs(T + '/lobbydata')
import own_lobby as O
pushed = []
O.push = lambda pid, msg: pushed.append((pid, msg[1])) or 1
def nmroom():
    O.ROOMS.clear(); O.NM_POLLS.clear()
    r = {'mid': 2000000100, 'kind': 'nm', 'state': 'lobby', 'match': 'm9', 'pids': {31, 32}, 'members': {31: {}}, 'params': {}, 'host': 31}
    O.ROOMS[r['mid']] = r
    O.NM_POLLS[1] = {'pid': 39, 'steam': C, 'poll': 900000001, 'state': 'matched', 'view': {'match': 'm9', 'watchers': [C], 'role': 'watcher'}}
    return r
sess = {'pid': 39, 'steam': C, 'alias': 'obs'}
r = nmroom()
check('an observer while a player is missing: let in', O.nm_check_join(r, {}, sess), None)
r = nmroom(); r['members'][32] = {}
check('an observer just after every player is in: let in (the race with the last guest)', O.nm_check_join(r, {}, sess), None)
r = nmroom(); r['members'][32] = {}; r['all_in_t'] = time.time() - O.NM_OBS_LATE - 0.5
check('an observer NM_OBS_LATE s after every player is in: refused', O.nm_check_join(r, {}, sess), O.NM_JOIN_FULL)
r = nmroom(); O.nm_check_join(r, {}, sess); r['members'][39] = {'watch': True}; r['members'][32] = {}; r.pop('all_in_t', None)
O.nm_obs_eject(1000.0); check('every player in: no eject at once', pushed, [])
O.nm_obs_eject(1000.0 + O.NM_OBS_GRACE + 0.1); check('every player in for the grace: the observer sent out', pushed, [(39, 'AutomatchStopPollingMessage')])
O.nm_obs_eject(1020.0); check('only once', len(pushed), 1)
open(T + '/lobbydata/nm_obs_eject.off', 'w').close(); pushed.clear()
r = nmroom(); O.nm_check_join(r, {}, sess); r['members'][39] = {'watch': True}; r['members'][32] = {}; r.pop('all_in_t', None)
O.nm_obs_eject(2000.0); O.nm_obs_eject(2000.0 + O.NM_OBS_GRACE + 1); check('nm_obs_eject.off: nobody sent out', pushed, [])
print('FAILED: %s' % fails if fails else 'all ok'); shutil.rmtree(T, ignore_errors=True); sys.exit(1 if fails else 0)
