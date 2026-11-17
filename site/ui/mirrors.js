// The site's mirrors in the header of every page (owner 17.11.2026): a mirror icon, then each mirror as its country's flag and
// its number there - Germany 1 = rts, Germany 2 = dow2, Russia 1 = dow2ru (Moscow, a proxy of the same site). The one in use is
// lit; a click opens this very page (path, query, #part) on the other. A page puts <span data-mirrors></span> in its header;
// without one the switcher sits in the top right corner.
(function () {
  var M = [['rts.fintebtc.de', 'de', 1], ['dow2.fintebtc.de', 'de', 2], ['dow2ru.fintebtc.de', 'ru', 1]];
  var F = { de: ['#111', '#d00', '#fc0'], ru: ['#fff', '#1c57c9', '#d52b1e'] };
  var flag = function (c) {
    return '<svg viewBox="0 0 9 6" width="12" height="8" aria-hidden="true"><path fill="' + c[0] + '" d="M0 0h9v2H0z"/><path fill="' + c[1]
      + '" d="M0 2h9v2H0z"/><path fill="' + c[2] + '" d="M0 4h9v2H0z"/></svg>';
  };
  var icon = '<svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true" fill="none" stroke="currentColor"><rect x=".5" y="3.5" width="8" height="8"/><path d="M3.5 3V.5h8v8H9"/></svg>';
  var css = '.mirrors{display:inline-flex;align-items:center;gap:5px;font:600 10px/1 system-ui,sans-serif;white-space:nowrap;opacity:.8}'
    + '.mirrors a{display:inline-flex;align-items:center;gap:2px;padding:2px 3px;border-radius:3px;color:inherit;text-decoration:none;opacity:.65}'
    + '.mirrors a:hover{opacity:1}.mirrors a.on{opacity:1;box-shadow:inset 0 0 0 1px currentColor}.mirrors svg{display:block}'
    + '.mirrors svg[viewBox="0 0 9 6"]{box-shadow:0 0 0 .5px rgba(128,128,128,.6)}'
    + '.mirrors-float{position:absolute;top:3px;right:6px;z-index:60}';
  function draw() {
    var st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
    var box = document.querySelector('[data-mirrors]');
    if (!box) { box = document.createElement('div'); box.className = 'mirrors-float'; document.body.appendChild(box); }
    box.classList.add('mirrors');
    var here = location.hostname.toLowerCase();
    box.innerHTML = '<span title="Mirrors / Зеркала">' + icon + '</span>' + M.map(function (m) {
      return '<a href="https://' + m[0] + '/" data-h="' + m[0] + '" title="' + m[0] + '"' + (m[0] === here ? ' class="on" aria-current="true"' : '')
        + '>' + flag(F[m[1]]) + m[2] + '</a>';
    }).join('');
    // the page may have moved (tabs, #how, ?mode=) since it was drawn: the link takes where it is at the click
    var at = function (e) {
      var a = e.target.closest && e.target.closest('a[data-h]');
      if (a) a.href = 'https://' + a.getAttribute('data-h') + location.pathname + location.search + location.hash;
    };
    ['mouseover', 'focusin', 'click', 'auxclick', 'touchstart'].forEach(function (n) { box.addEventListener(n, at, { passive: true }); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', draw); else draw();
})();
