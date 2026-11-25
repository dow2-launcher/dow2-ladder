'use strict';
// The header of the ladder pages (/ladder/ and /ladder/chat; style: ladder-hdr.css), 18.11.2026 (SirItos).
//  - the phone's menu: a drawer from the left behind ☰ (<= 980 px); closes on a tap outside (the scrim), on an item, on Esc, and when
//    the window grows to a desktop's
//  - a page without the ladder's own texts (the chat) marks the header's words data-ht: here they follow the ladder's language choice
//    (?lang=, then the one picked on /ladder/, then the browser's); /ladder/ itself labels its header (data-t, ladder-t.js)
(function () {
  const H = document.querySelector('.hdr'), B = document.getElementById('burger');
  if (!H || !B || H.dataset.hdrOn) return; H.dataset.hdrOn = '1';
  const TX = { ru: { tabTable: 'Рейтинг', tabHistory: 'История матчей', tabLive: 'Идущие матчи', chatLink: 'Чат', dlLauncher: 'Скачать лаунчер', menuT: 'Меню' },
    en: { tabTable: 'Rating', tabHistory: 'Match history', tabLive: 'Live matches', chatLink: 'Chat', dlLauncher: 'Download launcher', menuT: 'Menu' } };
  if (H.querySelector('[data-ht]')) {
    let l = new URLSearchParams(location.search).get('lang');
    if (l === 'ru' || l === 'en') H.querySelectorAll('.tab[href^="/ladder"]').forEach(a => { a.href += (a.href.includes('?') ? '&' : '?') + 'lang=' + l; });
    else { try { l = localStorage.getItem('ladderLang'); } catch (e) { l = null; } }
    if (l !== 'ru' && l !== 'en') l = /^(ru|uk|be|kk)/i.test(navigator.language || '') ? 'ru' : 'en';
    H.querySelectorAll('[data-ht]').forEach(e => { const v = TX[l][e.dataset.ht]; if (v) { if (e === B) e.title = v; else e.textContent = v; } });
  }
  const menu = open => {
    H.classList.toggle('open', open); B.setAttribute('aria-expanded', open); document.body.classList.toggle('menu-open', open);
    if (open) { const a = H.querySelector('.menu .tab.on') || H.querySelector('.menu a'); if (a) a.focus({ preventScroll: true }); }
  };
  B.addEventListener('click', () => menu(!H.classList.contains('open')));
  const s = H.querySelector('.scrim'); if (s) s.addEventListener('click', () => menu(false));
  H.querySelector('.menu').addEventListener('click', e => { if (e.target.closest('a')) menu(false); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && H.classList.contains('open')) { menu(false); B.focus(); } });
  matchMedia('(min-width: 981px)').addEventListener('change', e => { if (e.matches) menu(false); });
})();
// 25.11.2026 (SirItos: "the chat's profile block not over the chat - into the toolbar or the side menu"): who is signed in (the chat's
// Steam sign-in, its session cookie, /ladder/api/c/whoami) on every ladder page. A desktop: a chip at the header's right end (avatar,
// name), a click opens its menu - the Elite rating per mode with the place and the top-3 badge (/ladder/api/own/all), my rating page,
// Sign out. A phone: the drawer's first block, open. Not signed in: "Sign in" (the same Steam sign-in, back to this page).
// The page shares the two answers (window._wa / window._oa): the chat and the table ask once.
(function () {
  const H = document.querySelector('.hdr'), box = document.getElementById('hdrMe');
  if (!H || !box) return;
  const lang = () => { let l = new URLSearchParams(location.search).get('lang'); if (l !== 'ru' && l !== 'en') { try { l = localStorage.getItem('ladderLang'); } catch (e) { l = null; } }
    return l === 'ru' || l === 'en' ? l : /^(ru|uk|be|kk)/i.test(navigator.language || '') ? 'ru' : 'en'; };
  const TX = { ru: { page: 'Моя страница рейтинга', out: 'Выйти', in: 'Войти', inT: 'Войти через Steam', cal: 'калибровка', place: 'место', none: 'нет игр', menu: 'Профиль' },
    en: { page: 'My rating page', out: 'Sign out', in: 'Sign in', inT: 'Sign in with Steam', cal: 'calibration', place: 'place', none: 'no games', menu: 'Profile' } };
  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const STEAM = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2a10 10 0 0 0-9.9 8.6l5.3 2.2a2.8 2.8 0 0 1 1.6-.5h.1l2.4-3.4v-.1a3.7 3.7 0 1 1 3.7 3.7h-.1l-3.4 2.4v.1a2.8 2.8 0 0 1-5.5.8L2 18.2A10 10 0 1 0 12 2z"/></svg>';
  window._wa = window._wa || fetch('/ladder/api/c/whoami', { credentials: 'same-origin', cache: 'no-store' }).then(r => r.json()).catch(() => ({}));
  window._oa = window._oa || fetch('/ladder/api/own/all').then(r => r.json()).catch(() => ({}));
  let ME = null, OWN = null;
  function draw() {
    const t = TX[lang()];
    box.hidden = false;
    if (!ME) {
      box.className = 'hme out';
      box.innerHTML = `<button type="button" class="hme-in" id="hmeIn" title="${esc(t.inT)}">${STEAM}<span>${esc(t.in)}</span></button>`;
      document.getElementById('hmeIn').onclick = () => { let n = ''; const a = new Uint8Array(24); crypto.getRandomValues(a); a.forEach(x => n += x.toString(16).padStart(2, '0'));
        location.href = '/ladder/api/c/login?nonce=' + n + '&to=' + encodeURIComponent(location.pathname); };
      return;
    }
    const e = OWN && OWN.players ? OWN.players[String(ME.steam)] || {} : {}, k = (OWN && OWN.cal_games) || 5;
    const rows = ['1v1', '2v2', '3v3'].map(m => { const x = e[m];
      const v = x && x.c != null ? `<b>${esc(x.c)}</b>` + (x.rank ? `<span class="pl">${esc(t.place)} ${esc(x.rank)}</span>` : '')
        + (x.rank && x.rank <= 3 ? `<i class="rt-b m${m} r${x.rank}"></i>` : '') : `<span class="cl">${x ? esc(t.cal) + ' ' + Math.min(x.g || 0, k) + '/' + k : esc(t.none)}</span>`;
      return `<a class="hme-r" href="/ladder/player/${esc(ME.steam)}?mode=${m}"><span class="md">${m}</span>${v}</a>`; }).join('');
    const av = ME.avatar ? `<img src="${esc(ME.avatar)}" alt="">` : `<span class="av0">${esc(String(ME.name || '?').slice(0, 1).toUpperCase())}</span>`;
    box.className = 'hme';
    box.innerHTML = `<button type="button" class="hme-chip" id="hmeChip" aria-haspopup="true" aria-expanded="false" title="${esc(t.menu)}">${av}<span class="nm">${esc(ME.name || ME.steam)}</span><i class="chev"></i></button>`
      + `<div class="hme-p" id="hmeP"><div class="hme-h">${av}<span class="nm">${esc(ME.name || ME.steam)}</span></div><div class="hme-rs">${rows}</div>`
      + `<a class="hme-a" href="/ladder/player/${esc(ME.steam)}">${esc(t.page)} ›</a><button type="button" class="hme-a out" id="hmeOut">${esc(t.out)}</button></div>`;
    const chip = document.getElementById('hmeChip');
    chip.onclick = ev => { ev.stopPropagation(); const on = !box.classList.contains('open'); box.classList.toggle('open', on); chip.setAttribute('aria-expanded', on); };
    document.getElementById('hmeOut').onclick = async () => {
      try { await fetch('/ladder/api/c/logout', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: '{}' }); } catch (er) {}
      location.reload();
    };
  }
  document.addEventListener('click', ev => { if (box.classList.contains('open') && !ev.target.closest('#hdrMe')) { box.classList.remove('open'); const c = document.getElementById('hmeChip'); if (c) c.setAttribute('aria-expanded', 'false'); } });
  document.addEventListener('keydown', ev => { if (ev.key === 'Escape') box.classList.remove('open'); });
  const lb = document.getElementById('lang'); if (lb) lb.addEventListener('click', () => setTimeout(draw, 0));   // /ladder/'s RU / EN
  Promise.all([window._wa, window._oa]).then(([me, oa]) => { ME = me && me.signed_in ? me : null; OWN = oa; draw(); });
})();
