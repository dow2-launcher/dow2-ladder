#!/usr/bin/env python3
# The quick match of a lone pool (20.11.2026, SirItos): exactly one match's players in the mode's pool (a party with all its members)
# and nobody new for MM_ALONE_S (10 s) -> they play whatever the own-rating window says; a pool with one more player keeps the window.
# usage: python3 ladder/tests/test_mm_alone.py [<app dir>]   (a temp copy and data dir; nothing live)
import json, os, shutil, sys, tempfile, io, contextlib
APP = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = tempfile.mkdtemp(prefix='ladder_alone_'); shutil.copytree(APP, T + '/app', ignore=shutil.ignore_patterns('__pycache__', '*.bak*', 'tests'))
os.makedirs(T + '/data'); sys.path.insert(0, T + '/app'); os.environ['LADDER_NO_CRAWL'] = '1'
json.dump({'label': 'tpre', 'start': 1}, open(T + '/data/own_season.json', 'w'))
CLOCK = [1_800_000_000.0]
import time as _time
_time.time = lambda: CLOCK[0]
import ladder as L
R = {}
L._rating_info = lambda steam, mode: (int(steam[-3:]), 1500, 60.0, 9, 'P' + steam[-3:], 'own')
L._own_mm = lambda steam, mode, game, base: (R.get(steam, 1500), 60.0, 9, 'own')
S = ['7656119000000001%02d' % i for i in range(10)]
fails = []
def check(name, ok, info=''):
    print('  %-80s %s' % (name, 'ok' if ok else 'FAIL %r' % (info,)))
    if not ok: fails.append(name)
def reset():
    L.MM.clear(); L.MM_MATCHES.clear(); L.NM_HINTS.clear(); L.MM_CANCELLED.clear(); L.OWN_RETRY[0] = 0; L.MM_ALONE_LOGGED.clear()
def join(i, mode='1v1', party=None):
    CLOCK[0] += 1
    d = {'steam': S[i], 'mode': mode, 'game': 'elite-3.2.1', 'key': 'k', 'name': 'P%d' % i, 'pid': 9000 + i}
    if party: d['party'] = [{'steam': S[j], 'pid': 9000 + j} for j in party]
    L.nm_join(d)
def wait(sec, who):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        for _ in range(int(sec)):
            CLOCK[0] += 1; L.nm_sync({'steams': [S[i] for i in who]})
    return out.getvalue()
def matched(): return sorted(sorted(m['host'] + m['guest']) for m in L.MM_MATCHES.values())

print('== 1v1: 1900 and 1500 alone (spread 400, window 150 at first)')
reset(); R.update({S[0]: 1900, S[1]: 1500})
join(0); join(1)
check('not at once (the window)', matched() == [])
log = wait(5, [0, 1])
check('not after 5 s', matched() == [])
log = wait(8, [0, 1])
check('matched after ~10 s alone', matched() == [sorted([S[0], S[1]])], matched())
check('logged: quick match, window ignored', 'quick match' in log, log)
print('== 1v1: three in the pool (1900, 1500, 1100) - not alone: the window stays')
reset(); R.update({S[0]: 1900, S[1]: 1500, S[2]: 1100})
join(0); join(1); join(2)
wait(30, [0, 1, 2])
check('nobody matched after 30 s (every pair over the window)', matched() == [], matched())
print('== 1v1: a newcomer resets the 10 s')
reset(); R.update({S[0]: 1900, S[1]: 1500, S[2]: 1100})
join(0); wait(8, [0]); join(1); wait(6, [0, 1])
check('6 s after the second joined: not yet', matched() == [])
wait(6, [0, 1])
check('12 s after: matched', matched() == [sorted([S[0], S[1]])], matched())
print('== 2v2: a party of two + two singles, far apart')
reset(); R.update({S[3]: 2100, S[4]: 2100, S[5]: 1300, S[6]: 1300})
join(3, '2v2', party=[4]); join(5, '2v2'); join(6, '2v2')
check('not at once', matched() == [])
wait(12, [3, 5, 6])
check('matched after ~10 s alone (the party counts with both)', len(matched()) == 1 and sorted(matched()[0]) == sorted(S[3:7]), matched())
print('== close ratings: at once as before')
reset(); R.update({S[7]: 1500, S[8]: 1520})
join(7); join(8)
check('matched at once', matched() == [sorted([S[7], S[8]])], matched())
shutil.rmtree(T, ignore_errors=True)
print('all ok' if not fails else 'FAILED: %s' % fails); sys.exit(1 if fails else 0)
