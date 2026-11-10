#!/usr/bin/env python3
"""own rating step 2 tests: decide() on made-up matches (every branch of the rules) + resolve/step2/recompute_own on a COPY of the
tables (base.sqlite = the 48 own matches exported from rts; never the live DB). Run: python3 test_step2.py [dir with own_matches.py, ladder.py]"""
import json, os, shutil, sqlite3, sys
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__)))
import own_matches as o

HERE = os.path.dirname(os.path.abspath(__file__)); T0 = 1_800_000_000; N = [0]
def P(steam, team, rep=None, rep_t=None, leave=None): return dict(steam=steam, team=team, rep=rep, rep_t=rep_t, leave=leave)
def M(**k): d = dict(kind='mm', started=T0, end_est=False, conflict=False); d.update(k); return d
def F(r): return {s: v[0] for s, v in r['players'].items()}
def ok(name, cond):
    N[0] += 1
    if not cond: print('FAIL', name); sys.exit(1)
    print('ok  ', name)

E = T0 + 900   # the end of a game of 15 min
# 1. all reports 1/0 and agree
r = o.decide(M(), [P('a', 1, 1, E, E + 10), P('b', 2, 0, E, E + 300)])
ok('reports agree -> win/loss, rated', F(r) == {'a': 'win', 'b': 'loss'} and r['rated'] == 1 and r['result_src'] == 'reports' and r['winner_team'] == 1)
# 2. the winner leaves first from the score screen (480): a leave after the end is no leave
r = o.decide(M(), [P('a', 1, 1, E, E + 3), P('b', 2, 0, E, E + 270)])
ok('winner leaves first after the end -> normal', F(r) == {'a': 'win', 'b': 'loss'} and r['rated'] == 1)
# 3. a leave during the game, the other reports a win
r = o.decide(M(), [P('a', 1, None, None, T0 + 600), P('b', 2, 1, E, E + 20)])
ok('left before the end -> loss_leave, opponent win', F(r) == {'a': 'loss_leave', 'b': 'win'} and r['rated'] == 1 and r['result_src'] == 'reports+node')
# 3b. inside END_EPS of the end = not a leave
r = o.decide(M(), [P('a', 1, 0, E, E - 3), P('b', 2, 1, E, E + 20)])
ok('left 3 s before the end -> plain loss', F(r) == {'a': 'loss', 'b': 'win'})
# 4. 2v2: a teammate left, his team lost short-handed -> the other gets the loss at weight 0.5
r = o.decide(M(), [P('a', 1, None, None, T0 + 500), P('a2', 1, 0, E, E + 5), P('b', 2, 1, E, E + 9), P('b2', 2, 1, E, E + 9)])
ok('2v2 teammate left, team lost -> loss_leave + loss w0.5', F(r) == {'a': 'loss_leave', 'a2': 'loss', 'b': 'win', 'b2': 'win'}
   and r['players']['a2'][1] == o.SHORT_W and r['players']['a2'][3] == 'short_handed' and r['rated'] == 1)
# 5. 2v2: a teammate left, his team still won -> he loses anyway, the teammate wins
r = o.decide(M(), [P('a', 1, None, None, T0 + 500), P('a2', 1, 1, E, E + 5), P('b', 2, 0, E, E + 9), P('b2', 2, 0, E, E + 9)])
ok('2v2 teammate left, team won -> loss_leave + win', F(r) == {'a': 'loss_leave', 'a2': 'win', 'b': 'loss', 'b2': 'loss'} and r['players']['a2'][1] == 1.0)
# 6. only 3 (472): the first to leave loses, the one who stayed wins
r = o.decide(M(), [P('g', 1, 3, E + 7, E + 690), P('n', 2, 3, E + 7, E)])
ok('3/3, one left, other stayed -> node result', F(r) == {'g': 'win', 'n': 'loss_leave'} and r['result_src'] == 'node' and r['rated'] == 1)
# 6b. 2v2 only 3: team 2 all gone first; a player of team 1 had left before that -> loss_leave too
r = o.decide(M(), [P('a', 1, 3, None, T0 + 400), P('a2', 1, 3, None, T0 + 900), P('b', 2, 3, None, T0 + 500), P('b2', 2, None, None, T0 + 600)])
ok('2v2 3s -> the team gone first loses, earlier leavers too', F(r) == {'a': 'loss_leave', 'a2': 'win', 'b': 'loss_leave', 'b2': 'loss_leave'} and r['winner_team'] == 1)
# 7. early leave (< EARLY_S): unrated for all; the leaver forgiven the first time in 24 h, loss_leave the next
r = o.decide(M(), [P('a', 1, None, None, T0 + 40), P('b', 2, 1, T0 + 80, T0 + 85)], early_before=lambda s: 0)
ok('early leave, first in 24h -> unrated, forgiven', r['why'] == 'early_leave' and r['rated'] == 0 and F(r) == {'a': 'none', 'b': 'none'}
   and r['players']['a'][2] == 1 and r['players']['a'][3] == 'early_forgiven')
r = o.decide(M(), [P('a', 1, None, None, T0 + 40), P('b', 2, 1, T0 + 80, T0 + 85)], early_before=lambda s: 1)
ok('early leave, second in 24h -> loss_leave for him only', r['why'] == 'early_leave' and F(r) == {'a': 'loss_leave', 'b': 'none'})
# 8. everyone gone at once before a result = the node
r = o.decide(M(), [P('a', 1, None, None, T0 + 600), P('b', 2, None, None, T0 + 601.5)])
ok('all gone within ALL_GONE_S -> all_gone', r['why'] == 'all_gone' and r['rated'] == 0 and set(F(r).values()) == {'none'})
r = o.decide(M(), [P('a', 1, 3, None, T0 + 600), P('b', 2, 3, None, T0 + 602)])
ok('3/3 and both left within ALL_GONE_S -> all_gone', r['why'] == 'all_gone')
# 9. no data
r = o.decide(M(), [P('a', 1), P('b', 2)])
ok('no reports, no node -> no_data', r['why'] == 'no_data' and r['rated'] == 0)
r = o.decide(M(), [P('a', 1, 3, None, None), P('b', 2, 3, None, None)])
ok('3/3 without node data -> no_winner', r['why'] == 'no_winner')
# 10. the reports disagree
r = o.decide(M(), [P('a', 1, 1, E, E + 5), P('b', 2, 1, E, E + 5)])
ok('both teams 1 -> reports_disagree', r['why'] == 'reports_disagree' and r['result_src'] == 'check' and r['rated'] == 0)
r = o.decide(M(conflict=True), [P('a', 1, 1, E, E + 5), P('b', 2, 0, E, E + 5)])
ok('games tell differently -> reports_disagree', r['why'] == 'reports_disagree')
# 11. rule 1
r = o.decide(M(kind='room'), [P('a', 1, 1, E), P('b', 2, 0, E)])
ok('room -> unrated room, result kept', r['why'] == 'room' and r['rated'] == 0 and F(r) == {'a': 'win', 'b': 'loss'})
r = o.decide(M(), [P('a', 1, 1, E), P('a2', 1, 1, E), P('b', 2, 0, E)])
ok('2v1 -> not_full_teams', r['why'] == 'not_full_teams' and r['rated'] == 0)
r = o.decide(M(), [P('pid:5', 1, 1, E), P('b', 2, 0, E)])
ok('no steam -> no_steam', r['why'] == 'no_steam')
r = o.decide(M(kind=None), [P('a', 1, 1, E), P('b', 2, 0, E)])
ok('no ladder row -> no_history', r['why'] == 'no_history')

# ---- on a copy of the tables ----
db = os.path.join(HERE, 'test_copy.sqlite'); base = os.path.join(HERE, 'base.sqlite'); real = os.path.exists(base)
if real: shutil.copy(base, db)                         # base.sqlite: the exported own matches (not in the repo: players' data)
else:
    if os.path.exists(db): os.remove(db)
    c = sqlite3.connect(db); o.migrate(c); c.execute('CREATE TABLE matches (id INTEGER PRIMARY KEY, data TEXT)'); c.commit(); c.close()
ok('step2 on the copy', o.step2(db, log=lambda s: None))
c = sqlite3.connect(db)
if real:
    fin = dict(c.execute('SELECT name, final FROM own_match_players WHERE sid = 2006052472'))
    ok('472 (backfill, 3/3) -> GRAFF win, Нежданчег loss_leave', fin == {'GRAFF': 'win', 'Нежданчег': 'loss_leave'})
    fin = dict(c.execute('SELECT name, final || coalesce(":" || note, "") FROM own_match_players WHERE sid = 2006052475'))
    ok('475 (room, nookiega at +31 dead) -> early_forgiven', fin == {'pivolan': 'none', 'nookiega': 'none:early_forgiven'})
    row = c.execute('SELECT rated, why_unrated, winner_team FROM own_matches WHERE sid = 2006052480').fetchone()
    ok('480 (winner out first) -> rated, team 1', row == (1, None, 1))
    row = c.execute('SELECT rated, why_unrated FROM own_matches WHERE sid = 2006052457').fetchone()
    ok('457 (room, surrender at 60 s) -> room', row == (0, 'room'))
a = sorted(c.execute('SELECT * FROM own_ratings')); c.close()
o.step2(db, log=lambda s: None)
c = sqlite3.connect(db); b = sorted(c.execute('SELECT * FROM own_ratings'))
ok('recompute_own deterministic', a == b and (len(a) > 0 or not real))
ok('cons = rating - 2 RD, cal_left', all(abs(x[11] - (x[3] - 2 * x[4])) < 1e-9 and x[10] == max(0, o.CAL_GAMES - x[6]) for x in b))
# made-up matches on the copy: an early leaver twice in 24 h, a 2v2 short-handed loss
def add(sid, start, kind, ps, reports):
    c.execute('INSERT INTO own_matches (sid, lobby, kind, mode, season, started, reports) VALUES (?,?,?,?,?,?,?)',
              (sid, 'NM-%d' % sid, kind, '%dv%d' % (len(ps) // 2, len(ps) // 2), '2027-Q1', start, json.dumps(reports)))
    for st, team, rep, rep_t, lv in ps:
        c.execute('INSERT INTO own_match_players (sid, steam, pid, team, report_result, report_t, leave_t) VALUES (?,?,?,?,?,?,?)',
                  (sid, st, abs(hash(st)) % 10**8, team, rep, rep_t, lv))
S = 1_800_000_000
add(9001, S, 'mm', [('x', 1, None, None, S + 30), ('y', 2, 1, S + 70, S + 80)], {'reports': {}})
add(9002, S + 3600, 'mm', [('x', 1, None, None, S + 3650), ('y', 2, 1, S + 3690, S + 3700)], {'reports': {}})
add(9003, S + 7200, 'mm', [('p', 1, None, None, S + 7500), ('q', 1, 0, S + 8000, S + 8005), ('r', 2, 1, S + 8000, S + 8010), ('s', 2, 1, S + 8000, S + 8010)],
    {'reports': {'1': {'profile_ids': '[1,2]', 'results': '[1,0]'}, '2': {'profile_ids': '[1,2]', 'results': '[1,0]'}}})
add(9004, S + 9000, 'mm', [('u', 1, 1, S + 9900, S + 9905), ('v', 2, 0, S + 9900, S + 9905)],
    {'reports': {'1': {'profile_ids': '[1,2]', 'results': '[1,0]'}, '2': {'profile_ids': '[1,2]', 'results': '[0,1]'}}})
c.commit(); c.close()
o.step2(db, log=lambda s: None)
c = sqlite3.connect(db)
q = lambda sql, *a: c.execute(sql, a).fetchall()
ok('early: first forgiven, second in 24 h loss_leave', q('SELECT sid, final, early_leave FROM own_match_players WHERE steam = "x" ORDER BY sid') == [(9001, 'none', 1), (9002, 'loss_leave', 1)])
ok('early: x rated only by his 2nd leave, y untouched', q('SELECT games, leaves, rating < 1500 FROM own_ratings WHERE steam = "x"') == [(1, 1, 1)]
   and q('SELECT COUNT(*) FROM own_ratings WHERE steam = "y"') == [(0,)])
ok('9003: p loss_leave, q loss w0.5, r/s win', q('SELECT steam, final, weight FROM own_match_players WHERE sid = 9003 ORDER BY steam') ==
   [('p', 'loss_leave', 1.0), ('q', 'loss', 0.5), ('r', 'win', 1.0), ('s', 'win', 1.0)])
dp, dq = [1500 - q('SELECT rating FROM own_ratings WHERE steam = ?', s)[0][0] for s in ('p', 'q')]
ok('weight 0.5 halves the drop', abs(dq - dp / 2) < 1e-6)
ok('9004 games disagree -> unrated', q('SELECT rated, why_unrated FROM own_matches WHERE sid = 9004') == [(0, 'reports_disagree')])
c.close()
ok('a broken DB -> False, no exception', o.step2(os.path.join(HERE, 'no_such_dir', 'x.sqlite'), log=lambda s: None) is False)
os.remove(db)
print('ALL %d OK' % N[0])
