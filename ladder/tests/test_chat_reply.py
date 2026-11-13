#!/usr/bin/env python3
# The chat's replies (13.11.2026, the launcher's Reply): say() with reply_to, the quote of the original on every message that
# answers one (c/msgs, the stream's missed and the "msg" event, say's own answer), a deleted / missing original, the features.
# usage: python3 ladder/tests/test_chat_reply.py [<app dir>, default: this ladder/] - against a temp copy with an empty
# community.sqlite; nothing live is touched, no Steam / translation calls.
import json, os, shutil, sys, tempfile, time
APP = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = tempfile.mkdtemp(prefix='ladder_r_'); shutil.copytree(APP, T + '/app', ignore=shutil.ignore_patterns('__pycache__', '*.bak*'))
os.makedirs(T + '/data'); sys.path.insert(0, T + '/app')
import users; users.PROFILE_SECS = 10 ** 10                # no Steam fetches from the test
import community, stream
community.MODFLAGS = lambda: {'premod': False, 'translate': False}   # stored at once, no translation thread
A, B = '76561198000000001', '76561198000000002'
with community.db() as c:
    for s, tok in ((A, 'tok-a'), (B, 'tok-b')): c.execute('INSERT INTO sess(token, steam, ts) VALUES(?,?,?)', (tok, s, int(time.time())))
fails = []
def check(name, ok, got=None):
    print('  %-58s %s' % (name, 'ok' if ok else 'FAIL %s' % (json.dumps(got, ensure_ascii=False)[:200] if got is not None else '')))
    if not ok: fails.append(name)
def say(tok, text, cid, **kw):
    r = community.say(dict(token=tok, room='all', text=text, cid=cid, **kw)); time.sleep(1.6); return r   # 1.5 s between one's messages
got = []; stream.publish = lambda ev, d, to=None: got.append((ev, d))

print('== features')
check('hello says reply', 'reply' in community.hello({'token': 'tok-a'}).get('features', []))
check('msgs says reply', 'reply' in community.msgs('all', 0).get('features', []))

print('== a reply')
a = say('tok-a', 'Собираю 2v2 в лобби лаунчера, одно место свободно', 'c1')
b = say('tok-b', 'иду', 'c2', reply_to=a['id'])
q = b['msg'].get('reply') or {}
check("say's answer carries the quote", q.get('id') == a['id'] and q.get('steam') == A and q.get('text', '').startswith('Собираю'), b['msg'])
ev = [d for e, d in got if e == 'msg' and d['id'] == b['id']]
check("the stream's msg event carries it", ev and (ev[0].get('reply') or {}).get('id') == a['id'], ev)
ms = {m['id']: m for m in community.msgs('all', 0)['msgs']}
check('msgs: the reply has the quote', (ms[b['id']].get('reply') or {}).get('id') == a['id'], ms.get(b['id']))
check('msgs: the original has none', 'reply' not in ms[a['id']], ms.get(a['id']))
check('msgs ru / en: the quote in each', all((m.get('reply') or {}).get('id') == a['id'] for room in ('ru', 'en') for m in community.msgs(room, 0)['msgs'] if m['id'] == b['id']))
mi = [d for e, d in community.missed('all:0') if d.get('id') == b['id']]
check("the stream's missed carries it", mi and (mi[0].get('reply') or {}).get('id') == a['id'], mi)
check('a retry with the same cid: the same reply', say('tok-b', 'иду', 'c2', reply_to=a['id'])['id'] == b['id'])

print('== the quote is short')
long_ = say('tok-a', 'x' * 400, 'c3'); r = say('tok-b', 'ок', 'c4', reply_to=long_['id'])
check('140 characters of the original', len(r['msg']['reply']['text']) == community.QUOTE, r['msg']['reply'])

print('== no original')
r = say('tok-b', 'в пустоту', 'c5', reply_to=999999)
check('a missing id: a plain message', 'reply' not in r['msg'], r['msg'])
r = say('tok-b', 'текст', 'c6', reply_to='abc')
check('a bad id: a plain message', r.get('ok') and 'reply' not in r['msg'], r)
with community.db() as c: c.execute('UPDATE msg SET deleted=1 WHERE id=?', (a['id'],))
ms = {m['id']: m for m in community.msgs('all', 0)['msgs']}
check('the original deleted: the quote says so', ms[b['id']].get('reply') == {'id': a['id'], 'deleted': True}, ms.get(b['id']))
r = say('tok-b', 'поздно', 'c7', reply_to=a['id'])
check('a reply to a deleted one: a plain message', 'reply' not in r['msg'], r['msg'])

print('== an old row (no reply_to column value)')
with community.db() as c: c.execute("INSERT INTO msg(room,steam,text,ts,lang,t_ru,t_en) VALUES('all',?,'old',?,'ru','old','old')", (A, int(time.time())))
check('no reply, builds as before', all('reply' not in m for m in community.msgs('all', 0)['msgs'] if m['orig'] == 'old'))

shutil.rmtree(T, ignore_errors=True)
print('PASS' if not fails else 'FAIL: %d' % len(fails)); sys.exit(1 if fails else 0)
