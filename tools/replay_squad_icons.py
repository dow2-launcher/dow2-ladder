#!/usr/bin/env python3
"""Squad icons for the replay page's match player (17.11.2026): site/assets/squads.json + site/assets/squads/<bp>.webp.

The game's own squad portraits (64x64 webp) and names (en/ru) come from the Elite Codex build on prod_gpu
(/mnt/dow2bench/dev/elite_wiki: cache/wiki.json, cache/icons.json, site/img - DDS from the UI archives, converted there).
The key is the squad blueprint's short name - the "bp" the replay runner dumps (sim_view.py keeps it as squads[id][3]).

squads.json: {"<bp>": {"i": "squads/<bp>.webp" | absent, "n": {"en": .., "ru": ..}, "s": 1 when summoned (no cost, not a hero)}}
The page numbers the squads a player built in build order; "s" ones (temporary Bloodletters, Noxious Cloud...) are not numbered.

    tools/replay_squad_icons.py [WIKI_DIR] [SITE_ASSETS_DIR]
"""
import json, os, shutil, sys

WIKI = sys.argv[1] if len(sys.argv) > 1 else '/mnt/dow2bench/dev/elite_wiki'
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'site', 'assets')

wiki = json.load(open(os.path.join(WIKI, 'cache', 'wiki.json')))
icons = json.load(open(os.path.join(WIKI, 'cache', 'icons.json')))
os.makedirs(os.path.join(OUT, 'squads'), exist_ok=True)
rank = {'hero': 0, 'hq': 1, 'other': 2}
out = {}
for key, q in sorted(wiki['squads'].items(), key=lambda kv: rank.get(kv[1].get('cat'), 3)):
    bp = key.split('/')[-1]
    if bp in out: continue
    summon = q.get('cat') != 'hero' and not (q.get('req') or 0) and not (q.get('power') or 0)
    e = {'n': {k: v for k, v in (q.get('name') or {}).items() if v}}
    if summon: e['s'] = 1
    src = icons.get('squad|%s|%s' % (q.get('icon'), q.get('race')))
    if src and os.path.exists(os.path.join(WIKI, 'site', src)):
        shutil.copyfile(os.path.join(WIKI, 'site', src), os.path.join(OUT, 'squads', bp + '.webp'))
        e['i'] = 'squads/%s.webp' % bp
    out[bp] = e
# ability entities the runner dumps as squads but the Codex does not list (CSM "chaos nuke" cores, seen in the pool 17.11)
for bp in ('csm_chaos_nuke_core_aura', 'csm_chaos_nuke_core_aura_nurgle', 'csm_chaos_nuke_core_aura_tzeentch'):
    out.setdefault(bp, {'n': {'en': 'Chaos nuke core', 'ru': 'Ядро хаос-удара'}, 's': 1})
with open(os.path.join(OUT, 'squads.json'), 'w') as f:
    json.dump(out, f, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
print(len(out), 'squads,', sum(1 for e in out.values() if 'i' in e), 'with icons,', sum(1 for e in out.values() if e.get('s')), 'summoned')
