#!/usr/bin/env python3
# The automatch's map and teams (20.11.2026, SirItos 19.11: "the map was always the same, the teams never changed"):
#  - the map: of the season pool, one this group has not played lately (the newest len(pool)-1 different maps of its players'
#    matches of the mode are out - this process's picks and own_matches), when all were played lately the one played longest ago;
#  - the teams: any split within MM_TEAM_TOL of the most even one, at random, not the teams of the same group's previous match
#    (memory, else own_matches); a party stays in one team; MM_FAIR=0 = the old picks.
# usage: python3 ladder/tests/test_mm_fair.py [<app dir>, default: this ladder/]   (a temp copy and data dir; nothing live)
import json, os, shutil, sqlite3, sys, tempfile
APP = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = tempfile.mkdtemp(prefix='ladder_fair_'); shutil.copytree(APP, T + '/app', ignore=shutil.ignore_patterns('__pycache__', '*.bak*', 'tests'))
os.makedirs(T + '/data'); sys.path.insert(0, T + '/app'); os.environ['LADDER_NO_CRAWL'] = '1'
POOL = {'1v1': ['2p_doom_of_tularis', '2p_fortuna_sanctum', '2p_lugganath_glacier', '2p_selenon_island'],
        '2v2': ['4p_edgeofannihilation', '4p_selenonfissure', '4p_ancestors_rest', '4p_settlement'],
        '3v3': ['6p_fortuna_sanctum', '6p_fen_dunloch_redux', '6p_garvusicegate', '6p_valhallaoilfield']}
json.dump({'label': 'tpre', 'start': 1, 'maps': POOL}, open(T + '/data/own_season.json', 'w'))
import ladder as L, own_matches as O
O.REPO_MAPS = {}   # 25.11.2026: the file's pool here, not the repo's (ladder/season_maps.py)
with L.db() as c: O.migrate(c)
RATING = {}
L._rating_info = lambda steam, mode: (int(steam[-3:]), RATING.get(steam, 1500), 200.0, 0, 'P' + steam[-3:], 'new')
L._own_mm = lambda steam, mode, game, base: base          # the queue by these ratings (no own_ratings rows here)
S = ['7656119000000000%d' % i for i in range(1, 7)]
fails = []
def check(name, ok, info=''):
    print('  %-84s %s' % (name, 'ok' if ok else 'FAIL %r' % (info,)))
    if not ok: fails.append(name)

def match(steams, mode, party=None):
    """these players search (native, Elite); -> the match formed: (map, frozenset of the two teams)"""
    L.MM.clear(); L.MM_MATCHES.clear(); L.NM_HINTS.clear(); L.MM_CANCELLED.clear()
    for s in steams:
        if party and s in party[1:]: continue
        d = {'steam': s, 'mode': mode, 'game': 'elite-3.2.1', 'key': 'k', 'name': 'P' + s[-1], 'pid': 9000 + int(s[-1])}
        if party and s == party[0]: d['party'] = [{'steam': q, 'pid': 9000 + int(q[-1])} for q in party[1:]]
        L.nm_join(d)
    m = next(iter(L.MM_MATCHES.values()), None)
    assert m, 'no match formed'
    return m['map'], frozenset((frozenset(m['host']), frozenset(m['guest'])))

def store(sid, mode, mp, teams, started):
    with L.db() as c:
        c.execute('INSERT INTO own_matches (sid, lobby, kind, mode, map, modname, started) VALUES (?,?,?,?,?,?,?)', (sid, 'NM-%d' % sid, 'mm', mode, mp, 'Elite', started))
        for t, side in enumerate(teams, 1):
            for s in side: c.execute('INSERT INTO own_match_players (sid, steam, pid, team) VALUES (?,?,?,?)', (sid, s, 1, t))

def fresh():
    L.MM_RECENT_MAPS.clear(); L.MM_LAST_SPLIT.clear()
    with L.db() as c: c.execute('DELETE FROM own_matches'); c.execute('DELETE FROM own_match_players')

print('== the map: the same four players, 2v2, ten matches in a row (all at 1500)')
fresh(); L.MM_RNG.seed(1)
maps = [match(S[:4], '2v2')[0] for _ in range(10)]
print('   ', [m[3:] for m in maps])
check('every map of the pool', all(m in POOL['2v2'] for m in maps))
check('no map again within the next two matches (any three in a row are all different)', all(len(set(maps[i:i + 3])) == 3 for i in range(8)), maps)
rot = 0
for seed in range(10, 18):                               # a pure rotation = maps[i] == maps[i + 4] all along
    fresh(); L.MM_RNG.seed(seed); ms = [match(S[:4], '2v2')[0] for _ in range(12)]
    rot += all(ms[i] == ms[i + 4] for i in range(8))
check('no fixed rotation (of 8 seeds, at most 1 runs a pure 4-cycle)', rot <= 1, rot)
print('== the map: own_matches says the group played garvus, then fortuna lately -> one of the other two')
fresh(); L.MM_RNG.seed(2)
store(1, '3v3', '6p_garvusicegate', [S[:3], S[3:]], 1000); store(2, '3v3', '6p_fortuna_sanctum', [S[:3], S[3:]], 2000)
got = set()
for _ in range(12): L.MM_RECENT_MAPS.clear(); got.add(match(S, '3v3')[0])
check('only the two not played lately, both come up', got == {'6p_fen_dunloch_redux', '6p_valhallaoilfield'}, got)
print('== the map: all four played lately, MM_MAP_RECENT 3 -> the one played longest ago')
fresh(); L.MM_RNG.seed(3); os.environ['MM_MAP_RECENT'] = '3'
for i, mp in enumerate(['4p_settlement', '4p_ancestors_rest', '4p_selenonfissure', '4p_edgeofannihilation']):
    store(10 + i, '2v2', mp, [[S[i]], []], 10000 - i * 100)      # settlement newest ... edgeofannihilation oldest
check('the one not among the 3 newest', match(S[:4], '2v2')[0] == '4p_edgeofannihilation')
# both maps the players still allow (no season pool rule here: a direct call) among the newest -> the one played longest ago
g = [{'steam': S[0], 'game': 'elite-3.2.1', 'maps': ['4p_settlement', '4p_ancestors_rest']}]
check('none fresh: the one played longest ago (ancestors 9900 < settlement 10000)', L._nm_pick_map(g, '2v2') == '4p_ancestors_rest')
del os.environ['MM_MAP_RECENT']
print('== the map: another mode\'s history does not count')
fresh(); L.MM_RNG.seed(4)
store(20, '3v3', '4p_settlement', [S[:3], S[3:]], 1000)
seen = set()
for _ in range(30):
    L.MM_RECENT_MAPS.clear(); seen.add(match(S[:4], '2v2')[0])
check('all four maps come up', seen == set(POOL['2v2']), seen)

print('== the teams: four players at 1500, eight 2v2 in a row')
fresh(); L.MM_RNG.seed(5)
splits = [match(S[:4], '2v2')[1] for _ in range(8)]
check('never the same teams twice in a row', all(a != b for a, b in zip(splits, splits[1:])))
check('more than one composition over eight matches', len(set(splits)) >= 2, len(set(splits)))
print('== the teams: the previous match\'s teams from own_matches (a restart forgot the memory)')
fresh(); L.MM_RNG.seed(6)
prev = frozenset((frozenset(S[:3]), frozenset(S[3:])))
store(30, '3v3', '6p_garvusicegate', [S[:3], S[3:]], 5000)
got = {match(S, '3v3')[1] != prev for _ in range(1)}
check('the first 3v3 of the six is not their previous teams', got == {True})
print('== the teams: only fair splits (MM_TEAM_TOL %d): 1700 1650 1600 1550' % L.TEAM_TOL)
fresh(); L.MM_RNG.seed(7)
for s, r in zip(S[:4], (1700, 1650, 1600, 1550)): RATING[s] = r
want = frozenset((frozenset([S[0], S[3]]), frozenset([S[1], S[2]])))
got = {match(S[:4], '2v2')[1] for _ in range(6)}
check('always 1700+1550 vs 1650+1600 (the others are 100 / 200 apart)', got == {want}, got)
RATING.clear()
print('== the teams: a party stays together')
fresh(); L.MM_RNG.seed(8)
got = [match(S[:4], '2v2', party=[S[0], S[1]])[1] for _ in range(6)]
check('the party S1+S2 in one team every time', all(frozenset([S[0], S[1]]) in g for g in got), got)
print('== MM_FAIR=0: the old picks (first even split)')
fresh(); L.MM_FAIR = False
got = {match(S[:4], '2v2')[1] for _ in range(5)}
L.MM_FAIR = True
check('the same teams every time (the old rule)', len(got) == 1, got)
shutil.rmtree(T, ignore_errors=True)
print('all ok' if not fails else 'FAILED: %s' % fails)
sys.exit(1 if fails else 0)
