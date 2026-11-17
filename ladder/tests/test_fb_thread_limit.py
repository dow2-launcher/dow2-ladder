#!/usr/bin/env python3
# 17.11.2026 (Malum): the dev chat thread GET /ladder/api/fb/thread takes limit=<n> (the last n messages) besides after=<id>.
# usage: python3 ladder/tests/test_fb_thread_limit.py [<repo dir>]   (a temp copy, an empty data dir; nothing live)
import os, shutil, sys, tempfile, time
REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
T = tempfile.mkdtemp(prefix='ladder_fb_')
shutil.copytree(REPO + '/ladder', T + '/app', ignore=shutil.ignore_patterns('__pycache__', '*.bak*', 'tests'))
os.makedirs(T + '/data'); sys.path.insert(0, T + '/app'); os.environ['LADDER_NO_CRAWL'] = '1'
import ladder as L
fails = []
def check(name, got, want):
    ok = got == want
    print('  %-70s %s' % (name, 'ok' if ok else 'FAIL: got %r, want %r' % (got, want)))
    if not ok: fails.append(name)
U, V = 'u' * 20, 'v' * 20
c = L.fb_db()
for i in range(30):
    for uid in (U, V):
        c.execute('INSERT INTO fb (uid, name, author, text, images, ts, seen, meta) VALUES (?,?,?,?,?,?,?,?)',
                  (uid, 'n', 'player' if i % 2 else 'dev', '%s%d' % (uid[0], i), '[]', int(time.time()) + i, 0, ''))
c.commit(); c.close()
ids = lambda r: [m['text'] for m in r['messages']]
allu = L.fb_thread(U)
check('no limit: the whole thread, oldest first, no "more"', (ids(allu), 'more' in allu), (['u%d' % i for i in range(30)], False))
last = L.fb_thread(U, 0, '20')
check('limit=20: the last 20, oldest first', ids(last), ['u%d' % i for i in range(10, 30)])
check('... more = true (older ones left out)', last['more'], True)
mid = last['messages'][-1]['id']
check('after=<last id>: nothing new', ids(L.fb_thread(U, mid)), [])
check('after=<id of u24>, limit=20: the 5 newer, more = false',
      (ids(L.fb_thread(U, allu['messages'][24]['id'], 20)), L.fb_thread(U, allu['messages'][24]['id'], 20)['more']), (['u25', 'u26', 'u27', 'u28', 'u29'], False))
check('after + limit smaller: the newest n after it', ids(L.fb_thread(U, allu['messages'][24]['id'], 2)), ['u28', 'u29'])
check('limit=100: whole thread, more = false', (len(L.fb_thread(U, 0, 100)['messages']), L.fb_thread(U, 0, 100)['more']), (30, False))
check('limit capped at FB_THREAD_MAX, 0 -> 1', (len(L.fb_thread(U, 0, 10 ** 6)['messages']), ids(L.fb_thread(U, 0, 0))), (30, ['u29']))
check('limit="" (the handler\'s default): no limit', len(L.fb_thread(U, 0, '')['messages']), 30)
check('only his thread', all(m['text'].startswith('u') for m in L.fb_thread(U, 0, 50)['messages']), True)
check('bad limit / after -> error, not an exception', (L.fb_thread(U, 0, 'x'), L.fb_thread(U, 'x')), ({'error': 'limit'}, {'error': 'after'}))
check('bad uid', L.fb_thread('short', 0, 5), {'error': 'uid'})
shutil.rmtree(T, ignore_errors=True)
print('ALL OK' if not fails else 'FAILED: %s' % fails); sys.exit(1 if fails else 0)
