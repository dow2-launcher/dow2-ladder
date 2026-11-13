#!/usr/bin/env python3
"""The match as the game's own simulation saw it, for the replay page (13.11.2026).

Input: the per-second dumps of the headless replay runner (fastbench on prod_gpu, extract mode):
  <SIM>/<rid>.csv.gz          t,player,squad,bp,x,z,hp,hpmax,n,state[,sup]   every squad every second
  <SIM>/<rid>.players.csv.gz  t,player,req,pow,waaagh,pop,popmax,points       every player every second
and the replay itself (names, teams, races, heroes, chat, the map size from DATASDSC).
Output: <STORE>/<rid>/sim.json.gz - what the page plays back: positions, economy, points held, deaths, fights, heat maps, chat.

The minimap of the game covers the whole terrain: width x height from DATASDSC, centred at 0, +z up.
Engine player ids (1000..) are NOT the lobby slot order: matched by the hero squad (race + hero choice), then by team.

  sim_view.py <rid> [<rid> ...]     or     sim_view.py --all
"""
import csv, gzip, json, math, os, struct, sys
from collections import Counter, defaultdict

APP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP)
import dow2rec

ROOT = os.environ.get('REPLAY_ROOT', os.path.dirname(APP))
STORE = ROOT + '/data'
SIM = os.environ.get('SIM_DIR', ROOT + '/sim')
ASSETS = os.environ.get('ASSETS_INDEX', '/var/www/rts-site/elite/assets/index.json')

STATES = ['Idle', 'Move', 'AttackMove', 'Combat', 'Melee', 'Retreat', 'Capture', 'Ability', 'HunkerDown', 'Jump', 'Construction']
PALETTE = [['#4aa3ff', '#3fd6c6', '#9b87ff', '#7fc8ff'], ['#ff5a4f', '#ffb02e', '#ff6fb5', '#ff8a5c']]


def sdsc(d):
    """map name, width, height from the replay's DATASDSC chunk"""
    i = d.find(b'DATASDSC')
    size, nl = struct.unpack_from('<II', d, i + 12)
    b = d[i + 28 + nl:i + 28 + nl + size]
    o = 4; n = struct.unpack_from('<I', b, o)[0]; o += 4 + n * 2 + 4
    if b[o:o + 4] != b'DOW2': raise ValueError('no DOW2 in DATASDSC')
    o += 4; n = struct.unpack_from('<I', b, o)[0]; mp = b[o + 4:o + 4 + n].decode('latin1'); o += 4 + n
    for _ in range(2):
        n = struct.unpack_from('<I', b, o)[0]; o += 4 + n * 2
    _, _, w, h = struct.unpack_from('<IIII', b, o)
    return mp.replace('/', '\\').split('\\')[-1].lower(), w, h


def label(bp):
    p = bp.split('_')
    if len(p) > 1 and p[0] in ('sm', 'csm', 'ork', 'ig', 'tau', 'eld', 'tyr', 'gk', 'om', 'inq', 'nis', 'kroot'): p = p[1:]
    return ' '.join(p).strip().capitalize() or bp


def build(rid, assets):
    d = open(f'{STORE}/{rid}/replay.rec', 'rb').read()
    meta, _ = dow2rec.parse(f'{STORE}/{rid}/replay.rec')
    mapk, W, H = sdsc(d)
    lobby = [p for p in meta['players'] if p.get('race')]

    rows = []
    for r in csv.DictReader(gzip.open(f'{SIM}/{rid}.csv.gz', 'rt')):
        try: rows.append((float(r['t']), int(r['player']), int(r['squad']), r['bp'], float(r['x']), float(r['z']),
                          float(r['hp'] or 0), float(r['hpmax'] or 0), int(float(r['n'] or 0)), r['state']))
        except ValueError: continue
    if not rows: raise ValueError('empty dump')
    prow = []   # the first ~380 extracted replays have no per-player file: no economy / points for them
    pf = f'{SIM}/{rid}.players.csv.gz'
    for r in (csv.DictReader(gzip.open(pf, 'rt')) if os.path.exists(pf) else []):
        try: prow.append((float(r['t']), int(r['player']), int(float(r['req'] or 0)), int(float(r['pow'] or 0)),
                          int(float(r['waaagh'] or 0)), int(float(r['points'] or 0)) if r.get('points') not in (None, '', '?') else None))
        except ValueError: continue

    # ---- engine player id -> lobby player
    pids = sorted({r[1] for r in rows} | {r[1] for r in prow})
    early = defaultdict(set)
    t_first = rows[0][0]
    for t, pid, sq, bp, *_ in rows:
        if t <= t_first + 10: early[pid].add(bp)
    pts_series = defaultdict(list)
    for t, pid, req, pw, wg, pt in prow: pts_series[pid].append(pt)
    groups = {}
    for pid in pids: groups.setdefault(tuple(pts_series.get(pid, [])), []).append(pid)
    eng_team = {}
    for gi, (k, g) in enumerate(groups.items()):
        for pid in g: eng_team[pid] = gi if len(groups) > 1 else None

    def hero_bp(p):
        r = (assets.get('races') or {}).get(p['race']) or {}
        hs = r.get('heroes') or []
        h = p.get('hero', 0)
        return hs[h]['sbp'].split('/')[-1] if 0 <= h < len(hs) else None, (hs[h]['name'] if 0 <= h < len(hs) else '')

    cand = {}
    for i, p in enumerate(lobby):
        hb, _ = hero_bp(p)
        cand[i] = [pid for pid in pids if hb and hb in early[pid]]
    assign, used = {}, set()
    for _ in range(3):
        for i, c in cand.items():
            if i in assign: continue
            free = [pid for pid in c if pid not in used]
            if len(free) == 1: assign[i] = free[0]; used.add(free[0])
        # team of an engine group = the lobby team of the players already matched in it
        gteam = {}
        for i, pid in assign.items():
            if eng_team.get(pid) is not None: gteam.setdefault(eng_team[pid], Counter())[lobby[i]['team']] += 1
        for i, c in cand.items():
            if i in assign: continue
            free = [pid for pid in c if pid not in used]
            same = [pid for pid in free if eng_team.get(pid) in gteam and gteam[eng_team[pid]].most_common(1)[0][0] == lobby[i]['team']]
            if len(same) == 1: assign[i] = same[0]; used.add(same[0])
    left = [pid for pid in pids if pid not in used]
    for i in range(len(lobby)):
        if i not in assign and left: assign[i] = left.pop(0)
    players, pinfo = [], {}
    tcount = Counter()
    for i, p in enumerate(lobby):
        pid = assign.get(i)
        if pid is None: continue
        team = p['team']; col = PALETTE[team % 2][tcount[team] % 4]; tcount[team] += 1
        _, hname = hero_bp(p)
        pinfo[pid] = {'pid': pid, 'name': p['name'], 'race': p['race'], 'team': team, 'hero': p.get('hero', 0),
                      'hero_name': hname, 'level': p.get('level'), 'color': col}
        players.append(pinfo[pid])
    matched = sum(1 for i, p in enumerate(lobby) if i in assign and (hero_bp(p)[0] in early[assign[i]]))

    # ---- frames
    t0 = rows[0][0]
    sec = lambda t: int(round(t - t0))
    nsec = sec(rows[-1][0]) + 1
    frames = [[] for _ in range(nsec)]
    squads = {}
    last = {}
    firstseen = {}
    hero_bps = {hero_bp(p)[0] for p in lobby}
    for t, pid, sq, bp, x, z, hp, hpm, n, st in rows:
        s = sec(t)
        if sq not in squads:
            squads[sq] = [pid, label(bp), 1 if bp in hero_bps else 0, bp]
            firstseen[sq] = s
        hpp = int(round(100 * hp / hpm)) if hpm > 0 else 0
        frames[s] += [sq, round(x, 1), round(z, 1), hpp, n, STATES.index(st) if st in STATES else -1]
        last[sq] = (s, x, z, hp, n, pid)

    # ---- deaths: a squad that stops being dumped for good; heroes stay in the dump and lie at 0 hp
    deaths = []
    end = nsec - 1
    for sq, (s, x, z, hp, n, pid) in last.items():
        if s < end - 2: deaths.append([s + 1, sq, round(x, 1), round(z, 1)])
    prevhp = {}
    for t, pid, sq, bp, x, z, hp, hpm, n, st in rows:   # a hero goes down: stays in the dump at 0 hp until revived
        if squads[sq][2] and (hp <= 0 or n == 0) and prevhp.get(sq, 0) > 0: deaths.append([sec(t), sq, round(x, 1), round(z, 1)])
        prevhp[sq] = hp if n > 0 else 0
    deaths.sort()

    # ---- damage per second -> fights (place + time clusters), army strength
    army = defaultdict(lambda: [0] * nsec)
    prev = {}
    dmg = []   # (s, x, z, team, hp lost, squad)
    for t, pid, sq, bp, x, z, hp, hpm, n, st in rows:
        s = sec(t)
        army[pid][s] += hp
        if sq in prev:
            ps, phx = prev[sq]
            if s - ps <= 2 and hp < phx - 1: dmg.append((s, x, z, pinfo.get(pid, {}).get('team', -1), phx - hp, sq))
        prev[sq] = (s, hp)
    for s0, sq, x, z in deaths:
        pid = squads[sq][0]
        if not squads[sq][2]: dmg.append((s0, x, z, pinfo.get(pid, {}).get('team', -1), prev.get(sq, (0, 0))[1], sq))
    CELL = 40.0
    open_f = []
    fights = []
    for e in sorted(dmg):
        s, x, z = e[0], e[1], e[2]
        hit = None
        for f in open_f:
            if s - f['t1'] <= 6 and math.hypot(x - f['cx'], z - f['cz']) <= CELL * 1.5: hit = f; break
        if not hit:
            hit = {'t0': s, 't1': s, 'ev': [], 'cx': x, 'cz': z}; open_f.append(hit)
        hit['ev'].append(e); hit['t1'] = s
        w = sum(v[4] for v in hit['ev'])
        hit['cx'] = sum(v[1] * v[4] for v in hit['ev']) / max(w, 1); hit['cz'] = sum(v[2] * v[4] for v in hit['ev']) / max(w, 1)
        open_f = [f for f in open_f if s - f['t1'] <= 6 or fights.append(f)]
    fights += open_f
    dset = {(sq) for _, sq, _, _ in deaths}
    out_f = []
    for f in fights:
        loss = Counter(); killed = defaultdict(list)
        for s, x, z, team, v, sq in f['ev']: loss[team] += v
        for s, sq, x, z in deaths:
            if f['t0'] <= s <= f['t1'] + 2 and math.hypot(x - f['cx'], z - f['cz']) <= CELL * 2:
                killed[pinfo.get(squads[sq][0], {}).get('team', -1)].append(sq)
        tot = sum(loss.values())
        if tot < 900 or len([k for k in loss if k >= 0]) < 2 or f['t1'] - f['t0'] < 4: continue
        teams = sorted(k for k in loss if k >= 0)
        win = min(teams, key=lambda k: loss[k]) if max(loss.values()) > 1.35 * min(loss[k] for k in teams) else None
        out_f.append({'t0': f['t0'], 't1': f['t1'], 'x': round(f['cx'], 1), 'z': round(f['cz'], 1), 'loss': {str(k): int(loss[k]) for k in teams},
                      'killed': {str(k): v for k, v in killed.items() if k >= 0}, 'win': win, 'size': int(tot)})
    out_f.sort(key=lambda f: -f['size'])
    out_f = sorted(out_f[:14], key=lambda f: f['t0'])

    # ---- heat maps: seconds spent per 32 x 32 cell (army squads only)
    G = 32
    heat = {}
    for t, pid, sq, bp, x, z, hp, hpm, n, st in rows:
        if n <= 0: continue
        gx = min(G - 1, max(0, int((x / W + .5) * G))); gz = min(G - 1, max(0, int((.5 - z / H) * G)))
        heat.setdefault(pid, [0] * (G * G))[gz * G + gx] += 1

    # ---- economy and points held
    eco = {}
    pts = {}
    for t, pid, req, pw, wg, pt in prow:
        s = sec(t)
        if s < 0 or s >= nsec: continue
        e = eco.setdefault(pid, {'req': [None] * nsec, 'pow': [None] * nsec, 'wg': [None] * nsec})
        e['req'][s] = req; e['pow'][s] = pw; e['wg'][s] = wg
        tm = pinfo.get(pid, {}).get('team')
        if tm is not None and pt is not None: pts.setdefault(str(tm), [None] * nsec)[s] = pt
    teams_army = defaultdict(lambda: [0] * nsec)
    for pid, a in army.items():
        tm = pinfo.get(pid, {}).get('team', -1)
        for i, v in enumerate(a): teams_army[str(tm)][i] += v

    chat = [[max(0, c['tick'] // 10 - int(round(t0))), c['name'], c['to'], c['text']] for c in meta.get('chat') or []]
    try: mpts = json.load(open(APP + '/maps_points.json')).get(mapk) or []
    except Exception: mpts = []
    KIND = {'victory_point_02': 'vp', 'capture_point': 'cp', 'requisition_point': 'cp', 'power_point': 'pw', 'starting_point': 'base'}
    mpoints = [[KIND.get(p['kind'], 'cp'), p['x'], p['y']] for p in mpts if p.get('kind') in KIND]
    # strategic points from the game itself (extract's <rid>.points.csv.gz, 13.11): owner and capturers on every change
    pown = None
    pf = f'{SIM}/{rid}.points.csv.gz'
    if os.path.exists(pf):
        pidx, plist, pev = {}, [], []
        side = lambda pid: pinfo.get(pid, {}).get('team', -1)
        for r in csv.DictReader(gzip.open(pf, 'rt')):
            try: eid = int(r['point']); t = float(r['t']); owner = int(r['owner'])
            except (ValueError, KeyError): continue
            if eid not in pidx:
                bp = r.get('bp') or ''
                kd = 'vp' if r.get('vp') == '1' or 'victory' in bp else ('req' if 'requisition' in bp else 'pw' if 'power' in bp else 'sp')
                pidx[eid] = len(plist); plist.append([kd, float(r['x']), float(r['z'])])
            caps = {side(int(c)) for c in (r.get('capturer') or '').split('+') if c.strip().lstrip('-').isdigit()}
            caps.discard(-1)
            capt = (caps.pop() if len(caps) == 1 else 2) if caps else -1
            pev.append([round(max(0.0, t - t0), 1), pidx[eid], side(owner) if owner >= 0 else -1, capt])
        if plist: pown = {'pts': plist, 'ev': pev}
    return {'v': 1, 'rid': rid, 'map': mapk, 'w': W, 'h': H, 't0': t0, 'dur': nsec, 'states': STATES,
            'players': players, 'matched_by_hero': matched, 'squads': {str(k): v for k, v in squads.items()},
            'frames': frames, 'deaths': deaths, 'fights': out_f,
            'heat': {str(k): v for k, v in heat.items()}, 'grid': G,
            'eco': {str(k): v for k, v in eco.items()}, 'points': pts,
            'army': {str(k): [int(x) for x in v] for k, v in army.items()}, 'army_team': {k: [int(x) for x in v] for k, v in teams_army.items()},
            'chat': chat, 'mpoints': mpoints, 'pown': pown}


def main(rids):
    assets = json.load(open(ASSETS))
    ok = bad = 0
    for rid in rids:
        try:
            if not os.path.exists(f'{SIM}/{rid}.csv.gz') or not os.path.exists(f'{STORE}/{rid}/replay.rec'): continue
            j = build(rid, assets)
            tmp = f'{STORE}/{rid}/sim.json.gz.tmp'
            with gzip.open(tmp, 'wt', compresslevel=6) as f: json.dump(j, f, ensure_ascii=False, separators=(',', ':'))
            os.replace(tmp, f'{STORE}/{rid}/sim.json.gz')
            ok += 1
            print(rid, 'ok', j['map'], j['dur'], 's', len(j['players']), 'players', j['matched_by_hero'], 'by hero', len(j['fights']), 'fights', flush=True)
        except Exception as e:
            bad += 1; print(rid, 'FAIL', repr(e)[:200], flush=True)
    print('done', ok, 'failed', bad)


if __name__ == '__main__':
    a = sys.argv[1:]
    if a == ['--all']:
        a = sorted({json.loads(l)['rid'] for l in open(f'{SIM}/index.jsonl') if '"ok"' in l})
    main(a)
