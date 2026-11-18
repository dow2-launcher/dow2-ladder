// The match player of the replay page (13.11.2026): the game's own simulation of the replay (headless runner on the bench,
// per-second dump of every squad) drawn over the in-game minimap. Data: /replay/api/r/<rid>/sim.json (sim_view.py).
// Uses the page's globals: L, T, AS, A, esc, mins, rk, rname, assetsReady.
(function () {
  const TX = {
    en: { title: 'The match, second by second', badge: 'game engine', sub: 'Every squad of the match as the game itself simulated it: positions, health and orders each second. Press play or click any moment.',
      play: 'Play', pause: 'Pause', trails: 'Trails', heat: 'Heat map', heatNone: 'off', army: 'Army strength (total HP of the squads on the field)',
      pts: 'Strategic points held', req: 'Squads on the field', moments: 'Key moments', all: 'All', fights: 'Fights', heroes: 'Heroes', deaths: 'Losses', chat: 'Chat',
      team: n => 'Team ' + n, sides: ['Blue', 'Red'], fight: 'Fight', near: d => d === 'C' ? 'in the centre' : 'in the ' + TX.en.dirs[d], won: t => 'won by ' + t, even: 'even trade', lostHp: 'HP lost', wiped: 'squads wiped',
      heroDown: (h, p) => `${h} (${p}) is down`, squadLost: (s, p) => `${s} (${p}) wiped out`, alive: 'squads', bank: 'req', power: 'power', waaagh: 'Waaagh',
      dirs: { N: 'north', NE: 'north-east', E: 'east', SE: 'south-east', S: 'south', SW: 'south-west', W: 'west', NW: 'north-west', C: 'centre' },
      st: ['idle', 'moving', 'attack-move', 'in combat', 'melee', 'retreating', 'capturing', 'ability', 'dug in', 'jumping', 'building'],
      offer: 'The detailed analysis is not made for this replay yet: the game itself replays the match (no graphics, about a minute) and the whole match appears here on the map - every squad, fights, points, losses.',
      ask: '▶ Make the detailed analysis', queued: 'In the queue - this page will show the match by itself, usually within 2-5 minutes.', running: 'The game is replaying the match right now…', building: 'Almost ready…',
      failed: 'The game could not replay this match', unsupported: 'The detailed analysis works for Elite 3.2 / 3.2.1 and vanilla Retribution replays of at least half a minute.', busy: 'The queue is full right now - try in a few minutes.',
      hp: 'HP', sec: 's', models: 'models', qBuilt: 'built', qDead: 'wiped out', qDown: 'down', qOff: 'not on the map (garrison / transport)', end: 'Points at the end', loading: 'Loading the match…', fail: 'Could not load the match data', start: '▶ Watch the match',
      resTitle: 'Match result', resWin: 'Winner', resLikely: 'Probable winner', resUnknown: 'Result unknown', at: 'At', resPts: 'points held', resVp: 'victory points held', resSq: 'squads on the field',
      resWipe: 'all squads of the other side were destroyed', resRead: 'read from the state of the match at its end: victory points and points held, army strength', resGuess: 'estimated from retreats and squad losses in the last quarter of the match',
      resNone: 'the replay does not say clearly enough who won',
      resNote: 'The replay does not record how the match ended (victory points, HQ, surrender), so the verdict comes from the last seconds.',
      tk: 'Victory point score', tkHint: n => `each side starts with ${n}; the side holding fewer victory points loses score, 0 = defeat. Marks: a victory point changes hands`,
      tkS: 'VP score', tkPts: 'strategic points held', tkVp: 'victory points held', resScore: 'victory point score',
      resVpWin: 'the victory point score of the other side ran out (the game\'s own win condition)', resConcede: 'the other side conceded (the game\'s own win condition)',
      resHq: 'the HQ of the other side was destroyed (the game\'s own win condition)', resGame: 'the game\'s own win condition' },
    ru: { title: 'Матч посекундно', badge: 'движок игры', sub: 'Все отряды матча так, как их просчитала сама игра: где стоят, сколько здоровья и что делают — каждую секунду. Жмите «Смотреть» или кликайте в любой момент.',
      play: 'Смотреть', pause: 'Пауза', trails: 'Следы', heat: 'Тепловая карта', heatNone: 'выкл', army: 'Сила армий (сумма HP отрядов на поле)',
      pts: 'Стратегические точки под контролем', req: 'Отрядов на поле', moments: 'Ключевые моменты', all: 'Все', fights: 'Бои', heroes: 'Герои', deaths: 'Потери', chat: 'Чат',
      team: n => 'Команда ' + n, sides: ['Синие', 'Красные'], fight: 'Бой', near: d => d === 'C' ? 'в центре' : 'на ' + TX.ru.dirs[d], won: t => t + ' выиграли', even: 'размен на равных', lostHp: 'потеряно HP', wiped: 'отрядов уничтожено',
      heroDown: (h, p) => `${h} (${p}) пал`, squadLost: (s, p) => `${s} (${p}) уничтожен`, alive: 'отрядов', bank: 'рек.', power: 'энергия', waaagh: 'Waaagh',
      dirs: { N: 'севере', NE: 'северо-востоке', E: 'востоке', SE: 'юго-востоке', S: 'юге', SW: 'юго-западе', W: 'западе', NW: 'северо-западе', C: 'центре' },
      st: ['стоит', 'идёт', 'атака с ходу', 'в бою', 'рукопашная', 'отступает', 'захватывает', 'способность', 'окопался', 'прыжок', 'строит'],
      offer: 'Подробный разбор для этого реплея ещё не делали: сама игра заново прокрутит матч (без графики, около минуты), и здесь появится весь матч на карте — каждый отряд, бои, точки, потери.',
      ask: '▶ Сделать подробный разбор', queued: 'В очереди — страница сама покажет матч, обычно через 2–5 минут.', running: 'Игра прямо сейчас прокручивает матч…', building: 'Почти готово…',
      failed: 'Игра не смогла прокрутить этот матч', unsupported: 'Подробный разбор работает для реплеев Elite 3.2 / 3.2.1 и ванильной Retribution длиной от полминуты.', busy: 'Очередь сейчас заполнена — попробуйте через несколько минут.',
      hp: 'HP', sec: 'с', models: 'моделей', qBuilt: 'построен', qDead: 'уничтожен', qDown: 'повержен', qOff: 'не на карте (в здании / транспорте)', end: 'Точки в конце', loading: 'Загружаю матч…', fail: 'Не удалось загрузить данные матча', start: '▶ Смотреть матч',
      resTitle: 'Итог матча', resWin: 'Победа', resLikely: 'Вероятная победа', resUnknown: 'Результат неизвестен', at: 'На', resPts: 'точек под контролем', resVp: 'VP-точек под контролем', resSq: 'отрядов на поле',
      resWipe: 'все отряды другой стороны уничтожены', resRead: 'по состоянию матча в конце: очки и точки под контролем, сила армий', resGuess: 'оценка по ретритам и потерям отрядов в последней четверти матча',
      resNone: 'по реплею не удаётся уверенно сказать, кто победил',
      resNote: 'Реплей не хранит, чем закончился матч (очки, штаб, сдача), поэтому вывод сделан по последним секундам.',
      tk: 'Счёт победных очков', tkHint: n => `у каждой стороны ${n}; у той, что держит меньше победных точек, счёт тает, 0 — поражение. Отметки — победная точка сменила хозяина`,
      tkS: 'счёт', tkPts: 'стратегических точек под контролем', tkVp: 'победных точек под контролем', resScore: 'счёт победных очков',
      resVpWin: 'у другой стороны кончились победные очки (по условию победы самой игры)', resConcede: 'другая сторона сдалась (по условию победы самой игры)',
      resHq: 'штаб другой стороны уничтожен (по условию победы самой игры)', resGame: 'по условию победы самой игры' } };
  const tx = k => (TX[L] || TX.en)[k];
  const tnm = (teams, tm) => { const i = teams.indexOf(tm); return i >= 0 && i < 2 ? tx('sides')[i] : tx('team')(tm + 1); };
  const tname = tm => tnm(S.teams, tm);
  // player rating (page's players block data: at match time or current), by name
  const ratingOf = name => {
    const q = window.RESCTX && window.RESCTX.players.find(x => x.name === name);
    if (!q || !q.rating) return '';
    const now = q.rating_kind === 'now', ru = L === 'ru';
    return `<small style="color:var(--muted);font-size:11px;margin-left:4px;white-space:nowrap" title="${now ? (ru ? 'рейтинг сейчас' : 'rating now') : (ru ? 'рейтинг на момент матча' : 'rating at match time')}">${q.rating}${now ? (ru ? ' сейчас' : ' now') : ''}</small>`;
  };
  const TEAMC = ['#2f8bff', '#ff3b30'];
  // 17.11.2026 (owner): the squads of every player with their icons in build order, numbered - the same numbers on the minimap.
  // squads.json: the game's squad portraits + names by blueprint (tools/replay_squad_icons.py, from the Elite Codex build)
  let sqaP = null;
  const SQA = () => sqaP || (sqaP = fetch(A + 'squads.json').then(r => r.json()).catch(() => ({})));   // by side: the first team blue, the second red
  const SPEEDS = [1, 4, 8, 16, 32];
  let S = null;

  const css = `
.sim { padding: 16px 16px 18px; overflow: visible; }
.sim-h { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.sim-badge { font-size: 11px; letter-spacing: .6px; text-transform: uppercase; color: #111; background: var(--gold); border-radius: 6px; padding: 2px 7px; font-weight: 700; }
.sim-views { color: var(--muted); font-size: 14px; margin-left: auto; }
.sim-sub { color: var(--muted); font-size: 14px; margin: 4px 0 12px; }
.sim-main { display: grid; grid-template-columns: minmax(0, 1fr) 250px; gap: 14px; align-items: start; }
.sim-mapw { position: relative; border-radius: 10px; overflow: hidden; background: #08090a; border: 1px solid var(--line); line-height: 0; }
.sim-mapw canvas { display: block; width: 100%; cursor: crosshair; }
.sim-clock { position: absolute; left: 10px; top: 8px; font: 700 20px/1.2 ui-monospace, Menlo, Consolas, monospace; color: #fff; text-shadow: 0 1px 4px #000; pointer-events: none; }
.sim-score { position: absolute; right: 10px; top: 8px; font: 700 16px/1.2 system-ui, sans-serif; color: #fff; text-shadow: 0 1px 4px #000; pointer-events: none; }
.sim-leg { position: absolute; left: 10px; top: 38px; display: flex; flex-direction: column; gap: 2px; pointer-events: auto; line-height: 1.25; }
.sim-leg div { display: flex; align-items: center; gap: 5px; background: rgba(0,0,0,.55); color: #fff; padding: 1px 7px 1px 5px; border-radius: 5px; font-size: 12px; cursor: pointer; max-width: 170px; }
.sim-leg div span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sim-leg div.on { background: rgba(0,0,0,.85); outline: 1px solid #fff; }
.sim-sh { width: 11px; height: 11px; flex: none; border: 2px solid; box-sizing: border-box; }
.sim-sh.c0 { border-radius: 50%; }
.sim-p.on { background: rgba(230,195,92,.12); border-radius: 6px; }
.sim-p { cursor: pointer; }
.sim-chatbox { position: absolute; left: 10px; right: 10px; bottom: 10px; display: flex; flex-direction: column; gap: 3px; align-items: flex-start; pointer-events: none; line-height: 1.35; }
.sim-chatbox div { background: rgba(0,0,0,.62); color: #fff; padding: 3px 8px; border-radius: 6px; font-size: 13px; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; transition: opacity .4s; }
.sim-chatbox b { font-weight: 700; }
.sim-tip { position: absolute; pointer-events: none; background: rgba(10,11,13,.92); color: #fff; border: 1px solid #444; border-radius: 7px; padding: 5px 8px; font-size: 12.5px; line-height: 1.4; white-space: nowrap; display: none; z-index: 2; }
.sim-big { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; background: rgba(0,0,0,.25); }
.sim-big button { background: rgba(15,16,18,.85); border: 2px solid var(--gold); color: #fff; font-size: 18px; padding: 12px 22px; border-radius: 12px; }
.sim-side { display: flex; flex-direction: column; gap: 10px; font-size: 13px; }
.sim-team { border: 1px solid var(--line); border-radius: 10px; padding: 8px 9px; min-width: 0; }
.sim-team h4 { margin: 0 0 6px; font-size: 13px; display: flex; justify-content: space-between; }
.sim-p { padding: 4px 0; border-top: 1px solid var(--line); }
.sim-p:first-of-type { border-top: 0; }
.sim-pn { display: flex; align-items: center; gap: 5px; min-width: 0; }
.sim-pn i { flex: none; }
.sim-pn img { width: 20px; height: 20px; border-radius: 4px; flex: none; }
.sim-pn span { font-weight: 600; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sim-ps { color: var(--muted); font-size: 12px; display: flex; gap: 8px; flex-wrap: wrap; margin-top: 2px; font-variant-numeric: tabular-nums; }
.sim-ps b { color: var(--text); font-weight: 600; }
.sim-qs { position: relative; display: flex; flex-wrap: wrap; gap: 4px 3px; margin-top: 5px; }
.sim-qs:empty { display: none; }
.sim-q { position: relative; width: 24px; height: 24px; flex: none; border-radius: 4px; border: 1.5px solid; box-sizing: border-box; background: #1b1c1f; cursor: pointer; touch-action: manipulation; }
.sim-q img { display: block; width: 100%; height: 100%; border-radius: 2.5px; }
.sim-q em { display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; font: 700 8.5px/1 system-ui, sans-serif; font-style: normal; color: #eee; letter-spacing: -.2px; overflow: hidden; }
.sim-q b { position: absolute; right: -4px; bottom: -4px; min-width: 13px; height: 13px; padding: 0 2px; box-sizing: border-box; border-radius: 7px; background: #111; color: #fff; border: 1px solid rgba(255,255,255,.55); z-index: 1; font: 700 9.5px/11px system-ui, sans-serif; text-align: center; font-variant-numeric: tabular-nums; }
.sim-q.d img, .sim-q.x img, .sim-q.d em, .sim-q.x em { filter: grayscale(1) brightness(.6); }
.sim-q.d, .sim-q.x { opacity: .5; border-color: rgba(127,127,127,.6) !important; }
.sim-q.x::after { content: ''; position: absolute; inset: 0; background: linear-gradient(45deg, transparent 45%, #ff4d4d 45% 55%, transparent 55%), linear-gradient(-45deg, transparent 45%, #ff4d4d 45% 55%, transparent 55%); }
.sim-q.g { opacity: .6; border-style: dashed; }
.sim-q.on { outline: 2px solid var(--gold); outline-offset: 1px; opacity: 1; }
.sim-qtip { position: absolute; z-index: 3; display: none; pointer-events: none; background: rgba(10,11,13,.94); color: #fff; border: 1px solid #555; border-radius: 7px; padding: 5px 8px; font-size: 12.5px; line-height: 1.4; max-width: 230px; box-sizing: border-box; }
.sim-qtip small { color: #bbb; font-size: 11.5px; }
.sim-side { position: relative; }
.sim-bar { height: 5px; border-radius: 3px; background: rgba(127,127,127,.18); margin-top: 4px; overflow: hidden; }
.sim-bar i { display: block; height: 100%; border-radius: 3px; transition: width .25s; }
.sim-ctl { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 12px 0 6px; }
.sim-ctl button { padding: 6px 12px; font-size: 14px; }
.sim-ctl .play { min-width: 104px; background: var(--gold); color: #111; font-weight: 700; }
.sim-seg { display: flex; border: 1px solid var(--line); border-radius: 9px; overflow: hidden; }
.sim-seg button { border: 0; border-radius: 0; padding: 6px 9px; color: var(--muted); font-size: 13px; }
.sim-seg button.on { background: rgba(230,195,92,.2); color: var(--text); }
.sim-time { font: 600 14px ui-monospace, Menlo, Consolas, monospace; color: var(--muted); }
.sim-opt { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--muted); }
.sim-opt select { font: inherit; color: var(--text); background: var(--bg); border: 1px solid var(--line); border-radius: 7px; padding: 4px 6px; }
.sim-tl canvas { width: 100%; height: 54px; display: block; cursor: pointer; border-radius: 8px; }
.sim-tk { margin-top: 6px; }
.sim-tk[hidden] { display: none; }
.sim-tkh { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; flex-wrap: wrap; font-size: 12.5px; color: var(--muted); margin: 0 0 3px; }
.sim-tkh b { font: 700 13px ui-monospace, Menlo, Consolas, monospace; }
.sim-tk canvas { width: 100%; height: 40px; display: block; cursor: pointer; border-radius: 8px; }
.sim-tkp { display: inline-block; min-width: 2.2em; padding: 0 5px; margin-left: 4px; border-radius: 6px; color: #fff; text-align: center; font-variant-numeric: tabular-nums; text-shadow: none; }
.sim-team h4 .sim-tkp { font-size: 12px; line-height: 17px; }
.sim-charts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 14px; }
.sim-ch { font-size: 12.5px; color: var(--muted); margin: 0 0 4px; }
.sim-charts canvas { width: 100%; height: 120px; display: block; cursor: pointer; border: 1px solid var(--line); border-radius: 8px; }
.sim-res { margin-top: 12px; border: 1px solid var(--line); border-left: 4px solid var(--gold); border-radius: 8px; padding: 8px 12px; font-size: 13.5px; line-height: 1.5; }
.sim-res .res-h { font-size: 15px; }
.sim-res .res-d { color: var(--muted); font-size: 12.5px; }
.sim-final { position: absolute; left: 50%; top: 42%; transform: translate(-50%, -50%); background: rgba(10,11,13,.88); color: #fff; border: 2px solid var(--gold); border-radius: 12px; padding: 12px 22px; text-align: center; font: 600 15px/1.5 system-ui, sans-serif; pointer-events: none; z-index: 1; }
.sim-final[hidden] { display: none; }
.sim-ev { margin-top: 16px; }
.sim-evf { display: flex; gap: 6px; flex-wrap: wrap; margin: 4px 0 8px; }
.sim-evf button { padding: 3px 10px; font-size: 13px; border-color: var(--line); color: var(--muted); }
.sim-evf button.on { border-color: var(--gold); color: var(--text); }
.sim-evl { position: relative; max-height: 330px; overflow-y: auto; border: 1px solid var(--line); border-radius: 10px; }
.sim-e { display: grid; grid-template-columns: 52px 22px minmax(0, 1fr); gap: 6px; align-items: start; padding: 6px 10px; border-top: 1px solid var(--line); cursor: pointer; font-size: 13.5px; line-height: 1.4; }
.sim-e:first-child { border-top: 0; }
.sim-e:hover { background: rgba(230,195,92,.07); }
.sim-e.cur { background: rgba(230,195,92,.14); }
.sim-e .t { font: 600 13px ui-monospace, Menlo, Consolas, monospace; color: var(--gold); }
.sim-e .d { color: var(--muted); font-size: 12.5px; }
.sim-e .x { overflow-wrap: anywhere; }
@media (max-width: 760px) { .sim-main { grid-template-columns: 1fr; } .sim-side { display: grid; grid-template-columns: 1fr 1fr; } .sim-charts { grid-template-columns: 1fr; } }
@media (max-width: 460px) { .sim-side { grid-template-columns: 1fr; } .sim-score { font-size: 13.5px; right: 6px; } }
`;

  function el(h) { const d = document.createElement('div'); d.innerHTML = h.trim(); return d.firstChild; }
  const fmt = s => { s = Math.max(0, Math.floor(s)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); };
  const nf = v => (v == null ? '–' : Math.round(v).toLocaleString(L === 'ru' ? 'ru-RU' : 'en-GB'));

  // ---------- match result ----------
  // The replay holds no explicit winner (the end of the game is not recorded), so the end state of the engine's simulation votes:
  // all squads of one side gone = decisive; otherwise victory points held (2), points held (1), army strength at least 1.3x (1)
  // and the retreat/loss guess of the report (1, half when 'medium'). A lead of 3+ is a probable winner, anything less is unknown.
  function verdict(D, players, guess, dur) {
    const teams = [...new Set(players.map(p => p.team))].sort();
    const r = { teams, players, level: 'unknown', team: null, how: '', facts: null, dur: D ? D.dur - 1 : dur };
    if (teams.length !== 2) return r;
    const [a, b] = teams, other = tm => (tm === a ? b : a), vote = { [a]: 0, [b]: 0 };
    const gw = guess && teams.includes(guess.team) ? guess : null;
    if (gw) vote[gw.team] += gw.conf === 'высокая' ? 1 : gw.conf === 'средняя' ? 0.5 : 0;
    if (D) {
      const s = D.dur - 1, tmOf = {}; D.players.forEach(p => { tmOf[p.pid] = p.team; });
      const f = { pts: {}, sq: {}, vp: null, army: {} };
      teams.forEach(tm => { f.pts[tm] = ((D.points || {})[tm] || [])[s]; f.army[tm] = ((D.army_team || {})[tm] || [])[s]; f.sq[tm] = 0; });
      const fr = D.frames[s] || [];
      for (let i = 0; i < fr.length; i += 6) { const sq = D.squads[fr[i]], tm = sq && tmOf[sq[0]]; if (tm != null && fr[i + 4] > 0 && fr[i + 3] > 0) f.sq[tm]++; }
      if (D.pown) {
        const own = D.pown.pts.map(() => -1); for (const e of D.pown.ev) own[e[1]] = e[2];
        const vps = D.pown.pts.map((p, i) => p[0] === 'vp' ? own[i] : null).filter(o => o !== null);
        if (vps.length) { f.vp = { n: vps.length }; teams.forEach(tm => { f.vp[tm] = vps.filter(o => o === tm).length; }); }
      }
      // 18.11: the victory-point score (tickets) and the end as the game's own win condition saw it (sim_view.py tickets_block) - exact
      if (D.tk && D.tk.vp && D.tk.end && teams.every(tm => D.tk.end[tm] != null)) { f.tk = {}; teams.forEach(tm => { f.tk[tm] = D.tk.end[tm]; }); }
      r.facts = f;
      const gwin = D.tk && D.tk.win;
      if (gwin && teams.includes(gwin.team)) { r.team = gwin.team; r.level = 'sure'; r.game = true; r.how = { vp: 'resVpWin', concede: 'resConcede', annihilate: 'resHq' }[gwin.how] || 'resGame'; return r; }
      if (f.sq[a] === 0 && f.sq[b] > 0) { r.team = b; r.level = 'sure'; r.how = 'resWipe'; return r; }
      if (f.sq[b] === 0 && f.sq[a] > 0) { r.team = a; r.level = 'sure'; r.how = 'resWipe'; return r; }
      if (f.tk && Math.abs(f.tk[a] - f.tk[b]) >= 50) vote[f.tk[a] > f.tk[b] ? a : b] += 2;
      if (f.vp && f.vp[a] !== f.vp[b]) vote[f.vp[a] > f.vp[b] ? a : b] += 2;
      if (f.pts[a] != null && f.pts[b] != null && f.pts[a] !== f.pts[b]) vote[f.pts[a] > f.pts[b] ? a : b] += 1;
      const ra = f.army[a], rb = f.army[b];
      if (ra != null && rb != null && Math.max(ra, rb) >= 1.3 * Math.max(1, Math.min(ra, rb))) vote[ra > rb ? a : b] += 1;
      const w = vote[a] > vote[b] ? a : b;
      if (Math.abs(vote[a] - vote[b]) >= 3) { r.team = w; r.level = 'likely'; r.how = 'resRead'; }
    } else if (gw && gw.conf === 'высокая') { r.team = gw.team; r.level = 'likely'; r.how = 'resGuess'; }
    return r;
  }
  // text parts of a verdict (language of the page)
  function resParts(r) {
    const col = tm => TEAMC[r.teams.indexOf(tm) % 2], nm = tm => `<span style="color:${col(tm)}">${tnm(r.teams, tm)}</span>`;
    const names = tm => r.players.filter(p => p.team === tm).map(p => esc(p.name)).join(', ');
    const head = r.team != null ? `<b>${tx(r.level === 'sure' ? 'resWin' : 'resLikely')}: ${nm(r.team)}</b> (${names(r.team)})` : `<b>${tx('resUnknown')}</b>`;
    const f = r.facts;
    const facts = f ? tx('at') + ' ' + fmt(r.dur) + ': ' + r.teams.map(tm => `${nm(tm)} - ` + [f.tk ? `${tx('resScore')} <b>${f.tk[tm]}</b>` : '', f.pts[tm] != null ? `${f.pts[tm]} ${tx('resPts')}` : '', f.vp ? `${f.vp[tm]}/${f.vp.n} ${tx('resVp')}` : '', `${f.sq[tm]} ${tx('resSq')}`].filter(Boolean).join(', ')).join(' · ') : '';
    return { head, why: r.team != null ? tx(r.how) : tx('resNone'), facts, note: r.how === 'resWipe' || r.game ? '' : tx('resNote') };
  }
  const resHTML = r => { const p = resParts(r); return `<div class="res-h">${tx('resTitle')}: ${p.head}</div><div class="res-d">${p.why}${p.facts ? '<br>' + p.facts : ''}${p.note ? '<br><i>' + p.note + '</i>' : ''}</div>`; };
  function resbox() {
    if (!S || !S.res || !S.el.res) return;
    S.el.res.innerHTML = resHTML(S.res);
    const f = S.res.facts, sc = f && f.tk ? `<br><small>${tx('tk')}: ${S.res.teams.map(tm => `<b style="color:${TEAMC[S.res.teams.indexOf(tm) % 2]}">${f.tk[tm]}</b>`).join(' : ')}</small>` : '';
    S.el.final.innerHTML = `${tx('resTitle')}<br>${resParts(S.res).head}${sc}`;
  }

  async function show(rid, mapKey, views) {
    let card = document.getElementById('sim');
    if (S && S.rid === rid && card) { relabel(); return; }
    stop();
    if (!document.getElementById('sim-css')) { const st = document.createElement('style'); st.id = 'sim-css'; st.textContent = css; document.head.appendChild(st); }
    if (!card) { card = el('<div class="card sim" id="sim"></div>'); const r = document.getElementById('story'); r.parentNode.insertBefore(card, r); }
    card.hidden = false; card.innerHTML = `<div class="sim-sub">${tx('loading')}</div>`;
    let D;
    try { D = await (await fetch('/replay/api/r/' + rid + '/sim.json?v=2')).json(); } catch (e) { card.innerHTML = `<div class="sim-sub">${tx('fail')}</div>`; return; }
    await assetsReady;
    const sqa = await SQA();
    S = { rid, D, SQ: sqa, views: views || 0, t: 0, playing: false, speed: 8, trails: true, heat: '', last: 0, evf: 'all', mapKey: mapKey || D.map, hover: null };
    prep();
    S.res = verdict(D, D.players, window.RESCTX && window.RESCTX.guess, 0);
    window.SIMD = { rid, D, res: S.res };
    build(card);
    if (window.renderResBox) window.renderResBox();
    if (location.hash === '#sim') setTimeout(() => card.scrollIntoView({ behavior: 'smooth', block: 'start' }), 150);   // opened from the launcher
  }
  // no data yet: offer the detailed analysis (the replay goes to the runner's queue), then wait for it
  function offer(rid, state, why, auto) {
    stop();
    if (!document.getElementById('sim-css')) { const st = document.createElement('style'); st.id = 'sim-css'; st.textContent = css; document.head.appendChild(st); }
    let card = document.getElementById('sim');
    if (!card) { card = el('<div class="card sim" id="sim"></div>'); const r = document.getElementById('story'); r.parentNode.insertBefore(card, r); }
    if (S && S.rid !== rid) S = null;
    card.hidden = false;
    const wait = st => st === 'queued' || st === 'running' || st === 'building';
    const render = (st, w) => {
      const msg = st === 'none' ? tx('offer') : st === 'failed' ? tx('failed') + (w ? ' (' + esc(w) + ')' : '') + '. ' : tx(st) || '';
      card.innerHTML = `<div class="sim-h"><span class="cap">${tx('title')}</span><span class="sim-badge">${tx('badge')}</span></div>`
        + `<div class="sim-sub" style="margin-bottom:10px">${msg}</div>`
        + (st === 'none' || st === 'failed' || st === 'busy' ? `<button class="play" id="simAsk" style="background:var(--gold);color:#111;font-weight:700">${tx('ask')}</button>` : '')
        + (wait(st) ? '<div class="sim-wait" style="height:4px;border-radius:2px;background:linear-gradient(90deg,transparent,var(--gold),transparent);background-size:40% 100%;background-repeat:no-repeat;animation:simw 1.4s linear infinite"></div><style>@keyframes simw{from{background-position:-40% 0}to{background-position:140% 0}}</style>' : '');
      const b = document.getElementById('simAsk'); if (b) b.onclick = ask;
    };
    const ask = async () => {
      let st = 'busy';
      try { const r = await fetch('/replay/api/r/' + rid + '/sim', { method: 'POST' }); st = (await r.json()).state || st; } catch (e) {}
      render(st); if (wait(st)) poll();
    };
    let pt = null;
    const poll = () => {
      clearTimeout(window.__simPoll);
      window.__simPoll = setTimeout(async () => {
        try {
          const j = await (await fetch('/replay/api/r/' + rid)).json();
          if (j.sim_state === 'ready') { show(rid, j.meta && j.meta.map); return; }
          render(j.sim_state, j.sim_why); if (wait(j.sim_state)) poll();
        } catch (e) { poll(); }
      }, 5000);
    };
    if (state === 'unsupported') { card.hidden = true; return; }
    render(state, why);
    if (wait(state)) poll();
    else if (auto && state === 'none') ask();
  }
  function hide() { stop(); const c = document.getElementById('sim'); if (c) c.hidden = true; S = null; }
  function stop() { if (S && S.raf) cancelAnimationFrame(S.raf); if (S) S.raf = 0; }

  // ---------- data ----------
  function prep() {
    const D = S.D;
    S.P = {}; D.players.forEach(p => { S.P[p.pid] = p; });
    S.teams = [...new Set(D.players.map(p => p.team))].sort();
    // a team = a shape (blue circles / red squares) and a hue family; a player = his own shade inside it
    const FILL = [['#4da3ff', '#35e0d0', '#b18cff', '#9fd8ff'], ['#ff5c4d', '#ffa43a', '#ff70c8', '#ffe066']];
    const seen = {};
    D.players.forEach(p => { const side = Math.max(0, S.teams.indexOf(p.team)) % 2, n = seen[side] = (seen[side] || 0) + 1; p.side = side; p.color = FILL[side][(n - 1) % 4]; });
    S.focus = null; S.focusLock = null; S.hl = null; S.qtip = null;
    // build order: the second a squad first shows up in the dump; summoned ones (temporary Bloodletters, clouds) get no number
    const first = {}, last = {};
    D.frames.forEach((fr, s) => { for (let i = 0; i < fr.length; i += 6) { const id = fr[i]; if (first[id] == null) first[id] = s; last[id] = s; } });
    S.life = { first, last }; S.order = {}; S.num = {};
    Object.keys(D.squads).map(Number).filter(id => first[id] != null).sort((a, b) => first[a] - first[b] || a - b).forEach(id => {
      const sq = D.squads[id], a = (S.SQ || {})[sq[3]];
      if (!S.P[sq[0]] || !(sq[2] || (a ? !a.s : last[id] - first[id] >= 30))) return;
      const l = S.order[sq[0]] || (S.order[sq[0]] = []); l.push(id); S.num[id] = l.length;
    });
    S.idx = D.frames.map(fr => { const m = new Map(); for (let i = 0; i < fr.length; i += 6) m.set(fr[i], i); return m; });
    const ax = Object.values(D.army || {}).flat(); S.armyMax = Math.max(1, ...ax);
    // events
    const ev = [];
    const dir = (x, z) => { const r = Math.hypot(x / D.w, z / D.h); if (r < 0.12) return 'C'; const a = Math.atan2(z / D.h, x / D.w) * 180 / Math.PI; return ['E', 'NE', 'N', 'NW', 'W', 'SW', 'S', 'SE'][Math.round(((a + 360) % 360) / 45) % 8]; };
    S.dir = dir;
    (D.fights || []).forEach((f, i) => ev.push({ k: 'fights', t: f.t0, f, i }));
    (D.deaths || []).forEach(d => { const sq = D.squads[d[1]]; if (!sq) return; ev.push({ k: sq[2] ? 'heroes' : 'deaths', t: d[0], d, sq }); });
    (D.chat || []).forEach(c => ev.push({ k: 'chat', t: c[0], c }));
    ev.sort((a, b) => a.t - b.t);
    S.ev = ev;
    if (D.pown) {   // points held per team per second from the game's owners (the same numbers the map shows)
      const own = new Array(D.pown.pts.length).fill(-1), ser = {}; S.teams.forEach(tm => { ser[tm] = new Array(D.dur).fill(0); });
      const ev = D.pown.ev; let j = 0;
      for (let s = 0; s < D.dur; s++) {
        while (j < ev.length && ev[j][0] <= s) { own[ev[j][1]] = ev[j][2]; j++; }
        own.forEach(o => { if (ser[o]) ser[o][s]++; });
      }
      D.points = ser;
    }
    // 18.11 (owner): the victory-point score per team per second (VP mode only), gaps carried forward, the last second = the final score;
    // the VP marks: a victory point changes hands (a new owner or back to neutral)
    S.tk = null;
    const TK = D.tk;
    if (TK && TK.vp && TK.by && S.teams.length === 2 && S.teams.every(tm => TK.by[tm])) {
      S.tk = { by: {}, max: 1, vpEv: [], vpN: {} };
      S.teams.forEach(tm => {
        const src = TK.by[tm], out = new Array(D.dur); let v = (TK.start || {})[tm] != null ? TK.start[tm] : 500;
        for (let i = 0; i < D.dur; i++) { if (src[i] != null) v = src[i]; out[i] = v; }
        if (TK.end && TK.end[tm] != null && TK.win) out[D.dur - 1] = TK.end[tm];
        S.tk.by[tm] = out; S.tk.max = Math.max(S.tk.max, ...out.slice(0, 5), (TK.start || {})[tm] || 0);
      });
      if (D.pown) {
        const own = D.pown.pts.map(() => -1), vpi = D.pown.pts.map(p => p[0] === 'vp');
        const ser = {}; S.teams.forEach(tm => { ser[tm] = new Array(D.dur).fill(0); });
        let j = 0; const ev = D.pown.ev;
        for (let s = 0; s < D.dur; s++) {
          while (j < ev.length && ev[j][0] <= s) { const [es, i, o] = ev[j]; if (vpi[i] && o !== own[i]) { if (es > 0) S.tk.vpEv.push([es, o]); own[i] = o; } else own[i] = o; j++; }
          own.forEach((o, i) => { if (vpi[i] && ser[o]) ser[o][s]++; });
        }
        if (vpi.some(Boolean)) S.tk.vpN = ser;
      }
    }
    S.alive = {};   // squads on the field per team per second
    D.frames.forEach((fr, s) => { for (let i = 0; i < fr.length; i += 6) { const sq = D.squads[fr[i]], p = sq && S.P[sq[0]]; if (!p || fr[i + 4] <= 0 || fr[i + 3] <= 0) continue; (S.alive[p.team] || (S.alive[p.team] = new Array(D.dur).fill(0)))[s]++; } });
  }

  function pointsAt(t) {   // [owner team, capturing team (-1 none, 2 both)] per point at time t
    const P = S.D.pown, st = P.pts.map(() => [-1, -1]);
    for (const [s, i, o, cp] of P.ev) { if (s > t) break; st[i] = [o, cp]; }
    return st;
  }
  function squadAt(t) {   // interpolated squads at time t (s, float)
    const D = S.D, s = Math.min(D.dur - 1, Math.max(0, Math.floor(t))), f = t - s;
    const fr = D.frames[s] || [], nx = D.frames[s + 1], ni = S.idx[s + 1];
    const out = [];
    for (let i = 0; i < fr.length; i += 6) {
      let x = fr[i + 1], z = fr[i + 2];
      if (nx && f > 0) { const j = ni.get(fr[i]); if (j != null) { const x2 = nx[j + 1], z2 = nx[j + 2]; if (Math.abs(x2 - x) + Math.abs(z2 - z) < 40) { x += (x2 - x) * f; z += (z2 - z) * f; } } }
      out.push({ id: fr[i], x, z, hp: fr[i + 3], n: fr[i + 4], st: fr[i + 5] });
    }
    return out;
  }

  // ---------- DOM ----------
  function build(card) {
    const D = S.D;
    card.innerHTML = `
      <div class="sim-h"><span class="cap" id="simT"></span><span class="sim-badge" id="simB"></span><span class="sim-views" id="simViews"></span></div>
      <div class="sim-sub" id="simSub"></div>
      <div class="sim-main">
        <div class="sim-mapw" id="simW"><canvas id="simMap"></canvas><div class="sim-clock" id="simClock"></div><div class="sim-score" id="simScore"></div>
          <div class="sim-leg" id="simLeg"></div><div class="sim-chatbox" id="simChat"></div><div class="sim-tip" id="simTip"></div><div class="sim-big" id="simBig"><button id="simStart"></button></div><div class="sim-final" id="simFinal" hidden></div></div>
        <div class="sim-side" id="simSide"></div>
      </div>
      <div class="sim-ctl">
        <button class="play" id="simPlay"></button>
        <div class="sim-seg" id="simSpd">${SPEEDS.map(v => `<button data-v="${v}">${v}×</button>`).join('')}</div>
        <span class="sim-time" id="simTime"></span>
        <label class="sim-opt"><input type="checkbox" id="simTr" checked> <span id="simTrL"></span></label>
        <label class="sim-opt"><span id="simHL"></span> <select id="simHeat"></select></label>
      </div>
      <div class="sim-tl"><canvas id="simTl"></canvas></div>
      <div class="sim-tk" id="simTkW" ${S.tk ? '' : 'hidden'}><div class="sim-tkh"><span id="simTkL"></span><span id="simTkV"></span></div><canvas id="simTk"></canvas></div>
      <div class="sim-res" id="simRes"></div>
      <div class="sim-charts">
        <div><div class="sim-ch" id="simC1"></div><canvas id="simArmy"></canvas></div>
        <div><div class="sim-ch" id="simC2"></div><canvas id="simPts"></canvas></div>
        <div><div class="sim-ch" id="simC3"></div><canvas id="simReq"></canvas></div>
      </div>
      <div class="sim-ev"><div class="cap" id="simMo"></div><div class="sim-evf" id="simEvf"></div><div class="sim-evl" id="simEvl"></div></div>
      <div class="sim-cb" id="simCb" hidden></div>`;
    const $ = id => document.getElementById(id);
    S.el = { map: $('simMap'), tl: $('simTl'), tk: $('simTk'), army: $('simArmy'), pts: $('simPts'), req: $('simReq'), clock: $('simClock'), score: $('simScore'),
      chat: $('simChat'), tip: $('simTip'), side: $('simSide'), time: $('simTime'), play: $('simPlay'), evl: $('simEvl'), big: $('simBig'), res: $('simRes'), final: $('simFinal') };
    // background minimap
    const m = AS.maps && AS.maps[S.mapKey];
    S.bg = null;
    if (m && (m.minimap_plain || m.minimap)) { const im = new Image(); im.onload = () => { S.bg = im; draw(); }; im.src = A + (m.minimap_plain || m.minimap); }
    $('simPlay').onclick = () => toggle();
    $('simStart').onclick = () => { S.el.big.remove(); S.el.big = null; S.speed = 8; toggle(true); };
    $('simSpd').onclick = e => { const v = +e.target.dataset.v; if (v) { S.speed = v; segs(); } };
    $('simTr').onchange = e => { S.trails = e.target.checked; draw(); };
    $('simHeat').onchange = e => { S.heat = e.target.value; draw(); };
    const seekCanvas = (cv, e) => { const r = cv.getBoundingClientRect(); seek(Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * (D.dur - 1)); };
    for (const cv of [S.el.tl, S.el.tk, S.el.army, S.el.pts, S.el.req]) {
      cv.addEventListener('pointerdown', e => { cv.setPointerCapture(e.pointerId); S.drag = cv; seekCanvas(cv, e); });
      cv.addEventListener('pointermove', e => { if (S.drag === cv) seekCanvas(cv, e); });
      cv.addEventListener('pointerup', () => { S.drag = null; });
    }
    S.el.map.addEventListener('pointermove', e => { const r = S.el.map.getBoundingClientRect(); S.hover = [e.clientX - r.left, e.clientY - r.top]; if (!S.playing) draw(); });
    S.el.map.addEventListener('pointerleave', () => { S.hover = null; S.el.tip.style.display = 'none'; if (!S.playing) draw(); });
    S.el.map.addEventListener('click', () => { if (S.qpin) qhide(); if (S.el.big) return; toggle(); });
    $('simEvf').onclick = e => { const k = e.target.dataset.k; if (k) { S.evf = k; events(); } };
    S.el.evl.onclick = e => { const r = e.target.closest('.sim-e'); if (r) { seek(Math.max(0, +r.dataset.t - 4)); if (!S.playing) toggle(true); } };
    if (!S.ro) { S.ro = new ResizeObserver(() => { if (S) { sizeAll(); draw(); charts(); } }); }
    S.ro.disconnect(); S.ro.observe(card);
    relabel(); viewsLabel();
    sizeAll(); draw(); charts();
  }

  function relabel() {
    if (!S || !S.el) return;
    const $ = id => document.getElementById(id);
    $('simT').textContent = tx('title'); $('simB').textContent = tx('badge'); $('simSub').textContent = tx('sub');
    $('simTrL').textContent = tx('trails'); $('simHL').textContent = tx('heat');
    $('simC1').textContent = tx('army'); $('simC2').textContent = tx('pts'); $('simC3').textContent = tx('req'); $('simMo').textContent = tx('moments');
    if (S.tk) { $('simTkL').innerHTML = `${tx('tk')} <small>(${S.tk.max} → 0)</small>`; $('simTkL').title = tx('tkHint')(S.tk.max); }
    if (S.el.big) $('simStart').textContent = tx('start');
    const hs = $('simHeat'); hs.innerHTML = `<option value="">${tx('heatNone')}</option>` + S.D.players.map(p => `<option value="${p.pid}">${esc(p.name)}</option>`).join(''); hs.value = S.heat;
    $('simEvf').innerHTML = ['all', 'fights', 'heroes', 'deaths', 'chat'].map(k => `<button data-k="${k}" class="${S.evf === k ? 'on' : ''}">${tx(k)}</button>`).join('');
    side(true); segs(); events(); ui(true); charts(); combat(); resbox();
  }
  function segs() { document.querySelectorAll('#simSpd button').forEach(b => b.classList.toggle('on', +b.dataset.v === S.speed)); }

  function side(full) {
    const D = S.D, s = Math.min(D.dur - 1, Math.floor(S.t));
    if (full) {
      S.el.side.innerHTML = S.teams.map(tm => `<div class="sim-team"><h4><span style="color:${TEAMC[S.teams.indexOf(tm) % 2]}">${tname(tm)}</span><span id="simTP${tm}"></span></h4>` +
        D.players.filter(p => p.team === tm).map(p => {
          const r = AS.races[rk(p.race)] || {}, h = r.heroes && r.heroes[p.hero];
          return `<div class="sim-p" data-pid="${p.pid}"><div class="sim-pn"><i class="sim-sh c${p.side}" style="background:${p.color};border-color:${TEAMC[p.side]}"></i>${r.icon ? `<img src="${A + r.icon}" alt="">` : ''}${h ? `<img src="${A + h.icon}" alt="" title="${esc(h.name)}">` : ''}<span title="${esc(p.name)}">${esc(p.name)}</span>${ratingOf(p.name)}</div>` +
            `<div class="sim-ps" id="simPS${p.pid}"></div><div class="sim-qs" id="simQ${p.pid}"></div><div class="sim-bar"><i id="simPB${p.pid}" style="background:${p.color}"></i></div></div>`;
        }).join('') + '</div>').join('') + '<div class="sim-qtip" id="simQT"></div>';
      S.qkey = {}; S.qtip = null; S.hl = null;
      S.el.side.onpointerover = e => { const q = e.pointerType === 'mouse' && e.target.closest('.sim-q'); if (q) qshow(+q.dataset.q, false); };
      S.el.side.onpointerout = e => { const q = e.pointerType === 'mouse' && e.target.closest('.sim-q'); if (q && !q.contains(e.relatedTarget) && !S.qpin) qhide(); };
      document.getElementById('simLeg').innerHTML = D.players.map(p => `<div data-pid="${p.pid}"><i class="sim-sh c${p.side}" style="background:${p.color};border-color:${TEAMC[p.side]}"></i><span>${esc(p.name)}</span></div>`).join('');
      for (const box of [S.el.side, document.getElementById('simLeg')]) {
        box.onmouseover = e => { const r = e.target.closest('[data-pid]'); if (r) setFocus(+r.dataset.pid); };
        box.onmouseleave = () => { setFocus(null); if (!S.qpin) qhide(); };
        box.onclick = e => { if (qclick(e)) return; const r = e.target.closest('[data-pid]'); if (!r) return; S.focusLock = S.focusLock === +r.dataset.pid ? null : +r.dataset.pid; setFocus(null); };
      }
    }
    // live values
    const alive = {}; const fr = D.frames[s] || [];
    for (let i = 0; i < fr.length; i += 6) { const sq = D.squads[fr[i]]; if (sq && fr[i + 4] > 0 && fr[i + 3] > 0) alive[sq[0]] = (alive[sq[0]] || 0) + 1; }
    D.players.forEach(p => {
      const e = (D.eco || {})[p.pid] || {}, a = ((D.army || {})[p.pid] || [])[s] || 0;
      const ps = document.getElementById('simPS' + p.pid); if (!ps) return;
      const wg = p.race === 'orks' && e.wg ? ` · ${tx('waaagh')} <b>${nf(e.wg[s])}</b>` : '';
      ps.innerHTML = `${tx('bank')} <b>${nf(e.req && e.req[s])}</b> · ${tx('power')} <b>${nf(e.pow && e.pow[s])}</b>${wg}` + (S.order[p.pid] ? '' : ` · ${tx('alive')} <b>${alive[p.pid] || 0}</b>`);
      qrow(p, s);
      document.getElementById('simPB' + p.pid).style.width = Math.min(100, 100 * a / S.armyMax) + '%';
    });
    if (S.qtip != null) { const tip = document.getElementById('simQT'); if (tip && S.el.side.querySelector(`.sim-q[data-q="${S.qtip}"]`)) tip.innerHTML = qtext(S.qtip); else qhide(); }
    S.teams.forEach(tm => { const x = document.getElementById('simTP' + tm); if (x) x.innerHTML = scoreHTML(tm, s); });
    if (S.tk) { const v = document.getElementById('simTkV'); if (v) v.innerHTML = S.teams.map(tm => `<b style="color:${TEAMC[S.teams.indexOf(tm) % 2]}">${S.tk.by[tm][s]}</b>`).join(' : '); }
  }

  // ⚑ strategic points held, ◆ victory points held, then the victory-point score (VP mode only)
  function scoreHTML(tm, s) {
    const D = S.D, pt = ((D.points || {})[tm] || [])[s], k = S.tk, col = TEAMC[S.teams.indexOf(tm) % 2];
    const vp = k && k.vpN[tm] ? `<span title="${tx('tkVp')}"> · ◆ ${k.vpN[tm][s]}</span>` : '';
    return (pt != null ? `<span title="${tx('tkPts')}">⚑ ${pt}</span>` : '') + vp + (k ? `<span class="sim-tkp" style="background:${col}" title="${tx('tk')}">${k.by[tm][s]}</span>` : '');
  }
  // squad state at second s: a alive, d down (a hero at 0 HP, can be revived), g not on the map (garrison, transport), x wiped out
  function qstate(id, s) {
    if (s > S.life.last[id]) return 'x';
    const j = S.idx[s] && S.idx[s].get(id); if (j == null) return 'g';
    const fr = S.D.frames[s]; return fr[j + 4] <= 0 || fr[j + 3] <= 0 ? 'd' : 'a';
  }
  const qname = id => { const sq = S.D.squads[id], a = (S.SQ || {})[sq[3]]; return (a && a.n && (a.n[L] || a.n.en)) || (sq[2] ? (S.P[sq[0]] || {}).hero_name : '') || sq[1]; };
  const qshort = n => { const w = n.replace(/[^\p{L}\p{N} ]/gu, ' ').split(/\s+/).filter(x => x && !/^(squad|team|отряд)$/i.test(x)); return (w.length > 1 ? w.slice(0, 3).map(x => x[0]).join('') : (w[0] || '?').slice(0, 3)).toUpperCase(); };
  function qrow(p, s) {
    const box = document.getElementById('simQ' + p.pid); if (!box) return;
    const ids = (S.order[p.pid] || []).filter(id => S.life.first[id] <= s), st = ids.map(id => qstate(id, s));
    const key = L + ids.map((id, i) => id + st[i]).join(',');
    if (S.qkey[p.pid] === key) return; S.qkey[p.pid] = key;
    box.innerHTML = ids.map((id, i) => { const a = (S.SQ || {})[S.D.squads[id][3]], n = qname(id);
      return `<span class="sim-q ${st[i]}${S.hl === id ? ' on' : ''}" data-q="${id}" style="border-color:${p.color}">${a && a.i ? `<img src="${A + a.i}" alt="${esc(n)}" loading="lazy" draggable="false">` : `<em>${esc(qshort(n))}</em>`}<b>${S.num[id]}</b></span>`; }).join('');
  }
  function qtext(id) {
    const D = S.D, sq = D.squads[id], p = S.P[sq[0]] || {}, s = Math.min(D.dur - 1, Math.floor(S.t)), st = qstate(id, s);
    const fr = D.frames[s], j = S.idx[s] && S.idx[s].get(id);
    const now = st === 'x' ? `${tx('qDead')} ${fmt(S.life.last[id] + 1)}` : st === 'g' ? tx('qOff') : st === 'd' ? tx('qDown') :
      `${fr[j + 3]}% ${tx('hp')} · ${fr[j + 4]} ${tx('models')}` + ((tx('st')[fr[j + 5]] || '') ? ' · ' + tx('st')[fr[j + 5]] : '');
    return `<b style="color:${p.color}">#${S.num[id]} ${esc(qname(id))}</b><br>${now}<br><small>${esc(p.name || '')} · ${tx('qBuilt')} ${fmt(S.life.first[id])}</small>`;
  }
  function qshow(id, pin) {
    const tip = document.getElementById('simQT'), q = S.el.side.querySelector(`.sim-q[data-q="${id}"]`); if (!tip || !q) return;
    S.qtip = id; S.qpin = pin; qmark(id);
    tip.innerHTML = qtext(id); tip.style.display = 'block';
    const sr = S.el.side.getBoundingClientRect(), r = q.getBoundingClientRect(), tw = tip.offsetWidth;
    tip.style.left = Math.max(0, Math.min(sr.width - tw, r.left - sr.left + r.width / 2 - tw / 2)) + 'px';
    tip.style.top = (r.bottom - sr.top + 6) + 'px';
  }
  function qhide() { const tip = document.getElementById('simQT'); if (tip) tip.style.display = 'none'; S.qtip = null; S.qpin = false; qmark(null); }
  function qmark(id) {
    if (S.hl === id) return; S.hl = id;
    S.el.side.querySelectorAll('.sim-q.on').forEach(x => x.classList.remove('on'));
    if (id != null) { const q = S.el.side.querySelector(`.sim-q[data-q="${id}"]`); if (q) q.classList.add('on'); }
    if (!S.playing) draw();
  }
  function qclick(e) {   // a tap on an icon (touch screens have no hover): pin its tooltip and ring the squad on the map; again = off
    const q = e.target.closest('.sim-q'); if (!q) { if (S.qpin) qhide(); return false; }
    const id = +q.dataset.q; if (S.qpin && S.qtip === id) qhide(); else qshow(id, true);
    return true;
  }

  // ---------- squad stats: every hit of the match from the game engine (damage hook) + kill events (combatstats.py, 14.11) ----------
  const CX = {
    en: { title: 'Squad stats', sub: 'Every hit of the match as the game engine dealt it: damage, kills and who fought whom. Click a column to sort, a squad for details.',
      squad: 'Squad', dealt: 'Dealt', taken: 'Taken', kills: 'Kills', dpm: 'Dmg / min', weapons: 'Weapons', abilities: 'Abilities', ranged: 'ranged', melee: 'melee',
      ability: 'ability weapons', effect: 'ability effects', other: 'other', wlist: 'Damage by weapon', klist: 'Kills (models)', tf: 'Damaged by', per: 'Wargear and upgrades',
      start: 'start', bought: 'bought', ko: 'heroes knocked out', st: 'buildings destroyed', alive: 'on the field', none: '—', perMin: '/min',
      kd: { ranged: 'ranged', melee: 'melee', ability: 'ability', effect: 'ability effect', other: 'other', unknown: 'no hit' },
      note: 'Damage = health actually lost (overkill not counted). Ability effects = damage the engine deals without a weapon: psychic powers, grenade and charge effects, burning and poison, crush. Buffs (Waaagh!, auras) are inside the hits and are not split out.' },
    ru: { title: 'Статистика отрядов', sub: 'Каждое попадание матча так, как его нанёс движок игры: урон, убийства и кто с кем дрался. Клик по столбцу — сортировка, по отряду — подробности.',
      squad: 'Отряд', dealt: 'Нанёс', taken: 'Получил', kills: 'Убил', dpm: 'Урон / мин', weapons: 'Оружие', abilities: 'Способности', ranged: 'дальний бой', melee: 'ближний бой',
      ability: 'оружие способностей', effect: 'эффекты способностей', other: 'прочее', wlist: 'Урон по оружию', klist: 'Убитые модели', tf: 'Кто наносил урон', per: 'Снаряжение и улучшения',
      start: 'начало', bought: 'куплено', ko: 'героев повержено', st: 'зданий разрушено', alive: 'на поле', none: '—', perMin: '/мин',
      kd: { ranged: 'дальний', melee: 'ближний', ability: 'способность', effect: 'эффект способности', other: 'прочее', unknown: 'без попадания' },
      note: 'Урон — реально снятое здоровье (лишний урон по уже убитым не считается). Эффекты способностей — урон, который движок наносит без оружия: псайкерские силы, действие гранат и рывков, горение и яд, давка. Баффы (Waaagh!, ауры) сидят внутри попаданий и отдельно не выделяются.' } };
  const cx = k => (CX[L] || CX.en)[k];
  const cbCss = `
.sim-cb { margin-top: 18px; }
.sim-cbp { margin-top: 12px; border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
.sim-cbp > .sim-pn { padding: 7px 10px; background: rgba(127,127,127,.06); }
.sim-cbt { width: 100%; border-collapse: collapse; font-size: 13.5px; font-variant-numeric: tabular-nums; }
.sim-cbt { table-layout: fixed; }
.sim-cbt th:not(.l) { width: 15%; }
@media (max-width: 560px) { .sim-cbt th:not(.l) { width: 18%; } .sim-cbt th { white-space: normal; padding: 5px 6px; } .sim-cbt td { padding: 5px 6px; } .sim-cbt .life { display: block; margin: 0; } }
.sim-cbt th { text-align: right; font-weight: 600; color: var(--muted); font-size: 12.5px; padding: 5px 10px; cursor: pointer; white-space: nowrap; user-select: none; border-top: 1px solid var(--line); }
.sim-cbt th.l, .sim-cbt td.l { text-align: left; }
.sim-cbt th.on { color: var(--text); }
.sim-cbt td { text-align: right; padding: 5px 10px; border-top: 1px solid var(--line); white-space: nowrap; }
.sim-cbt td.l { white-space: normal; }
.sim-cbr { cursor: pointer; }
.sim-cbr:hover { background: rgba(230,195,92,.07); }
.sim-cbr.open { background: rgba(230,195,92,.14); }
.sim-cbt .life { color: var(--muted); font-size: 12px; margin-left: 6px; }
.sim-cbd td { text-align: left; white-space: normal; background: rgba(127,127,127,.04); padding: 8px 10px 12px; }
.sim-cbs { margin-bottom: 8px; }
.sim-cbg { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 8px 16px; }
.sim-cbg h5 { margin: 0 0 3px; font-size: 12.5px; color: var(--muted); font-weight: 600; }
.sim-cbg div div { font-size: 13px; line-height: 1.45; }
.sim-cbg .m { color: var(--muted); }
.sim-cbn { color: var(--muted); font-size: 12px; margin-top: 8px; }
.sim-kd { font-size: 11.5px; color: var(--muted); }
`;
  const KIND_W = ['ranged', 'melee'], KIND_A = ['ability', 'effect'];
  const csum = o => Object.values(o || {}).reduce((a, b) => a + b, 0);
  const clife = q => Math.max(1, q.a[1] - q.a[0]);
  function cval(q, k) { return k === 'n' ? q.n.toLowerCase() : k === 'd' ? csum(q.d) : k === 'tk' ? csum(q.tk) : k === 'k' ? q.k + q.ko / 10 : k === 'dpm' ? csum(q.d) / clife(q) * 60 : 0; }
  function csplit(d) {
    const part = (ks, t) => { const v = ks.filter(k => d[k]); return v.length ? `${t} <b>${nf(v.reduce((a, k) => a + d[k], 0))}</b> (${v.map(k => cx(k) + ' ' + nf(d[k])).join(', ')})` : ''; };
    return [part(KIND_W, cx('weapons')), part(KIND_A, cx('abilities')), d.other ? `${cx('other')} <b>${nf(d.other)}</b>` : ''].filter(Boolean).join(' · ') || cx('none');
  }
  const pcol = pid => (S.P[pid] || {}).color || 'var(--muted)';
  const kdn = k => (cx('kd') || {})[k] || k;
  function cdetail(q) {
    const C = S.D.combat;
    const w = q.w.map(x => `<div>${x[0] ? esc(x[0]) + ` <span class="sim-kd">${kdn(x[1])}</span>` : `<i>${kdn(x[1])}</i>`} <b>${nf(x[2])}</b></div>`).join('') || `<div class="m">${cx('none')}</div>`;
    const kv = q.kv.map(x => `<div>${x[3]} × <span style="color:${pcol(x[1])}">${esc(x[0])}</span> <span class="sim-kd">${kdn(x[2])}${x[4] ? ', ' + esc(x[4]) : ''}</span></div>`).join('')
      + (q.kol || []).map(x => `<div>☠ <span style="color:${pcol(x[1])}">${esc(x[0])}</span> <span class="sim-kd">${cx('ko')}: ${x[3]}${x[4] ? ', ' + esc(x[4]) : ''}</span></div>`).join('')
      + (q.stl || []).map(x => `<div>▣ <span style="color:${pcol(x[1])}">${esc(x[0])}</span> <span class="sim-kd">${cx('st')}: ${x[2]}</span></div>`).join('') || `<div class="m">${cx('none')}</div>`;
    const tf = q.tf.map(x => `<div><span style="color:${pcol(x[1])}">${esc(x[2])}</span>${S.P[x[1]] ? ` <span class="sim-kd">${esc(S.P[x[1]].name)}</span>` : ''} <b>${nf(x[3])}</b></div>`).join('') || `<div class="m">${cx('none')}</div>`;
    const pe = (q.pe || []).map((x, i) => { const dur = Math.max(1, x[1] - x[0]);
      return `<div><span class="m">${fmt(x[0])}–${fmt(x[1])}</span> ${i === 0 ? cx('start') : cx('bought') + ' <b>' + esc(x[2].join(', ') || '?') + '</b>'}: ${cx('dealt').toLowerCase()} <b>${nf(x[3])}</b> (${nf(x[3] / dur * 60)}${cx('perMin')}), ${cx('taken').toLowerCase()} ${nf(x[4])}, ${cx('kills').toLowerCase()} ${x[5]}` +
        (Object.keys(x[6] || {}).length ? `<div class="sim-kd">${csplit(x[6])}</div>` : '') + '</div>'; }).join('');
    return `<tr class="sim-cbd"><td colspan="5"><div class="sim-cbs">${cx('dealt')}: ${csplit(q.d)}<br>${cx('taken')}: ${csplit(q.tk)}</div>
      <div class="sim-cbg"><div><h5>${cx('wlist')}</h5>${w}</div><div><h5>${cx('klist')}</h5>${kv}</div><div><h5>${cx('tf')}</h5>${tf}</div>${pe ? `<div><h5>${cx('per')}</h5>${pe}</div>` : ''}</div></td></tr>`;
  }
  function combat() {
    const box = document.getElementById('simCb'); if (!box || !S) return;
    const C = S.D.combat; if (!C || !C.sq || !Object.keys(C.sq).length) { box.hidden = true; return; }
    if (!document.getElementById('sim-cb-css')) { const st = document.createElement('style'); st.id = 'sim-cb-css'; st.textContent = cbCss; document.head.appendChild(st); }
    box.hidden = false;
    const so = S.cbSort || (S.cbSort = { k: 'd', dir: -1 });
    const cols = [['n', cx('squad')], ['d', cx('dealt')], ['tk', cx('taken')], ['k', cx('kills')], ['dpm', cx('dpm')]];
    let h = `<div class="cap">${cx('title')}</div><div class="sim-sub">${cx('sub')}</div>`;
    for (const tm of S.teams) for (const p of S.D.players.filter(p => p.team === tm)) {
      const list = Object.entries(C.sq).filter(([, q]) => q.p === p.pid);
      if (!list.length) continue;
      list.sort((a, b) => { const x = cval(a[1], so.k), y = cval(b[1], so.k); return (x < y ? -1 : x > y ? 1 : 0) * so.dir; });
      const r = AS.races[rk(p.race)] || {};
      h += `<div class="sim-cbp"><div class="sim-pn"><i class="sim-sh c${p.side}" style="background:${p.color};border-color:${TEAMC[p.side]}"></i>${r.icon ? `<img src="${A + r.icon}" alt="">` : ''}<span>${esc(p.name)}</span></div>` +
        `<table class="sim-cbt"><thead><tr>${cols.map(([k, t]) => `<th data-k="${k}" class="${k === 'n' ? 'l' : ''}${so.k === k ? ' on' : ''}">${t}${so.k === k ? (so.dir < 0 ? ' ▾' : ' ▴') : ''}</th>`).join('')}</tr></thead><tbody>` +
        list.map(([id, q]) => `<tr class="sim-cbr${S.cbOpen === id ? ' open' : ''}" data-id="${id}"><td class="l">${q.h ? '★ ' : ''}${esc(q.n)}<span class="life">${fmt(q.a[0])}–${fmt(q.a[1])}</span></td>` +
          `<td>${nf(csum(q.d))}</td><td>${nf(csum(q.tk))}</td><td>${q.k}${q.ko ? ` <span class="sim-kd">+${q.ko}☠</span>` : ''}</td><td>${nf(csum(q.d) / clife(q) * 60)}</td></tr>` +
          (S.cbOpen === id ? cdetail(q) : '')).join('') + '</tbody></table></div>';
    }
    box.innerHTML = h + `<div class="sim-cbn">${cx('note')}</div>`;
    box.onclick = e => {
      const th = e.target.closest('th[data-k]');
      if (th) { const k = th.dataset.k; S.cbSort = so.k === k ? { k, dir: -so.dir } : { k, dir: k === 'n' ? 1 : -1 }; combat(); return; }
      const tr = e.target.closest('tr.sim-cbr');
      if (tr) { S.cbOpen = S.cbOpen === tr.dataset.id ? null : tr.dataset.id; combat(); }
    };
  }

  function setFocus(pid) {
    S.focus = pid != null ? pid : S.focusLock;
    document.querySelectorAll('#sim [data-pid]').forEach(x => x.classList.toggle('on', +x.dataset.pid === S.focus));
    draw();
  }
  function events() {
    const D = S.D;
    const pn = pid => (S.P[pid] || {}).name || '?';
    const rows = S.ev.filter(e => S.evf === 'all' || e.k === S.evf).map(e => {
      let ic = '', x = '', d = '';
      if (e.k === 'fights') {
        const f = e.f, ts = Object.keys(f.loss).sort();
        ic = '⚔'; const w = f.win != null ? tx('won')(`<b style="color:${TEAMC[S.teams.indexOf(+f.win) % 2]}">${tname(+f.win)}</b>`) : tx('even');
        x = `${tx('fight')} ${tx('near')(S.dir(f.x, f.z))} · ${f.t1 - f.t0} ${tx('sec')} — ${w}`;
        d = ts.map(k => `<span style="color:${TEAMC[S.teams.indexOf(+k) % 2]}">${tname(+k)}</span>: −${nf(f.loss[k])} ${tx('hp')}` + ((f.killed[k] || []).length ? `, ${tx('wiped')} ${(f.killed[k] || []).length}` : '')).join(' · ');
      } else if (e.k === 'heroes') { ic = '☠'; x = tx('heroDown')(esc((S.P[e.sq[0]] || {}).hero_name || e.sq[1]), esc(pn(e.sq[0]))); }
      else if (e.k === 'deaths') { ic = '✖'; x = tx('squadLost')(esc(e.sq[1]), esc(pn(e.sq[0]))); }
      else { const c = e.c; const p = D.players.find(q => q.name === c[1]); ic = '💬'; x = `<b style="color:${p ? p.color : 'var(--muted)'}">${esc(c[1])}</b>: ${esc(c[3])}`; }
      return `<div class="sim-e" data-t="${e.t}"><span class="t">${fmt(e.t)}</span><span>${ic}</span><span class="x">${x}${d ? `<div class="d">${d}</div>` : ''}</span></div>`;
    });
    if (S.res && S.evf === 'all') { const p = resParts(S.res); rows.push(`<div class="sim-e" data-t="${D.dur - 1}"><span class="t">${fmt(D.dur - 1)}</span><span>🏁</span><span class="x"><b>${tx('resTitle')}</b>: ${p.head}<div class="d">${p.why}</div></span></div>`); }
    S.el.evl.innerHTML = rows.join('') || '<div class="sim-e"><span></span><span></span><span class="x">—</span></div>';
    S.curEv = null; ui(true);
  }

  // ---------- drawing ----------
  function sizeCanvas(cv, h) {
    const r = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    const w = Math.max(50, r.width); h = h || r.height;
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    const c = cv.getContext('2d'); c.setTransform(dpr, 0, 0, dpr, 0, 0); return [w, h];
  }
  function sizeAll() {
    const D = S.D, wrap = document.getElementById('simW'); if (!wrap) return;
    let w = wrap.clientWidth, h = w * D.h / D.w;
    const maxH = Math.min(720, window.innerHeight * 0.78);
    if (h > maxH) { h = maxH; w = h * D.w / D.h; }
    S.el.map.style.width = w + 'px'; S.el.map.style.height = h + 'px'; S.el.map.style.margin = '0 auto';
    S.mw = w; S.mh = h;
    sizeCanvas(S.el.map, h);
  }
  const W2P = (x, z) => [(x / S.D.w + 0.5) * S.mw, (0.5 - z / S.D.h) * S.mh];

  function draw() {
    if (!S || !S.el) return;
    const D = S.D, c = S.el.map.getContext('2d'), w = S.mw, h = S.mh, t = S.t, k = Math.max(0.7, Math.min(1.6, w / 560));
    c.clearRect(0, 0, w, h);
    if (S.bg) { c.imageSmoothingEnabled = true; c.drawImage(S.bg, 0, 0, w, h); c.fillStyle = 'rgba(0,0,0,.28)'; c.fillRect(0, 0, w, h); }
    else { c.fillStyle = '#1a1b1e'; c.fillRect(0, 0, w, h); }
    // heat map
    if (S.heat && D.heat[S.heat]) {
      const g = D.grid, hm = D.heat[S.heat], mx = Math.max(1, ...hm), col = (S.P[S.heat] || {}).color || '#fff';
      c.fillStyle = col;
      for (let i = 0; i < hm.length; i++) { if (!hm[i]) continue; c.globalAlpha = Math.min(0.85, 0.08 + 0.8 * Math.sqrt(hm[i] / mx)); c.fillRect((i % g) * w / g, Math.floor(i / g) * h / g, w / g + .5, h / g + .5); }
      c.globalAlpha = 1;
    }
    // map points: with the game's own owners (pown) - filled with the owner's team colour, a capture as a pulsing ring
    if (D.pown) {
      const st = pointsAt(t), ph = (performance.now() / 700) % 1;
      D.pown.pts.forEach(([kd, x, z], i) => {
        const [px, py] = W2P(x, z), [own, cap] = st[i], vp = kd === 'vp', r = (vp ? 8 : 6) * k;
        const col = own >= 0 ? TEAMC[Math.max(0, S.teams.indexOf(own)) % 2] : 'rgba(150,150,150,.85)';
        if (cap >= 0 && cap !== 2 && cap !== own || cap === 2) {
          const cc = cap === 2 ? '#fff' : TEAMC[Math.max(0, S.teams.indexOf(cap)) % 2];
          c.beginPath(); c.arc(px, py, r + (4 + 9 * ph) * k, 0, 7); c.strokeStyle = cc; c.globalAlpha = 1 - ph; c.lineWidth = 2.5; c.stroke(); c.globalAlpha = 1;
        }
        c.save(); c.translate(px, py);
        if (vp) { c.rotate(Math.PI / 4); c.beginPath(); c.rect(-r * .8, -r * .8, r * 1.6, r * 1.6); }
        else if (kd === 'req') { c.beginPath(); c.arc(0, 0, r, 0, 7); }
        else { c.beginPath(); for (let a = 0; a < 6; a++) { const an = Math.PI / 6 + a * Math.PI / 3; c[a ? 'lineTo' : 'moveTo'](Math.cos(an) * r, Math.sin(an) * r); } c.closePath(); }
        if (vp) { c.fillStyle = col; c.fill(); c.lineWidth = 2.4; c.strokeStyle = '#ffd75e'; c.stroke(); }
        else {   // a point = a hollow ring in the owner's colour (squads are filled), a dark core with a light dot
          c.fillStyle = 'rgba(8,9,10,.78)'; c.fill(); c.lineWidth = 3.2 * k; c.strokeStyle = col; c.stroke();
          c.beginPath(); c.arc(0, 0, 1.6 * k, 0, 7); c.fillStyle = 'rgba(255,255,255,.85)'; c.fill();
        }
        c.restore();
      });
    }
    for (const [kd, x, z] of D.pown ? [] : D.mpoints || []) {
      const [px, py] = W2P(x, z);
      if (kd === 'vp') { c.save(); c.translate(px, py); c.rotate(Math.PI / 4); c.fillStyle = 'rgba(230,195,92,.9)'; c.strokeStyle = '#000'; c.lineWidth = 1.5; c.fillRect(-5 * k, -5 * k, 10 * k, 10 * k); c.strokeRect(-5 * k, -5 * k, 10 * k, 10 * k); c.restore(); }
      else if (kd === 'cp' || kd === 'pw') { c.beginPath(); c.arc(px, py, 5 * k, 0, 7); c.strokeStyle = 'rgba(255,255,255,.75)'; c.lineWidth = 2; c.stroke(); }
    }
    // trails
    if (S.trails) {
      c.lineWidth = 1.6 * k; c.lineCap = 'round';
      const s0 = Math.max(0, Math.floor(t) - 14), s1 = Math.min(D.dur - 1, Math.floor(t));
      const paths = new Map();
      for (let s = s0; s <= s1; s++) { const fr = D.frames[s]; for (let i = 0; i < fr.length; i += 6) { if (fr[i + 4] <= 0) continue; let a = paths.get(fr[i]); if (!a) paths.set(fr[i], a = []); a.push(fr[i + 1], fr[i + 2]); } }
      for (const [id, a] of paths) {
        if (a.length < 4) continue; const sq = D.squads[id], p = S.P[sq[0]]; if (!p) continue;
        c.strokeStyle = p.color; c.globalAlpha = S.focus != null && sq[0] !== S.focus ? 0.06 : 0.4; c.beginPath();
        for (let i = 0; i < a.length; i += 2) { const [px, py] = W2P(a[i], a[i + 1]); if (i && Math.abs(a[i] - a[i - 2]) + Math.abs(a[i + 1] - a[i - 1]) > 40) c.moveTo(px, py); else if (i) c.lineTo(px, py); else c.moveTo(px, py); }
        c.stroke();
      }
      c.globalAlpha = 1;
    }
    // fights in progress
    for (const f of D.fights || []) {
      if (t < f.t0 - 1 || t > f.t1 + 3) continue;
      const [px, py] = W2P(f.x, f.z), ph = (performance.now() / 600) % 1;
      c.beginPath(); c.arc(px, py, (18 + 14 * ph) * k, 0, 7); c.strokeStyle = `rgba(255,190,80,${0.7 * (1 - ph)})`; c.lineWidth = 3; c.stroke();
      c.beginPath(); c.arc(px, py, 18 * k, 0, 7); c.strokeStyle = 'rgba(255,120,60,.55)'; c.lineWidth = 1.5; c.stroke();
    }
    // deaths (fade 25 s)
    for (const d of D.deaths || []) {
      const age = t - d[0]; if (age < 0 || age > 25) continue;
      const sq = D.squads[d[1]], p = sq && S.P[sq[0]]; const [px, py] = W2P(d[2], d[3]);
      c.globalAlpha = 1 - age / 25; c.strokeStyle = p ? p.color : '#fff'; c.lineWidth = 2.5 * k; const r = (sq && sq[2] ? 7 : 5) * k;
      c.beginPath(); c.moveTo(px - r, py - r); c.lineTo(px + r, py + r); c.moveTo(px + r, py - r); c.lineTo(px - r, py + r); c.stroke();
      if (age < 1.2) { c.beginPath(); c.arc(px, py, (8 + age * 30) * k, 0, 7); c.strokeStyle = '#fff'; c.lineWidth = 2; c.globalAlpha = 1 - age / 1.2; c.stroke(); }
    }
    c.globalAlpha = 1;
    // squads
    const sqs = squadAt(t);
    sqs.sort((a, b) => (D.squads[a.id][2] - D.squads[b.id][2]));
    const blink = (performance.now() / 250 | 0) % 2;
    let hov = null, hd = 1e9;
    const labels = [];
    for (const q of sqs) {
      const sq = D.squads[q.id], p = S.P[sq[0]]; if (!p) continue;
      const [px, py] = W2P(q.x, q.z), hero = sq[2], down = q.hp <= 0 || q.n <= 0;
      const r = (hero ? 6.5 : 3.4 + Math.min(q.n, 8) * 0.42) * k;
      if (S.hover) { const dd = Math.hypot(S.hover[0] - px, S.hover[1] - py); if (dd < Math.max(10, r + 4) && dd < hd) { hd = dd; hov = { q, sq, p, px, py }; } }
      if (down) { c.globalAlpha = 0.8; c.strokeStyle = '#ccc'; c.lineWidth = 2; c.beginPath(); c.moveTo(px - r, py - r); c.lineTo(px + r, py + r); c.moveTo(px + r, py - r); c.lineTo(px - r, py + r); c.stroke(); c.globalAlpha = 1; continue; }
      const st = q.st, retreat = st === 5, fight = st === 3 || st === 4, dim = S.focus != null && sq[0] !== S.focus;
      c.globalAlpha = dim ? 0.16 : 1;
      if (fight && blink && !dim) { c.beginPath(); c.arc(px, py, r + 4.5 * k, 0, 7); c.fillStyle = 'rgba(255,150,40,.5)'; c.fill(); }
      const shape = rr => { c.beginPath(); if (p.side) { c.rect(px - rr, py - rr, 2 * rr, 2 * rr); } else c.arc(px, py, rr * 1.08, 0, 7); };
      if (hero) { shape(r + 2.6 * k); c.fillStyle = '#ffd75e'; c.fill(); }
      shape(r);
      c.fillStyle = p.color; if (retreat) c.globalAlpha *= 0.5; c.fill(); c.globalAlpha = dim ? 0.16 : 1;
      c.lineWidth = 2 * k; c.strokeStyle = TEAMC[p.side]; if (retreat) { c.setLineDash([3, 2]); c.strokeStyle = '#fff'; c.lineWidth = 1.4; } c.stroke(); c.setLineDash([]);
      if (S.num[q.id] && !dim) labels.push([S.num[q.id], px, py, r, q.id === S.hl, p.color, hero]);
      if (q.id === S.hl) { c.beginPath(); c.arc(px, py, r + 6 * k, 0, 7); c.strokeStyle = '#fff'; c.lineWidth = 2.2; c.stroke(); c.beginPath(); c.arc(px, py, r + 6 * k + 2.2, 0, 7); c.strokeStyle = 'rgba(0,0,0,.7)'; c.lineWidth = 1.2; c.stroke(); }
      if (q.hp < 99) { const bw = Math.max(8, 2 * r), by = py + r + 3 * k; c.fillStyle = 'rgba(0,0,0,.7)'; c.fillRect(px - bw / 2 - 1, by - 1, bw + 2, 4); c.fillStyle = q.hp > 50 ? '#6dff7a' : q.hp > 25 ? '#ffd23f' : '#ff4d4d'; c.fillRect(px - bw / 2, by, bw * q.hp / 100, 2); }
      c.globalAlpha = 1;
    }
    // squad numbers (build order per player, as in the side panel): a small dark badge beside the marker, over all markers.
    // Badges do not overlap: each tries four corners of its marker; one that finds no free place is left out (hover / the panel tell)
    if (labels.length) {
      const fs = Math.max(9, Math.min(12, 9 * k)), placed = [];
      c.textAlign = 'center'; c.textBaseline = 'middle';
      labels.sort((a, b) => (b[4] - a[4]) || (b[6] - a[6]) || (a[0] - b[0]));
      for (const [n, px, py, r, on, col] of labels) {
        const f = on ? fs + 2 : fs; c.font = `700 ${f}px system-ui, -apple-system, sans-serif`;
        const bw = Math.max(f + 2, c.measureText(n).width + 6), bh = f + 3, o = r * 0.55 + 1;
        let box = null;
        for (const [dx, dy] of [[1, -1], [-1, -1], [1, 1], [-1, 1]]) {
          const x = dx > 0 ? px + o : px - o - bw, y = dy < 0 ? py - o - bh : py + o;
          if (on || !placed.some(b => x < b[0] + b[2] && b[0] < x + bw && y < b[1] + b[3] && b[1] < y + bh)) { box = [x, y, bw, bh]; break; }
        }
        if (!box) continue;
        placed.push(box);
        const [x, y] = box;
        c.beginPath(); if (c.roundRect) c.roundRect(x, y, bw, bh, bh / 2); else c.rect(x, y, bw, bh);
        c.fillStyle = on ? 'rgba(0,0,0,.92)' : 'rgba(0,0,0,.74)'; c.fill(); c.lineWidth = on ? 1.6 : 1; c.strokeStyle = on ? '#ffd75e' : col; c.stroke();
        c.fillStyle = on ? '#ffd75e' : '#fff'; c.fillText(n, x + bw / 2, y + bh / 2 + 0.5);
      }
    }
    // tooltip
    const tip = S.el.tip;
    if (hov) {
      const { q, sq, p, px, py } = hov; const name = sq[2] ? (p.hero_name || sq[1]) : sq[1];
      tip.innerHTML = `<b style="color:${p.color}">${S.num[q.id] ? '#' + S.num[q.id] + ' ' : ''}${esc(S.num[q.id] ? qname(q.id) : name)}</b><br>${esc(p.name)} · ${q.hp}% ${tx('hp')} · ${q.n} ${tx('models')}<br>${(tx('st')[q.st] || '')}`;
      tip.style.display = 'block'; const tw = tip.offsetWidth;
      tip.style.left = Math.min(w - tw - 4, Math.max(4, px + 12)) + 'px'; tip.style.top = Math.max(4, py - 46) + 'px';
    } else tip.style.display = 'none';
    // clock + score + chat
    S.el.clock.textContent = fmt(t);
    const s = Math.min(D.dur - 1, Math.floor(t));
    const sk = s + '|' + L; if (sk !== S.scoreKey) { S.scoreKey = sk; S.el.score.innerHTML = S.teams.map(tm => `<span style="color:${TEAMC[S.teams.indexOf(tm) % 2]}">${scoreHTML(tm, s)}</span>`).join(' &nbsp;'); }
    const cl = (D.chat || []).filter(x => x[0] <= t && t - x[0] < 9).slice(-3);
    const ck = cl.map(x => x[0] + x[1] + x[3]).join('|');
    if (ck !== S.chatKey) {
      S.chatKey = ck;
      S.el.chat.innerHTML = cl.map(x => { const p = D.players.find(q => q.name === x[1]); return `<div><b style="color:${p ? p.color : '#ddd'}">${esc(x[1])}</b>${x[2] === 'team' ? ' ▸' : ''}: ${esc(x[3])}</div>`; }).join('');
    }
  }

  function chart(cv, series, opts) {
    const [w, h] = sizeCanvas(cv, 120), c = cv.getContext('2d'), D = S.D, n = D.dur;
    c.clearRect(0, 0, w, h);
    let mx = opts.max || 1; series.forEach(se => se.v.forEach(v => { if (v != null && v > mx) mx = v; }));
    const X = i => 6 + (w - 12) * i / Math.max(1, n - 1), Y = v => h - 16 - (h - 26) * v / mx;
    c.strokeStyle = 'rgba(127,127,127,.18)'; c.lineWidth = 1; c.fillStyle = 'rgba(150,150,150,.9)'; c.font = '10px system-ui, sans-serif';
    for (let m = 0; m * 60 < n; m += (n > 1500 ? 10 : 5)) { const x = X(m * 60); c.beginPath(); c.moveTo(x, 6); c.lineTo(x, h - 14); c.stroke(); c.fillText(m + "'", x + 2, h - 3); }
    // fights as bands
    if (opts.fights) for (const f of D.fights || []) { c.fillStyle = 'rgba(255,170,60,.10)'; c.fillRect(X(f.t0), 6, Math.max(2, X(f.t1) - X(f.t0)), h - 20); }
    for (const se of series) {
      c.strokeStyle = se.c; c.lineWidth = se.w || 1.8; c.globalAlpha = se.a || 1; c.beginPath(); let on = false;
      const step = Math.max(1, Math.floor(n / (w * 1.5)));
      for (let i = 0; i < n; i += step) { const v = se.v[i]; if (v == null) { on = false; continue; } const x = X(i), y = Y(v); if (on) c.lineTo(x, y); else { c.moveTo(x, y); on = true; } }
      c.stroke(); c.globalAlpha = 1;
    }
    const x = X(Math.min(n - 1, S.t)); c.strokeStyle = 'rgba(230,195,92,.95)'; c.lineWidth = 1.5; c.beginPath(); c.moveTo(x, 4); c.lineTo(x, h - 14); c.stroke();
  }
  function charts() {
    if (!S || !S.el) return;
    const D = S.D;
    chart(S.el.army, S.teams.map(tm => ({ c: TEAMC[S.teams.indexOf(tm) % 2], v: (D.army_team || {})[tm] || [], w: 2.2 })), { fights: true });
    chart(S.el.pts, S.teams.map(tm => ({ c: TEAMC[S.teams.indexOf(tm) % 2], v: (D.points || {})[tm] || [], w: 2.2 })), {});
    chart(S.el.req, S.teams.map(tm => ({ c: TEAMC[S.teams.indexOf(tm) % 2], v: S.alive[tm] || [], w: 2.2 })), {});
    timeline(); tkline();
  }
  // the victory-point score of both sides over the match (0 at the bottom), marks where a victory point changes hands
  function tkline() {
    const cv = S.el.tk; if (!S.tk || !cv) return;
    const [w, h] = sizeCanvas(cv, 40), c = cv.getContext('2d'), D = S.D, n = D.dur, K = S.tk;
    const X = s => 8 + (w - 16) * s / Math.max(1, n - 1), Y = v => 5 + (h - 10) * (1 - Math.max(0, v) / K.max);
    c.clearRect(0, 0, w, h);
    c.fillStyle = 'rgba(127,127,127,.12)'; c.fillRect(0, 0, w, h);
    c.strokeStyle = 'rgba(127,127,127,.35)'; c.lineWidth = 1; c.beginPath(); c.moveTo(8, Y(0) + .5); c.lineTo(w - 8, Y(0) + .5); c.stroke();
    for (const [es, o] of K.vpEv) { const x = Math.round(X(es)) + .5, i = S.teams.indexOf(o); c.strokeStyle = i >= 0 ? TEAMC[i % 2] : 'rgba(150,150,150,.9)'; c.globalAlpha = .45; c.beginPath(); c.moveTo(x, 0); c.lineTo(x, h); c.stroke(); c.globalAlpha = 1;
      c.fillStyle = c.strokeStyle; c.beginPath(); c.moveTo(x, 0); c.lineTo(x + 3, 3); c.lineTo(x, 6); c.lineTo(x - 3, 3); c.fill(); }
    const step = Math.max(1, Math.floor(n / (w * 1.5)));
    S.teams.forEach((tm, ti) => {
      const v = K.by[tm]; c.strokeStyle = TEAMC[ti % 2]; c.lineWidth = 2; c.beginPath();
      for (let i = 0; i < n; i += step) { const x = X(i), y = Y(v[i]); if (i) c.lineTo(x, y); else c.moveTo(x, y); }
      c.lineTo(X(n - 1), Y(v[n - 1])); c.stroke();
    });
    const x = X(Math.min(n - 1, S.t)); c.fillStyle = 'rgba(230,195,92,.18)'; c.fillRect(8, 0, x - 8, h); c.strokeStyle = '#e6c35c'; c.lineWidth = 2; c.beginPath(); c.moveTo(x, 0); c.lineTo(x, h); c.stroke();
  }
  function timeline() {
    const cv = S.el.tl, [w, h] = sizeCanvas(cv, 54), c = cv.getContext('2d'), D = S.D, n = D.dur;
    const X = s => 8 + (w - 16) * s / Math.max(1, n - 1);
    c.clearRect(0, 0, w, h);
    c.fillStyle = 'rgba(127,127,127,.12)'; c.fillRect(0, 0, w, h);
    // army difference as a band
    const a0 = (D.army_team || {})[S.teams[0]] || [], a1 = (D.army_team || {})[S.teams[1]] || [];
    if (a1.length) {
      const mx = Math.max(1, ...a0.map((v, i) => Math.abs(v - (a1[i] || 0))));
      for (let px = 0; px < w - 16; px += 2) { const i = Math.floor(px / (w - 16) * (n - 1)), d = (a0[i] || 0) - (a1[i] || 0); c.fillStyle = d >= 0 ? TEAMC[0] : TEAMC[1]; c.globalAlpha = 0.18 + 0.5 * Math.abs(d) / mx; c.fillRect(8 + px, 22, 2, 10); }
      c.globalAlpha = 1;
    }
    for (const f of D.fights || []) { c.fillStyle = f.win != null ? TEAMC[S.teams.indexOf(+f.win) % 2] : '#bbb'; c.fillRect(X(f.t0), 8, Math.max(3, X(f.t1) - X(f.t0)), 9); }
    for (const d of D.deaths || []) { const sq = D.squads[d[1]], p = sq && S.P[sq[0]]; c.fillStyle = p ? p.color : '#fff'; if (sq && sq[2]) { const x = X(d[0]); c.beginPath(); c.moveTo(x, 44); c.lineTo(x - 4, 52); c.lineTo(x + 4, 52); c.fill(); } else c.fillRect(X(d[0]) - 1, 36, 2, 7); }
    for (const ch of D.chat || []) { c.fillStyle = 'rgba(255,255,255,.75)'; c.beginPath(); c.arc(X(ch[0]), 4, 1.8, 0, 7); c.fill(); }
    const x = X(Math.min(n - 1, S.t)); c.fillStyle = 'rgba(230,195,92,.25)'; c.fillRect(8, 0, x - 8, h); c.strokeStyle = '#e6c35c'; c.lineWidth = 2; c.beginPath(); c.moveTo(x, 0); c.lineTo(x, h); c.stroke();
  }

  function ui(force) {
    if (!S || !S.el) return;
    S.el.time.textContent = fmt(S.t) + ' / ' + fmt(S.D.dur - 1);
    if (S.el.final) S.el.final.hidden = !(S.t >= S.D.dur - 3 && !S.el.big);
    S.el.play.textContent = S.playing ? '❚❚ ' + tx('pause') : '▶ ' + tx('play');
    side(false);
    // current event highlight
    let cur = null; for (const e of S.ev) { if (e.t <= S.t + 0.5 && (S.evf === 'all' || e.k === S.evf)) cur = e; }
    const key = cur ? cur.t + cur.k : '';
    if (key !== S.curEv || force) {
      S.curEv = key;
      S.el.evl.querySelectorAll('.sim-e.cur').forEach(x => x.classList.remove('cur'));
      if (cur) { const rows = S.el.evl.querySelectorAll(`.sim-e[data-t="${cur.t}"]`); const r = rows[rows.length - 1]; if (r) { r.classList.add('cur'); if (S.playing) { const box = S.el.evl; if (r.offsetTop < box.scrollTop || r.offsetTop > box.scrollTop + box.clientHeight - 40) box.scrollTop = r.offsetTop - box.clientHeight / 3; } } }
    }
  }
  function seek(t) { S.t = Math.max(0, Math.min(S.D.dur - 1, t)); if (S.el.big) { S.el.big.remove(); S.el.big = null; } draw(); charts(); ui(); }
  // 14.11.2026 (owner): the views of the detailed analysis - counted when the match is actually played (once per page; the server
  // counts a viewer once a day)
  function countView() {
    if (S.viewed) return; S.viewed = true;
    fetch('/replay/api/r/' + S.rid + '/view', { method: 'POST' }).then(r => r.json()).then(j => { S.views = j.views; viewsLabel(); }).catch(() => {});
  }
  function viewsLabel() { const e = document.getElementById('simViews'); if (e) e.textContent = S.views ? '👁 ' + S.views : ''; }
  function toggle(on) {
    S.playing = on != null ? on : !S.playing;
    if (S.playing) countView();
    if (S.playing && S.t >= S.D.dur - 1.01) S.t = 0;
    S.last = performance.now(); ui();
    if (S.playing && !S.raf) S.raf = requestAnimationFrame(loop);
  }
  let uiTick = 0;
  function loop(now) {
    if (!S) return;
    const dt = Math.min(0.1, (now - S.last) / 1000); S.last = now;
    if (S.playing) { S.t += dt * S.speed; if (S.t >= S.D.dur - 1) { S.t = S.D.dur - 1; S.playing = false; } }
    draw();
    if (now - uiTick > 220) { uiTick = now; ui(); if (S.drag == null) charts(); }
    S.raf = (S.playing || (S.D.fights || []).some(f => S.t >= f.t0 - 1 && S.t <= f.t1 + 3) || (S.D.pown && pointsAt(S.t).some(([o, cp]) => cp >= 0 && cp !== o))) ? requestAnimationFrame(loop) : 0;
    if (!S.raf) ui();
  }

  window.SIM = { show, hide, offer, verdict, resHTML };
})();
