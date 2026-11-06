#!/usr/bin/env python3
# Map bans of the native automatch (06.11.2026, players: "the map ban does not work"): a ban is a veto - the match's map is one nobody
# of it banned (MMFind 0.49 "bans", older MMFind's "maps" = the maps left checked); all banned -> the least banned; a party member's
# own bans (kept by steam id from his MMFind's mm/native peek); mm/native answers name the mode's pool for MMFind's Map Preferences.
# usage: python3 ladder/tests/test_map_veto.py [<app dir>, default: this ladder/]   (a temp copy, an empty data dir; nothing live)
import io, json, os, shutil, sys, tempfile
APP = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = tempfile.mkdtemp(prefix='ladder_mv_'); shutil.copytree(APP, T + '/app', ignore=shutil.ignore_patterns('__pycache__', '*.bak*', 'tests'))
os.makedirs(T + '/data'); sys.path.insert(0, T + '/app'); os.environ['LADDER_NO_CRAWL'] = '1'
POOL = ['2p_bay_of_grots', '2p_calderis_desert', '2p_calderis_jungle', '2p_fen_dunloch', '2p_outerreaches', '2p_vulcan_pits']
json.dump({'elite': {'1v1': POOL}}, open(T + '/data/nm_maps.json', 'w'))
import ladder as L
L._rating_info = lambda steam, mode: (int(steam[-3:]), 1500, 200.0, 0, 'P' + steam[-3:], 'new')
A, B, C, D = '76561190000000001', '76561190000000002', '76561190000000003', '76561190000000004'
NAME = {k: (L._catalog().get(k) or {}).get('name') for k in POOL}
fails = []
def check(name, got, want):
    ok = got == want
    print('  %-78s %s' % (name, 'ok' if ok else 'FAIL: got %r, want %r' % (got, want)))
    if not ok: fails.append(name)

def match_map(hints, mode='1v1', party=None):
    """a native match of these players (steam -> his mm/native body), the map the ladder gives it"""
    L.MM.clear(); L.MM_MATCHES.clear(); L.NM_HINTS.clear()
    for s, h in hints.items(): L.NM_HINTS[s] = {'t': L.time.time(), 'd': dict(h, mode=mode, game='elite')}
    for s in hints:
        if party and s in party.values(): continue
        d = {'steam': s, 'mode': mode, 'game': 'elite', 'key': 'k'}
        if party and s in party: d['party'] = [{'steam': party[s], 'pid': 9}]
        v = L.nm_join(d)
    m = next(iter(L.MM_MATCHES.values()), None)
    return m and m['map']

print('== names of the game -> keys')
check('"(2p) Bay of Grots" -> 2p_bay_of_grots', L._map_keys(['(2p) Bay of Grots']), {'2p_bay_of_grots'})
check('a key stays a key', L._map_keys(['2p_vulcan_pits']), {'2p_vulcan_pits'})
check('wishes from bans: the pool without them', L._nm_wishes('elite', '1v1', {'bans': [NAME['2p_bay_of_grots'], NAME['2p_vulcan_pits']]}),
      [k for k in POOL if k not in ('2p_bay_of_grots', '2p_vulcan_pits')])
check('no bans: any map ([])', L._nm_wishes('elite', '1v1', {'bans': []}), [])
check('older MMFind: the maps left checked', L._nm_wishes('elite', '1v1', {'maps': [NAME['2p_fen_dunloch']]}), ['2p_fen_dunloch'])
check('pool names for Map Preferences', L._nm_pool_names('elite', '1v1'), sorted(NAME.values(), key=str.lower))

print('== the match never gets a map one of its players banned')
seen = set()
for i in range(150):
    seen.add(match_map({A: {'bans': [NAME['2p_bay_of_grots'], NAME['2p_calderis_desert']]}, B: {'bans': [NAME['2p_vulcan_pits']]}}))
check('A bans 2, B bans 1: only the other 3 maps', sorted(seen), ['2p_calderis_jungle', '2p_fen_dunloch', '2p_outerreaches'])
seen = set()
for i in range(100):
    seen.add(match_map({A: {'maps': [NAME[k] for k in POOL if k != '2p_outerreaches']}, B: {'bans': [NAME['2p_fen_dunloch']]}}))
check('older MMFind (maps) + 0.49 (bans) together', '2p_outerreaches' in seen or '2p_fen_dunloch' in seen, False)
seen = set()
for i in range(60):
    seen.add(match_map({A: {'bans': [NAME[k] for k in POOL[:4]]}, B: {'bans': [NAME[k] for k in POOL[2:]]}}))
check('every map banned by someone: one of the least banned', sorted(seen), sorted(POOL[:2] + POOL[4:]))
seen = set()
for i in range(60): seen.add(match_map({A: {}, B: {}}))
check('nobody bans: any map of the pool', seen <= set(POOL) and len(seen) > 3, True)

print('== a party: the member\'s own bans count')
P4 = L._nm_maps('elite', '2v2'); N4 = {k: (L._catalog().get(k) or {}).get('name') for k in P4}
L.NM_PREFS.clear(); L.NM_PREFS[B] = {'t': L.time.time(), 'd': {'bans': [N4[P4[1]]], 'mode': '2v2'}}
L.MM.clear(); L.MM_MATCHES.clear(); L.NM_HINTS.clear()
L.NM_HINTS[A] = {'t': L.time.time(), 'd': {'bans': [N4[P4[0]]], 'mode': '2v2'}}
L.nm_join({'steam': A, 'mode': '2v2', 'game': 'elite', 'key': 'k', 'party': [{'steam': B, 'pid': 9}]})
check('the leader: his own bans', (P4[0] in L.MM[A]['maps'], P4[1] in L.MM[A]['maps']), (False, True))
check('the member: his own bans, not the leader\'s', (P4[1] in L.MM[B]['maps'], P4[0] in L.MM[B]['maps']), (False, True))
L.NM_PREFS.clear(); L.MM.clear(); L.nm_join({'steam': A, 'mode': '2v2', 'game': 'elite', 'key': 'k', 'party': [{'steam': B, 'pid': 9}]})
check('a member without known bans: any map', L.MM[B]['maps'], [])

print('== mm/native: the pool in the answer, the bans kept by steam id (a peek too)')
class R(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False
L.urllib.request.urlopen = lambda *a, **k: R(json.dumps({'native': True, 'here': True}).encode())
L.NM_PREFS.clear()
r = L.mm_native(C, {'steam': C, 'mode': '1v1', 'game': 'elite', 'peek': True, 'bans': [NAME['2p_vulcan_pits']], 'maps': []})
check('peek: native + the pool', (r.get('native'), r.get('pool')), (True, sorted(NAME.values(), key=str.lower)))
check('peek keeps his bans (NM_PREFS)', L.NM_PREFS[C]['d']['bans'], [NAME['2p_vulcan_pits']])
check('peek keeps no search hint', C in L.NM_HINTS, False)
r = L.mm_native(D, {'steam': D, 'mode': '1v1', 'game': 'elite', 'bans': []})
check('Start Searching: native + the pool, the hint kept', (r.get('native'), bool(r.get('pool')), D in L.NM_HINTS), (True, True, True))

print('\n%d failed' % len(fails) if fails else '\nall ok')
shutil.rmtree(T, ignore_errors=True)
sys.exit(1 if fails else 0)
