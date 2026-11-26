#!/usr/bin/env python3
"""own_lobby: automatch/stoppolling WITHOUT a poll id (26.11.2026, stands party_1126) ends the caller's own search:
python3 lobby/tests/test_nm_stoppoll.py   (imports own_lobby with a temp data dir; no sockets, nothing live)
The game sends stoppolling with no pollID - the player's Stop Searching and the party leader's game ending its search by itself
when a party member leaves the party. Before: nothing found, the ladder kept the party's search, the member who left hung on
"Processing". Now: the caller's searching search is gone, the ladder is told (leave), every party member gets the stop push;
a matched search (in a room) and other players' searches are left alone; with a poll id it is as before."""
import asyncio, os, sys, tempfile
D = tempfile.mkdtemp(prefix='ownlobby_stoppoll_'); os.environ['LOBBY_DATA'] = D
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import own_lobby as O
open(os.path.join(O.DATA, 'native_mm.on'), 'w').close()
fails = []
def check(name, ok, info=''):
    print('  %-80s %s' % (name, 'ok' if ok else 'FAIL %s' % (info,)))
    if not ok: fails.append(name)
LADDER, PUSHED = [], []
O.ladder_bg = lambda fn, body: LADDER.append((fn, body))
O.push = lambda pid, msg: (PUSHED.append((pid, msg[1], msg[3])), 1)[1]
def search(poll, pid, steam, members=(), state='searching'):
    mem = [{'pid': pid, 'steam': steam, 'race': 1}] + [{'pid': q, 'steam': s, 'race': 2} for q, s in members]
    x = {'poll': poll, 'sid': poll - 100000000, 'pid': pid, 'steam': steam, 'alias': steam, 'mt': 2, 'mode': '2v2', 'race': 1,
         'state': state, 't': 0, 'polled': O.time.time(), 'view': {'state': state}, 'pushed': {}, 'joined': True, 'members': mem,
         'party': 69525006}
    O.NM_POLLS[poll] = x; return x
def call(fn, p, pid, steam):
    return asyncio.run(O.nm_call(fn, p, {'pid': pid, 'steam': steam, 'alias': steam, 'sg': 1}))
def reset(): O.NM_POLLS.clear(); del LADDER[:]; del PUSHED[:]

print("== the party leader's game ends its search (a member left): stoppolling {}")
reset(); old = search(900000001, 1, 'L', [(2, 'M')], state='gone'); x = search(900000002, 1, 'L', [(2, 'M')]); other = search(900000003, 7, 'O')
a = call('stoppolling', {}, 1, 'L')
check('answer [0]', a == [0], a)
check('his searching search is gone', x['state'] == 'gone', x['state'])
check('the ladder is told: leave L', LADDER == [('leave', {'steam': 'L', 'why': 'Stop Searching'})], LADDER)
check('the member gets AutomatchStopPollingMessage [poll, party]', PUSHED == [(2, 'AutomatchStopPollingMessage', [900000002, 69525006])], PUSHED)
check("another player's search untouched", other['state'] == 'searching')
print('== stoppolling {} while matched (in a room): left to the room handling')
reset(); x = search(900000004, 1, 'L', [(2, 'M')], state='matched')
call('stoppolling', {}, 1, 'L')
check('matched search untouched, nothing sent', x['state'] == 'matched' and not LADDER and not PUSHED, (x['state'], LADDER, PUSHED))
print("== a party member's stoppolling {} (his game ignores it itself; not his search)")
reset(); x = search(900000005, 1, 'L', [(2, 'M')])
call('stoppolling', {}, 2, 'M')
check("the leader's search untouched", x['state'] == 'searching' and not LADDER and not PUSHED, (x['state'], LADDER, PUSHED))
print('== no search at all')
reset(); a = call('stoppolling', {}, 1, 'L')
check('[0], nothing sent', a == [0] and not LADDER and not PUSHED)
print('== with a poll id: as before')
reset(); x = search(900000006, 1, 'L'); y = search(900000007, 1, 'L')
call('stoppolling', {'pollID': '900000006'}, 1, 'L')
check('that very search gone, the other one kept', x['state'] == 'gone' and y['state'] == 'searching', (x['state'], y['state']))
reset(); search(900000008, 1, 'L')
call('stoppolling', {'pollID': '123'}, 1, 'L')
check('an unknown poll id: nothing (no fallback)', not LADDER and O.NM_POLLS[900000008]['state'] == 'searching')
print('FAILED: %s' % fails if fails else 'ALL OK'); sys.exit(1 if fails else 0)
