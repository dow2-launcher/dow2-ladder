#!/usr/bin/env python3
"""own_lobby: the guests of a native room get its id one after another (20.11.2026, SirItos 19.11 - players swapped in m19 / m20):
python3 lobby/tests/test_nm_stagger.py   (imports own_lobby with a temp data dir; no sockets, nothing live)
A 3v3 match: the host's room comes up, the five guests (one of them a party member of another guest's search) must get the
AutomatchGameMessage push in the ladder's order, NM_GUEST_GAP s apart (the 0.5 s syncs push the next one); a launcher room's match
keeps its own turns (lroom_turn); data/nm_stagger.off and NM_GUEST_GAP=0 = everyone at once (as before)."""
import os, sys, tempfile
D = tempfile.mkdtemp(prefix='ownlobby_stagger_'); os.environ['LOBBY_DATA'] = D
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import own_lobby as O
fails = []
def check(name, ok, info=''):
    print('  %-80s %s' % (name, 'ok' if ok else 'FAIL %s' % (info,)))
    if not ok: fails.append(name)

NOW = [1000.0]
O.time.time = lambda: NOW[0]
O.ladder_bg = lambda fn, body: None
PUSHED = []
O.push = lambda pid, msg: (PUSHED.append((NOW[0], pid, msg[1])), 1)[1]

H, G = 'H', ['G1', 'G2', 'G3', 'G4', 'G5']           # team 0: H, G1, G2; team 1: G3, G4 (+ his party member G5)
PID = {'H': 1, 'G1': 11, 'G2': 12, 'G3': 13, 'G4': 14, 'G5': 15}
def view(lroom=''):
    return {'state': 'matched', 'match': 'm99', 'mode': '3v3', 'host_steam': H, 'host_pid': 1, 'team': 0, 'teams': 2, 'size': 3,
            'map': '6p_garvusicegate', 'steams': [H] + G, 'pids': sorted(PID.values()), 'relay': '', 'room': None, 'lroom': lroom, 'joined': []}
def searches(lroom=''):
    O.NM_POLLS.clear(); O.NM_ROOM_T.clear(); O.LROOM_PUSHED.clear()
    xs = {}
    for s in [H, 'G1', 'G2', 'G3', 'G4']:
        mem = [{'pid': PID[s], 'steam': s, 'race': 1}] + ([{'pid': PID['G5'], 'steam': 'G5', 'race': 2}] if s == 'G4' else [])
        x = {'poll': 900 + PID[s], 'sid': 800 + PID[s], 'pid': PID[s], 'steam': s, 'alias': s, 'mt': 3, 'mode': '3v3', 'race': 1, 'state': 'matched',
             't': NOW[0], 'polled': NOW[0], 'view': view(lroom), 'pushed': {}, 'joined': True, 'members': mem, 'party': 0}
        O.NM_POLLS[x['poll']] = x; xs[s] = x
    return xs
def run(lroom='', steps=16):
    del PUSHED[:]; NOW[0] = 1000.0
    xs = searches(lroom)
    for x in xs.values(): O.nm_push_news(x)                     # the host's push (no room yet)
    O.nm_hosted(xs[H], 2000000001, '15.220.68.107')            # the room is up: nm_hosted pushes whoever's turn it is
    t0 = NOW[0]
    for i in range(steps):                                       # the 0.5 s syncs
        NOW[0] += 0.5
        for x in xs.values(): x['view']['room'] = 2000000001; O.nm_push_news(x)
    inv = {v: k for k, v in PID.items()}
    return [(round(t - t0, 1), inv[pid]) for t, pid, kind in PUSHED if kind == 'AutomatchGameMessage' and pid != 1]

print('== a native 3v3 room (NM_GUEST_GAP %.1f s)' % O.NM_GUEST_GAP)
got = run()
print('   pushes (s after the room, guest):', got)
check('each guest pushed once', sorted(g for _, g in got) == sorted(G))
check('in the ladder\'s order (the party member G5 after G4)', [g for _, g in got] == G)
check('NM_GUEST_GAP apart (within one 0.5 s sync)', all(abs(t - O.NM_GUEST_GAP * i) <= 0.5 for i, (t, _) in enumerate(got)), got)
print('== the polls (automatch/polling answers) hand out the room only at the guest\'s turn too')
del PUSHED[:]; NOW[0] = 1000.0; xs = searches(); O.nm_hosted(xs[H], 2000000001, '15.220.68.107')
for x in xs.values(): x['view']['room'] = 2000000001
NOW[0] += 0.5; early = O.nm_answer(xs['G3'], PID['G3'])[4]; host = O.nm_answer(xs[H], PID[H])[4]
NOW[0] += 3.0; later = O.nm_answer(xs['G3'], PID['G3'])[4]
check('G3 at 0.5 s: no room id yet (0)', early == 0, early)
check('G3 at 3.5 s: the room id', later == 2000000001, later)
check('the host: the room id at once', host == 2000000001, host)
print('== data/nm_stagger.off')
open(os.path.join(D, 'nm_stagger.off'), 'w').close()
got = run(); os.unlink(os.path.join(D, 'nm_stagger.off'))
check('everyone at once with the room', len(got) == 5 and all(t == 0 for t, _ in got), got)
print('== NM_GUEST_GAP = 0')
O.NM_GUEST_GAP, keep = 0.0, O.NM_GUEST_GAP
got = run(); O.NM_GUEST_GAP = keep
check('everyone at once with the room', len(got) == 5 and all(t == 0 for t, _ in got), got)
print('== a launcher room\'s match: its own turns (lroom_turn), not the stagger')
got = run(lroom='abc123', steps=40)
check('all five pushed', sorted(g for _, g in got) == sorted(G), got)
check('the first guest at once', got and got[0][1] == 'G1' and got[0][0] == 0, got)
print('ALL OK' if not fails else 'FAILED: %s' % fails)
sys.exit(1 if fails else 0)
