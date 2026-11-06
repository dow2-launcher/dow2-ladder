#!/usr/bin/env python3
# Node quality per player (nodeq.py, 06.11.2026): the thresholds, the "2 newest bad / 1 good clears / use it anyway" rule, and the
# matchmaker (ladder._best_relay - classic and native chain - and the launcher rooms' lroom._net / _launch) not putting a player
# on a node bad for him, his chain through a good node staying possible, and the marks ignored when nothing else fits.
# usage: python3 ladder/tests/test_nodeq.py [<app dir>, default: this ladder/]   (a temp copy, an empty data dir; nothing live)
import json, os, shutil, sys, tempfile, time
APP = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = tempfile.mkdtemp(prefix='ladder_nq_'); shutil.copytree(APP, T + '/app', ignore=shutil.ignore_patterns('__pycache__', '*.bak*', 'tests'))
os.makedirs(T + '/data'); sys.path.insert(0, T + '/app'); os.environ['LADDER_NO_CRAWL'] = '1'
PL, DE, MSK = '15.220.68.107', '116.202.106.150', '83.217.192.34'
json.dump({'v': 1, 'relays': [{'ip': PL, 'name': 'Poland'}, {'ip': DE, 'name': 'Germany'}, {'ip': MSK, 'name': 'Moscow'}]}, open(T + '/data/relays.json', 'w'))
json.dump({'links': {PL: {DE: 19, MSK: 54}, DE: {PL: 19, MSK: 47}, MSK: {PL: 54, DE: 47}}}, open(T + '/data/relay_links.json', 'w'))
import ladder as L, nodeq, lroom
KNOWN = {PL, DE, MSK}
A, B, C = '76561190000000001', '76561190000000002', '76561190000000003'
fails = []
def check(name, got, want):
    ok = got == want
    print('  %-74s %s' % (name, 'ok' if ok else 'FAIL: got %r, want %r' % (got, want)))
    if not ok: fails.append(name)

def test(steam, ip, t, **k):   # one launcher run with a single node
    row = dict(ip=ip, transport='udp', verdict='excellent', why=[], med=30, loss_up=0, loss_down=0, stall_ms=0, max_gap_ms=120, cut=False); row.update(k)
    return nodeq.add_test(steam, {'ts': t, 'mode': '1v1', 'vpn': False, 'nodes': [row]}, KNOWN, now=t)

print('== judging one measurement')
check('clean test: good', nodeq.judge_test(dict(transport='udp', why=[], loss_up=0.5, stall_ms=0))[:2], (False, []))
check('loss 35 % up: bad (loss)', nodeq.judge_test(dict(transport='udp', why=['loss_up'], loss_up=35))[:2], (True, ['loss']))
check('loss 9.9 %: good', nodeq.judge_test(dict(transport='udp', why=['loss'], loss_down=9.9))[0], False)
check('stuck 24 s: bad (stall)', nodeq.judge_test(dict(transport='udp', why=['cut', 'stall'], stall_ms=24000, cut=True))[:2], (True, ['stall', 'cut']))
check('pause 1.2 s: bad (stall)', nodeq.judge_test(dict(transport='udp', why=['pauses'], max_gap_ms=1200))[:2], (True, ['stall']))
check('stream stopped on the way (DPI): bad', nodeq.judge_test(dict(transport='udp', why=['stream_blocked']))[:2], (True, ['dpi']))
check('no answer at all: no information', nodeq.judge_test(dict(transport='none', why=['no_answer'])), None)
check('high ping only: good (not a mark reason)', nodeq.judge_test(dict(transport='udp', why=['high_ping'], med=180))[0], False)
check('match: 38 % resent down: bad', nodeq.judge_match(dict(rx=3000, tx=3000, resent=1140))[:2], (True, ['loss']))
check('match: 2 stalls of his alone: bad', nodeq.judge_match(dict(rx=3000, tx=3000, solo_stalls=2, max_solo_ms=1800))[:2], (True, ['stall']))
check('match: 1 stall of his alone: good', nodeq.judge_match(dict(rx=3000, tx=3000, solo_stalls=1))[0], False)
check('match: connection died: bad', nodeq.judge_match(dict(rx=3000, tx=3000, dead=True))[:2], (True, ['cut']))
check('match: too short (100 packets): no information', nodeq.judge_match(dict(rx=100, tx=100, resent=90)), None)

print('== marks: 2 newest bad, 1 good clears, use it anyway')
now = time.time()
test(A, PL, now - 3000, loss_up=35, why=['loss_up'])
check('one bad test: not avoided yet', nodeq.avoid(A, now), frozenset())
test(A, PL, now - 2000, loss_up=38, why=['loss_up'])
nodeq._CACHE.clear()
check('two bad tests: Poland avoided for A', nodeq.avoid(A, now), frozenset({PL}))
pm = nodeq.public(A, now)[PL]
check('the mark says losses 38 % and when', (pm['why'], pm['loss'], pm['t']), (['loss'], 38.0, int(now - 2000)))
check('B has no marks', nodeq.avoid(B, now), frozenset())
test(A, PL, now - 1000)
check('one good fresh test clears it', nodeq.avoid(A, now), frozenset())
test(A, PL, now - 900, stall_ms=24000, cut=True, why=['cut', 'stall'])
nodeq.add_matches([dict(steam=A, ip=PL, t=now - 800, ref='pl:1:1', rx=4000, tx=4000, resent=1500, lost_in=10)], KNOWN, now=now)
check('a bad test + a bad match after it: avoided again', nodeq.avoid(A, now), frozenset({PL}))
check('the same match line twice is one sample', nodeq.add_matches([dict(steam=A, ip=PL, t=now - 800, ref='pl:1:1', rx=4000, tx=4000, resent=1500)], KNOWN, now=now), 0)
nodeq.force(A, PL, True, now=now)
check('use it anyway: not avoided, the mark stays shown', (nodeq.avoid(A, now), nodeq.public(A, now)[PL]['avoid'], 'forced_until' in nodeq.public(A, now)[PL]), (frozenset(), False, True))
check('... for 24 h only', nodeq.avoid(A, now + 86400 + 61), frozenset({PL}))
nodeq.force(A, PL, False, now=now)
check('undo: avoided again', nodeq.avoid(A, now), frozenset({PL}))
check('older than 7 days: forgotten', nodeq.avoid(A, now + 8 * 86400), frozenset())
check('an unknown node is not kept', test(C, '1.2.3.4', now, loss_up=50), 0)

print('== the matchmaker (A: Poland bad - 38 % losses)')
V = L.CHAIN_V                     # Relay 22+ puts this key into its pings (it chains)
def mm(**pings):
    L.MM.clear()
    for s, p in pings.items(): L.MM[{'a': A, 'b': B, 'c': C}[s]] = {'ping': p}
# A reaches everything, Poland best; B reaches Poland and Germany
mm(a={PL: 30, DE: 35, MSK: 60}, b={PL: 32, DE: 40, MSK: -1})
check('classic: A vs B - not Poland, Germany (good for both)', L._best_relay([A, B]), DE)
check('native: the same', L._best_relay([A, B], chain=True), DE)
check('without the mark it would be Poland', L._best_relay_q([A, B], True, {}), PL)
# B reaches only Poland (Germany cut on his way), with Relay 22 chains: B to Germany through Poland
mm(a={PL: 30, DE: 35, MSK: 60, V: 1}, b={PL: 32, DE: -1, MSK: -1, V: 1})
check('native: B only Poland - Germany, B chained through Poland', L._best_relay([A, B], chain=True), DE)
check('classic (no chains): nothing else fits - marks ignored, Poland', L._best_relay([A, B]), PL)
# A can't reach Poland at all and has a chain: no straight connection to it - a chain via his good Germany would be fine
mm(a={PL: -1, DE: 35, MSK: 60, V: 1}, b={PL: 32, DE: -1, MSK: -1, V: 1})
check('native: A reaches no Poland - his chain via Germany to Poland stays', L._relay_cost(L.MM[A]['ping'], PL, L.relay_order(), L._relay_links(), nodeq.avoid(A)), (64, DE))
check('... and he still reaches Poland straight -> no', L._relay_cost({PL: 30, DE: 35, V: 1}, PL, L.relay_order(), L._relay_links(), nodeq.avoid(A)), (None, None))
check('native: A vs B there - Germany (worst 61) over Poland (64)', L._best_relay([A, B], chain=True), DE)
# A's nearest node (the one Relay.dll chains through) is the bad one: no chain through it
test(A, DE, now - 500, loss_down=40, why=['loss']); test(A, DE, now - 400, loss_down=41, why=['loss'])
mm(a={PL: 20, DE: 35, MSK: -1, V: 1}, b={PL: -1, DE: -1, MSK: 50, V: 1})
check('native: A bad PL+DE, Moscow only through his nearest (bad PL) - marks ignored, Moscow', L._best_relay([A, B], chain=True), MSK)
nodeq.force(A, DE, True, now=time.time())
check('... A forces Germany: Germany', L._best_relay([A, B], chain=True), DE)
nodeq.force(A, DE, False, now=time.time())
# a party member without pings: his bad node is not taken
D = '76561190000000004'
L.MM.clear(); L.MM[B] = {'ping': {PL: 30, DE: 40, MSK: 70, V: 1}}; L.MM[D] = {'ping': {PL: 32, DE: 45, MSK: 80, V: 1}}; L.MM[C] = {'ping': None}
check('native: B vs D with C (no pings, party): Poland', L._best_relay([B, D, C], chain=True), PL)
test(C, PL, now - 300, loss_up=50, why=['loss_up']); test(C, PL, now - 200, loss_up=50, why=['loss_up'])
check('... C has Poland bad: Germany', L._best_relay([B, D, C], chain=True), DE)

print('== the launcher room (A, B; A: Poland and Germany bad)')
r = {'id': 'r1', 'owner': A, 'slots': [{'steam': A}, {'steam': B}], 'mode': '1v1', 'pings': {
    A: {'p': {PL: 20, DE: 25, MSK: 60}, 't': time.time(), 'chain': True}, B: {'p': {PL: 30, DE: 30, MSK: 55}, 't': time.time(), 'chain': True}}}
net = lroom._net(r)
check('room: the match on Moscow (good for both)', (net['pick'], net['nq_ignored']), (MSK, False))
check("room: A's row carries his marks", sorted(net['rows'][0]['nq']), sorted([PL, DE]))
check("room: B's row has none", net['rows'][1]['nq'], {})
r['pings'][A]['p'][MSK] = -1; r['pings'][B]['p'][PL] = -1; r['pings'][B]['p'][DE] = -1
net = lroom._net(r)
check('room: A only PL/DE (bad), B only Moscow: marks ignored', (net['pick'], net['nq_ignored']), (MSK, True))

print('FAILED: %s' % fails if fails else 'ALL OK')
shutil.rmtree(T, ignore_errors=True)
sys.exit(1 if fails else 0)
