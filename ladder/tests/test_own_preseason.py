#!/usr/bin/env python3
"""own rating preseason tests (17.11.2026): the season cutoff (own_season.json), the manual decisions (own_overrides, own_admin.py),
anti-abuse 3a (a match over before 4 min = unrated, the leaver still loses) and 3b (a 1v1 pair's 4th+ rated match in 24 h = weight
0.25). decide() on made-up matches + step2 on a temp DB; nothing live is touched.
usage: python3 test_own_preseason.py [<dir with own_matches.py, ladder.py>] [--live-copy <ladder.sqlite COPY>]
  --live-copy: the copy is copied again into a temp dir (the given file is only read) and reported: the preseason from now (must be
  empty) and the tables of the old rules (the copy's own_ratings as it came) vs the new rules on all the data."""
import json, os, shutil, sqlite3, subprocess, sys, tempfile, time
args = sys.argv[1:]; LIVE = None
if '--live-copy' in args: i = args.index('--live-copy'); LIVE = args[i + 1]; del args[i:i + 2]
APP = args[0] if args else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
import own_matches as o

T = tempfile.mkdtemp(prefix='own_pre_'); T0 = 1_800_000_000; N = [0]
def P(steam, team, rep=None, rep_t=None, leave=None): return dict(steam=steam, team=team, rep=rep, rep_t=rep_t, leave=leave)
def M(**k): d = dict(kind='mm', started=T0, end_est=False, conflict=False); d.update(k); return d
def F(r): return {s: v[0] for s, v in r['players'].items()}
def W(r): return {s: v[1] for s, v in r['players'].items()}
def ok(name, cond):
    N[0] += 1
    if not cond: print('FAIL', name); sys.exit(1)
    print('ok  ', name)
quiet = lambda s: None

# ---------- 3a: short matches ----------
r = o.decide(M(), [P('a', 1, 1, T0 + 200, T0 + 205), P('b', 2, 0, T0 + 200, T0 + 210)])
ok('3a: reports at 200 s -> short_match, unrated, finals kept', r['why'] == 'short_match' and r['rated'] == 0 and F(r) == {'a': 'win', 'b': 'loss'})
r = o.decide(M(), [P('a', 1, 1, T0 + 245, T0 + 250), P('b', 2, 0, T0 + 245, T0 + 250)])
ok('3a: reports at 245 s -> rated as before', r['why'] is None and r['rated'] == 1)
r = o.decide(M(), [P('a', 1, None, None, T0 + 150), P('b', 2, 1, T0 + 230, T0 + 235)])
ok('3a: left at 150 s, over at 230 s -> short_match, leaver loss_leave', r['why'] == 'short_match' and F(r) == {'a': 'loss_leave', 'b': 'win'})
r = o.decide(M(), [P('a', 1, None, None, T0 + 60), P('b', 2, 1, T0 + 100, T0 + 105)])
ok('3a: a leave before 120 s keeps the early-leave rule', r['why'] == 'early_leave')
r = o.decide(M(), [P('a', 1, 3, None, T0 + 200), P('b', 2, 3, None, T0 + 400)])
ok('3a: no 1/0, the loser gone at 200 s (node) -> short_match', r['why'] == 'short_match' and F(r) == {'a': 'loss_leave', 'b': 'win'} and r['result_src'] == 'node')
r = o.decide(M(kind='room'), [P('a', 1, 1, T0 + 200), P('b', 2, 0, T0 + 200)])
ok('3a: a short room match stays "room"', r['why'] == 'room')
r = o.decide(M(), [P('a', 1, 1, None), P('b', 2, 0, None)])
ok('3a: 1/0 without a time -> no length known, rated', r['why'] is None and r['rated'] == 1)

# ---------- 3b: the same 1v1 pair ----------
E = T0 + 900
G = [P('a', 1, 1, E, E + 5), P('b', 2, 0, E, E + 5)]
r = o.decide(M(), G, pair_before=lambda a, b: 2)
ok('3b: 3rd match of the pair in 24 h -> weight 1', W(r) == {'a': 1.0, 'b': 1.0} and r['rated'] == 1)
r = o.decide(M(), G, pair_before=lambda a, b: 3)
ok('3b: 4th -> weight 0.25 both, note repeat_pair', W(r) == {'a': o.REPEAT_W, 'b': o.REPEAT_W} and r['players']['a'][3] == 'repeat_pair'
   and 'repeat_pair_4' in r['notes'])
r = o.decide(M(), [P('a', 1, None, None, T0 + 500), P('b', 2, 1, E, E + 5)], pair_before=lambda a, b: 5)
ok('3b: the leaver too (0.25, both notes)', W(r) == {'a': o.REPEAT_W, 'b': o.REPEAT_W} and r['players']['a'][3].endswith(',repeat_pair'))
r = o.decide(M(), [P('a', 1, 1, E), P('a2', 1, 1, E), P('b', 2, 0, E), P('b2', 2, 0, E)], pair_before=lambda a, b: 9)
ok('3b: not for 2v2', set(W(r).values()) == {1.0})
r = o.decide(M(), [P('a', 1, 1, T0 + 200), P('b', 2, 0, T0 + 200)], pair_before=lambda a, b: 9)
ok('3b: not on an unrated match', set(W(r).values()) == {1.0})

# ---------- manual decisions ----------
D = [P('a', 1, 1, E, E + 5), P('b', 2, 1, E, E + 5)]                                # both say "I won"
ok('base: both 1 -> reports_disagree', o.decide(M(), D)['why'] == 'reports_disagree')
r = o.decide(M(override={'action': 'winner', 'team': 2}), D)
ok('winner 2 on reports_disagree -> rated, b win, a loss', r['rated'] == 1 and r['why'] is None and r['winner_team'] == 2
   and F(r) == {'a': 'loss', 'b': 'win'} and r['result_src'] == 'manual')
r = o.decide(M(override={'action': 'winner', 'team': 2}), D, pair_before=lambda a, b: 3)
ok('winner + 4th of the pair -> 0.25', W(r) == {'a': o.REPEAT_W, 'b': o.REPEAT_W})
r = o.decide(M(override={'action': 'void'}), G)
ok('void -> unrated why=void, finals kept', r['rated'] == 0 and r['why'] == 'void' and F(r) == {'a': 'win', 'b': 'loss'})
r = o.decide(M(override={'action': 'void'}), [P('a', 1, None, None, T0 + 40), P('b', 2, 1, T0 + 80, T0 + 85)], early_before=lambda s: 1)
ok('void of an early leave -> early flag cleared (not counted later)', r['why'] == 'void' and r['players']['a'][2] == 0)
r = o.decide(M(kind='room', override={'action': 'winner', 'team': 1}), D)
ok('winner on a room -> result set, still unrated room', r['why'] == 'room' and r['rated'] == 0 and F(r) == {'a': 'win', 'b': 'loss'})
r = o.decide(M(override={'action': 'winner', 'team': 7}), D)
ok('winner with a wrong team -> ignored, noted', r['why'] == 'reports_disagree' and 'manual_bad_team' in r['notes'])
r = o.decide(M(override={'action': 'winner', 'team': 1}), [P('a', 1, 1, T0 + 200), P('b', 2, 0, T0 + 200)])
ok('winner on a short match -> rated', r['rated'] == 1 and r['why'] is None)
r = o.decide(M(override={'action': 'winner', 'team': 1}), [P('a', 1, None, None, T0 + 500), P('a2', 1, 1, E), P('b', 2, None, None, T0 + 400), P('b2', 2, 0, E)])
ok('winner 1 in 2v2: a (team 1 leaver) win, b keeps loss_leave', F(r) == {'a': 'win', 'a2': 'win', 'b': 'loss_leave', 'b2': 'loss'})

# ---------- season_cfg ----------
def cfgfile(d, body):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, o.SEASON_FILE), 'w') as f: f.write(body)
ok('no file -> None', o.season_cfg(T + '/nofile', quiet) is None)
cfgfile(T + '/c1', '{"label": "2026-pre", "start": 1795000000}')
ok('file -> label/start', o.season_cfg(T + '/c1', quiet) == {'label': '2026-pre', 'start': 1795000000} and o.default_season(T + '/c1') == '2026-pre')
cfgfile(T + '/c2', '{"label": "a label that is too long", "start": 1}'); ok('too long a label -> None', o.season_cfg(T + '/c2', quiet) is None)
cfgfile(T + '/c3', '{broken'); ok('broken JSON -> None', o.season_cfg(T + '/c3', quiet) is None)
cfgfile(T + '/c4', '{"label": "x", "start": "1795000000"}'); ok('start as a string -> None', o.season_cfg(T + '/c4', quiet) is None)

# ---------- step2 on a temp DB ----------
def newdb(d):
    os.makedirs(d, exist_ok=True); fn = d + '/ladder.sqlite'
    c = sqlite3.connect(fn); o.migrate(c); c.execute('CREATE TABLE matches (id INTEGER PRIMARY KEY, data TEXT)'); c.commit(); return fn, c
def add(c, sid, start, ps, kind='mm', secs=900):
    """ps: (steam, team, rep) - the reports at start+secs, everybody leaves 10 s later"""
    c.execute('INSERT INTO own_matches (sid, lobby, kind, mode, modname, season, started, reports) VALUES (?,?,?,?,?,?,?,?)',   # 17.11: Elite (a preseason rates Elite only)
              (sid, 'NM-%d' % sid, kind, '%dv%d' % (len(ps) // 2, len(ps) // 2), 'Elite', '2027-Q1', start, json.dumps({'reports': {}})))
    for i, (st, team, rep) in enumerate(ps):
        c.execute('INSERT INTO own_match_players (sid, steam, pid, team, report_result, report_t, leave_t) VALUES (?,?,?,?,?,?,?)',
                  (sid, st, i + 1, team, rep, start + secs, start + secs + 10))
S = 1_800_000_000; H = 3600
fn, c = newdb(T + '/d1')
for i in range(5): add(c, 100 + i, S + i * H, [('x', 1, 1), ('y', 2, 0)])            # x beats y 5 times in 5 hours
add(c, 105, S + 30 * H, [('x', 1, 1), ('y', 2, 0)])                                   # a day later
add(c, 106, S + 31 * H, [('x', 1, 1), ('z', 2, 0)], secs=180)                          # short
add(c, 107, S + 32 * H, [('u', 1, 1), ('v', 2, 0)])                                   # another pair
c.commit(); c.close()
ok('step2 (no season file next to the DB)', o.step2(fn, log=quiet))
c = sqlite3.connect(fn); q = lambda sql, *a: c.execute(sql, a).fetchall()
ok('pair weights 1,1,1,0.25,0.25 then 1 a day later', [w for (w,) in q('SELECT weight FROM own_match_players WHERE steam = "x" AND sid < 106 ORDER BY sid')]
   == [1, 1, 1, o.REPEAT_W, o.REPEAT_W, 1])
ok('106: 180 s -> short_match, unrated', q('SELECT rated, why_unrated FROM own_matches WHERE sid = 106') == [(0, 'short_match')])
ok('z (only the short match) not in the table', q('SELECT COUNT(*) FROM own_ratings WHERE steam = "z"') == [(0,)])
ok('no file -> the quarter season, every match', q('SELECT season, games FROM own_ratings WHERE steam = "x"') == [('2027-Q1', 6)])
c.close()
# the same with a preseason from match 103 on
ok('step2 with a preseason from match 103', o.step2(fn, log=quiet, cfg={'label': '2027-pre', 'start': S + 3 * H}))
c = sqlite3.connect(fn)
ok('only 103+ counted, under the label (106 too: 180 s is not short in a preseason, 17.11)', q('SELECT season, games FROM own_ratings WHERE steam = "x"') == [('2027-pre', 4)]
   and q('SELECT DISTINCT season FROM own_ratings') == [('2027-pre',)])
ok('pair count restarts at the preseason start: 103, 104 weight 1', [w for (w,) in q('SELECT weight FROM own_match_players WHERE steam = "x" AND sid IN (103, 104) ORDER BY sid')] == [1, 1])
c.close()
# the file next to the DB is read by step2 (as match_log_collect calls it)
cfgfile(T + '/d1', json.dumps({'label': '2027-pre', 'start': S + 100 * H}))
o.step2(fn, log=quiet); c = sqlite3.connect(fn)
ok('own_season.json next to the DB, start after every match -> empty table', q('SELECT COUNT(*) FROM own_ratings') == [(0,)])
c.close(); os.remove(T + '/d1/' + o.SEASON_FILE)

# ---------- overrides survive the recompute; own_admin.py ----------
ADM = [sys.executable, os.path.join(APP, 'own_admin.py'), '--db', fn]
def adm(*a): return subprocess.run(ADM + list(a), capture_output=True, text=True)
x = adm('void', '107', 'test: farm'); ok('own_admin void -> exit 0', x.returncode == 0)
c = sqlite3.connect(fn)
ok('107 void, u/v not rated', q('SELECT rated, why_unrated, result_src FROM own_matches WHERE sid = 107') == [(0, 'void', 'manual')]
   and q('SELECT COUNT(*) FROM own_ratings WHERE steam IN ("u", "v")') == [(0,)])
c.close(); o.step2(fn, log=quiet); o.step2(fn, log=quiet); c = sqlite3.connect(fn)
ok('void survives two more recomputes', q('SELECT why_unrated FROM own_matches WHERE sid = 107') == [('void',)])
c.close()
x = adm('winner', 'NM-106', '2', 'z actually won'); ok('own_admin winner NM-106 2 -> exit 0', x.returncode == 0)
c = sqlite3.connect(fn)
ok('106 winner team 2: z win, rated', q('SELECT steam, final FROM own_match_players WHERE sid = 106 ORDER BY steam') == [('x', 'loss'), ('z', 'win')]
   and q('SELECT rated, winner_team FROM own_matches WHERE sid = 106') == [(1, 2)] and q('SELECT games FROM own_ratings WHERE steam = "z"') == [(1,)])
c.close()
ok('own_admin winner with a team not in the match -> refused', adm('winner', '106', '5').returncode != 0)
ok('own_admin void without a note -> refused', adm('void', '105').returncode != 0)
ok('own_admin unknown match -> refused', adm('void', '999', 'x').returncode != 0)
x = adm('clear', '107', 'undo'); c = sqlite3.connect(fn)
ok('clear -> 107 back to the rules (rated)', x.returncode == 0 and q('SELECT rated, why_unrated FROM own_matches WHERE sid = 107') == [(1, None)])
ok('the log keeps every decision', q('SELECT match_id, action FROM own_overrides ORDER BY id') == [(107, 'void'), (106, 'winner'), (107, 'clear')])
c.close()
x = adm('list'); ok('own_admin list', x.returncode == 0 and 'match 107 void' in x.stdout and '107=rules' in x.stdout and '106=winner' in x.stdout)
x = adm('--no-recompute', 'void', '105', 'n'); c = sqlite3.connect(fn)
ok('--no-recompute: written, not applied yet', x.returncode == 0 and q('SELECT why_unrated FROM own_matches WHERE sid = 105') == [(None,)])
c.close(); o.step2(fn, log=quiet); c = sqlite3.connect(fn)
ok('... applied by the next step2', q('SELECT why_unrated FROM own_matches WHERE sid = 105') == [('void',)]); c.close()

# ---------- the site: default season, player history, /own/season ----------
o.setup(lambda: sqlite3.connect(fn), __import__('threading').Lock(), lambda t: '2027-Q1', data_dir=T + '/d1')
ok('site_season without the file', o.site_season() == {'preseason': False, 'label': None, 'start': None, 'info': None})
ok('default_season without the file -> None (the API takes the quarter)', o.default_season() is None)
ok('site_player: every match without the file', len(o.site_player('x')['matches']) == 7)
ok('site_player without the file: no previous season, no roster', o.site_player('x')['prev'] is None and o.site_player('x')['cal_modes'] == [])
cfgfile(T + '/d1', json.dumps({'label': '2027-pre', 'start': S + 3 * H})); o.step2(fn, log=quiet)
ok('site_season with the file', o.site_season() == {'preseason': True, 'label': '2027-pre', 'start': S + 3 * H, 'info': None})
cfgfile(T + '/d1', json.dumps({'label': '2027-pre', 'start': S + 3 * H, 'info': 'https://example.org/elite#preseason'}))
ok('season_cfg: info kept (https)', o.season_cfg(T + '/d1', quiet).get('info') == 'https://example.org/elite#preseason')
cfgfile(T + '/d1', json.dumps({'label': '2027-pre', 'start': S + 3 * H, 'info': 'javascript:alert(1)'}))
ok('season_cfg: info not https -> dropped, the season kept', 'info' not in o.season_cfg(T + '/d1', quiet) and o.season_cfg(T + '/d1', quiet)['label'] == '2027-pre')
cfgfile(T + '/d1', json.dumps({'label': '2027-pre', 'start': S + 3 * H}))
ok('default_season -> the label', o.default_season() == '2027-pre')
b = o.site_board('1v1', o.default_season())
ok('site_board of the preseason', b['seasons'] == ['2027-pre'] and b['season'] == '2027-pre' and len(b['calibrating']) + len(b['board']) > 0)
ok('site_player: only the preseason matches', sorted(m['sid'] for m in o.site_player('x')['matches']) == [103, 104, 105, 106])
# /own/all (launcher 1.6.20): every player of the season, every mode; the number and the place as the site's table, none while calibrating
a = o.site_all(o.default_season()); b1 = o.site_board('1v1', o.default_season())
ok('site_all: the season and the calibration length', a['season'] == '2027-pre' and a['cal_games'] == o.CAL_GAMES)
ok('site_all: the same players as the 1v1 board', {s for s, m in a['players'].items() if '1v1' in m} == {p['steam'] for p in b1['board'] + b1['calibrating']})
ok('site_all: c / rank as the board', all(a['players'][p['steam']]['1v1'].get('c') == p['cons'] and a['players'][p['steam']]['1v1'].get('rank') == p['rank'] for p in b1['board']))
ok('site_all: calibrating - games left, no number', all('c' not in a['players'][p['steam']]['1v1'] and a['players'][p['steam']]['1v1']['cal'] == p['cal_left'] for p in b1['calibrating']))
ok('site_all: an unknown season - empty', o.site_all('1999-Q1')['players'] == {})
# 17.11.2026 (SirItos): the test's players stay in the preseason's table (calibration 0/5), the profile shows the previous season
c = sqlite3.connect(fn); add(c, 99, S - 5 * H, [('w', 1, 1), ('x', 2, 0)]); c.commit(); c.close(); o.step2(fn, log=quiet); c = sqlite3.connect(fn)
b = o.site_board('1v1', o.default_season()); rw = {p['steam']: p for p in b['rows']}
ok('roster: w (a rated Elite match before the start only) in calibration 0/5', 'w' in rw and rw['w']['calibrating'] and
   (rw['w']['cal_played'], rw['w']['games'], rw['w']['wins'], rw['w']['cal_left']) == (0, 0, 0, o.CAL_GAMES) and rw['w']['rank'] is None)
ok('roster: the rated players unchanged, each once', [p['steam'] for p in b['rows']].count('x') == 1 and all(p['steam'] != 'w' for p in b['board']))
ok('roster: not in another mode', all(p['steam'] != 'w' for p in o.site_board('2v2', o.default_season())['rows']))
ok('roster: not in an old season\'s board', all(p['steam'] != 'w' for p in o.site_board('1v1', '2027-Q1')['rows']))
ok('roster: own_ratings still the preseason only, w not in it; /own/all without him', q('SELECT DISTINCT season FROM own_ratings') == [('2027-pre',)]
   and q('SELECT COUNT(*) FROM own_ratings WHERE steam = "w"') == [(0,)] and 'w' not in o.site_all(o.default_season())['players'])
pw, px = o.site_player('w'), o.site_player('x')
ok('previous season: w 1v1 1 game (calibrating), cal_modes 1v1', pw['prev'] and pw['prev']['season'] == '2027-Q1' and
   [(r['mode'], r['games'], r['wins'], r['cal_left']) for r in pw['prev']['ratings']] == [('1v1', 1, 1, o.CAL_GAMES - 1)] and pw['cal_modes'] == ['1v1'] and pw['ratings'] == [])
ok('previous season: x 4 games before the start (99-102), 3 wins', [(r['games'], r['wins'], r['losses']) for r in px['prev']['ratings']] == [(4, 3, 1)])
ok('previous season: old rules (the quarter season), the preseason number apart', q('SELECT DISTINCT season FROM own_ratings_prev') == [('2027-Q1',)]); c.close()
shutil.rmtree(T + '/d1')

# ---------- the live copy ----------
if LIVE:
    def board(c):
        nm = {s: n for s, n in c.execute('SELECT steam, name FROM own_match_players WHERE coalesce(name, "") != "" ORDER BY sid')}
        rows = c.execute('SELECT season, mode, steam, rating, rd, games, wins, losses, leaves, cal_left FROM own_ratings ORDER BY season, mode, cons DESC').fetchall()
        return {(s, m, st): (nm.get(st, st), r, rd, g, w, l, lv, cl) for s, m, st, r, rd, g, w, l, lv, cl in rows}
    def fmt(k, v):
        name, r, rd, g, w, l, lv, cl = v
        return '%-6s %-20s %s  games %2d  %2d-%2d-%d' % (k[1], name[:20], ('cons %5d (%4d±%3d)' % (r - 2 * rd, r, rd)) if not cl else ('calibration %d/5     ' % g), g, w, l - lv, lv)
    d = T + '/live'; os.makedirs(d); fn = d + '/ladder.sqlite'
    src = sqlite3.connect('file:%s?mode=ro' % os.path.abspath(LIVE), uri=True); dst = sqlite3.connect(fn); src.backup(dst); src.close(); dst.close()
    c = sqlite3.connect(fn); old = board(c)
    nm_all = c.execute('SELECT COUNT(*), COUNT(DISTINCT p.steam) FROM own_matches m JOIN own_match_players p ON p.sid = m.sid').fetchone()
    print('\n=== live copy: %d own matches, %d player rows (old rules: rated %d) ===' % (
        c.execute('SELECT COUNT(*) FROM own_matches').fetchone()[0], len(old), c.execute('SELECT COUNT(*) FROM own_matches WHERE rated = 1').fetchone()[0]))
    c.close()
    now = int(time.time())
    o.step2(fn, log=lambda s: print('  ' + s), cfg={'label': '2026-pre', 'start': now})
    c = sqlite3.connect(fn)
    n_m = c.execute('SELECT COUNT(*) FROM own_matches WHERE started >= ?', (now,)).fetchone()[0]
    n_p = c.execute('SELECT COUNT(DISTINCT steam) FROM own_ratings').fetchone()[0]
    print('preseason from now (%d): %d matches, %d players in own_ratings' % (now, n_m, n_p))
    ok('live copy: preseason from now is empty', n_m == 0 and n_p == 0)
    c.close()
    o.step2(fn, log=lambda s: print('  ' + s), cfg=None)        # the new rules (3a, 3b) on all the data, no cutoff
    c = sqlite3.connect(fn); new = board(c)
    print('\nmatches changed by 3a (short_match):')
    for sid, mode, st, notes in c.execute('SELECT sid, mode, started, notes FROM own_matches WHERE why_unrated = "short_match" ORDER BY started'):
        names = ' vs '.join(','.join(n or s for s, n in c.execute('SELECT steam, name FROM own_match_players WHERE sid = ? AND team = ?', (sid, t)))
                            for (t,) in c.execute('SELECT DISTINCT team FROM own_match_players WHERE sid = ? ORDER BY team', (sid,)))
        print('  %d %s %s %s  %s' % (sid, mode, time.strftime('%m-%d %H:%M', time.gmtime(st)), notes, names))
    rp = c.execute('SELECT m.sid, m.started, m.notes FROM own_matches m WHERE m.notes LIKE "%repeat_pair%" ORDER BY m.started').fetchall()
    print('\nmatches at weight %.2f by 3b (repeat pair): %d' % (o.REPEAT_W, len(rp)))
    pairs = {}
    for sid, st, notes in rp:
        k = ' vs '.join(sorted(n or s for s, n in c.execute('SELECT steam, name FROM own_match_players WHERE sid = ?', (sid,))))
        pairs.setdefault(k, []).append(sid)
    for k, v in sorted(pairs.items(), key=lambda kv: -len(kv[1])): print('  %-40s %d matches' % (k, len(v)))
    print('\nwhy unrated (new rules):', dict(c.execute("SELECT coalesce(why_unrated, 'rated'), COUNT(*) FROM own_matches GROUP BY 1")))
    for mode in ('1v1', '2v2', '3v3'):
        print('\n--- %s: OLD rules (live own_ratings) ---' % mode)
        for k, v in sorted(((k, v) for k, v in old.items() if k[1] == mode), key=lambda kv: (kv[1][7] > 0, -(kv[1][1] - 2 * kv[1][2]))): print('  ' + fmt(k, v))
        print('--- %s: NEW rules (3a + 3b), all data ---' % mode)
        for k, v in sorted(((k, v) for k, v in new.items() if k[1] == mode), key=lambda kv: (kv[1][7] > 0, -(kv[1][1] - 2 * kv[1][2]))): print('  ' + fmt(k, v))
    c.close()
shutil.rmtree(T, ignore_errors=True)
print('ALL %d OK' % N[0])
