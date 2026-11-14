#!/usr/bin/env python3
# 14.11.2026 (siritos): (1) /ladder/api/rooms tells the open observer seats of an ordinary lobby (obs_open / obs_free / obs_taken,
# from the lobby's slotinfo); (2) the native match's view for own_lobby names its observers ("watchers"), never in "pids";
# (3) own_lobby lets a launcher room's observer into the host's native room, keeps him out of the result and of the ladder's
# fail/joined calls; a stranger is still refused; data/nm_watch.off turns it off.
# usage: python3 ladder/tests/test_obs_seats_watchers.py [<repo dir>]   (temp copies, empty data dirs; nothing live)
import asyncio, base64, io, json, os, shutil, struct, sys, tempfile, zlib
REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
T = tempfile.mkdtemp(prefix='ladder_obs_')
shutil.copytree(REPO + '/ladder', T + '/app', ignore=shutil.ignore_patterns('__pycache__', '*.bak*', 'tests'))
os.makedirs(T + '/data'); sys.path.insert(0, T + '/app'); os.environ['LADDER_NO_CRAWL'] = '1'
import ladder as L
fails = []
def check(name, got, want):
    ok = got == want
    print('  %-78s %s' % (name, 'ok' if ok else 'FAIL: got %r, want %r' % (got, want)))
    if not ok: fails.append(name)

# ---- (1) observer seats of an ordinary lobby
def seat(pid=-1, team=0, kind=0, order=1):
    a, b, c = (-1, -1, -1) if pid == -1 else (0, order, 0)
    return struct.pack('<7i', pid, a, b, c, team, 255, 255) + b'\0' + struct.pack('<i', -1) + bytes(7) + bytes([kind]) + bytes(2)
def slotinfo(seats):
    return base64.b64encode(zlib.compress(struct.pack('<IH', 12, len(seats)) + b''.join(seats))).decode()
def ad(i, mapname, seats, members):
    return {'id': i, 'description': 'room %d' % i, 'mapname': mapname, 'maxplayers': 8, 'observernum': 0, 'observermax': 512,
            'slotinfo': slotinfo(seats), 'matchmembers': [{'profile_id': p, 'teamid': t} for p, t in members], 'host_profile_id': members[0][0]}
ADS = {'matches': [
    # 1v1: seat 0 host, seat 1 an open observer seat, seat 2 an observer on his seat, seat 3 closed; seat 4 open for a player
    ad(1, '2p_calderis_desert', [seat(100, 0, 0, 1), seat(-1, 0, 5), seat(200, 0, 0, 2), seat(-1, 0, 1),
                                 seat(-1, 1, 0), seat(-1, 1, 1), seat(-1, 1, 1), seat(-1, 1, 1)], [(100, 0), (200, 0)]),
    # 1v1 as the game makes it: every observer seat closed (the browser's "Observers 0/0")
    ad(2, '2p_calderis_desert', [seat(101, 0, 0, 1)] + [seat(-1, 0, 1)] * 3 + [seat(-1, 1, 0)] + [seat(-1, 1, 1)] * 3, [(101, 0)]),
    # 3v3 (Relic's live list 14.11: seats 3 and 7 type 5 = the host opened both observer seats)
    ad(3, '6p_angelgate', [seat(102, 0, 0, 1), seat(-1, 0), seat(-1, 0), seat(-1, 0, 5), seat(-1, 1), seat(-1, 1), seat(-1, 1), seat(-1, 1, 5)], [(102, 0)]),
    # an unknown map (no size): not readable
    ad(4, 'zz_unknown_map', [seat(103, 0, 0, 1)] + [seat(-1, 0, 5)] * 7, [(103, 0)]),
], 'avatars': []}
class _R(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): pass
L.urllib.request.urlopen = lambda req, timeout=None: _R(json.dumps(ADS).encode())
rooms = {r['id']: r for r in L._rooms_once()}
print('observer seats (/ladder/api/rooms)')
pick = lambda r: (r['obs_open'], r['obs_free'], r['obs_taken'])
check('1v1, one open + one taken observer seat', pick(rooms[1]), (2, 1, 1))
check('1v1, observer seats closed (the default)', pick(rooms[2]), (0, 0, 0))
check('3v3, the host opened both observer seats', pick(rooms[3]), (2, 2, 0))
check('unknown map size: not readable (None)', pick(rooms[4]), (None, None, None))
check('the old fields stay', (rooms[1]['observers'], rooms[1]['observers_max'], rooms[1]['free']), (0, 512, 1))
check('the observer is marked as one', [p['observer'] for p in rooms[1]['players']], [False, True])

# ---- (2) the native match's view names its observers
print('ladder _nm_view')
H, G, W = '76561190000000001', '76561190000000002', '76561190000000009'
L.MM.clear(); L.MM_MATCHES.clear()
L.MM[H] = {'steam': H, 'pid': 11, 'state': 'matched', 'match': 'm1', 'mode': '1v1'}
L.MM[G] = {'steam': G, 'pid': 12, 'state': 'matched', 'match': 'm1', 'mode': '1v1'}
L.MM[W] = {'steam': W, 'pid': 19, 'state': 'matched', 'match': 'm1', 'mode': 'watch', 'role': 'watcher'}
L.MM_MATCHES['m1'] = {'id': 'm1', 'mode': '1v1', 'host': [H], 'guest': [G], 'watchers': [W], 'host_steam': H, 'relay': '', 'room': '2000000001',
                      'native': True, 'lroom': 'abc', 'unrated': True}
v = L._nm_view(L.MM[H])
check('watchers listed', v.get('watchers'), [W])
check('pids = the players only (the host game compares that list)', sorted(v['pids']), [11, 12])

# ---- (3) own_lobby: the observer's join
print('own_lobby: an observer of the match joins the host room')
LD = T + '/lobby_data'; os.makedirs(LD); os.environ['LOBBY_DATA'] = LD
sys.path.insert(0, REPO + '/lobby'); import own_lobby as O
sent = []
O.ladder_bg = lambda fn, body: sent.append((fn, body))
O.push = lambda pid, msg: 1
def sess(pid, steam): return {'pid': pid, 'steam': steam, 'alias': 'p%d' % pid, 'sg': 0}
CRC = {k: 'x' for k in O.CRC_KEYS}
O.NM_POLLS.clear(); O.ROOMS.clear()
O.NM_POLLS[1] = {'poll': 1, 'pid': 11, 'steam': H, 'state': 'matched', 'view': dict(v, room=2000000001)}
mid = 2000000001
O.ROOMS[mid] = {'mid': mid, 'host': 11, 'relay': ['1.2.3.4', 47100], 'state': 'lobby', 'kind': 'nm', 'match': 'm1', 'steams': {H, G}, 'pids': {11, 12},
                'params': dict(CRC, mapname='2p_x', description='AUTOMATCH'), 'members': {11: {'sg': 0, 'steam': H, 'alias': 'p11', 'race': 1, 'team': 0}},
                'created': 0, 'seen': 0, 'reports': {}, 'started': None, 'lobby_id': None, 'unrated': True, 'lroom': 'abc'}
call = lambda fn, s, **p: O.own_call('advertisement/' + fn, dict(CRC, advertisementid=str(mid), **p), s)
r = call('join', sess(12, G)); check('the guest (a player) joins', r[0], 0)
check('  ... nm/joined for him', [f for f, b in sent if f == 'joined'], ['joined'])
sent.clear()
r = call('join', sess(19, W)); check('the observer joins', r[0], 0)
check('  ... no nm/joined for him (not a player)', [f for f, b in sent if f == 'joined'], [])
check('  ... kept as the room\'s observer', O.ROOMS[mid].get('watch_pids'), [19])
r = call('join', sess(77, '76561190000000077')); check('a stranger is refused', r, O.NM_JOIN_FULL)
r = call('join', dict(sess(19, W))); check('the observer again (a retry): in', r[0], 0)
open(LD + '/nm_watch.off', 'w').close()
O.ROOMS[mid]['watch_pids'] = []
r = call('join', sess(19, W)); check('nm_watch.off: the observer is refused', r, O.NM_JOIN_FULL)
os.remove(LD + '/nm_watch.off'); r = call('join', sess(19, W)); check('nm_watch.off gone: in again', r[0], 0)
sent.clear(); call('leave', sess(19, W))
check('the observer leaves: no nm/fail (the match goes on)', [f for f, b in sent if f == 'fail'], [])
r = call('join', sess(19, W)); check('  ... and may come back before the start', r[0], 0)
O.ROOMS[mid]['order'] = [11, 12, 19]
O.ROOMS[mid]['members'][12]['team'] = 1; O.ROOMS[mid]['members'][19]['team'] = 2
O.LADDER_DB = T + '/data/none.sqlite'
sent.clear()
rep = lambda pid: O.report(O.ROOMS[mid], sess(pid, {11: H, 12: G, 19: W}[pid]), {'profile_ids': '[11,12]', 'results': '[1,0]', 'race_ids': '[1,2]'})
rep(19); rep(11); check('the observer\'s and the host\'s report: not stored yet', bool(O.ROOMS[mid].get('stored')), False)
rep(12); check('every player reported: stored (the observer is not waited for)', bool(O.ROOMS[mid].get('stored')), True)
body = next((b for f, b in sent if f == 'report'), {})
check('nm/report: members = the players, the observer apart', (sorted(body.get('members', {})), body.get('watchers'), body.get('missing')), (['11', '12'], [19], []))
check('room_players leaves the observer out', O.room_players(O.ROOMS[mid]), [11, 12])
O.ROOMS[mid]['state'] = 'playing'; O.ROOMS[mid]['watch_pids'] = []
r = call('join', sess(19, W)); check('after the start: a new observer is refused', r, O.NM_JOIN_FULL)

shutil.rmtree(T, ignore_errors=True)
print('FAILED: %s' % fails if fails else 'all ok'); sys.exit(1 if fails else 0)
