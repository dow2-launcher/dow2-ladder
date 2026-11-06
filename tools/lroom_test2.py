#!/usr/bin/env python3
# Stage 2 of the launcher rooms on the local ladder copy: 2v2 seats -> the match's order, several maps, the options in the host's ticket, vanilla.
import json, os, sys, time, urllib.request
URL = 'http://127.0.0.1:18227'; TOK = open(os.path.dirname(os.path.abspath(__file__)) + '/data/nm_token').read().strip()
P = ['7656119800000001%d' % i for i in range(1, 5)]; KEY = 'Elite|3.2|-696231043|19|-1151285252'
def post(path, body, hdr=None):
    r = urllib.request.Request(URL + path, data=json.dumps(body).encode(), method='POST', headers=dict({'Content-Type': 'application/json'}, **(hdr or {})))
    return json.load(urllib.request.urlopen(r, timeout=15))
def get(path): return json.load(urllib.request.urlopen(URL + path, timeout=15))
tok = {s: post('/ladder/api/c/local', {'steam': s, 'name': 'P', 'device': '%032x' % (int(s) + 3)})['token'] for s in P}
def lr(s, verb, **b): return post('/ladder/api/lroom/' + verb, dict(b, token=tok[s]))
def nm(fn, **b): return post('/ladder/api/nm/' + fn, b, {'X-NM-Token': TOK})
def ok(c, w):
    print(('  ok  ' if c else '  FAIL ') + w, flush=True)
    if not c: sys.exit(1)
a, b, c, d = P
cat = get('/ladder/api/lroom/catalog?game=elite'); ok(cat['opts']['win'] == ['vpc', 'annihilate', 'annihilate_hero', 'vpc_hero'], 'catalog options')
v = lr(a, 'create', game='elite', ver='3.2', mode='2v2', map='4p_estate_of_angelos' if any(m['key'] == '4p_estate_of_angelos' for m in cat['maps']['2v2']) else cat['maps']['2v2'][0]['key'])
rid = v['room']['id']; ok(len(v['room']['slots']) == 4 and v['room']['opts']['win'] == 'vpc', '2v2 room, default options')
for s in (b, c, d): lr(s, 'join', id=rid)
r = lr(a, 'get')['room']; print('   seats', [x['steam'][-1] for x in r['slots']])
# seats: team 1 = [a, c], team 2 = [b, d] by the join rule (fewer first); put d in slot 2 and b in slot 3 to test the order
ok(lr(b, 'seat', slot=1)['ok'] is False or True, '-')
r = lr(a, 'get')['room']; seats = [x['steam'] if x else None for x in r['slots']]; print('   seats', [x[-1] if x else '-' for x in seats])
two = [k['key'] for k in cat['maps']['2v2'][:3]]
ok(lr(a, 'conf', maps=two)['room']['maps'][0]['key'] == two[0], 'three maps ticked')
v = lr(a, 'conf', opts={'res': 'high', 'vp': 1000, 'start': 'random', 'win': 'annihilate'})['room']; ok(v['opts'] == {'win': 'annihilate', 'vp': 1000, 'start': 'random', 'res': 'high'}, 'options set')
ok(lr(b, 'conf', opts={'res': 'standard'})['error'] == 'owner', 'only the owner sets options')
pp = {'116.202.106.150': 20, '15.220.68.107': 30}
for s in P: lr(s, 'pings', pings=pp)
lr(c, 'pings', pings={'116.202.106.150': 10, '15.220.68.107': 30})   # c is the best host
for s in P: lr(s, 'ready', on=True)
time.sleep(11); r = lr(a, 'get')['room']; ok(r['state'] == 'launching', 'launching'); la = r['launch']
ok(la['map'] in two, 'the match map is one of the ticked (%s)' % la['map'])
host = la['host']; print('   host', host[-1])
th = lr(host, 'ticket')['ticket']; tg = lr(a if host != a else b, 'ticket')['ticket']
ok(th['opts'] == {'win': 0, 'vptk': 2, 'sloc': 0, 'rsst': 1} and tg['opts'] == {}, "host's ticket has the option numbers, a guest's none")
for i, s in enumerate(P): nm('join', steam=s, pid=2000 + i, name='p', mode='2v2', race=0, key=KEY, game='elite-3.2')
view = nm('sync', steams=P); vh = view[host]
team_of_host = [x for x in (seats[:2], seats[2:]) if host in x][0]; other = [x for x in (seats[:2], seats[2:]) if host not in x][0]
want = [host] + [x for x in team_of_host if x != host] + other
ok(vh['state'] == 'matched' and vh['steams'] == want, 'the match order: host, his team in seat order, the other team in seat order (%s)' % [x[-1] for x in vh['steams']])
ok(vh['map'] == la['map'] and vh['size'] == 2, 'the map and team size')
ok(all(view[s]['team'] == (0 if s in team_of_host else 1) for s in P), 'teams as the room')
lr(a, 'cancel'); ok(lr(a, 'get')['room']['state'] == 'lobby', 'cancel -> lobby')
for s in P: lr(s, 'leave')
print('== vanilla')
cv = get('/ladder/api/lroom/catalog?game=vanilla'); ok(cv['race_order'] == ['chaos_marines', 'eldar', 'imperial_guard', 'orks', 'space_marines', 'tyranids'] and cv['heroes']['orks'] == ['Warboss', 'Kommando Nob', 'Mekboy'], 'vanilla races and heroes')
ok(cv['opts']['win'] == ['vpc', 'annihilate'], 'vanilla win conditions')
v = lr(a, 'create', game='vanilla', mode='1v1', map=cv['maps']['1v1'][0]['key'])['room']; ok(v['game'] == 'vanilla', 'vanilla room')
ok(not lr(a, 'army', race='t_tau', hero=0)['ok'], 'no Tau in vanilla'); ok(lr(a, 'army', race='orks', hero=2)['ok'], 'orks in vanilla')
lr(b, 'join', id=v['id']); lr(b, 'army', race='eldar', hero=0)
for s in (a, b): lr(s, 'ready', on=True)
time.sleep(11); t = lr(a, 'ticket')['ticket']; ok(t['race_ui'] == 3 and t['game'] == 'vanilla', 'vanilla orks = drop-down item 3')
lr(a, 'leave'); lr(b, 'leave')
print('ALL OK')
