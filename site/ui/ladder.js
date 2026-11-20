'use strict';
// /ladder/ (ladder/ladder.html): the state, the table, the player page, the rules; after ladder-t.js (the texts), before ladder-x.js

const QS = new URLSearchParams(location.search);
let LANG = (() => {
  const q = QS.get('lang'); if (q === 'ru' || q === 'en') return q;
  try { const v = localStorage.getItem('ladderLang'); if (v === 'ru' || v === 'en') return v; } catch (e) {}
  return /^(ru|uk|be|kk)/i.test(navigator.language || '') ? 'ru' : 'en';
})();
const $ = s => document.querySelector(s);
const T = k => { for (const D of [UI, RI, LI]) { const v = D[LANG][k]; if (v !== undefined) return v; } return ''; };
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const fmtN = n => Math.round(n).toLocaleString(LANG === 'ru' ? 'ru-RU' : 'en-GB');
const MODES = ['1v1', '2v2', '3v3'], okMode = m => MODES.includes(m) ? m : null;
const PSTEAM = (location.pathname.match(/^\/ladder\/player\/(\d{5,20})\/?$/) || [])[1] || '';
const ON_TABLE_PATH = /^\/ladder\/table\/?$/.test(location.pathname);
const okView = v => ['table', 'history', 'live'].includes(v) ? v : null;
// 17.11.2026: the old /ladder/#elite[:steam] links go to the rating's pages (the table is the main view now)
(() => { const m = decodeURIComponent(location.hash.slice(1)).match(/^elite(?:[:/](\d{5,20}))?$/);
  if (m) location.replace(m[1] ? '/ladder/player/' + m[1] + '?lang=' + LANG : '/ladder/?lang=' + LANG); })();
let VIEW = PSTEAM ? 'player' : (okView(QS.get('view')) || (location.hash === '#history' ? 'history' : 'table'));
// the mode: ?mode=2v2, or the old #2v2; #how opens the rules
let MODE = okMode(QS.get('mode')) || okMode(location.hash.slice(1)) || '1v1';
let PMODE = okMode(QS.get('mode')) || '';        // the player page's match filter ('' = all modes)
let DATA = null, PDATA = null, SEQ = 0, PRE = false;
const A = '/elite/assets/'; let ASSETS = { races: {}, maps: {} }, assetsP = null;
const loadAssets = () => assetsP || (assetsP = fetch(A + 'index.json').then(r => r.json()).then(d => { ASSETS = d; }).catch(() => {}));
const keepLang = () => QS.get('lang') ? 'lang=' + LANG : '';
const qjoin = (...p) => { const s = p.filter(Boolean).join('&'); return s ? '?' + s : ''; };
const tableUrl = m => (ON_TABLE_PATH ? '/ladder/table' : '/ladder/') + qjoin(m && m !== '1v1' ? 'mode=' + m : '', keepLang());
const viewUrl = v => v === 'table' ? tableUrl(MODE) : '/ladder/' + qjoin('view=' + v, keepLang());
const playerUrl = (s, m) => '/ladder/player/' + encodeURIComponent(s) + qjoin('mode=' + (m || MODE), keepLang());

function applyLang() {
  document.documentElement.lang = LANG;
  document.querySelectorAll('[data-t]').forEach(e => { const v = T(e.dataset.t); if (typeof v === 'string') e.textContent = v; });
  document.querySelectorAll('[data-h]').forEach(e => { e.title = T(e.dataset.h); });
  document.querySelectorAll('[data-tp]').forEach(e => { e.placeholder = T(e.dataset.tp); });
  document.querySelectorAll('#lang button').forEach(b => b.classList.toggle('on', b.dataset.l === LANG));
  document.querySelectorAll('#tabs .tab[data-v]').forEach(a => { a.href = viewUrl(a.dataset.v); });   // "Чат": a page of its own
  document.querySelectorAll('#tabs .tab:not([data-v])').forEach(a => { a.href = '/ladder/chat' + qjoin(keepLang()); });
  $('#howText').innerHTML = T('how')(PRE);
  setTitle(); render(); renderPlayer();
  if (histInit) { hFillSelects(hMaps); if (hItems.length) hPaint(); }
  if (!$('#smaps').hidden) renderMaps();
  if (liveInit) { loadLive(); loadRooms(); }
}
function setTitle() {
  document.title = VIEW === 'player' ? (PDATA && PDATA.name ? PDATA.name + ' — ' : '') + T('title') + ' — Dawn of War II'
    : VIEW === 'history' ? T('hTitle') : VIEW === 'live' ? T('lTitle') : T('title') + ' — Elite Ladder — Dawn of War II';
}
function setTag(pre, season) {
  if (pre !== PRE) { PRE = pre; $('#howText').innerHTML = T('how')(PRE); }
  const tag = $('#tag'); tag.hidden = !!PRE; tag.textContent = PRE ? T('pre') : T('test');
  // the preseason (SirItos 17.11): no tag, the header says "Предсезон 2027" (the year from the season's label, e.g. 2027-pre)
  if (PRE) { const y = String(season || '').match(/\d{4}/); $('#seasonL').textContent = T('pre') + (y ? ' ' + y[0] : ''); }
  else if (season) $('#seasonL').textContent = T('seasonL')(season);
}

// ---------- the views (tabs) ----------
function showView(v) {
  VIEW = v;
  $('#vTable').hidden = v !== 'table'; $('#vPlayer').hidden = v !== 'player'; $('#vHistory').hidden = v !== 'history'; $('#vLive').hidden = v !== 'live';
  $('#how').hidden = !(v === 'table' || v === 'player');
  document.querySelectorAll('#tabs .tab').forEach(a => { const on = a.dataset.v === (v === 'player' ? 'table' : v); a.classList.toggle('on', on);
    if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  setTitle();
  if (v === 'table') initTable(); else if (v === 'history') initHistory(); else if (v === 'live') initLive();
}
$('#tabs').addEventListener('click', e => {
  const a = e.target.closest('.tab'); if (!a || !okView(a.dataset.v) || PSTEAM || e.ctrlKey || e.metaKey || e.shiftKey || e.button) return;   // the player page: a real link
  e.preventDefault(); if (a.dataset.v === VIEW) return;
  history.pushState(null, '', viewUrl(a.dataset.v)); showView(a.dataset.v);
});
window.addEventListener('popstate', () => { if (PSTEAM) return; const q = new URLSearchParams(location.search);
  MODE = okMode(q.get('mode')) || '1v1'; syncModes(); showView(okView(q.get('view')) || 'table'); if (VIEW === 'table') { DATA = null; loadTable(); } });

// ---------- the table ----------
const skulls = (k, n) => `<span class="csks" aria-hidden="true">${Array.from({ length: n }, (_, i) => `<i class="csk${i < k ? ' on' : ''}"></i>`).join('')}</span>`;
const calCell = (k, n) => `${skulls(k, n)}<span>${Math.min(k, n)}/${n}</span>`;
const badge = (rank, m) => rank && rank <= 3 ? `<i class="rt-b m${m} r${rank}" title="${esc(T('place')(rank) + ' · ' + m)}"></i>` : '';
function render() {
  if (VIEW !== 'table' || !DATA) return;
  const tb = $('#rows');
  if (DATA.error) { tb.innerHTML = `<div class="empty">${esc(T('err'))}</div>`; return; }
  setTag(!!DATA.preseason, DATA.season);
  const rows = DATA.rows || [];
  if (!rows.length) { tb.innerHTML = `<div class="empty">${esc(T('empty'))}</div>`; return; }
  let html = '', sep = false;
  for (const p of rows) {
    if (p.calibrating && !sep) { sep = true; html += `<div class="calh">${esc(T('calHead'))}</div>`; }
    const lost = p.losses + p.leaves;              // a leave is a loss (SirItos: W–L only)
    const wl = `<span class="wl" title="${esc(T('wlHint2') + (p.leaves ? ' · ' + T('leavesT')(p.leaves) : ''))}"><span class="w">${p.wins}</span>–<span class="lo">${lost}</span></span>`;
    const tip = esc(T('stats') + (p.hours_played != null ? ' · ' + T('hoursLine')(p.hours_played) : ''));
    const name = `<span class="nm"><span>${esc(p.name || p.steam)}</span>${badge(p.rank, DATA.mode || MODE)}</span>`;
    const href = esc(playerUrl(p.steam, DATA.mode || MODE));
    html += p.calibrating
      ? `<a class="tr p cr" href="${href}" title="${tip}"><span class="l rk">—</span><span class="l">${name}</span><span class="cal" title="${esc(T('calT')(p.cal_played, p.cal_needed))}">${calCell(p.cal_played, p.cal_needed)}</span><span>${p.games}</span>${wl}</a>`
      : `<a class="tr p${p.rank <= 3 ? ' top top' + p.rank : ''}" href="${href}" title="${tip}"><span class="l rk">${p.rank}</span><span class="l">${name}</span><span class="rv" title="${esc('± ' + p.rd)}">${p.cons}</span><span>${p.games}</span>${wl}</a>`;
  }
  tb.innerHTML = html;
}
async function loadTable() {
  const my = ++SEQ;
  if (!DATA) $('#rows').innerHTML = `<div class="empty">${esc(T('loading'))}</div>`;
  try {
    const r = await fetch('/ladder/api/own?' + new URLSearchParams({ mode: MODE }));
    const d = await r.json();
    if (my !== SEQ) return;
    DATA = r.ok ? d : { error: true };
  } catch (e) { if (my === SEQ) DATA = { error: true }; }
  render();
}
let tableInit = false;
function initTable() {
  if (tableInit) return render(); tableInit = true;
  if (/^#[123]v[123]$/.test(location.hash)) history.replaceState(null, '', tableUrl(MODE));   // the old #2v2 links
  syncModes(); loadTable(); setInterval(() => { if (VIEW === 'table' && !document.hidden) loadTable(); }, 60000);
}
function syncModes() { document.querySelectorAll('#modes button').forEach(b => b.classList.toggle('on', b.dataset.m === MODE)); }
$('#modes').addEventListener('click', e => { const b = e.target.closest('button'); if (!b || b.dataset.m === MODE) return; MODE = b.dataset.m;
  history.replaceState(null, '', tableUrl(MODE) + (/^#(how|maps)$/.test(location.hash) ? location.hash : '')); syncModes(); DATA = null; loadTable();
  if (!$('#smaps').hidden) renderMaps();                 // 18.11.2026: the season's maps light the mode picked
  document.querySelectorAll('#tabs .tab[data-v]').forEach(a => { a.href = viewUrl(a.dataset.v); }); });

// ---------- the player page ----------
function hDate(t) { return new Date(t * 1000).toLocaleString(LANG === 'ru' ? 'ru-RU' : 'en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }); }
function pMapTitle(k) { const m = ASSETS.maps[k]; return esc(m && m.name ? m.name.replace(/^\(\d+p\)\s*/, '') : String(k || '').replace(/^\d+p_/, '').replace(/_/g, ' ')); }
function raceImg(k) { const r = k && ASSETS.races[k]; return r ? `<img src="${A + r.icon}" alt="" title="${esc(r.name)}">` : ''; }
// a mode's card: the preseason's (a button: the matches' filter) or, prev = {season, ratings}, the previous season's (17.11.2026, SirItos)
function card(m, prev) {
  const r = ((prev || PDATA).ratings || []).find(x => x.mode === m && (prev || x.season === PDATA.season));
  const cn = PDATA.cal_games || 5;
  let v, s1 = '', s2 = '';
  // the test's players are in the preseason's calibration from 0/5 (the table is not wiped, SirItos 17.11); 18.11.2026 (SirItos: "0/5
  // everywhere, the same"): in the preseason every mode with no entry yet shows the skulls 0/5, not only the modes of his roster (cal_modes)
  if (!r && !prev && (PDATA.preseason || (PDATA.cal_modes || []).includes(m))) v = `<div class="cv cal" title="${esc(T('calT')(0, cn))}"><span class="cal">${calCell(0, cn)}</span></div>`, s1 = esc(T('noGames'));
  else if (!r) v = `<div class="cv none">—</div>`, s1 = esc(T('noGames'));
  else {
    if (r.cons != null) v = `<div class="cv" title="${esc('± ' + r.rd)}">${r.cons}</div>`;   // 20.11.2026: the shown rating = the Glicko mean; RD only in the tip
    else v = `<div class="cv cal" title="${esc(T('calT')(r.games, PDATA.cal_games || 5))}"><span class="cal">${calCell(r.games, PDATA.cal_games || 5)}</span></div>`;
    s2 = `<span title="${esc(T('wlHint2') + (r.leaves ? ' · ' + T('leavesT')(r.leaves) : ''))}">W–L ${r.wins}–${r.losses + r.leaves}</span> · ${esc(T('gamesN')(r.games))}`;
  }
  const rk = r && r.rank ? `<span class="prk${r.rank <= 3 ? ' t' + r.rank : ''}">${badge(r.rank, m)}${esc(T('place')(r.rank))}</span>` : '';
  const body = `<div class="cm"><span>${m.replace('v', ' vs ')}</span>${rk}</div>${v}${s1 ? `<div class="cs">${s1}</div>` : ''}${s2 ? `<div class="cs">${s2}</div>` : ''}`;
  return prev ? `<div class="mc card pv">${body}</div>` : `<button class="mc card${PMODE === m ? ' on' : ''}" data-m="${m}">${body}</button>`;
}
function matchRow(m) {
  const me = m.me || {}, f = me.final || 'none', why = [];
  const notes = [...new Set((me.note || '').split(',').map(n => /^left_/.test(n) ? 'left_first' : n).filter(n => T('note')[n]))];   // left_36s_before_end
  notes.forEach(n => why.push(T('note')[n]));
  const counted = me.n != null;                                   // it moved his rating (rated, or his own loss for an early leave)
  if (!m.rated) why.push(T('unrated') + ': ' + ((m.why && T('why')[m.why]) || m.why || '—'));
  const pq = p => `<span class="pq${p.steam === PSTEAM ? ' me' : ''}">${raceImg(p.race)}${p.steam === PSTEAM ? esc(p.name || p.steam)
    : `<a href="${esc(playerUrl(p.steam, m.mode))}">${esc(p.name || p.steam)}</a>`}</span>`;
  const mine = m.teams.find(tm => tm.some(p => p.steam === PSTEAM)) || [], other = m.teams.filter(tm => tm !== mine);
  const teams = `<span class="sd">${mine.map(pq).join('')}</span>` + other.map(tm => `<span class="vs">${esc(T('vs'))}</span><span class="sd">${tm.map(pq).join('')}</span>`).join('');
  let dl;
  if (!counted) dl = `<div class="dl un">${esc(T('unrated'))}</div>`;
  else if (me.d != null) dl = `<div class="dl ${me.d > 0 ? 'up' : me.d < 0 ? 'down' : 'zero'}" title="${esc(T('tableNum')(me.c))}">${me.d > 0 ? '+' + me.d : me.d < 0 ? '−' + (-me.d) : '±0'}<small>${me.c}</small></div>`;
  else if (me.c != null) dl = `<div class="dl zero" title="${esc(T('calDone'))}">${me.c}<small>${esc(T('calDone'))}</small></div>`;
  else dl = `<div class="dl cal2">${esc(T('cal')(Math.min(me.n, PDATA.cal_games || 5), PDATA.cal_games || 5))}</div>`;
  const dur = m.ended && m.started ? Math.round((m.ended - m.started) / 60) : null;
  return `<div class="m"><div class="res2 ${f}">${esc(T('fin')[f] || f)}<small>${esc(m.mode || '')}</small></div>
    <div class="mid"><div class="meta">${hDate(m.started)} · ${pMapTitle(m.map)}${dur != null ? ' · ' + dur + ' ' + esc(T('min')) : ''}</div><div class="teams2">${teams}</div>
    ${why.length ? `<div class="why">${why.map(esc).join(' · ')}</div>` : ''}</div>${dl}</div>`;
}
function renderPlayer() {
  if (!PSTEAM) return;
  const v = $('#pv'); $('#back').href = tableUrl(PMODE || MODE);
  if (!PDATA) return;
  if (PDATA.error) { v.innerHTML = `<div class="empty">${esc(T('err'))}</div>`; return; }
  setTag(!!PDATA.preseason, PDATA.season);
  const name = PDATA.name || PSTEAM;
  setTitle();
  const av = PDATA.avatar ? `<img class="av" src="${esc(PDATA.avatar)}" alt="">` : `<div class="av">${esc(name.slice(0, 1).toUpperCase())}</div>`;
  const ms = (PDATA.matches || []).filter(m => !PMODE || m.mode === PMODE);
  const hrs = PDATA.hours_played != null ? `<span title="${esc(T('hoursHint'))}">${esc(T('hoursLine')(PDATA.hours_played))}</span>` : '';
  v.innerHTML = `<div class="pp-h">${av}<div><h1>${esc(name)}</h1><div class="pp-sub"><a href="https://steamcommunity.com/profiles/${esc(PSTEAM)}" target="_blank" rel="noopener">${esc(T('steam'))} ↗</a>${hrs}<span class="tag pre">${esc(PRE ? T('pre') : T('test'))}</span></div></div></div>
    <div class="cards">${MODES.map(m => card(m)).join('')}</div>${PDATA.prev && (PDATA.prev.ratings || []).length ? `
    <div class="prevh"><h2 class="h2">${esc(T('prevSeason')(PDATA.prev.season))}</h2><span class="muted">${esc(T('prevNote'))}</span></div>
    <div class="cards">${MODES.map(m => card(m, PDATA.prev)).join('')}</div>` : ''}
    <div class="ph" style="margin-top:16px"><h2 class="h2">${esc(T('recent'))}</h2><span class="sp"></span><div class="seg small" id="pmodes">${['', ...MODES].map(m => `<button data-m="${m}" class="${PMODE === m ? 'on' : ''}">${m ? m.replace('v', ' vs ') : esc(T('all'))}</button>`).join('')}</div></div>
    <div class="ms">${ms.length ? ms.map(matchRow).join('') : `<div class="empty">${esc(T('noMatches'))}</div>`}</div>`;
}
async function loadPlayer() {
  try {
    await loadAssets();
    const r = await fetch('/ladder/api/own/player?steam=' + encodeURIComponent(PSTEAM));
    PDATA = r.ok ? await r.json() : { error: true };
    if (!PDATA.error && !QS.get('mode')) {            // no mode asked: the mode he has played most this season
      const rs = (PDATA.ratings || []).filter(x => x.season === PDATA.season).sort((a, b) => b.games - a.games);
      PMODE = rs.length > 1 ? '' : (rs[0] && rs[0].mode) || '';
    }
  } catch (e) { PDATA = { error: true }; }
  renderPlayer();
}
$('#pv').addEventListener('click', e => { const b = e.target.closest('button[data-m]'); if (!b) return;
  PMODE = PMODE === b.dataset.m && b.classList.contains('mc') ? '' : b.dataset.m; if (PMODE) MODE = PMODE;
  history.replaceState(null, '', PMODE ? playerUrl(PSTEAM, PMODE) : '/ladder/player/' + PSTEAM + qjoin(keepLang())); renderPlayer(); });

// ---------- the rules (#how) ----------
function openHow() { if (location.hash === '#how' && !$('#how').hidden) { const d = $('#how'); d.open = true; setTimeout(() => d.scrollIntoView({ block: 'start' }), 0); } }
$('#how').addEventListener('toggle', () => { const want = $('#how').open ? '#how' : ''; if (location.hash !== want && (want || location.hash === '#how'))
  history.replaceState(null, '', location.pathname + location.search + want); });
window.addEventListener('hashchange', openHow);

