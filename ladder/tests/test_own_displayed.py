#!/usr/bin/env python3
"""The displayed own rating, variant B (20.11.2026, SirItos): the table / launcher / player page / match list number never goes up after
a loss nor down after a win (greysky 19.11: three losses after calibration showed +16 / +13 / +10 - the conservative rating
mean - 2*RD rose because RD fell faster than the mean). Glicko (mean, RD) unchanged; displayed = conservative made monotonic by the result.
Run: python3 ladder/tests/test_own_displayed.py [dir with own_matches.py]   (a temp DB; nothing live)"""
import os, sqlite3, sys, tempfile, threading
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import own_matches as o
fails = []
def ok(name, cond, info=''):
    print('  %-80s %s' % (name, 'ok' if cond else 'FAIL %s' % (info,)))
    if not cond: fails.append(name)
fn = tempfile.mktemp(suffix='.sqlite'); c = sqlite3.connect(fn); o.migrate(c)
T0 = 1_800_000_000; SID = [100]
def match(a, b, winner):           # a 1v1, a vs b; winner 'a' / 'b'
    SID[0] += 1; s = SID[0]
    c.execute('INSERT INTO own_matches (sid, lobby, kind, mode, map, modname, started, season, rated) VALUES (?,?,?,?,?,?,?,?,1)',
              (s, 'NM-%d' % s, 'mm', '1v1', 'm', 'Elite', T0 + s * 100, '2027-Q1'))
    for st, team, fin in ((a, 1, 'win' if winner == 'a' else 'loss'), (b, 2, 'win' if winner == 'b' else 'loss')):
        c.execute('INSERT INTO own_match_players (sid, steam, pid, team, final, weight) VALUES (?,?,?,?,?,1)', (s, st, 1, team, fin))
# greysky's pattern: calibration 1-4 against a strong / weak field, then losses right after calibration while RD still falls fast
for i in range(5): match('G', 'S%d' % i, 'b' if i % 2 else 'a')                     # calibration: 3 wins, 2 losses
for i in range(3): match('G', 'T%d' % i, 'b')                                         # three losses after calibration
for i in range(3): match('G', 'U%d' % i, 'a')                                         # three wins
for i in range(6): match('W', 'V%d' % i, 'a')                                         # another player: wins only
c.commit()
o.recompute_own(c, log=lambda *a: None); c.commit()
rows = c.execute('SELECT m.sid, p.final, p.own_c, p.own_d, p.own_n FROM own_match_players p JOIN own_matches m ON m.sid = p.sid '
                 'WHERE p.steam = ? ORDER BY m.started', ('G',)).fetchall()
print('   G:', [(f, None if oc is None else round(oc), None if od is None else round(od)) for _, f, oc, od, _ in rows])
ok('calibration: no number, the 5th match shows the first (no change)', all(r[2] is None for r in rows[:4]) and rows[4][2] is not None and rows[4][3] is None)
ok('every loss after calibration: change <= 0', all(r[3] <= 0 for r in rows[5:] if r[1] == 'loss'), [r[3] for r in rows[5:8]])
ok('every win: change >= 0', all(r[3] >= 0 for r in rows[5:] if r[1] == 'win'), [r[3] for r in rows[8:]])
ok('own_d = the step of own_c', all(abs((rows[i][2] - rows[i - 1][2]) - rows[i][3]) < 1e-6 for i in range(5, len(rows))))
# the raw conservative really rose on a loss here (what variant B is for) - recompute it by Glicko alone
g = c.execute("SELECT rating, rd, cons FROM own_ratings WHERE steam = 'G'").fetchone()
ok('own_ratings.cons = the displayed number (= the last own_c)', abs(g[2] - rows[-1][2]) < 1e-6, (g, rows[-1][2]))
ok('the mean / RD kept (the queue): rating, rd are Glicko', g[0] > 1000 and 0 < g[1] < 350)
# the readers: the table, the launcher (/own/all), the player page and its match list, the launcher object
o.setup(lambda: sqlite3.connect(fn), threading.Lock(), lambda t: '2027-Q1', data_dir=tempfile.mkdtemp())
b = o.site_board('1v1', '2027-Q1'); bp = {p['steam']: p for p in b['board']}
ok('site_board: cons = the displayed', bp['G']['cons'] == round(g[2]))
ok('site_board: ordered by the displayed', [p['cons'] for p in b['board']] == sorted([p['cons'] for p in b['board']], reverse=True))
a = o.site_all('2027-Q1')
ok('/own/all (launcher): c = the displayed, rank as the board', a['players']['G']['1v1']['c'] == bp['G']['cons'] and a['players']['G']['1v1']['rank'] == bp['G']['rank'])
sp = o.site_player('G')
ok('player page: the rating row = the displayed', sp['ratings'][0]['cons'] == bp['G']['cons'] and sp['ratings'][0]['rank'] == bp['G']['rank'])
mm = {m['sid']: m['me'] for m in sp['matches']}
ok('player page match list: c / d from own_c / own_d, losses never up',
   all(mm[r[0]]['d'] is None or (mm[r[0]]['d'] <= 0 if r[1] == 'loss' else mm[r[0]]['d'] >= 0) for r in rows) and mm[rows[-1][0]]['c'] == round(rows[-1][2]))
o._CACHE['t'] = 0; o.api_season = lambda quarter=None: ('2027-Q1', False)   # no season file here: this quarter
ok('launcher object (player_own): conservative = the displayed', o.player_own('G')['modes']['1v1']['conservative'] == bp['G']['cons'])
ok('the queue still gets the Glicko mean', round(o.mm_rating('G', '1v1')[0]) == round(g[0]))
ok('shown(): first, win, loss', o.shown(None, 1400, 'loss') == 1400 and o.shown(1400, 1380, 'win') == 1400 and o.shown(1400, 1420, 'loss') == 1400
   and o.shown(1400, 1420, 'win') == 1420 and o.shown(1400, 1380, 'loss_leave') == 1380)
print('ALL OK' if not fails else 'FAILED: %s' % fails); sys.exit(1 if fails else 0)
