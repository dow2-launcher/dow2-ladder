#!/usr/bin/env python3
# 06.11.2026 fixes: another race in the search -> the start is off with "race" and who; the spoil counter; the ticket's ttl
import json, os, sys, time, urllib.request
URL = 'http://127.0.0.1:18227'; TOK = open(os.path.dirname(os.path.abspath(__file__)) + '/data/nm_token').read().strip()
A, B = '76561198000000031', '76561198000000032'; KEY = 'Elite|3.2|-696231043|19|-1151285252'
def post(path, body, hdr=None):
    r = urllib.request.Request(URL + path, data=json.dumps(body).encode(), method='POST', headers=dict({'Content-Type': 'application/json'}, **(hdr or {})))
    return json.load(urllib.request.urlopen(r, timeout=15))
tok = {s: post('/ladder/api/c/local', {'steam': s, 'name': 'P', 'device': '%032x' % (int(s) + 5)})['token'] for s in (A, B)}
def lr(s, verb, **b): return post('/ladder/api/lroom/' + verb, dict(b, token=tok[s]))
def nm(fn, **b): return post('/ladder/api/nm/' + fn, b, {'X-NM-Token': TOK})
def ok(c, w):
    print(('  ok  ' if c else '  FAIL ') + w, flush=True)
    if not c: sys.exit(1)
rid = lr(A, 'create', game='elite', ver='3.2', mode='1v1', map='2p_calderisdunes')['room']['id']; lr(B, 'join', id=rid)
lr(A, 'army', race='orks', hero=2); lr(B, 'army', race='space_marines', hero=0)
for s in (A, B): lr(s, 'ready', on=True)
time.sleep(11); t = lr(B, 'ticket')['ticket']; ok(100 < t['ttl'] <= 150, 'ticket ttl %s' % t['ttl'])
nm('join', steam=A, pid=31, name='a', mode='1v1', race=4, key=KEY, game='elite-3.2')
v = nm('join', steam=B, pid=32, name='b', mode='1v1', race=1, key=KEY, game='elite-3.2')   # eldar instead of space marines
ok(v['state'] == 'cancelled', 'B searching as eldar: no match, his search cancelled')
r = lr(A, 'get')['room']; ok(r['state'] == 'lobby' and r['note']['k'] == 'race' and r['note']['why'] == 'eldar', 'room back in lobby, note race (%s)' % r['note'])
ok([x['spoil'] for x in r['slots']] == [0, 1], 'B: spoiled the start x1')
ok(nm('sync', steams=[A])[A]['state'] == 'cancelled', "A's search stopped too")
ok(lr(A, 'kick', steam=B)['ok'], 'the owner kicks B')
lr(A, 'leave'); print('ALL OK')
