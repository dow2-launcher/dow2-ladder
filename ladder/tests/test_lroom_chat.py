#!/usr/bin/env python3
# 16.11.2026 (owner, launcher 1.6.17): the lobby's chat - (1) the feed's own lines (open, join, join_obs, leave, gone, kick, to_obs,
# to_seat, host) and who gets them (the lobby's people only, never the room's view that goes to everybody); (2) verb say: say_pre
# (no room, empty, the pace, the moderation) outside MM_LOCK, then the message (obs flag, a reply's quote, a retry by cid), its
# translation after it (lroom_msg_tr); (3) verb seat with slot "obs": a player into the observers (never the owner, not past the
# seats), an observer back onto a seat.
# usage: python3 ladder/tests/test_lroom_chat.py [<repo dir>]   (temp copies, empty data dirs; nothing live)
import os, shutil, sys, tempfile, threading, time
REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
T = tempfile.mkdtemp(prefix='ladder_lchat_')
shutil.copytree(REPO + '/ladder', T + '/app', ignore=shutil.ignore_patterns('__pycache__', '*.bak*', 'tests'))
os.makedirs(T + '/data'); sys.path.insert(0, T + '/app'); os.environ['LADDER_NO_CRAWL'] = '1'
import ladder as L
R = L.lroom
fails = []
def check(name, got, want):
    ok = got == want
    print('  %-84s %s' % (name, 'ok' if ok else 'FAIL: got %r, want %r' % (got, want)))
    if not ok: fails.append(name)
A, B, C, D, E = ('7656119000000040%d' % i for i in range(1, 6))
SENT = []                                                    # (event, data, to) of the stream
L.stream.publish = lambda ev, data, to=None: SENT.append((ev, data, to))
R._pub = lambda r: None
L.community.MODFLAGS = lambda: {'premod': True, 'translate': False}
L.community.PREMOD = lambda t: 'политика' in t
def lines(rid): return [(e.get('sys') or 'msg', e['steam']) for e in R.ROOMS[rid]['chat']]
def to_of(ev, pred=lambda d: True): return sorted({to for e, d, to in SENT if e == ev and pred(d)})
def say(steam, d):                                           # as ladder.py: say_pre outside the lock, then api
    pre = R.say_pre(steam, d)
    return pre or R.api('say', steam, d)
def fresh():
    R.ROOMS.clear(); R.BY.clear(); R.CHAT_RATE.clear(); SENT.clear()

print('(1) the feed\'s own lines and who gets them')
fresh()
v = R.api('create', A, {'game': 'elite', 'ver': '3.2', 'mode': '2v2', 'map': '4p_calderisrefinery', 'name': 'chat'}); rid = v['room']['id']
check('create: the feed opens with "open" (the owner)', [(m['sys'], m['steam']) for m in v['room']['chat']], [('open', A)])
r = R.ROOMS[rid]
check('the room\'s view (to everybody) has no chat, only cseq', ('chat' in R.view(r), R.view(r)['cseq']), (False, 1))
check('nor the list\'s summary', 'chat' in R.summary(r), False)
j = R.api('join', B, {'id': rid})
check('join: "join" of B, the answer carries the feed', ([m['sys'] for m in j['room']['chat']], j['room']['chat'][-1]['steam']), (['open', 'join'], B))
SENT.clear(); R.api('join', C, {'id': rid, 'as': 'obs'})
check('join as an observer: "join_obs"', lines(rid)[-1], ('join_obs', C))
check('  ... sent to the lobby\'s people only (A, B, C), one by one', to_of('lroom_msg'), sorted([A, B, C]))
check('  ... the line\'s shape', {k: v for k, v in SENT[-1][1]['m'].items() if k != 'ts'}, {'id': 3, 'sys': 'join_obs', 'steam': C, 'name': 'Player'})
check('get: the whole feed', [m['id'] for m in R.api('get', A, {})['room']['chat']], [1, 2, 3])
check('here: cseq (a launcher behind asks get)', R.api('here', B, {})['cseq'], 3)

print('(2) say')
fresh()
rid = R.api('create', A, {'game': 'elite', 'ver': '3.2', 'mode': '2v2', 'map': '4p_calderisrefinery'})['room']['id']
R.api('join', B, {'id': rid}); R.api('join', C, {'id': rid, 'as': 'obs'})
check('not in a lobby: no_room', R.say_pre(D, {'text': 'hi'}), {'ok': False, 'error': 'no_room'})
check('empty: empty', R.say_pre(B, {'text': '   '}), {'ok': False, 'error': 'empty'})
SENT.clear(); m1 = say(B, {'text': '  Всем привет!\x07 ', 'cid': 'c1'})
check('a message: stored, the original, a player\'s (obs false)', (m1['ok'], m1['m']['text'], m1['m']['orig'], m1['m']['obs']), (True, 'Всем привет!', 'Всем привет!', False))
check('  ... to A, B, C', to_of('lroom_msg'), sorted([A, B, C]))
check('again at once: too_fast (1.5 s between two)', say(B, {'text': 'ещё'})['error'], 'too_fast')
R.CHAT_RATE[B] = [time.time() - 2]
check('the same cid again (a retry): the one stored, no second line', (say(B, {'text': 'Всем привет!', 'cid': 'c1'})['m']['id'], len(R.ROOMS[rid]['chat'])), (m1['m']['id'], 4))
check('the moderation: premod (outside the lock, nothing stored)', (R.say_pre(A, {'text': 'политика тут'}), len(R.ROOMS[rid]['chat'])), ({'ok': False, 'error': 'premod'}, 4))
R.CHAT_RATE.clear()
m2 = say(C, {'text': '@Player смотрю', 'reply_to': m1['m']['id']})
check('an observer writes: obs true; a reply carries the quote', (m2['m']['obs'], m2['m']['reply']['id'], m2['m']['reply']['text'], m2['m']['reply']['steam']), (True, m1['m']['id'], 'Всем привет!', B))
R.CHAT_RATE.clear()
check('a reply to a line of the lobby (sys): a plain message', 'reply' in say(A, {'text': 'ок', 'reply_to': 1})['m'], False)
R.CHAT_RATE[A] = [time.time() - 30] * 20
check('20 in a minute: too_fast', R.say_pre(A, {'text': 'x'})['error'], 'too_fast')
print('   the translation after the message')
fresh(); L.community.MODFLAGS = lambda: {'premod': True, 'translate': True}
L.community.translate = lambda t: ('ru', t, 'EN:' + t)
rid = R.api('create', A, {'game': 'elite', 'ver': '3.2', 'mode': '1v1', 'map': '2p_calderisrefinery'})['room']['id']; R.api('join', B, {'id': rid})
SENT.clear(); m = say(A, {'text': 'Привет'})
first = next(d['m'] for e, d, to in SENT if e == 'lroom_msg' and d['m'].get('text') == 'Привет')
check('the message goes at once, no translations yet (ru / en null)', (first['ru'], first['en']), (None, None))
for th in threading.enumerate():
    if th is not threading.current_thread() and th.daemon and th.name.startswith('Thread'): th.join(2)
tr = [(d, to) for e, d, to in SENT if e == 'lroom_msg_tr']
check('then lroom_msg_tr to both, with ru / en', (sorted(to for d, to in tr), tr[0][0]['mid'] if tr else None, tr[0][0]['en'] if tr else None), (sorted([A, B]), m['m']['id'], 'EN:Привет'))
check('  ... and the feed has them (get)', R.api('get', B, {})['room']['chat'][-1]['en'], 'EN:Привет')
L.community.MODFLAGS = lambda: {'premod': True, 'translate': False}

print('(3) into the observers and back; who left')
fresh()
rid = R.api('create', A, {'game': 'elite', 'ver': '3.2', 'mode': '3v3', 'map': '6p_angelgate'})['room']['id']   # 3v3: 2 observer seats
for s in (B, C, D): R.api('join', s, {'id': rid})
r = R.ROOMS[rid]
check('the owner: no (owner)', R.api('seat', A, {'slot': 'obs'}), {'ok': False, 'error': 'owner'})
v = R.api('seat', B, {'slot': 'obs'})
check('a player: into the observers, his seat free', (v['ok'], B in [s['steam'] for s in r['slots'] if s], [o['steam'] for o in r['obs']]), (True, False, [B]))
check('  ... "to_obs" in the feed, the room\'s note', (lines(rid)[-1], r['note']['k']), (('to_obs', B), 'to_obs'))
R.api('seat', C, {'slot': 'obs'})
check('the seats taken (3v3: 2): obs_full', R.api('seat', D, {'slot': 'obs'}), {'ok': False, 'error': 'obs_full'})
free = r['slots'].index(None)
R.api('seat', B, {'slot': free})
check('an observer onto a seat: "to_seat" with the team', (lines(rid)[-1], R.ROOMS[rid]['chat'][-1]['team']), (('to_seat', B), 1 if free < 3 else 2))
SENT.clear(); R.api('leave', B, {})
check('leave: "leave", not sent to him', (lines(rid)[-1], B in to_of('lroom_msg')), (('leave', B), False))
SENT.clear(); R.api('leave', A, {})
check('the owner leaves: "leave", then "host" of the new one', lines(rid)[-2:], [('leave', A), ('host', r['owner'])])
own = r['owner']; other = next(s for s in R._everyone(r) if s != own)
R.api('kick', own, {'steam': other})
check('kick: "kick"', lines(rid)[-1], ('kick', other))
R.api('join', E, {'id': rid}); _slot = R._slot(r, E); _slot['seen'] = time.time() - R.HERE_GONE - 5
R.tick(time.time())
check('no heartbeat: "gone"', lines(rid)[-1], ('gone', E))
print('   the feed keeps the last CHAT_MAX lines')
for i in range(R.CHAT_MAX + 5): R._sys(r, 'join', own)
check('CHAT_MAX lines, the ids go on', (len(r['chat']), r['chat'][-1]['id'] - r['chat'][0]['id'] + 1), (R.CHAT_MAX, R.CHAT_MAX))

shutil.rmtree(T, ignore_errors=True)
print('FAIL: %d' % len(fails) if fails else 'all ok'); sys.exit(1 if fails else 0)
