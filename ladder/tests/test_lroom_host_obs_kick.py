#!/usr/bin/env python3
# 24.11.2026 (owner, launcher 1.6.32): (1) the owner of a launcher lobby goes into its observers and back - the room lives on with
# him there (even with no seated player), his Start / Stop / ready check still work, the match's host is a seated player; the
# room closes once nobody is seated and the owner is gone. (2) A kick keeps the player out of that room for KICK_BAN s (5 min):
# his Join is refused with the time left; the owner's invitation lets him back at once; another player's invitation of him is
# refused ("inv_kicked"); other rooms are open to him.
# usage: python3 -I ladder/tests/test_lroom_host_obs_kick.py [<repo dir>]   (temp copies, empty data dirs; nothing live)
import os, shutil, sys, tempfile, time
REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
T = tempfile.mkdtemp(prefix='ladder_hostobs_')
shutil.copytree(REPO + '/ladder', T + '/app', ignore=shutil.ignore_patterns('__pycache__', '*.bak*', 'tests'))
os.makedirs(T + '/data'); sys.path.insert(0, T + '/app'); os.environ['LADDER_NO_CRAWL'] = '1'
import ladder as L
R = L.lroom
fails = []
def check(name, got, want):
    ok = got == want
    print('  %-84s %s' % (name, 'ok' if ok else 'FAIL: got %r, want %r' % (got, want)))
    if not ok: fails.append(name)
A, B, C, D, E = ('7656119000000050%d' % i for i in range(1, 6))
SENT = []
L.stream.publish = lambda ev, data, to=None: SENT.append((ev, data, to))
R._pub = lambda r: None
R._launch = lambda r, now: r.update(state='launching')      # the launch itself is not this test's
def fresh():
    R.ROOMS.clear(); R.BY.clear(); R.KICKED.clear(); R.INVITED.clear(); R.INV_SENT.clear(); SENT.clear()
def mk(owner, mode='1v1', mp='2p_calderisrefinery'):
    return R.api('create', owner, {'game': 'elite', 'ver': '3.2', 'mode': mode, 'map': mp, 'start': 'host'})['room']['id']   # the launcher 1.5+: the owner's Play starts
obs = lambda r: [o['steam'] for o in r['obs']]
seated = lambda r: [s['steam'] for s in r['slots'] if s]

print('(1) the owner into the observers')
fresh(); rid = mk(A); r = R.ROOMS[rid]
v = R.api('seat', A, {'slot': 'obs'})
check('alone in his room: into the observers, the room lives on', (v['ok'], seated(r), obs(r), rid in R.ROOMS, r['owner']), (True, [], [A], True, A))
check('  ... "to_obs" in the feed', (r['chat'][-1]['sys'], r['chat'][-1]['steam']), ('to_obs', A))
R.tick(time.time())
check('  ... the clock does not close it (no seated player, the owner watches)', rid in R.ROOMS, True)
R.api('join', B, {'id': rid}); R.api('join', C, {'id': rid})
check('two players join: both seated, the owner still watches', (sorted(seated(r)), obs(r)), (sorted([B, C]), [A]))
check('the owner\'s ready check goes to the seated ones', sorted(R.api('ping', A, {'kind': 'ready'}).get('n') and r['ping']['ready']['to']), sorted([B, C]))
check('not ready yet: Start refused', R.api('start', A, {}).get('error'), 'not_ready')
R.api('ready', B, {'on': True}); R.api('ready', C, {'on': True})
check('a player may call the owner (hs room, every seat ready)', R.api('ping', B, {'kind': 'start'}).get('ok'), True)
v = R.api('start', A, {})
check('the owner\'s Start from the observers: the countdown', (v.get('ok'), r['state']), (True, 'countdown'))
check('his Stop', (R.api('stop', A, {}).get('ok'), r['state']), (True, 'lobby'))
R.api('start', A, {})
check('his Cancel during the countdown (an observer\'s Cancel is his only)', (R.api('cancel', A, {}).get('ok'), r['state']), (True, 'lobby'))
R.api('join', D, {'id': rid, 'as': 'obs'})
check('another observer\'s Cancel: refused', R.api('cancel', D, {}).get('error'), 'obs')
free = None
R.api('leave', C, {}); free = r['slots'].index(None)
v = R.api('seat', A, {'slot': free})
check('the owner back onto a seat', (v['ok'], A in seated(r), obs(r)), (True, True, [D]))
R.api('seat', A, {'slot': 'obs'}); R.api('leave', B, {})
check('the last seated player leaves: the room stays (the owner watches)', (rid in R.ROOMS, seated(r), sorted(obs(r))), (True, [], sorted([A, D])))
R.api('leave', A, {})
check('then the owner leaves too: closed (only an observer left)', (rid in R.ROOMS, R.BY.get(D)), (False, None))
check('  ... "lroom_gone" empty', [d['why'] for e, d, to in SENT if e == 'lroom_gone' and d['id'] == rid], ['empty'])
fresh(); rid = mk(A); r = R.ROOMS[rid]; R.api('join', B, {'id': rid}); R.api('seat', A, {'slot': 'obs'})
R.api('leave', A, {})
check('the observer owner leaves a room with a player: the player owns it', (rid in R.ROOMS, r['owner']), (True, B))
fresh(); rid = mk(A); r = R.ROOMS[rid]; R.api('seat', A, {'slot': 'obs'})
R._obs(r, A)['seen'] = time.time() - R.HERE_GONE - 5; R.tick(time.time())
check('the observer owner\'s launcher gone (no heartbeat): closed', rid in R.ROOMS, False)

print('(2) a kick keeps the player out for 5 minutes; the owner\'s invitation lets him back')
fresh(); rid = mk(A, '2v2', '4p_calderisrefinery'); r = R.ROOMS[rid]
R.api('join', B, {'id': rid}); R.api('join', C, {'id': rid})
check('KICK_BAN is 5 min', R.KICK_BAN, 300)
R.api('kick', A, {'steam': B})
ev = [d for e, d, to in SENT if e == 'lroom_kicked' and to == B]
check('kicked: out, told with left = 300', (B in seated(r), ev[-1]['left'] if ev else None), (False, 300))
j = R.api('join', B, {'id': rid})
check('his Join: refused, "kicked" with the time left', (j.get('error'), 295 <= (j.get('left') or 0) <= 300), ('kicked', True))
check('  ... as an observer too', R.api('join', B, {'id': rid, 'as': 'obs'}).get('error'), 'kicked')
i = R.api('invite', C, {'steam': B})
check('another player\'s invitation of him: refused (inv_kicked)', (i.get('error'), (rid, B) in R.KICKED), ('inv_kicked', True))
check('  ... nothing sent to him', [e for e, d, to in SENT if e == 'lroom_invite' and to == B], [])
other = mk(D)
check('another room is open to him', R.api('join', B, {'id': other}).get('ok'), True)
R.api('leave', B, {})
i = R.api('invite', A, {'steam': B})
check('the owner\'s invitation: sent, the ban dropped', (i.get('ok'), (rid, B) in R.KICKED, len([1 for e, d, to in SENT if e == 'lroom_invite' and to == B])), (True, False, 1))
check('his Join now: in', (R.api('join', B, {'id': rid}).get('ok'), B in seated(r)), (True, True))
R.api('kick', A, {'steam': B}); R.KICKED[(rid, B)] = time.time() - 1
R.tick(time.time())
check('after the 5 minutes: the ban is gone, Join works', ((rid, B) in R.KICKED, R.api('join', B, {'id': rid}).get('ok')), (False, True))

shutil.rmtree(T, ignore_errors=True)
print('FAIL: %d' % len(fails) if fails else 'all ok'); sys.exit(1 if fails else 0)
