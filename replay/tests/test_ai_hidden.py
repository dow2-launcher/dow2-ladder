#!/usr/bin/env python3
# 14.11.2026 (siritos): matches with a computer player in the replay pool - the game's own upload (MMFind) of such a match is not
# stored, EliteAI's (X-Lobby newai) is stored hidden, a person's upload (launcher token / site form) is stored and listed, the lists
# leave hidden ones out ("ai": "all" / "none"), replays stored before are hidden once by the same rule.
# usage: python3 replay/tests/test_ai_hidden.py <a .rec with a computer player> <a .rec of people only>   (a temp copy; nothing live)
import http.client, json, os, shutil, sqlite3, sys, tempfile, threading
from http.server import ThreadingHTTPServer
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); REC_AI, REC_PP = sys.argv[1], sys.argv[2]
T = tempfile.mkdtemp(prefix='replay_ai_'); shutil.copytree(HERE, T + '/app', ignore=shutil.ignore_patterns("__pycache__", "*.bak*", "tests"))
os.makedirs(T + '/data/old1'); shutil.copyfile(REC_AI, T + '/data/old1/replay.rec')
# a replay stored before (an old index without the column): MMFind's file name, a computer in it, nobody's
os.rename(T + '/data/old1', T + '/data/00000000000000a1'); open(T + '/data/00000000000000a1/name.txt', 'w').write('match_2026-11-03_22-25.rec')
sys.argv = ['app']; sys.path.insert(0, T + '/app')
import app as A
A.analyse = lambda rid: None                       # no report building here
A.who = lambda tok: {'steam': '76561190000000001', 'name': 'Tester'} if tok == 'tok-good-0123456789' else None
fails = []
def check(name, got, want):
    ok = got == want
    print('  %-74s %s' % (name, 'ok' if ok else 'FAIL: got %r, want %r' % (got, want)))
    if not ok: fails.append(name)
# the old row was indexed by backfill before the column existed? backfill ran with the column present: emulate an old index
with A.idb() as c: c.execute("UPDATE replays SET hidden = NULL")
srv = ThreadingHTTPServer(('127.0.0.1', 0), A.H); threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
def req(method, path, body=b'', **hdr):
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=30); c.request(method, path, body, hdr); r = c.getresponse()
    return r.status, json.loads(r.read() or b'{}')
def up(path, ua, lobby='', token=None, name='x.rec'):
    h = {'User-Agent': ua, 'X-Filename': name, 'X-Lobby': lobby}
    if token: h['X-Token'] = token
    return req('POST', '/replay/api/upload', open(path, 'rb').read(), **h)
def ids(q=None): return sorted(x['id'] for x in req('POST', '/replay/api/list', json.dumps(q or {}).encode())[1]['items'])
def hidden(rid):
    with A.idb() as c: return (c.execute('SELECT hidden FROM replays WHERE rid = ?', (rid,)).fetchone() or ['-'])[0]

print('replays stored before')
# run the one-off rule again as at the first start of the new code
with A._ilock, A.idb() as c:
    rows = c.execute('SELECT rid, name, lobby, players FROM replays WHERE author_steam IS NULL AND hidden IS NULL').fetchall()
    c.executemany("UPDATE replays SET hidden = 'ai_auto' WHERE rid = ?", [(r[0],) for r in rows if A.bot_match(r[3]) and (r[2] == 'newai' or A.AUTO_NAME.match(r[1] or ''))])
check('an old automatic AI replay is hidden', hidden('00000000000000a1'), 'ai_auto')

print('uploads')
s, j = up(REC_AI, 'MMFind/0.49', name='match_2026-11-14_10-00.rec'); check('MMFind, a match with a computer: 200, not stored', (s, j.get('stored'), j.get('reason')), (200, False, 'computer_player'))
check('  ... nothing in the index', len(ids({'ai': 'all'})), 1)
s, j = up(REC_PP, 'MMFind/0.49', lobby='NM-2000000001', name='NM-2000000001_2026-11-14_10-00.rec'); pp = j.get('id')
check('MMFind, people only: stored, listed', (s, pp in ids()), (200, True))
s, j = up(REC_AI, 'EliteAI/0.11', lobby='newai', name='newai_orks-B_2026-11-14.rec'); ai = j.get('id')
check('EliteAI (newai): stored hidden', (s, hidden(ai)), (200, 'ai_auto'))
check('  ... not in the default list', ai in ids(), False)
check('  ... in the list with "ai": "all"', ai in ids({'ai': 'all'}), True)
check('  ... GET list: hidden by default, ?ai=all lists it', (ai in [x['id'] for x in req('GET', '/replay/api/list')[1]['items']],
                                                             ai in [x['id'] for x in req('GET', '/replay/api/list?ai=all')[1]['items']]), (False, True))
check('  ... its page still opens (the AI team reads it by link)', req('GET', '/replay/api/r/' + ai)[1]['meta']['hidden'], True)
check('  ... marked "ai" in the item', req('GET', '/replay/api/r/' + ai)[1]['meta']['ai'], True)
for rid in ('00000000000000a1', pp): open('%s/data/%s/caption.txt' % (T, rid), 'w').write('c')
check('  ... the site\'s recent list leaves hidden ones out', sorted(x['id'] for x in A.recent(50)), [pp])
s, j = up(REC_AI, 'ureq/2.9', token='tok-good-0123456789', name='my_saved_game.rec')
check('the launcher (the player put it in): the same match becomes visible, his', (j.get('id'), j.get('duplicate'), j.get('mine'), hidden(ai)), (ai, True, True, None))
check('  ... listed now', ai in ids(), True)
check('  ... "ai": "none" leaves out every match with a computer', (ai in ids({'ai': 'none'}), pp in ids({'ai': 'none'})), (False, True))
check('  ... "mine" lists it', ai in ids({'mine': True, 'token': 'tok-good-0123456789'}), True)
check('versions count only listed replays', sum(v['count'] for v in A.version_list()), 2)
check('the site\'s recent list: the player\'s one is there now', sorted(x['id'] for x in A.recent(50)), sorted(['00000000000000a1', pp]))

srv.shutdown(); shutil.rmtree(T, ignore_errors=True)
print('FAILED: %s' % fails if fails else 'all ok'); sys.exit(1 if fails else 0)
