#!/usr/bin/env python3
"""own_admin.py - manual decisions on the own rating's matches (17.11.2026, preseason). No web UI.

A decision is a row of own_overrides (a log: rows are never deleted, the latest row of a match wins); own_matches.resolve() applies
it on every run of match_log_collect (every 5 min), so it survives the recompute. After writing, this script runs the same step 2
(resolve + recompute) at once, so the site shows it within its 60 s cache.
  own_admin.py void <match_id> "note"            the match is unrated for everyone
  own_admin.py winner <match_id> <team> ["note"] that team won (rated, unless a launcher room / incomplete teams / no Steam ID)
  own_admin.py clear <match_id> ["note"]         back to the automatic rules
  own_admin.py list [<match_id>]                 the log of decisions (all, or one match's) + the match's current result
options: --db PATH (default <app>/../data/ladder.sqlite, env OWN_DB), --no-recompute (write only; the collector applies it within 5 min)
match_id = own_matches.sid, "NM-<sid>" is accepted. Team = own_match_players.team (shown by list <match_id>)."""
import os, sqlite3, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import own_matches

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sid(x):
    x = str(x)
    if x.upper().startswith('NM-'): x = x[3:]
    if not x.isdigit(): sys.exit('match_id: a number or NM-<number>, got %r' % x)
    return int(x)


def show_match(c, sid):
    m = c.execute('SELECT mode, started, rated, why_unrated, winner_team, result_src, notes FROM own_matches WHERE sid = ?', (sid,)).fetchone()
    if not m: print('  match %d: not in own_matches' % sid); return
    print('  match %d %s %s  rated=%s why=%s winner_team=%s src=%s notes=%s' % (
        sid, m[0], time.strftime('%Y-%m-%d %H:%M', time.gmtime(m[1] or 0)), m[2], m[3], m[4], m[5], m[6]))
    for steam, name, team, final, w, note in c.execute('SELECT steam, name, team, final, weight, note FROM own_match_players WHERE sid = ? '
                                                         'ORDER BY team, pid', (sid,)):
        print('    team %s  %-20s %s  %s w=%s %s' % (team, name or '', steam, final, w, note or ''))


def main(argv):
    db = os.environ.get('OWN_DB', ROOT + '/data/ladder.sqlite'); recompute = True; args = []
    it = iter(argv)
    for a in it:
        if a == '--db': db = next(it, None) or sys.exit('--db PATH')
        elif a == '--no-recompute': recompute = False
        elif a in ('-h', '--help'): print(__doc__); return 0
        else: args.append(a)
    if not args: print(__doc__); return 2
    cmd = args[0]
    if not os.path.exists(db): sys.exit('no DB at %s' % db)
    c = sqlite3.connect(db, timeout=30)
    with c: own_matches.migrate(c)
    if cmd == 'list':
        sid = _sid(args[1]) if len(args) > 1 else None
        rows = c.execute('SELECT id, match_id, action, team, note, ts FROM own_overrides' + (' WHERE match_id = ?' if sid else '') + ' ORDER BY id',
                         (sid,) if sid else ()).fetchall()
        for i, mid, action, team, note, ts in rows:
            print('#%d %s match %d %s%s  %s' % (i, time.strftime('%Y-%m-%d %H:%M', time.gmtime(ts)), mid, action,
                                                ' team %s' % team if action == 'winner' else '', note or ''))
        if not rows: print('no manual decisions' + (' for match %d' % sid if sid else ''))
        if sid: show_match(c, sid)
        else:
            act = sorted({r[1] for r in rows})
            if act: print('in force: ' + ', '.join('%d=%s' % (m, (own_matches.override_of(c, m) or {}).get('action', 'rules')) for m in act))
        return 0
    if cmd not in ('void', 'winner', 'clear') or len(args) < 2: print(__doc__); return 2
    sid = _sid(args[1]); team = None
    if not c.execute('SELECT 1 FROM own_matches WHERE sid = ?', (sid,)).fetchone(): sys.exit('match %d is not in own_matches' % sid)
    if cmd == 'winner':
        if len(args) < 3 or not args[2].lstrip('-').isdigit(): sys.exit('winner <match_id> <team>')
        team = int(args[2]); note = ' '.join(args[3:])
        teams = sorted({r[0] for r in c.execute('SELECT team FROM own_match_players WHERE sid = ?', (sid,))}, key=lambda t: (t is None, t))
        if team not in teams: sys.exit('match %d has teams %s, not %d' % (sid, teams, team))
    else:
        note = ' '.join(args[2:])
        if cmd == 'void' and not note: sys.exit('void <match_id> "note" - say why')
    with c:
        c.execute('INSERT INTO own_overrides (match_id, action, team, note, ts) VALUES (?,?,?,?,?)', (sid, cmd, team, note or None, int(time.time())))
    c.close()
    print('match %d: %s%s written' % (sid, cmd, ' team %d' % team if team is not None else ''))
    if recompute:
        ok = own_matches.step2(db, log=print)
        if not ok: print('step 2 failed (see above); the decision is stored and applies on the next collector run'); return 1
    c = sqlite3.connect(db, timeout=30); show_match(c, sid); c.close()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
