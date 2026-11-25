#!/usr/bin/env python3
# The season's map pool of the Elite automatch (18.11.2026, SirItos): own_season.json "maps" {"1v1": [keys], ...}. While a mode has
# one and the game is Elite, _nm_maps is exactly that pool (no player bans / wishes - the server picks one at random), MMFind's Map
# Preferences lists only those; vanilla, no season file or no "maps" for the mode = the old rules. /ladder/api/own/season names the
# pool (key, name, minimap) for the site's "Season maps".
# usage: python3 ladder/tests/test_season_maps.py [<app dir>, default: this ladder/]   (a temp copy, an empty data dir; nothing live)
import io, json, os, shutil, sys, tempfile, threading, urllib.request
APP = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = tempfile.mkdtemp(prefix='ladder_sm_'); shutil.copytree(APP, T + '/app', ignore=shutil.ignore_patterns('__pycache__', '*.bak*', 'tests'))
os.makedirs(T + '/data'); sys.path.insert(0, T + '/app'); os.environ['LADDER_NO_CRAWL'] = '1'
OLD1 = ['2p_bay_of_grots', '2p_calderis_desert', '2p_doom_of_tularis', '2p_fen_dunloch', '2p_vulcan_pits']
json.dump({'elite': {'1v1': OLD1}}, open(T + '/data/nm_maps.json', 'w'))
SEASON = {'1v1': ['2p_doom_of_tularis', '2p_fortuna_sanctum', '2p_lugganath_glacier', '2p_selenon_island'],
          '2v2': ['4p_edgeofannihilation', '4p_selenonfissure', '4p_ancestors_rest', '4p_settlement'],
          '3v3': ['6p_fortuna_sanctum', '6p_fen_dunloch_redux', '6p_garvusicegate', '6p_valhallaoilfield']}
SFILE = T + '/data/own_season.json'
BASE = {'label': '2027-pre', 'start': 1794935116, 'info': 'https://rts.fintebtc.de/ladder/table#how'}
def season(d):
    if d is None:
        if os.path.exists(SFILE): os.unlink(SFILE)
    else: json.dump(d, open(SFILE, 'w'))
import ladder as L
# 25.11.2026: the repo's pool (ladder/season_maps.py) wins over the file's - off for the file's cases, its own section at the end
REPO = L.own_matches.REPO_MAPS; L.own_matches.REPO_MAPS = {}
L._rating_info = lambda steam, mode: (int(steam[-3:]), 1500, 200.0, 0, 'P' + steam[-3:], 'new')
A, B, C, D, E, F = ('7656119000000000%d' % i for i in range(1, 7))
CAT = L._catalog(); NAME = lambda k: (CAT.get(k) or {}).get('name')
fails = []
def check(name, got, want):
    ok = got == want
    print('  %-80s %s' % (name, 'ok' if ok else 'FAIL: got %r, want %r' % (got, want)))
    if not ok: fails.append(name)

def match_map(hints, mode='1v1', game='elite'):
    L.MM.clear(); L.MM_MATCHES.clear(); L.NM_HINTS.clear(); L.NM_PREFS.clear()
    for s, h in hints.items(): L.NM_HINTS[s] = {'t': L.time.time(), 'd': dict(h, mode=mode, game=game)}
    for s in hints: L.nm_join({'steam': s, 'mode': mode, 'game': game, 'key': 'k'})
    m = next(iter(L.MM_MATCHES.values()), None)
    return m and m['map']

def nn_map(wishes, mode='1v1', game='elite'):
    """a non-native match (the launcher's search, mm_join) of these players (steam -> his map wishes), the map it gets"""
    L.MM.clear(); L.MM_MATCHES.clear(); L.NM_HINTS.clear()
    for s, w in wishes.items(): L.mm_join(s, mode, {'game': game, 'maps': w, 'name': 'P' + s[-1]})
    m = next(iter(L.MM_MATCHES.values()), None)
    return m and m['map']
def nn_seen(wishes, n, **k): return {nn_map(wishes, **k) for i in range(n)}
def grp(game, mode, *wishes): return [{'rating': 1500, 'game': game, 'mode': mode, 'maps': w} for w in wishes]
X, Y, Z = '2p_bay_of_grots', '2p_vulcan_pits', '2p_fen_dunloch'

print('== the keys agreed with SirItos are in the catalog, of the mode\'s size')
for mode, keys in SEASON.items():
    check('%s: %s' % (mode, ', '.join(keys)), [CAT.get(k, {}).get('maxplayers') for k in keys], [2 * L.TEAM_N[mode]] * 4)

print('== no season file: the old rules')
season(None)
VAN2 = L._nm_maps('vanilla', '2v2')
OLD3 = L._nm_maps('elite', '3v3')
check('elite 1v1 = nm_maps.json', L._nm_maps('elite', '1v1'), OLD1)
check('bans narrow the wishes', L._nm_wishes('elite', '1v1', {'bans': [NAME('2p_vulcan_pits')]}), [k for k in OLD1 if k != '2p_vulcan_pits'])
check('Map Preferences: the old pool', L._nm_pool_names('elite', '1v1'), sorted((NAME(k) for k in OLD1), key=str.lower))
check('API: no "maps"', L._season_maps_view(), {})

print('== a season file without "maps": the old rules')
season(BASE)
check('season_cfg has no maps', 'maps' in L.own_matches.season_cfg(), False)
check('elite 1v1 = nm_maps.json', L._nm_maps('elite', '1v1'), OLD1)
check('elite 3v3 = the catalog\'s 6p maps', L._nm_maps('elite', '3v3'), OLD3)
check('bans narrow the wishes', L._nm_wishes('elite', '1v1', {'bans': [NAME('2p_vulcan_pits')]}), [k for k in OLD1 if k != '2p_vulcan_pits'])
check('non-native Elite: the common wish', nn_seen({A: [X, Y], B: [Y, Z]}, 30), {Y})
check('_group_ok: Elite wishes that do not meet -> no', L._group_ok(grp('elite', '1v1', [X], [Y])), False)

print('== the season pool (Elite)')
season(dict(BASE, maps=SEASON))
for mode, keys in SEASON.items():
    check('elite %s = exactly the season pool' % mode, L._nm_maps('elite', mode), keys)
    check('elite %s with wishes: still the pool' % mode, L._nm_maps('elite', mode, [NAME(keys[0])]), keys)
    check('Map Preferences %s: only its 4 maps' % mode, L._nm_pool_names('elite', mode), sorted((NAME(k) for k in keys), key=str.lower))
check('"elite-3.2.1" counts as Elite', L._nm_maps('elite-3.2.1', '2v2'), SEASON['2v2'])
check('bans ignored: any map ([])', L._nm_wishes('elite', '1v1', {'bans': [NAME(k) for k in SEASON['1v1'][:3]]}), [])
check('older MMFind wishes ignored too', L._nm_wishes('elite', '1v1', {'maps': [NAME('2p_doom_of_tularis')]}), [])
check('vanilla 2v2 unchanged', L._nm_maps('vanilla', '2v2'), VAN2)
check('vanilla bans still work', L._nm_wishes('vanilla', '2v2', {'bans': [NAME(VAN2[0])]}), VAN2[1:])
seen = set()
for i in range(120): seen.add(match_map({A: {'bans': [NAME(k) for k in SEASON['1v1'][:3]]}, B: {'bans': [NAME(SEASON['1v1'][3])]}}))
check('1v1, both ban: every season map still comes up, nothing else', sorted(seen), sorted(SEASON['1v1']))
seen = set()
for i in range(80): seen.add(match_map({A: {}, B: {}, C: {}, D: {}}, mode='2v2'))
check('2v2: only the season pool', sorted(seen), sorted(SEASON['2v2']))
seen = set()
for i in range(60): seen.add(match_map({A: {}, B: {}, C: {}, D: {}, E: {}, F: {}}, mode='3v3'))
check('3v3: only the season pool', sorted(seen), sorted(SEASON['3v3']))
seen = set()
for i in range(60): seen.add(match_map({A: {}, B: {}}, game='vanilla'))
check('vanilla 1v1 match: not the season pool', seen <= set(L._nm_maps('vanilla', '1v1')) and not seen <= set(SEASON['1v1']), True)

print('== the season pool: the non-native path (mm_join / _try_match / _group_ok)')
seen = nn_seen({A: [X], B: [Y]}, 120)
check('1v1 Elite, wishes that do not meet: matched, every season map, nothing else', sorted(seen), sorted(SEASON['1v1']))
seen = nn_seen({A: [X, Y], B: [Y, Z]}, 60, game='elite-3.2.1')
check('1v1 "elite-3.2.1", a common wish: still the season pool only', sorted(seen), sorted(SEASON['1v1']))
seen = nn_seen({A: ['4p_settlement'], B: [], C: ['4p_ancestors_rest'], D: ['4p_vulcan_x']}, 80, mode='2v2')
check('2v2 Elite: the season pool only', sorted(seen), sorted(SEASON['2v2']))
check('_group_ok: Elite wishes that do not meet -> yes (wishes do not count)', L._group_ok(grp('elite', '1v1', [X], [Y])), True)
check('_group_ok: max_diff still counts', L._group_ok([dict(grp('elite', '1v1', [X])[0], rating=1000, max_diff=100), grp('elite', '1v1', [Y])[0]]), False)
check('_group_ok: vanilla wishes that do not meet -> no (unchanged)', L._group_ok(grp('vanilla', '1v1', [X], [Y])), False)
check('vanilla non-native: the common wish (unchanged)', nn_seen({A: [X, Y], B: [Y, Z]}, 30, game='vanilla'), {Y})
check('vanilla non-native, no common wish: the anchor\'s (unchanged)', nn_seen({A: [X], B: [Y]}, 30, game='vanilla'), {X})

print('== the API (/ladder/api/own/season)')
v = L._season_maps_view()
check('three modes, the file\'s order', {m: [x['key'] for x in v[m]] for m in v}, SEASON)
check('name and minimap from the catalog', v['2v2'][0], {'key': '4p_edgeofannihilation', 'name': '(4p) Medean Cliff Mines', 'minimap': 'maps/4p_edgeofannihilation.png'})
srv = L.Server(('127.0.0.1', 0), L.H); threading.Thread(target=srv.serve_forever, daemon=True).start()
d = json.load(urllib.request.urlopen('http://127.0.0.1:%d/ladder/api/own/season' % srv.server_address[1], timeout=10))
check('GET: preseason + label + maps', (d.get('preseason'), d.get('label'), sorted(d.get('maps') or {})), (True, '2027-pre', ['1v1', '2v2', '3v3']))
check('GET: 4 maps per mode', [len(d['maps'][m]) for m in ('1v1', '2v2', '3v3')], [4, 4, 4])

print('== a broken / partial pool')
season(dict(BASE, maps={'1v1': ['2p_doom_of_tularis', 'no_such_map', '4p_settlement', '2p_doom_of_tularis', 'x y'], '3v3': []}))
check('unknown, wrong size, repeated keys dropped', L._nm_maps('elite', '1v1'), ['2p_doom_of_tularis'])
check('a mode with an empty list: the old rules', L._nm_maps('elite', '3v3'), OLD3)
check('a mode not named: the old rules (the catalog\'s 4p maps)', L._nm_maps('elite', '2v2'), sorted(k for k, x in CAT.items() if x.get('maxplayers') == 4))
season(dict(BASE, maps={'1v1': ['nothing_known']}))
check('no known key: the old rules', L._nm_maps('elite', '1v1'), OLD1)
season(dict(BASE, maps=['2p_doom_of_tularis']))
check('"maps" not an object: ignored, the season still on', (L.own_matches.season_cfg() or {}).get('label'), '2027-pre')
check('... and the old pool', L._nm_maps('elite', '1v1'), OLD1)

print('== the repo\'s pool (ladder/season_maps.py, 25.11.2026 SirItos): it wins over the file\'s "maps"')
AGREED = {'1v1': ['2p_seraph_palace', '2p_selenon_island', '2p_lugganath_glacier', '2p_calderisrefinery', '1v1typhonlowlands', '2p_questsdisaster'],
          '2v2': ['4p_ancestors_rest', '4p_selenonfissure', '4p_golgothadepths', '4p_edgeofannihilation', '4p_desertshowdown', '4p_valderusrefinery'],
          '3v3': ['6p_calderis_outskirts', '6p_angelgate', '6p_cityjungle', '6p_fen_dunloch_redux', '6p_hades_wastes_redux', '6p_meridianhighcity']}
check('season_maps.py = the pool SirItos sent 25.11', REPO, AGREED)
for mode, keys in AGREED.items():
    check('%s: every key in the catalog, of the mode\'s size' % mode, [CAT.get(k, {}).get('maxplayers') for k in keys], [2 * L.TEAM_N[mode]] * 6)
L.own_matches.REPO_MAPS = REPO
season(None)
check('no season file: the old rules, the repo\'s pool too', L._nm_maps('elite', '1v1'), OLD1)
season(BASE)
for mode, keys in AGREED.items(): check('a season file without "maps": elite %s = the repo\'s pool' % mode, L._nm_maps('elite', mode), keys)
notes = []
L.own_matches._NOTED.clear()
season(dict(BASE, maps=SEASON))
cfg = L.own_matches.season_cfg(log=notes.append); L.own_matches.season_cfg(log=notes.append)
check('the file\'s "maps" too: the repo\'s pool wins in every mode', cfg['maps'], AGREED)
check('... the file\'s pool noted once per mode', len(notes), 3)
for mode, keys in AGREED.items(): check('elite %s = the repo\'s pool' % mode, L._nm_maps('elite', mode), keys)
check('vanilla 2v2 unchanged', L._nm_maps('vanilla', '2v2'), VAN2)
check('bans ignored', L._nm_wishes('elite', '1v1', {'bans': [NAME(k) for k in AGREED['1v1'][:3]]}), [])
seen = set()
for i in range(150): seen.add(match_map({A: {'bans': [NAME(k) for k in AGREED['1v1'][:3]]}, B: {}}))
check('1v1 matches: every map of the repo\'s pool, nothing else', sorted(seen), sorted(AGREED['1v1']))
v = L._season_maps_view()
check('API: the repo\'s pool, its order', {m: [x['key'] for x in v[m]] for m in v}, AGREED)
d = json.load(urllib.request.urlopen('http://127.0.0.1:%d/ladder/api/own/season' % srv.server_address[1], timeout=10))
check('GET: 6 maps per mode', [len(d['maps'][m]) for m in ('1v1', '2v2', '3v3')], [6, 6, 6])
L.own_matches.REPO_MAPS = {'1v1': AGREED['1v1'], '2v2': []}
check('a mode the repo leaves out (or empty): the file\'s pool for it', (L._nm_maps('elite', '1v1'), L._nm_maps('elite', '2v2'), L._nm_maps('elite', '3v3')),
      (AGREED['1v1'], SEASON['2v2'], SEASON['3v3']))
L.own_matches.REPO_MAPS = REPO
srv.shutdown()

print('\n%d failed' % len(fails) if fails else '\nall ok')
shutil.rmtree(T, ignore_errors=True)
sys.exit(1 if fails else 0)
