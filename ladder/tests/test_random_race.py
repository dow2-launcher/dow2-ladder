#!/usr/bin/env python3
"""27.11.2026 (SirItos: "the site does not show the random race in the matches - add the "?" as in the launcher"): a player who picked
Random keeps the mark after the match. mm_history's row has race 'random' from the start; /ladder/api/history gives that player
random: true with the race the game rolled (Relic's report), and /ladder/api/own/player marks him random in his match's team.
usage: python3 ladder/tests/test_random_race.py [<repo dir>]   (a temp copy, an empty data dir; nothing live)"""
import json, os, shutil, sys, tempfile, threading, time, urllib.request
REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
T = tempfile.mkdtemp(prefix='ladder_rnd_')
shutil.copytree(REPO + '/ladder', T + '/app', ignore=shutil.ignore_patterns('__pycache__', '*.bak*', 'tests'))
os.makedirs(T + '/data'); sys.path.insert(0, T + '/app'); os.environ['LADDER_NO_CRAWL'] = '1'
import ladder as L
import own_matches as o
fails = []
def check(name, got, want):
    ok = got == want
    print('  %-74s %s' % (name, 'ok' if ok else 'FAIL: got %r, want %r' % (got, want)))
    if not ok: fails.append(name)

A, B = '76561198000000001', '76561198000000002'
now = int(time.time())
pl = [{'steam': A, 'pid': 11, 'name': 'Rando', 'team': 1, 'rating': 1500, 'rsrc': 'own', 'race': 'random', 'hero': -1},
      {'steam': B, 'pid': 12, 'name': 'Fixed', 'team': 2, 'rating': 1500, 'rsrc': 'own', 'race': 'eldar', 'hero': 1}]
res = {'relic_id': 1, 'mapname': '2p_seraph_palace', 'duration': 1200, 'players': [
    {'pid': 11, 'result': 1, 'team': 0, 'race': L.RACE_KEYS.index('orks'), 'hero': 2, 'stats': None},
    {'pid': 12, 'result': 0, 'team': 1, 'race': L.RACE_KEYS.index('eldar'), 'hero': 1, 'stats': None}]}
with L.db() as c:
    o.migrate(c)
    c.execute('INSERT INTO mm_history (lobby, mid, mode, map, started, ended, players, watchers, result, replay) VALUES (?,?,?,?,?,?,?,?,?,?)',
              ('NM-601', 'm1', '1v1', '2p_seraph_palace', now - 7200, now - 6000, json.dumps(pl), '[]', json.dumps(res), 'r601'))
    c.execute('INSERT INTO mm_history (lobby, mid, mode, map, started, players, watchers) VALUES (?,?,?,?,?,?,?)',
              ('NM-602', 'm2', '1v1', '2p_seraph_palace', now - 600, json.dumps(pl), '[]'))
    for sid, lobby in ((601, 'NM-601'), (602, 'NM-602')):
        c.execute('INSERT INTO own_matches (sid, lobby, kind, mode, map, modname, season, started, ended, winner_team, rated) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                  (sid, lobby, 'mm', '1v1', '2p_seraph_palace', 'Elite', L.current_season(), now - 7200, now - 6000, 1, 1))
        for st, team, race in ((A, 1, L.RACE_KEYS.index('orks')), (B, 2, L.RACE_KEYS.index('eldar'))):
            c.execute('INSERT INTO own_match_players (sid, steam, pid, name, team, race, hero, final) VALUES (?,?,?,?,?,?,?,?)',
                      (sid, st, 11 if st == A else 12, 'P', team, race, 1, 'win' if team == 1 else 'loss'))

srv = L.Server(('127.0.0.1', 0), L.H); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
get = lambda path: json.load(urllib.request.urlopen('http://127.0.0.1:%d%s' % (port, path), timeout=10))
h = {m['lobby']: m for m in get('/ladder/api/history?n=10')['items']}
p1 = {p['name']: p for p in h['NM-601']['players']}
check('finished: Random -> random true + the race rolled (orks) + its hero', (p1['Rando'].get('random'), p1['Rando']['race'], p1['Rando']['hero']), (True, 'orks', 2))
check('finished: a picked race - no mark', ('random' in p1['Fixed'], p1['Fixed']['race']), (False, 'eldar'))
p2 = {p['name']: p for p in h['NM-602']['players']}
check('still played: race "random" (not known yet) + the mark', (p2['Rando']['race'], p2['Rando'].get('random')), ('random', True))
check('the race filter "orks" finds the rolled race', [m['lobby'] for m in get('/ladder/api/history?race=orks')['items']], ['NM-601'])
d = get('/ladder/api/own/player?steam=%s' % A)
ps = {(m['sid'], p['steam']): p for m in d['matches'] for t in m['teams'] for p in t}
check('own/player: the Random player marked in both matches', (ps[(601, A)].get('random'), ps[(602, A)].get('random')), (True, True))
check('own/player: his race the one played', ps[(601, A)]['race'], 'orks')
check('own/player: the other player not marked', ('random' in ps[(601, B)], 'random' in ps[(602, B)]), (False, False))
srv.shutdown()
shutil.rmtree(T, ignore_errors=True)
print('FAILED: %s' % ', '.join(fails) if fails else 'ALL OK'); sys.exit(1 if fails else 0)
