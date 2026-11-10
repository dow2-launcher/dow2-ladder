#!/usr/bin/env python3
"""match_log_collect.py - the game nodes' match protocol into the ladder's own_matches (own rating step 1b, 10.11.2026).

Storage only: nothing here rates, queues or changes a room. Every few minutes (match-log-collect.timer) each node is asked over
ssh for the "match_log" lines its battle_relay wrote at the end of a played session since the last run (by the byte position
in battle.jsonl: state /var/lib/match-log-collect/state.json). Each player's last connection is joined with the UDP gateway's
"close" line by the local port (battle_relay sees a gateway connection as 127.0.0.1:<lport>; the gateway's own JSON lines
UDPGW_LOG=/var/lib/dow2udpgw/gw.jsonl, else its journal) -> gw_reason (peer / dead / silent / battle_relay ...).
The lines go into own_matches.node_log + own_match_players (join_t, leave_t, leave_tick, leave_reason, rejoins, max_solo_ms)
through own_matches.on_node_log - only sessions of OUR matches (a row exists, the time fits); a second run of the same line
replaces itself. Lines younger than LAG s wait for the next run (the gateway's close comes up to ~20 s after the leave).
  match_log_collect.py [--print]                  the new lines (--print: show, write nothing, keep the state)
  match_log_collect.py --resolve                  only own rating step 2: the results + the shadow rating (also after every run)
  match_log_collect.py --backfill [--print]       sessions of our matches from before the protocol, rebuilt from the
                                                  join/leave/away/back/away_expired/vote_drop/session_end lines (v=0)
"""
import json, os, sqlite3, subprocess, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import own_matches

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get('MLOG_DB', ROOT + '/data/ladder.sqlite')
RELAYS = ROOT + '/data/relays.json'
STATE = os.environ.get('MLOG_STATE', '/var/lib/match-log-collect/state.json')
SSH = {'83.217.192.34': 'node-timeweb', '116.202.106.150': 'node-iggy', '15.220.68.107': 'node-polsha', '91.107.122.186': 'node-rupivolan'}  # ~/.ssh/config: User dow2deploy (no root on the nodes)
LAG = 150

NODE = r'''
import json, os, subprocess, sys, time
pos, upto, mode, want = int(sys.argv[1]), float(sys.argv[2]), sys.argv[3], set(sys.argv[4].split(',')) if len(sys.argv) > 4 else set()
LOG = os.environ.get('MLOG_BLOG', '/var/lib/dow2battle/battle.jsonl')
GWLOG = os.environ.get('MLOG_GWLOG', '/var/lib/dow2udpgw/gw.jsonl')
size = os.path.getsize(LOG) if os.path.exists(LOG) else 0
if pos > size: pos = 0                                              # the log was cut / replaced
logs, newpos = [], pos
with open(LOG, 'rb') as f:
    f.seek(pos)
    for raw in f:
        if not raw.endswith(b'\n'): break
        if mode == 'new':
            if b'"match_log"' in raw:
                try: e = json.loads(raw)
                except Exception: e = None
                if e is not None:
                    if e.get('t', 0) > upto: break
                    logs.append(e)
            newpos += len(raw); continue
        l = raw.decode('utf-8', 'replace')
        if True:                                                      # backfill: the events of the sessions asked for
            if not any(s in l for s in want): continue
            try: e = json.loads(l)
            except Exception: continue
            if str(e.get('sid')) in want: logs.append(e)
if mode != 'new':                                                     # rebuild a v=0 match_log per session (the last played one)
    by = {}
    for e in logs: by.setdefault(e['sid'], []).append(e)
    out = []
    for sid, ev in by.items():
        if any(e['ev'] == 'match_log' for e in ev): continue
        ends = [i for i, e in enumerate(ev) if e['ev'] == 'session_end' and e.get('ticks')]
        if not ends: continue
        k = ends[-1]; prev = max([i for i, e in enumerate(ev[:k]) if e['ev'] == 'session_end'] or [-1])
        ev = ev[prev + 1:k + 1]; end = ev[-1]; pl = {}
        for e in ev:
            if 'idx' not in e: continue
            p = pl.setdefault(e['idx'], dict(idx=e['idx'], join_t=None, rejoins=-1, leave_t=None, leave_tick=e.get('tick'), reason=None,
                                             conn_reason=None, steam='', max_solo_ms=0, turns=0, peer=None, gw_reason=None))
            if e['ev'] == 'join': p['rejoins'] += 1; p['join_t'] = p['join_t'] or e['t']; p['peer'] = e.get('peer'); p['leave_t'] = None
            elif e['ev'] == 'leave':
                p['leave_t'] = e['t']; p['steam'] = e.get('steam') or p['steam']; p['turns'] += e.get('turns') or 0
                p['max_solo_ms'] = max(p['max_solo_ms'], e.get('max_solo_ms') or 0); p['peer'] = e.get('peer') or p['peer']
                p['reason'] = e.get('why'); p['leave_tick'] = e.get('tick')
            elif e['ev'] in ('away_expired', 'vote_drop'): p['conn_reason'] = p['reason']; p['reason'] = 'grace_over' if e['ev'] == 'away_expired' else 'vote_drop'
        for p in pl.values(): p['rejoins'] = max(0, p['rejoins'])
        lt = [p['leave_t'] for p in pl.values() if p['leave_t']]
        out.append(dict(ev='match_log', v=0, sid=sid, started=ev[0]['t'], t_end=end['t'], ticks=end.get('ticks'), turns=end.get('turns'),
                        late_ticks=end.get('late_ticks'), players=list(pl.values()), t=end['t'],
                        all_gone_within_s=round(max(lt) - min(lt), 1) if lt and len(lt) == len(pl) else None))
    logs, newpos = out, pos
closes = {}
lps = [int(str(p.get('peer') or '').rpartition(':')[2] or 0) for m in logs for p in m.get('players') or []
       if str(p.get('peer') or '').startswith('127.0.0.1:')]
if lps:
    lo, hi = min(m['started'] for m in logs) - 600, max(m['t_end'] for m in logs) + 600
    if os.path.exists(GWLOG):
        with open(GWLOG, 'rb') as f:
            f.seek(0, 2); n = f.tell(); f.seek(max(0, n - (24 << 20)))
            for l in f.read().decode('utf-8', 'replace').splitlines():
                try: e = json.loads(l)
                except Exception: continue
                if e.get('ev') == 'close' and lo <= e.get('t', 0) <= hi: closes.setdefault(int(e.get('lport') or 0), []).append((e['t'], e.get('by'), e.get('peer')))
    if not closes:                                                    # no JSON lines (yet): the journal
        j = subprocess.run(['journalctl', '-u', 'dow2-udpgw', '--since', '@%d' % lo, '--until', '@%d' % hi, '-o', 'short-unix', '--no-pager'],
                           capture_output=True, text=True).stdout
        for line in j.splitlines():
            if ' ev=close ' not in line or ' lport=' not in line: continue
            try:
                kv = dict(x.split('=', 1) for x in line.split() if '=' in x)
                closes.setdefault(int(kv['lport']), []).append((float(line.split()[0]), kv.get('by'), kv.get('peer')))
            except Exception: continue
for m in logs:
    for p in m.get('players') or []:
        h, _, port = str(p.get('peer') or '').rpartition(':')
        if h != '127.0.0.1' or not p.get('leave_t'): continue
        c = [x for x in closes.get(int(port or 0), []) if abs(x[0] - p['leave_t']) < 180]
        if c: x = min(c, key=lambda x: abs(x[0] - p['leave_t'])); p['gw_reason'] = x[1]; p['gw_peer'] = x[2]
        p['via'] = 'udp'
print(json.dumps({'logs': logs, 'pos': newpos, 'size': size}))
'''


def load_state():
    try: return json.load(open(STATE))
    except Exception: return {}


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + '.tmp'; json.dump(st, open(tmp, 'w')); os.replace(tmp, STATE)


def ask(host, *args):
    r = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', host, 'python3', '-'] + [str(a) for a in args],
                       input=NODE, capture_output=True, text=True, timeout=300)
    d = json.loads(r.stdout or 'null')
    if d is None: raise RuntimeError((r.stderr or '').strip()[-300:])
    return d


def step2():
    """own rating step 2 (shadow, shown to nobody): every own match's result + "a leave = a loss", then own_ratings from scratch"""
    try: own_matches.step2(DB, log=lambda s: print('mlog: ' + s, flush=True))
    except Exception as e: print('mlog: step2: %r' % e, flush=True)


def main():
    show, back = '--print' in sys.argv, '--backfill' in sys.argv
    if '--resolve' in sys.argv: return step2()
    own_matches.setup(lambda: sqlite3.connect(DB, timeout=30), threading.Lock(), lambda t: None)
    ips = [r['ip'] for r in json.load(open(RELAYS)).get('relays', []) if r.get('ip')]
    st = load_state(); upto = time.time() - LAG
    want = ''
    if back:
        c = sqlite3.connect('file:%s?mode=ro' % DB, uri=True, timeout=30)
        want = ','.join(str(r[0]) for r in c.execute('SELECT sid FROM own_matches WHERE node_log IS NULL')); c.close()
        if not want: print('mlog: backfill: nothing to do'); return
    for ip in ips:
        host = SSH.get(ip)
        if not host: continue
        s = st.get(ip) or {}
        try:
            d = ask(host, 0, upto, 'back', want) if back else ask(host, s.get('pos', 0), upto, 'new')
        except Exception as e:
            print('mlog: %s (%s): %r' % (ip, host, e), flush=True); continue
        res = {}
        for m in d['logs']:
            if show: print(ip, json.dumps(m)[:600]); continue
            r = own_matches.on_node_log(m, ip); res[r] = res.get(r, 0) + 1
        if not show and not back: st[ip] = dict(pos=d['pos'], t=int(time.time()))
        print('mlog: %s: %d lines %s' % (ip, len(d['logs']), json.dumps(res)), flush=True)
    if not show and not back: save_state(st)
    if not show: step2()


if __name__ == '__main__':
    main()
