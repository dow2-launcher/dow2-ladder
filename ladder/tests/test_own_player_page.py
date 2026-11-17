#!/usr/bin/env python3
"""17.11.2026, the player page /ladder/player/<steam>: recompute_own keeps what each match did to the table's number
(own_match_players.own_c / own_d / own_n), site_player gives it in `me` (c, d, n) and the place (`rank`) of each calibrated mode;
the hidden rating of calibration never shows. step2 on a temp DB; nothing live is touched.
usage: python3 test_own_player_page.py [<dir with own_matches.py, ladder.py>]"""
import json, os, shutil, sqlite3, sys, tempfile, threading
APP = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
import own_matches as o
T = tempfile.mkdtemp(prefix='own_pp_'); N = [0]
def ok(name, cond):
    N[0] += 1
    if not cond: print('FAIL', name); sys.exit(1)
    print('ok  ', name)
quiet = lambda s: None
fn = T + '/ladder.sqlite'
c = sqlite3.connect(fn); o.migrate(c); c.execute('CREATE TABLE matches (id INTEGER PRIMARY KEY, data TEXT)')
S, H = 1_800_000_000, 3600
def add(sid, start, ps, kind='mm'):
    c.execute('INSERT INTO own_matches (sid, lobby, kind, mode, modname, season, started, reports) VALUES (?,?,?,?,?,?,?,?)',
              (sid, 'NM-%d' % sid, kind, '%dv%d' % (len(ps) // 2, len(ps) // 2), 'Elite', '2027-Q1', start, json.dumps({'reports': {}})))
    for i, (st, team, rep) in enumerate(ps):
        c.execute('INSERT INTO own_match_players (sid, steam, pid, name, team, report_result, report_t, leave_t) VALUES (?,?,?,?,?,?,?,?)',
                  (sid, st, i + 1, st.upper(), team, rep, start + 900, start + 910))
for i in range(6): add(100 + i, S + i * 30 * H, [('x', 1, 1), ('y', 2, 0)])          # x beats y, a day+ apart (no repeat-pair weight)
add(106, S + 6 * 30 * H, [('x', 1, 0), ('y', 2, 1)])                                   # 7th: y wins
add(107, S + 7 * 30 * H, [('x', 1, 1), ('y', 2, 0)], kind='room')                      # a launcher room: unrated
for i in range(5): add(200 + i, S + i * 30 * H + H, [('u', 1, 1), ('v', 2, 0)])        # u: calibrated, below x
c.commit(); c.close()
ok('step2', o.step2(fn, log=quiet, cfg=None))
c = sqlite3.connect(fn); q = lambda sql, *a: c.execute(sql, a).fetchall()
xs = q('SELECT sid, own_c, own_d, own_n FROM own_match_players WHERE steam = "x" ORDER BY sid')
ok('own_n: his games after each match, NULL on the unrated room', [r[3] for r in xs] == [1, 2, 3, 4, 5, 6, 7, None])
ok('calibration (1-4): no number, no change', all(r[1] is None and r[2] is None for r in xs[:4]))
ok('5th: the number, no change (it was hidden before)', xs[4][1] is not None and xs[4][2] is None)
ok('6th, 7th: number and change; change = the difference of the numbers', all(r[1] is not None and r[2] is not None for r in xs[5:7])
   and abs(xs[5][2] - (xs[5][1] - xs[4][1])) < 1e-6 and abs(xs[6][2] - (xs[6][1] - xs[5][1])) < 1e-6)
cons = q('SELECT cons FROM own_ratings WHERE steam = "x"')[0][0]
ok('the last number = the table\'s', abs(xs[6][1] - cons) < 1e-6)
ok('the loser y: a win in 106 moves his number up from where it was', q('SELECT own_d FROM own_match_players WHERE steam = "y" AND sid = 106')[0][0] is not None)
c.close()
o.step2(fn, log=quiet, cfg=None)                       # again: same values (not stacked)
c = sqlite3.connect(fn)
ok('a second step2 gives the same', c.execute('SELECT sid, own_c, own_d, own_n FROM own_match_players WHERE steam = "x" ORDER BY sid').fetchall() == xs); c.close()
o.setup(lambda: sqlite3.connect(fn), threading.Lock(), lambda t: '2027-Q1', data_dir=T)
p = o.site_player('x')
me = {m['sid']: m['me'] for m in p['matches']}
ok('site_player: me.c / me.d / me.n', me[106]['n'] == 7 and me[106]['c'] == round(xs[6][1]) and me[106]['d'] == round(xs[6][2])
   and me[100] == dict(me[100], c=None, d=None, n=1) and me[107]['n'] is None)
r = [x for x in p['ratings'] if x['mode'] == '1v1'][0]
board = o.site_board('1v1', r['season'])
ok('site_player: rank = the board\'s place', r['rank'] == [b['rank'] for b in board['board'] if b['steam'] == 'x'][0])
ok('... u has his own place', [x for x in o.site_player('u')['ratings'] if x['mode'] == '1v1'][0]['rank'] == [b['rank'] for b in board['board'] if b['steam'] == 'u'][0])
# an old DB without the columns: setup adds them (the ladder may answer before the collector's next step2)
fn2 = T + '/old.sqlite'; c = sqlite3.connect(fn2)
c.executescript(o.SCHEMA); c.commit(); c.close()
o.setup(lambda: sqlite3.connect(fn2), threading.Lock(), lambda t: '2027-Q1', data_dir=T)
c = sqlite3.connect(fn2)
ok('setup migrates: own_c / own_d / own_n exist', {'own_c', 'own_d', 'own_n'} <= {r[1] for r in c.execute('PRAGMA table_info(own_match_players)')}); c.close()
ok('site_player on it: no error', o.site_player('x')['matches'] == [])
shutil.rmtree(T, ignore_errors=True)
print('ALL %d OK' % N[0])
