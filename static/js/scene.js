const log = (msg, cls = 'text-gray-400') => {
  const el = document.getElementById('console-log');
  if (!el) return;
  const t = new Date().toLocaleTimeString('en', { hour12: false });
  el.insertAdjacentHTML('beforeend', `<div class="${cls}"><span class="text-gray-600">${t}</span> ${msg}</div>`);
  el.scrollTop = el.scrollHeight;
  while (el.children.length > 200) el.firstChild.remove();
};

// Server events → console
document.body.addEventListener('console-log', (e) =>
  log(e.detail?.msg ?? '?', e.detail?.color ?? 'text-gray-400'));

document.body.addEventListener('cursor-update', (e) => {
  document.querySelectorAll('.iso-cursor').forEach(el => el.remove());
  const scene = document.getElementById('iso-scene');
  (e.detail?.cursors ?? []).forEach(c => {
    scene?.insertAdjacentHTML('beforeend',
      `<div class="iso-cursor" style="--col:${c.grid_x};--row:${c.grid_y};--color:${c.color}">
        <span class="iso-label">${c.name}</span>
      </div>`);
  });
});

// WS lifecycle
document.body.addEventListener('htmx:wsOpen', () => log('connected', 'text-green-400'));
document.body.addEventListener('htmx:wsClose', () => log('disconnected', 'text-red-400'));

log('initialized', 'text-gray-500');
