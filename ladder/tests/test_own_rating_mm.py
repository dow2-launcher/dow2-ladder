#!/usr/bin/env python3
"""own rating, the preseason's server side (17.11.2026, SirItos): 3-minute early leave / short match, Elite only, the match's mod
recorded, the queue by OUR rating with a window widening with the wait, the one table (rated, then calibration by name), the
launcher's own object. Everything behind data/own_season.json: without it nothing changes - checked against the code of main.
usage: python3 test_own_rating_mm.py [<app dir>] [--base <app dir of main>] [--live-copy <ladder.sqlite COPY>]
  --base: the ladder/ of the commit before (default: `git show HEAD~0:ladder/...` of origin/main written to a temp dir)
  --live-copy: a copy (only read) of the live DB's own tables: step 2 of main and of this code must give the same results there
  without the season file; with it, the effect is printed. Nothing live is touched."""
import json, os, shutil, sqlite3, subprocess, sys, tempfile, time
args = sys.argv[1:]; LIVE = BASE = None
if '--live-copy' in args: i = args.index('--live-copy'); LIVE = args[i + 1]; del args[i:i + 2]
if '--base' in args: i = args.index('--base'); BASE = args[i + 1]; del args[i:i + 2]
APP = os.path.abspath(args[0] if args else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
T = tempfile.mkdtemp(prefix='own_mm_')
N = [0]
def ok(name, cond):
    N[0] += 1
    if not cond: print('FAIL', name); sys.exit(1)
    print('ok  ', name)
quiet = lambda s: None

if not BASE:                                             # main's ladder/ (the code before this change)
    BASE = T + '/base'; os.makedirs(BASE)
    repo = os.path.dirname(APP)
    for f in ('ladder.py', 'own_matches.py', 'users.py', 'community.py', 'stream.py', 'lroom.py', 'live.py', 'inbox.py', 'nodeq.py',
              'maps.txt', 'assets_index.json', 'capture.py', 'relay_links.py'):
        r = subprocess.run(['git', '-C', repo, 'show', 'origin/main:ladder/' + f], capture_output=True)
        if r.returncode == 0: open(os.path.join(BASE, f), 'wb').write(r.stdout)
    ok('base: main\'s ladder.py and own_matches.py', os.path.exists(BASE + '/ladder.py') and os.path.exists(BASE + '/own_matches.py'))

sys.path.insert(0, APP)
import own_matches as o

def P(steam, team, rep=None, rep_t=None, leave=None): return dict(steam=steam, team=team, rep=rep, rep_t=rep_t, leave=leave)
T0 = 1_800_000_000
def M(**k): d = dict(kind='mm', started=T0, end_est=False, conflict=False); d.update(k); return d
PRE = dict(early_s=o.PRE_EARLY_S, short_s=o.PRE_SHORT_S, elite_only=True)
def F(r): return {s: v[0] for s, v in r['players'].items()}

# ---------- 1. the 3-minute rules (only with the season) ----------
r = o.decide(M(), [P('a', 1, None, None, T0 + 150), P('b', 2, 1, T0 + 400, T0 + 405)])
ok('no season: a leave at 150 s is a normal leave (loss_leave, rated) - as before', r['why'] is None and r['rated'] == 1 and F(r)['a'] == 'loss_leave')
r = o.decide(M(mod='Elite', **PRE), [P('a', 1, None, None, T0 + 150), P('b', 2, 1, T0 + 400, T0 + 405)])
ok('preseason: a leave at 150 s -> early_leave, unrated, forgiven (first in a day)', r['why'] == 'early_leave' and r['rated'] == 0
   and r['players']['a'][3] == 'early_forgiven' and F(r)['a'] == 'none')
r = o.decide(M(mod='Elite', **PRE), [P('a', 1, None, None, T0 + 150), P('b', 2, 1, T0 + 400, T0 + 405)], early_before=lambda s: 1)
ok('preseason: the 2nd early leave in a day -> loss_leave for the leaver only', r['why'] == 'early_leave' and F(r) == {'a': 'loss_leave', 'b': 'none'})
r = o.decide(M(mod='Elite', **PRE), [P('a', 1, None, None, T0 + 185), P('b', 2, 1, T0 + 400, T0 + 405)])
ok('preseason: a leave at 185 s -> a rated loss_leave', r['why'] is None and r['rated'] == 1 and F(r)['a'] == 'loss_leave')
r = o.decide(M(), [P('a', 1, 1, T0 + 200, T0 + 205), P('b', 2, 0, T0 + 200, T0 + 205)])
ok('no season: over at 200 s -> short_match (240 s) - as before', r['why'] == 'short_match')
r = o.decide(M(mod='Elite', **PRE), [P('a', 1, 1, T0 + 200, T0 + 205), P('b', 2, 0, T0 + 200, T0 + 205)])
ok('preseason: over at 200 s -> rated (threshold 180 s)', r['why'] is None and r['rated'] == 1)
r = o.decide(M(mod='Elite', **PRE), [P('a', 1, 1, T0 + 170, T0 + 175), P('b', 2, 0, T0 + 170, T0 + 175)])
ok('preseason: a surrender at 170 s -> short_match, unrated', r['why'] == 'short_match' and r['rated'] == 0)

# ---------- 2. Elite only ----------
G = [P('a', 1, 1, T0 + 900, T0 + 905), P('b', 2, 0, T0 + 900, T0 + 905)]
r = o.decide(M(mod='DOW2', **PRE), G)
ok('preseason: a vanilla match -> unrated not_elite, the result kept', r['why'] == 'not_elite' and r['rated'] == 0 and F(r) == {'a': 'win', 'b': 'loss'})
ok('preseason: mod unknown -> not_elite', o.decide(M(mod=None, **PRE), G)['why'] == 'not_elite')
ok('preseason: Elite -> rated', o.decide(M(mod='Elite', **PRE), G)['rated'] == 1)
ok('no season: vanilla rated as before', o.decide(M(mod='DOW2'), G)['rated'] == 1)
r = o.decide(M(mod='DOW2', override={'action': 'winner', 'team': 2}, **PRE), G)
ok('a manual winner does not rate a vanilla match', r['why'] == 'not_elite' and r['rated'] == 0 and F(r) == {'a': 'loss', 'b': 'win'})
ok('mod_of', [o.mod_of(x) for x in ('elite-3.2.1', 'Elite', 'elite', 'vanilla', 'DOW2', '', None, 'other')] ==
   ['Elite', 'Elite', 'Elite', 'DOW2', 'DOW2', None, None, None])
ok('_game_of: game, classic pool, native pool, launcher room pool', [o._game_of(m) for m in (
    {'game': 'elite-3.2.1'}, {'pool': '|vanilla'}, {'pool': 'grp|elite-3.2.1|nm|k'}, {'pool': 'lroom:7||elite|nm|k'}, {})] ==
   ['Elite', 'DOW2', 'Elite', 'Elite', None])

# ---------- 3. storage: on_start writes the mod, step 2 fills the old rows from matches ----------
def newdb(d):
    os.makedirs(d, exist_ok=True); fn = d + '/ladder.sqlite'
    c = sqlite3.connect(fn); o.migrate(c); c.execute('CREATE TABLE matches (id INTEGER PRIMARY KEY, data TEXT)'); c.commit(); return fn, c
fn, c = newdb(T + '/s1'); c.close()
import threading
o.setup(lambda: sqlite3.connect(fn), threading.Lock(), lambda t: '2027-Q1', data_dir=T + '/s1')
o.on_start({'lobby': 'NM-11', 'started': T0, 'mode': '1v1', 'pool': '|elite-3.2.1|nm|k'}, [{'steam': 'x', 'team': 1}, {'steam': 'y', 'team': 2}])
o.on_start({'lobby': 'NM-12', 'started': T0, 'mode': '1v1', 'game': 'vanilla'}, [{'steam': 'x', 'team': 1}, {'steam': 'y', 'team': 2}])
c = sqlite3.connect(fn)
ok('on_start stores the mod (pool / game)', c.execute('SELECT sid, modname FROM own_matches ORDER BY sid').fetchall() == [(11, 'Elite'), (12, 'DOW2')])
c.execute('INSERT INTO own_matches (sid, lobby, kind, started) VALUES (13, "NM-13", "mm", ?)', (T0,))
c.execute('INSERT INTO matches VALUES (13, ?)', (json.dumps({'modname': 'Elite'}),))
c.execute('INSERT INTO own_matches (sid, lobby, kind, started) VALUES (14, "NM-14", "mm", ?)', (T0,))
ok('fill_mods: from matches.data, only empty rows', o.fill_mods(c) == 1 and
   c.execute('SELECT sid, modname FROM own_matches ORDER BY sid').fetchall() == [(11, 'Elite'), (12, 'DOW2'), (13, 'Elite'), (14, None)])
c.close()

# ---------- 4. step 2: vanilla out of the table only with the season ----------
fn, c = newdb(T + '/s2')
def add(c, sid, start, ps, mod='Elite', secs=900):
    c.execute('INSERT INTO own_matches (sid, lobby, kind, mode, modname, season, started, reports) VALUES (?,?,?,?,?,?,?,?)',
              (sid, 'NM-%d' % sid, 'mm', '1v1', mod, '2027-Q1', start, json.dumps({'reports': {}})))
    for i, (st, team, rep) in enumerate(ps):
        c.execute('INSERT INTO own_match_players (sid, steam, pid, name, team, report_result, report_t, leave_t) VALUES (?,?,?,?,?,?,?,?)',
                  (sid, st, i + 1, st.upper(), team, rep, start + secs, start + secs + 10))
S = 1_800_000_000; H = 3600
add(c, 1, S, [('p', 1, 1), ('q', 2, 0)])
add(c, 2, S + H, [('p', 1, 1), ('r', 2, 0)], mod='DOW2')
add(c, 3, S + 2 * H, [('s', 1, 1), ('q', 2, 0)], secs=200)          # 200 s: short before, rated in the preseason
c.commit(); c.close()
o.step2(fn, log=quiet, cfg=None); c = sqlite3.connect(fn)
ok('no season: vanilla rated, 200 s short', c.execute('SELECT sid, rated, why_unrated FROM own_matches ORDER BY sid').fetchall() ==
   [(1, 1, None), (2, 1, None), (3, 0, 'short_match')])
c.close()
o.step2(fn, log=quiet, cfg={'label': 'pre', 'start': S}); c = sqlite3.connect(fn)
ok('preseason: vanilla not_elite (r not in the table), 200 s rated', c.execute('SELECT sid, rated, why_unrated FROM own_matches ORDER BY sid').fetchall() ==
   [(1, 1, None), (2, 0, 'not_elite'), (3, 1, None)] and c.execute('SELECT COUNT(*) FROM own_ratings WHERE steam = "r"').fetchone() == (0,)
   and c.execute('SELECT games FROM own_ratings WHERE steam = "p"').fetchone() == (1,))
c.close()

# ---------- 5. the one table and the launcher's own object ----------
fn, c = newdb(T + '/s3')
rows = [('a', '1v1', 'pre', 1700, 60, 0.06, 9, 7, 2, 1, 0), ('b', '1v1', 'pre', 1800, 120, 0.06, 6, 5, 1, 0, 0),
        ('c', '1v1', 'pre', 1600, 200, 0.06, 2, 1, 1, 0, 3), ('D', '1v1', 'pre', 1400, 250, 0.06, 1, 0, 1, 1, 4),
        ('e', '1v1', 'pre', 1550, 300, 0.06, 1, 1, 0, 0, 4), ('a', '2v2', 'pre', 1450, 280, 0.06, 1, 0, 1, 0, 4)]
for r in rows: c.execute('INSERT INTO own_ratings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', r + (r[3] - 2 * r[4], S))
for i, (st, nm) in enumerate((('a', 'Zed'), ('b', 'yan'), ('c', 'carl'), ('D', 'Bob'), ('e', 'alice'))):
    c.execute('INSERT INTO own_match_players (sid, steam, name, team) VALUES (?,?,?,1)', (100 + i, st, nm))
c.commit(); c.close()
o.setup(lambda: sqlite3.connect(fn), threading.Lock(), lambda t: 'q', data_dir=T + '/s3')
b = o.site_board('1v1', 'pre')
ok('rows: rated by the shown rating (a 1580 > b 1560), then calibration by name (alice, Bob, carl)',
   [(p['steam'], p['calibrating']) for p in b['rows']] == [('a', False), ('b', False), ('e', True), ('D', True), ('c', True)])
ok('rows: rank and the rating only for the rated; calibration k/5', b['rows'][0]['rank'] == 1 and b['rows'][0]['cons'] == 1580
   and b['rows'][2]['rank'] is None and 'cons' not in b['rows'][2] and (b['rows'][4]['cal_played'], b['rows'][4]['cal_needed']) == (2, 5))
ok('the old fields stay (board / calibrating)', [p['steam'] for p in b['board']] == ['a', 'b'] and len(b['calibrating']) == 3)
o._CACHE['t'] = 0
own = o.player_own('a', quarter='pre')
ok('player_own without a season file: the quarter given, preseason false', own['season'] == 'pre' and own['preseason'] is False and own['mod'] == 'Elite')
ok('player_own 1v1 rated: rating/rd/conservative/games/wins/losses(without leaves)/leaves', own['modes']['1v1'] ==
   {'rating': 1700, 'rd': 60, 'conservative': 1580, 'games': 9, 'wins': 7, 'losses': 1, 'leaves': 1, 'calibrating': False, 'cal_played': 5, 'cal_needed': 5})
ok('player_own 2v2 in calibration: rating hidden', own['modes']['2v2']['rating'] is None and own['modes']['2v2']['calibrating'] and own['modes']['2v2']['cal_played'] == 1)
ok('player_own 3v3 never played: 0/5', own['modes']['3v3'] == o.own_mode(None) and own['modes']['3v3']['cal_played'] == 0)
ok('card_own: only the played modes, short', o.card_own('a', 'pre') == {'1v1': {'rating': 1580, 'calibrating': False, 'cal_played': 5},
                                                                        '2v2': {'rating': None, 'calibrating': True, 'cal_played': 1}})
ok('card_own of a stranger: {}', o.card_own('zz', 'pre') == {})
with open(T + '/s3/' + o.SEASON_FILE, 'w') as f: json.dump({'label': 'pre', 'start': S}, f)
o._CACHE['t'] = 0
ok('with the season file: season = its label, preseason true', o.player_own('a', quarter='2027-Q1')['season'] == 'pre' and o.player_own('a')['preseason'])
ok('mm_rating: rated -> the mean, calibration -> 1500 + RD, new -> 1500/350', (o.mm_rating('a', '1v1'), o.mm_rating('c', '1v1'), o.mm_rating('zz', '1v1')) ==
   ((1700, 60, 9, 'own'), (1500.0, 200, 2, 'own_cal'), (1500.0, 350.0, 0, 'own_new')))
ok('mm_window: 150 at 0, 250 at 2 min, +RD over 100, none from 6 min',
   (o.mm_window(0), o.mm_window(120), o.mm_window(0, 350), o.mm_window(359), o.mm_window(360)) == (150, 250, 400, 150 + 50 * 359 / 60, None))
os.remove(T + '/s3/' + o.SEASON_FILE)

# ---------- 6. the queue: main's ladder vs this one (subprocesses: two ladders cannot share one interpreter) ----------
DRIVER = r'''
import json, os, random, shutil, sqlite3, sys, tempfile
app, out, season, scen = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
T = tempfile.mkdtemp(prefix='mmdrv_'); shutil.copytree(app, T + '/app', ignore=shutil.ignore_patterns('__pycache__', '*.bak*', 'tests'))
os.makedirs(T + '/data'); sys.path.insert(0, T + '/app'); os.environ['LADDER_NO_CRAWL'] = '1'
os.environ['MM_FAIR'] = '0'   # 20.11.2026: the map history / varied teams off - main's very picks (they are tested in test_mm_fair.py)
json.dump({'elite': {'1v1': ['m1', 'm2', 'm3'], '2v2': ['n1', 'n2'], '3v3': ['k1']}, 'vanilla': {'1v1': ['v1']}}, open(T + '/data/nm_maps.json', 'w'))
CLOCK = [1_800_000_000.0]
import time as _time
_time.time = lambda: CLOCK[0]
import ladder as L, own_matches as O
RATING = {}
L._rating_info = lambda steam, mode: (int(steam[-4:]), RATING.get(steam, 1500.0), 200.0, 3, 'P' + steam[-4:], 'ladder')
if season == 'on':
    json.dump({'label': 'tpre', 'start': 1}, open(T + '/data/own_season.json', 'w'))
    c = sqlite3.connect(T + '/data/ladder.sqlite'); O.migrate(c)
    for steam, mode, r, rd, g, cl in json.loads(sys.argv[5]):
        c.execute('INSERT INTO own_ratings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', (steam, mode, 'tpre', r, rd, 0.06, g, g, 0, 0, cl, r - 2 * rd, 1))
    c.commit(); c.close()
def S(i): return '7656119%010d' % i
res = []
def snap(tag):
    ms = []
    for mid, m in sorted(L.MM_MATCHES.items()):
        d = {k: v for k, v in m.items() if k not in ('created',)}
        ms.append(json.loads(json.dumps(d, sort_keys=True, default=lambda x: sorted(x) if isinstance(x, set) else str(x))))
    st = {s: (p['state'], p.get('match'), round(p['rating'], 3), p.get('rsrc')) for s, p in sorted(L.MM.items())}
    res.append({'tag': tag, 'matches': ms, 'states': st})
def tick(sec, steams):            # time passes; own_lobby's nm/sync every 0.5 s (here every 10 s) keeps the searches alive
    for _ in range(int(sec // 10)):
        CLOCK[0] += 10; L.nm_sync({'steams': steams})
def nm(i, mode='1v1', game='elite-3.2.1', party=None, **h):
    if h: L.NM_HINTS[S(i)] = {'t': CLOCK[0], 'd': dict(h, mode=mode, game=game)}
    d = {'steam': S(i), 'mode': mode, 'game': game, 'key': 'k', 'name': 'N%d' % i, 'pid': 9000 + i}
    if party: d['party'] = [{'steam': S(j), 'pid': 9000 + j} for j in party]
    CLOCK[0] += 1; return L.nm_join(d)
def classic(i, mode='1v1', **d):
    CLOCK[0] += 1; return L.mm_join(S(i), mode, dict(d, name='C%d' % i))
def reset():
    L.MM.clear(); L.MM_MATCHES.clear(); L.NM_HINTS.clear(); L.MM_CANCELLED.clear(); L.MM_SEQ[0] = 0; random.seed(7)
    if hasattr(O, '_CACHE'): O._CACHE['t'] = 0
if scen == 'random':
    for k in range(150):
        reset(); rnd = random.Random(k)
        for i in range(1, 9): RATING[S(i)] = rnd.choice([1200, 1400, 1500, 1550, 1700, 1900, 2100])
        steams = []
        for step in range(rnd.randint(2, 12)):
            i = rnd.randint(1, 8); mode = rnd.choice(['1v1', '1v1', '2v2', '3v3']); kind = rnd.random()
            if kind < 0.6: nm(i, mode, rnd.choice(['elite-3.2.1', 'elite-3.2.1', 'vanilla']), max_diff=rnd.choice([0, 0, 200]))
            elif kind < 0.8: classic(i, mode, maps=rnd.sample(['m1', 'm2', 'm3'], rnd.randint(0, 2)), max_diff=rnd.choice([0, 300]))
            else:
                j = rnd.randint(1, 8)
                if j != i: nm(i, rnd.choice(['2v2', '3v3']), party=[j])     # a party in 1v1 breaks main's team split too (no split exists)
            steams.append(S(i)); random.seed(k * 100 + step)
            if rnd.random() < 0.3: tick(20, steams)
            snap('random %d.%d' % (k, step))
else:
    for name, steps in json.loads(scen):
        reset()
        for st in steps:
            if st[0] == 'nm': nm(st[1], *st[2:])
            elif st[0] == 'tick': tick(st[1], [S(i) for i in st[2]])
            elif st[0] == 'rating': RATING[S(st[1])] = st[2]
            elif st[0] == 'snap': snap(name + ' ' + st[1])
json.dump(res, open(out, 'w'), sort_keys=True)
shutil.rmtree(T, ignore_errors=True)
'''
open(T + '/driver.py', 'w').write(DRIVER)
def drive(app, season, scen, own=()):
    out = T + '/out_%d.json' % N[0]
    r = subprocess.run([sys.executable, T + '/driver.py', app, out, season, scen, json.dumps(list(own))], capture_output=True, text=True, timeout=600)
    if r.returncode != 0: print(r.stdout[-2000:], r.stderr[-4000:]); ok('driver %s %s' % (app, season), False)
    return json.load(open(out))
old = drive(BASE, 'off', 'random'); new = drive(APP, 'off', 'random')
diff = [i for i, (a, b) in enumerate(zip(old, new)) if a != b]
if diff or len(old) != len(new): print('  first difference:', len(old), len(new), json.dumps(old[diff[0]])[:900], '\n  ', json.dumps(new[diff[0]])[:900])
print('  random queues: %d snapshots, %d matches' % (len(new), sum(len(x['matches']) for x in new)))
ok('no season file: 150 random queues (native, classic, parties, vanilla, max_diff, time passing) -> main and this code form the '
   'very same matches (teams, host, map, slots, ratings) and states', old == new and sum(len(x['matches']) for x in new) > 150)

def S_(i): return '7656119%010d' % i
OWN = [(S_(1), '1v1', 1900, 60, 9, 0), (S_(2), '1v1', 1500, 60, 9, 0), (S_(3), '1v1', 1520, 70, 8, 0), (S_(4), '1v1', 1700, 150, 3, 2), (S_(5), '1v1', 1100, 60, 9, 0),
       (S_(11), '2v2', 1700, 60, 9, 0), (S_(12), '2v2', 1650, 60, 9, 0), (S_(13), '2v2', 1600, 60, 9, 0), (S_(14), '2v2', 1550, 60, 9, 0)]
SC = [
    ('pair400', [['nm', 1], ['nm', 2], ['snap', 'at join'], ['tick', 240, [1, 2]], ['snap', '4 min'], ['tick', 70, [1, 2]], ['snap', '5 min']]),
    ('pair800', [['nm', 1], ['nm', 5], ['tick', 350, [1, 5]], ['snap', '5:50'], ['tick', 20, [1, 5]], ['snap', '6:10']]),
    ('prefer', [['nm', 2], ['nm', 1], ['nm', 3], ['snap', 'after 3']]),
    ('calib', [['nm', 4], ['nm', 2], ['snap', 'cal']]),
    ('newbies', [['nm', 21], ['nm', 1], ['snap', 'new vs 1900']]),
    ('teams', [['nm', 11, '2v2'], ['nm', 12, '2v2'], ['nm', 13, '2v2'], ['nm', 14, '2v2'], ['snap', '2v2']]),
    ('vanilla', [['rating', 31, 2400], ['rating', 32, 1200], ['nm', 31, '1v1', 'vanilla'], ['nm', 32, '1v1', 'vanilla'], ['snap', 'vanilla']]),
]
on = {x['tag']: x for x in drive(APP, 'on', json.dumps(SC), OWN)}
offn = {x['tag']: x for x in drive(APP, 'off', json.dumps(SC), OWN)}
offo = {x['tag']: x for x in drive(BASE, 'off', json.dumps(SC), OWN)}
ok('scenarios without the season: this code == main', offn == offo)
def pairs(x): return sorted(sorted(m['host'] + m['guest']) for m in x['matches'])
st = lambda x, i: x['states'].get(S_(i))
ok('season: 1900 vs 1500 not matched at once (window 150)', on['pair400 at join']['matches'] == [] and st(on['pair400 at join'], 1)[0] == 'searching')
ok('season: still not at 4 min (window 350 < 400)', on['pair400 4 min']['matches'] == [])
ok('season: matched at 5 min (window 400), with no new join (the polls retry)', pairs(on['pair400 5 min']) == [[S_(1), S_(2)]])
ok('season: 1900 vs 1100 (spread 800) still waiting at 5:50', on['pair800 5:50']['matches'] == [])
ok('season: ... and matched after 6 min whatever the spread (a lone pair always plays)', pairs(on['pair800 6:10']) == [[S_(1), S_(5)]])
ok('without the season the same pair matches at once', pairs(offn['pair400 at join']) == [[S_(1), S_(2)]])
ok('season: 1500 waiting, 1900 then 1520 join -> 1500 vs 1520, the 1900 waits', pairs(on['prefer after 3']) == [[S_(2), S_(3)]] and st(on['prefer after 3'], 1)[0] == 'searching')
ok('without the season: 1500 vs 1900 (first come)', pairs(offn['prefer after 3']) == [[S_(1), S_(2)]])
ok('season: queue ratings are ours (1900 own, 1500 own)', st(on['pair400 at join'], 1)[2:] == [1900, 'own'] and st(on['pair400 at join'], 2)[2:] == [1500, 'own'])
ok('season: calibrating player as 1500 (own_cal), matched with 1500 at once', st(on['calib cal'], 4)[2:] == [1500, 'own_cal'] and pairs(on['calib cal']) == [[S_(2), S_(4)]])
ok('season: a new player 1500/350 vs 1900 (spread 400 <= 150 + 250 for his RD) -> matched', pairs(on['newbies new vs 1900']) == [[S_(1), S_(21)]]
   and st(on['newbies new vs 1900'], 21)[2:] == [1500, 'own_new'])
tm = on['teams 2v2']['matches'][0]
ok('season: 2v2 split by our rating: 1700+1550 vs 1650+1600', sorted([sorted(tm['host']), sorted(tm['guest'])]) == sorted([sorted([S_(11), S_(14)]), sorted([S_(12), S_(13)])]))
ok('season: vanilla keeps the old rating and no window (2400 vs 1200 at once)', pairs(on['vanilla vanilla']) == [[S_(31), S_(32)]]
   and st(on['vanilla vanilla'], 31)[2:] == [2400, 'ladder'])

# ---------- 7. the live copy: step 2 of main == this code without the season file ----------
if LIVE:
    sys.path.insert(0, BASE)
    import importlib.util
    spec = importlib.util.spec_from_file_location('own_matches_base', BASE + '/own_matches.py'); ob = importlib.util.module_from_spec(spec); spec.loader.exec_module(ob)
    def copy(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        src = sqlite3.connect('file:%s?mode=ro' % os.path.abspath(LIVE), uri=True); d = sqlite3.connect(dst); src.backup(d); src.close(); d.close()
    a, b = T + '/la/ladder.sqlite', T + '/lb/ladder.sqlite'; copy(a); copy(b)
    ob.step2(a, log=quiet, cfg=None); o.step2(b, log=quiet, cfg=None)
    def dump(fn, skip=()):
        c = sqlite3.connect(fn)
        out = {}
        for t in ('own_matches', 'own_match_players', 'own_ratings'):
            cols = [r[1] for r in c.execute('PRAGMA table_info(%s)' % t) if r[1] not in skip]
            out[t] = sorted(map(tuple, c.execute('SELECT %s FROM %s' % (', '.join(cols), t)).fetchall()), key=repr)
        c.close(); return out
    da, db_ = dump(a, ('resolved', 'modname', 'updated')), dump(b, ('resolved', 'modname', 'updated'))
    ok('live copy, no season file: own_matches / own_match_players / own_ratings identical to main (except modname filled)', da == db_)
    c = sqlite3.connect(b)
    print('  modname now:', c.execute('SELECT coalesce(modname, "?"), COUNT(*) FROM own_matches GROUP BY 1').fetchall())
    ok('live copy: every match has its mod now', c.execute('SELECT COUNT(*) FROM own_matches WHERE modname IS NULL').fetchone()[0] == 0)
    c.close()
    o.setup(lambda: sqlite3.connect(a), threading.Lock(), lambda t: 'q', data_dir=os.path.dirname(a))
    q = sorted({r for (r,) in sqlite3.connect(a).execute('SELECT season FROM own_ratings')})[-1]
    for mode in ('1v1', '2v2', '3v3'):
        bo = o.site_board(mode, q); ob.setup(lambda: sqlite3.connect(a), threading.Lock(), lambda t: 'q', data_dir=os.path.dirname(a))
        bb = ob.site_board(mode, q)
        ok('live copy %s: the old fields of /ladder/api/own unchanged' % mode, {k: bo[k] for k in bb} == bb)
    now = int(time.time())
    o.step2(b, log=lambda s: print('  ' + s), cfg={'label': 'pre', 'start': now}); c = sqlite3.connect(b)
    ok('live copy: a preseason from now -> an empty table', c.execute('SELECT COUNT(*) FROM own_ratings').fetchone()[0] == 0); c.close()
    o.step2(b, log=lambda s: print('  ' + s), cfg={'label': 'pre', 'start': 0}); c = sqlite3.connect(b)
    print('  all the data under the preseason rules (3 min, Elite only):', dict(c.execute("SELECT coalesce(why_unrated, 'rated'), COUNT(*) FROM own_matches GROUP BY 1")))
    o.setup(lambda: sqlite3.connect(b), threading.Lock(), lambda t: 'q', data_dir=os.path.dirname(b))
    for r in o.site_board('1v1', 'pre')['rows']:
        print('   ', ('%3s' % r['rank']) if not r['calibrating'] else '  -', '%-22s' % r['name'][:22],
              ('calibration %d/%d' % (r['cal_played'], r['cal_needed'])) if r['calibrating'] else '%5d' % r['cons'], 'games', r['games'])
    c.close()
shutil.rmtree(T, ignore_errors=True)
print('ALL %d OK' % N[0])
