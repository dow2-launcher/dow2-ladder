"""lroom_unit_test.py - the launcher rooms without a server: the owner starts / stops the countdown of a 1.5+ room, the version
change, an older room counting down by itself. python3 tools/lroom_unit_test.py (from the repo root)."""
import sys, types, time
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", "ladder"))
import lroom
class Users:
    def get(self, s): return {'name': 'P' + s, 'avatar': '', 'rating': 1000}
pub = []
L = types.SimpleNamespace(TEAM_N={'1v1': 1, '2v2': 2, '3v3': 3}, MODES=['1v1', '2v2', '3v3'], users=Users(), RACE_KEYS=['eldar'] * 8,
    stream=types.SimpleNamespace(publish=lambda ev, d, to=None: pub.append(ev)), _catalog=lambda: {'2p_a': {'name': 'A', 'maxplayers': 2}},
    VAN_MAPS=[], _nm_maps=lambda g, m: [], _clean=lambda v, n: (str(v or '').strip()[:n]), _relays=lambda: {}, relay_order=lambda: [], MM={}, MM_MATCHES={}, MM_PLAYING={})
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
