#!/usr/bin/env python3
"""own rating: a match whose game server numbered two guests otherwise than the host (battle_relay match_log "swapped", 20.11.2026,
SirItos 19.11 m19 / m20) is never rated - why_unrated 'peer_order', a manual winner does not rate it either.
Run: python3 ladder/tests/test_own_peer_order.py [dir with own_matches.py]   (a temp DB; nothing live)"""
import json, os, sqlite3, sys, tempfile
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import own_matches as o
fails = []
def ok(name, cond, info=''):
    print('  %-74s %s' % (name, 'ok' if cond else 'FAIL %s' % (info,)))
    if not cond: fails.append(name)
T0 = 1_800_000_000; E = T0 + 900
def P(steam, team, rep=None, rep_t=None, leave=None): return dict(steam=steam, team=team, rep=rep, rep_t=rep_t, leave=leave)
ps = [P('a', 1, 1, E, E + 10), P('b', 1, 1, E, E + 10), P('c', 2, 0, E, E + 30), P('d', 2, 0, E, E + 30)]
r = o.decide(dict(kind='mm', started=T0, conflict=False), ps)
ok('a clean 2v2 is rated', r['rated'] == 1 and r['why'] is None, r)
r = o.decide(dict(kind='mm', started=T0, conflict=False, peer_order=True), ps)
ok('the same with peer_order: unrated, why peer_order', r['rated'] == 0 and r['why'] == 'peer_order', r)
r = o.decide(dict(kind='mm', started=T0, conflict=False, peer_order=True, override={'action': 'winner', 'team': 1}), ps)
ok('a manual winner keeps it unrated (rule 1)', r['rated'] == 0 and r['why'] == 'peer_order' and r['winner_team'] == 1, r)
# _match_input reads the node's match_log: swapped true -> peer_order; corrected (announce numbering) -> rated as usual
db = tempfile.mktemp(suffix='.sqlite'); c = sqlite3.connect(db); o.migrate(c)
def put(sid, logs):
    c.execute('INSERT INTO own_matches (sid, lobby, kind, mode, map, modname, started, node_log) VALUES (?,?,?,?,?,?,?,?)',
              (sid, 'NM-%d' % sid, 'mm', '2v2', '4p_settlement', 'Elite', T0, json.dumps(logs)))
    for s, t in (('a', 1), ('b', 1), ('c', 2), ('d', 2)):
        c.execute('INSERT INTO own_match_players (sid, steam, pid, team, report_result, report_t) VALUES (?,?,?,?,?,?)', (sid, s, 1, t, 1 if t == 1 else 0, E))
put(1, [{'ticks': 100, 'numbering': 'hello', 'order_mismatch': [{'idx': 3}], 'swapped': True}])
put(2, [{'ticks': 100, 'numbering': 'announce', 'order_mismatch': [{'idx': 3}], 'swapped': False}])
put(3, [{'ticks': 100}])                                    # an older node (no such fields)
for sid, want in ((1, True), (2, False), (3, False)):
    m, _ = o._match_input(c, sid)
    ok('match_input sid %d: peer_order %s' % (sid, want), bool(m.get('peer_order')) == want, m)
print('ALL OK' if not fails else 'FAILED: %s' % fails); sys.exit(1 if fails else 0)
