#!/usr/bin/env python3
"""25.11.2026 (SirItos: the player page's matches look like the history's cards and carry its Replay button): /ladder/api/own/player
gives each own match its lobby, the replay id and Relic's duration from mm_history (the history's row of the same lobby), and every
player his hero and his table number after the match / its change / his games (own_c / own_d / own_n), as the history's rows have them.
usage: python3 ladder/tests/test_player_matches.py [<repo dir>]   (a temp copy, an empty data dir; nothing live)"""
import json, os, shutil, sys, tempfile, threading, time, urllib.request
REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
T = tempfile.mkdtemp(prefix='ladder_pm_')
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
with L.db() as c:
    o.migrate(c)
    for sid, lobby, start in ((501, 'NM-501', now - 7200), (502, 'NM-502', now - 3600), (503, None, now - 600)):
        c.execute('INSERT INTO own_matches (sid, lobby, kind, mode, map, modname, season, started, ended, winner_team, rated) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                  (sid, lobby, 'mm', '1v1', '2p_seraph_palace', 'Elite', L.current_season(), start, start + 1500, 1, 1))
        for st, team, hero, oc, od, on in ((A, 1, 2, 1612.4, 11.6, 9), (B, 2, 7, None, None, 3)):
            c.execute('INSERT INTO own_match_players (sid, steam, pid, name, team, race, hero, own_c, own_d, own_n, final) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                      (sid, st, int(st[-1]), 'P' + st[-1], team, 5, hero, oc, od, on, 'win' if team == 1 else 'loss'))
    c.execute('INSERT INTO mm_history (lobby, mid, mode, map, started, ended, players, watchers, result, replay) VALUES (?,?,?,?,?,?,?,?,?,?)',
              ('NM-501', 'm1', '1v1', '2p_seraph_palace', now - 7200, now - 5700, '[]', '[]', json.dumps({'duration': 1432}), 'abc123'))
    c.execute('INSERT INTO mm_history (lobby, mid, mode, map, started, players, watchers) VALUES (?,?,?,?,?,?,?)',
              ('NM-502', 'm2', '1v1', '2p_seraph_palace', now - 3600, '[]', '[]'))

srv = L.Server(('127.0.0.1', 0), L.H); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
d = json.load(urllib.request.urlopen('http://127.0.0.1:%d/ladder/api/own/player?steam=%s' % (port, A), timeout=10))
ms = {m['sid']: m for m in d['matches']}
check('three matches, the newest first', [m['sid'] for m in d['matches']], [503, 502, 501])
check('a match: its lobby', (ms[501]['lobby'], ms[503]['lobby']), ('NM-501', None))
check('with a replay in mm_history: replay + Relic\'s duration', (ms[501].get('replay'), ms[501].get('duration')), ('abc123', 1432))
check('mm_history row without replay / result: neither', ('replay' in ms[502], 'duration' in ms[502]), (False, False))
check('no lobby: nothing added, no error', ('replay' in ms[503], ms[503]['ended'] - ms[503]['started']), (False, 1500))
pa = [p for t in ms[501]['teams'] for p in t if p['steam'] == A][0]
pb = [p for t in ms[501]['teams'] for p in t if p['steam'] == B][0]
check('every player: hero (0-2), own_c / own_d rounded, own_n', (pa['hero'], pa['own_c'], pa['own_d'], pa['own_n']), (2, 1612, 12, 9))
check('a hero out of 0-2 -> null; calibration: no number', (pb['hero'], pb['own_c'], pb['own_d'], pb['own_n']), (None, None, None, 3))
check('me (c, d, n) as before', (ms[501]['me']['c'], ms[501]['me']['d'], ms[501]['me']['n']), (1612, 12, 9))
srv.shutdown()
shutil.rmtree(T, ignore_errors=True)
print('FAILED: %s' % ', '.join(fails) if fails else 'ALL OK'); sys.exit(1 if fails else 0)
