#!/usr/bin/env python3
# 16.11.2026 (SirItos fb 1364): a room's exact game from relic_scan is kept for the room's whole life - also when the room drops out
# of the filtered answers (passworded, full, started) and when the scanner pauses for an hour (the stand's game runs) - and dropped
# as soon as the room is gone from Relic's public list.
# usage: python3 -I ladder/tests/test_rooms_exact_keep.py [<repo dir>]   (temp copies, empty data dirs; nothing live)
import io, json, os, shutil, sys, tempfile, time
REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
T = tempfile.mkdtemp(prefix='ladder_exact_')
shutil.copytree(REPO + '/ladder', T + '/app', ignore=shutil.ignore_patterns('__pycache__', '*.bak*', 'tests'))
os.makedirs(T + '/data'); sys.path.insert(0, T + '/app'); os.environ['LADDER_NO_CRAWL'] = '1'
os.environ['ADS_EXACT'] = T + '/data/ads_exact.json'
import ladder as L
fails = []
def check(name, got, want):
    ok = got == want
    print('  %-78s %s' % (name, 'ok' if ok else 'FAIL: got %r, want %r' % (got, want)))
    if not ok: fails.append(name)

ELITE = {'modname': 'Elite', 'modversion': '3.2.1', 'datachecksum': '-2120914952', 'src': 'scan', 'q': 'elite'}
VAN = {'modname': 'DOW2', 'modversion': '3.19', 'datachecksum': '371005917', 'src': 'scan', 'q': 'vanilla'}
def scan_file(ads, age):
    json.dump({'ts': int(time.time()), 'state': 'ok' if age < 60 else 'paused', 'scan_ts': int(time.time() - age), 'ads': ads, 'other': []},
              open(L.ADS_EXACT, 'w'))
PUBLIC = {'matches': [], 'avatars': []}
def ad(i, mapname, pw=0):
    return {'id': i, 'description': 'room %d' % i, 'mapname': mapname, 'maxplayers': 8, 'passwordprotected': pw,
            'slotinfo': '', 'matchmembers': [], 'host_profile_id': 0}
class _R(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): pass
L.urllib.request.urlopen = lambda req, timeout=None: _R(json.dumps(PUBLIC).encode())
def rooms(*ads):
    PUBLIC['matches'] = list(ads)
    return {r['id']: (r['game'], r['version'], r['exact']) for r in L._rooms_once()}

print('exact game of a room kept for its lifetime')
# 4p_edgeofannihilation: a map both games have - the case of fb 1364
scan_file({'101': ELITE, '102': VAN}, 5)
r = rooms(ad(101, '4p_edgeofannihilation'), ad(102, '4p_edgeofannihilation'), ad(103, '4p_edgeofannihilation'))
check('a fresh scan: the Elite room exact, Elite 3.2.1', r[101], ('elite', '3.2.1', 'scan'))
check('a fresh scan: the vanilla room exact, vanilla 3.19', r[102], ('vanilla', '3.19', 'scan'))
check('a room no scan listed: not exact (the fallback as before)', r[103][2], None)

scan_file({'101': ELITE, '102': VAN}, 3600)
r = rooms(ad(101, '4p_edgeofannihilation'), ad(102, '4p_edgeofannihilation'))
check('the scanner paused an hour (the file\'s last scan is old): still exact', (r[101], r[102]),
      (('elite', '3.2.1', 'scan'), ('vanilla', '3.19', 'scan')))

scan_file({}, 5)
r = rooms(ad(101, '4p_edgeofannihilation', pw=1), ad(102, '4p_edgeofannihilation'))
check('the room left the filtered answers (passworded / full / started): kept', r[101], ('elite', '3.2.1', 'scan'))
check('... the other one too', r[102], ('vanilla', '3.19', 'scan'))

scan_file({'102': ELITE}, 5)
r = rooms(ad(101, '4p_edgeofannihilation'), ad(102, '4p_edgeofannihilation'))
check('a newer scan answer for a room wins over the kept one', r[102], ('elite', '3.2.1', 'scan'))

scan_file({}, 5)
r = rooms(ad(102, '4p_edgeofannihilation'))
check('a room gone from the public list: dropped from memory', sorted(L._EXACT_KEEP), ['102'])
r = rooms(ad(101, '4p_edgeofannihilation'), ad(102, '4p_edgeofannihilation'))
check('... and not brought back when an id shows up again without a scan', r[101][2], None)

r = rooms()
check('an empty public list drops nothing (a Relic hiccup)', sorted(L._EXACT_KEEP), ['102'])
scan_file({'104': VAN}, 5)
r = rooms(ad(105, '2p_calderis_desert'))
check('memory bounded by the public list: rooms not in it are not kept', sorted(L._EXACT_KEEP), [])

print('the version at most major.minor.patch (fb 1385)')
for raw, want in (('3.2.1.0.0', '3.2.1'), ('3.2.1.0', '3.2.1'), ('3.2', '3.2'), ('3.19', '3.19'), ('3', '3'), ('', ''), (None, ''),
                  ('beta-7', 'beta-7'), (' 3.2.1.0.0 ', '3.2.1')):
    check('short_ver(%r)' % (raw,), L.short_ver(raw), want)
scan_file({'107': dict(ELITE, modversion='3.2.1.0.0')}, 5)
r = rooms(ad(107, '2p_calderis_desert'))
check('a room\'s version field is cut too', r[107], ('elite', '3.2.1', 'scan'))
import lroom as LR
LR.MAX_ROOMS = 100
S1 = '76561190000000001'
with L.MM_LOCK: x = LR.api('create', S1, {'game': 'elite', 'mode': '1v1', 'ver': '3.2.1.0.0'})
check('a launcher lobby\'s ver is cut when made', LR.ROOMS[LR.BY[S1]]['ver'], '3.2.1')
with L.MM_LOCK: LR.api('conf', S1, {'ver': '3.2.1.0.0'})
check('... and when its owner sends his version again (no change)', LR.ROOMS[LR.BY[S1]]['ver'], '3.2.1')

os.remove(L.ADS_EXACT)
r = rooms(ad(106, '2p_calderis_desert'))
check('no scan file at all: no exact, no error', r[106][2], None)

shutil.rmtree(T, ignore_errors=True)
print('FAILED: %d' % len(fails) if fails else 'all ok')
sys.exit(1 if fails else 0)
