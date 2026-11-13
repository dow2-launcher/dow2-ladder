"""lroom_unit_test.py - the launcher rooms without a server: the owner starts / stops the countdown of a 1.5+ room, the version
change, an older room counting down by itself; 10.11: observers, invitations, pings, the observer's ticket and watch search;
12.11: the call of the owner when the others are ready, the room's ping and the answers, a kick without a ban, invitations again.
python3 tools/lroom_unit_test.py (from the repo root)."""
import sys, types, time
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", "ladder"))
import lroom
class Users:
    def get(self, s): return {'name': 'P' + s, 'avatar': '', 'rating': 1000}
pub = []
L = types.SimpleNamespace(TEAM_N={'1v1': 1, '2v2': 2, '3v3': 3}, MODES=['1v1', '2v2', '3v3'], users=Users(), RACE_KEYS=['eldar'] * 8,
    stream=types.SimpleNamespace(publish=lambda ev, d, to=None: pub.append((ev, d, to))), _catalog=lambda: {'2p_a': {'name': 'A', 'maxplayers': 2}},
    VAN_MAPS=[], _nm_maps=lambda g, m: [], _clean=lambda v, n: (str(v or '').strip()[:n]), _relays=lambda: {}, relay_order=lambda: [], MM={}, MM_MATCHES={}, MM_PLAYING={}, MM_CANCELLED={}, WATCH='watch')
lroom.L = L
lroom._net = lambda r: {}
ok = lambda c, m: print(('ok  ' if c else 'FAIL') + ' ' + m)
r = lroom.api('create', 'a', {'game': 'elite', 'ver': '3.2', 'mode': '1v1', 'name': 'x', 'start': 'host'})
ok(r['ok'] and r['room']['hs'] is True, 'create with start=host -> hs')
lroom.api('join', 'b', {'id': r['room']['id']})
lroom.api('ready', 'a', {'on': True}); v = lroom.api('ready', 'b', {'on': True})['room']
ok(v['state'] == 'lobby' and v['all_ready'], 'all ready, no countdown by itself (hs)')
ok(lroom.api('start', 'b', {})['error'] == 'owner', 'a guest can not start')
v = lroom.api('start', 'a', {})['room']; ok(v['state'] == 'countdown', 'the owner starts the countdown')
v = lroom.api('stop', 'a', {})['room']; ok(v['state'] == 'lobby' and v['note']['k'] == 'cd_stop', 'the owner stops it')
lroom.api('start', 'a', {}); v = lroom.api('ready', 'b', {'on': False})['room']; ok(v['state'] == 'lobby', '"not ready" stops it')
v = lroom.api('conf', 'a', {'ver': '3.3'})['room']; ok(v['ver'] == '3.3' and not any(s and s['ready'] for s in v['slots']), 'the owner changes the version, everybody unready')
ok(lroom.api('conf', 'b', {'ver': '3.4'})['error'] == 'owner', 'a guest can not change the version')
r2 = lroom.api('create', 'c', {'game': 'elite', 'ver': '3.2', 'mode': '1v1', 'name': 'y'})['room']
lroom.api('join', 'd', {'id': r2['id']}); lroom.api('ready', 'c', {'on': True}); v = lroom.api('ready', 'd', {'on': True})['room']
ok(v['state'] == 'countdown' and v['hs'] is False, 'an older launcher\'s room counts down by itself')

# ---------- 10.11.2026: observers, invitations, pings ----------
fails = 0
def ok(c, m):
    global fails
    fails += 0 if c else 1
    print(('ok  ' if c else 'FAIL') + ' ' + m)
v = lroom.api('create', 'h', {'game': 'elite', 'ver': '3.2', 'mode': '2v2', 'name': 'obs', 'start': 'host'})['room']; rid = v['id']
lroom.api('join', 'p2', {'id': rid}); lroom.api('ready', 'h', {'on': True})
v = lroom.api('join', 'w1', {'id': rid, 'as': 'obs'})['room']
ok(v['obs_cap'] == 4 and [o['steam'] for o in v['obs']] == ['w1'], 'an observer joins a 2v2 room (4 observer seats)')
ok(next(s for s in v['slots'] if s and s['steam'] == 'h')['ready'], 'an observer coming in does not take "ready" from the players')
ok(lroom.api('ready', 'w1', {'on': True})['error'] == 'obs', 'an observer has no "ready"')
sm = next(x for x in lroom.listing()['rooms'] if x['id'] == rid)
ok(len(sm['slots']) == 4 and sm['slots'][0]['steam'] == 'h' and sm['obs'] == [{'steam': 'w1', 'name': 'Pw1'}], 'the list has the seats and the observers')
del pub[:]
r = lroom.api('ping', 'h', {'kind': 'ready'})
pp = [(e, d, t) for e, d, t in pub if e == 'lroom_ping']
ok(r['ok'] and [(e, t) for e, d, t in pp] == [('lroom_ping', 'p2')] and pp[0][1]['kind'] == 'ready' and pp[0][1]['ttl'] == 30, 'the owner\'s ready check goes to who is not ready')
ok(lroom.api('ping', 'h', {'kind': 'ready'})['error'] == 'too_soon', 'a second ready check within 30 s: no')
ok(lroom.api('ping', 'p2', {'kind': 'ready'})['error'] == 'owner', 'only the owner checks who is ready')
ok(lroom.api('ping', 'p2', {'kind': 'start'})['error'] == 'not_ready', 'calling the owner needs everybody ready')
del pub[:]
r = lroom.api('invite', 'p2', {'steam': '76561198000000099'})
ok(r['ok'] and pub and pub[0][0] == 'lroom_invite' and pub[0][2] == '76561198000000099' and pub[0][1]['from'] == 'p2' and pub[0][1]['id'] == rid, 'an invitation goes to the invited player\'s stream')
ok(lroom.api('invite', 'h', {'steam': '76561198000000099'}).get('again') and len(pub) == 1, 'invited again at once: not sent twice')
ok(lroom.api('invite', 'h', {'steam': 'w1'})['error'] == 'bad', 'nobody already in the room is invited')
v = lroom.api('seat', 'w1', {'slot': 3})['room']
ok(v['slots'][3] and v['slots'][3]['steam'] == 'w1' and not v['obs'], 'an observer sits down on a free seat')
v = lroom.api('create', 'q', {'game': 'elite', 'ver': '3.2', 'mode': '1v1', 'name': 'six'})['room']; rid2 = v['id']
for i in range(6): lroom.api('join', 'o%d' % i, {'id': rid2, 'as': 'obs'})
ok(lroom.api('join', 'o9', {'id': rid2, 'as': 'obs'})['error'] == 'obs_full', 'a 1v1 room: 6 observers at most')
# the launch, by hand (the countdown and the relays are tested elsewhere): the observer's ticket and his watch search
R = lroom.ROOMS[rid2]; lroom.api('join', 'q2', {'id': rid2})
R['state'] = 'launching'; R['launch'] = {'t': time.time(), 'deadline': time.time() + 150, 'relay': '', 'host': 'q', 'heroes': {}, 'map': '2p_a', 'teams': [['q'], ['q2']], 'match': None, 'room': None}
tk = lroom.api('ticket', 'o1', {})['ticket']
ok(tk['watch'] is True and tk['room'] == rid2 and 'race' not in tk, 'an observer\'s ticket: watch, no army')
ok(lroom.launching_member(rid2, 'o1', True) and not lroom.launching_member(rid2, 'o1'), 'mm/native lets an observer in only for a watch search')
L.MM['o2'] = {'steam': 'o2', 'mode': '1v1', 'state': 'searching', 'pool': '|elite'}
ok(lroom.on_nm_join('o2', L.MM['o2'], {}, {}) and 'o2' not in L.MM and L.MM_CANCELLED['o2']['match'] == 'lroom-' + rid2, 'an observer searching as a player (an older MMFind) is dropped')
L.MM['o1'] = {'steam': 'o1', 'mode': 'watch', 'state': 'searching', 'pool': '|elite', 'name': 'Po1'}
ok(lroom.on_watch_join('o1', L.MM['o1'], {'lroom': rid2}) and L.MM['o1']['state'] == 'searching', 'his watch search waits for the room\'s match')
L.MM_MATCHES['m1'] = {'id': 'm1', 'state': 'creating', 'watchers': [], 'players': {}}; R['launch']['match'] = 'm1'; lroom._watch_in(R)
ok(L.MM_MATCHES['m1']['watchers'] == ['o1'] and L.MM['o1']['role'] == 'watcher', 'the match made: the observer is its watcher')
L.MM['zz'] = {'steam': 'zz', 'mode': 'watch', 'state': 'searching', 'pool': '|elite'}
ok(lroom.on_watch_join('zz', L.MM['zz'], {'lroom': rid2}) and 'zz' not in L.MM, 'a watch search for a room he is not observing: dropped')
ok(not lroom.on_watch_join('yy', {'mode': 'watch'}, {}), 'a watch search without a room: the ladder\'s own watchers')
lroom.api('leave', 'o1', {})
ok(L.MM_MATCHES['m1']['watchers'] == [] and R['state'] == 'launching', 'an observer leaving: out of the match, the start goes on')
v = lroom.api('create', 's1', {'game': 'elite', 'ver': '3.2', 'mode': '1v1', 'name': 'go', 'start': 'host'})['room']
lroom.api('join', 's2', {'id': v['id']}); lroom.api('ready', 's1', {'on': True}); lroom.api('ready', 's2', {'on': True}); del pub[:]
r = lroom.api('ping', 's2', {'kind': 'start'})
ok(r['ok'] and [(e, t, d['kind']) for e, d, t in pub if e == 'lroom_ping'] == [('lroom_ping', 's1', 'start')], 'all ready: a player calls the owner to start')
ok(lroom.api('ping', 's1', {'kind': 'start'})['error'] == 'bad', 'the owner does not call himself')
ok(lroom.api('invite', 'h', {'steam': 'not-a-steam-id'})['error'] == 'bad', 'an invitation only to a SteamID')
res = [lroom.api('invite', 's1', {'steam': str(76561198000000100 + i)}).get('error') for i in range(12)]
ok(res[:10] == [None] * 10 and res[10:] == ['too_soon', 'too_soon'], 'one player: 10 invitations a minute at most')
# an observer never calls the start off
R2 = lroom.ROOMS[rid2]; R2['launch']['match'] = None
lroom.api('join', 'o7', {'id': rid2, 'as': 'obs'}) if not lroom._obs(R2, 'o3') else None
L.MM['o3'] = {'steam': 'o3', 'mode': 'watch', 'state': 'searching', 'pool': '|elite', 'lroom': rid2}
lroom.on_search_left('o3', 'went silent')
ok(R2['state'] == 'launching' and 'o3' not in L.MM, 'an observer\'s search gone: the start goes on')
L.MM_MATCHES['m2'] = {'id': 'm2', 'lroom': rid2, 'state': 'creating', 'watchers': ['o4'], 'players': {'o4': {}}}; R2['launch']['match'] = 'm2'
lroom.on_match_failed(L.MM_MATCHES['m2'], ['o4'], 'not in the room')
ok(R2['state'] == 'launching' and L.MM_MATCHES['m2']['watchers'] == [], 'only an observer not in the match: he is out, the players go on')

# ---------- 12.11.2026 (launcher 1.5.8): the call of the owner, the room's ping, the answers, kicks, invitations ----------
v = lroom.api('create', 'H', {'game': 'elite', 'ver': '3.2', 'mode': '2v2', 'name': 'r3', 'start': 'host'})['room']; rid3 = v['id']
for p in ('X', 'Y', 'Z'): lroom.api('join', p, {'id': rid3})
for p in ('X', 'Y', 'Z'): v = lroom.api('ready', p, {'on': True})['room']
ok(not v['all_ready'], 'all but the owner ready: not all ready')
del pub[:]
r = lroom.api('ping', 'X', {'kind': 'start'})
ok(r['ok'] and [(e, t) for e, d, t in pub if e == 'lroom_ping'] == [('lroom_ping', 'H')], 'a player calls the owner when every OTHER player is ready')
pv = r['room']['ping']['start']
ok(pv['from'] == 'X' and pv['to'] == ['H'] and pv['until'] - pv['t'] == 30000 and pv['ans'] == {}, 'the room\'s view carries the ping: who, whom, the pause')
r = lroom.api('ping', 'Y', {'kind': 'start'})
ok(r['error'] == 'too_soon' and r['room']['ping']['start']['from'] == 'X', 'a second player a moment later: too soon, with the room (who was first)')
ok(lroom.api('ping_answer', 'Y', {'kind': 'start', 'ans': 'no'})['error'] == 'bad', 'only the pinged player answers')
ok(lroom.api('ping_answer', 'H', {'kind': 'start', 'ans': 'no'})['ok'], 'the owner answers no')
v = lroom.api('get', 'X', {})['room']
ok(v['ping']['start']['ans']['H']['a'] == 'no', 'the answer is in the room\'s view')
v = lroom.api('start', 'H', {})['room']
ok(v['state'] == 'countdown' and next(s for s in v['slots'] if s['steam'] == 'H')['ready'], 'the owner\'s Start marks him ready and counts down')
lroom.api('stop', 'H', {})
del pub[:]
lroom.api('kick', 'H', {'steam': 'Z'})
ok(pub and pub[-1][0] == 'lroom' or any(e == 'lroom_kicked' and d.get('left') == 0 for e, d, t in pub), 'a kick tells the removed player, no ban')
ok(lroom.api('join', 'Z', {'id': rid3}).get('ok'), 'a removed player can come back at once (KICK_BAN 0)')
lroom.api('leave', 'Z', {})
del pub[:]
lroom.api('invite', 'X', {'steam': '76561198000000077'}); lroom.api('join', '76561198000000077', {'id': rid3}); lroom.api('leave', '76561198000000077', {})
lroom.api('invite', 'X', {'steam': '76561198000000077'})
ok(len([1 for e, d, t in pub if e == 'lroom_invite']) == 2, 'a player who came in and left can be invited again at once')
print('FAILED %d' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
