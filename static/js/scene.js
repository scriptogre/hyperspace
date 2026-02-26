const log = (msg, cls = 'text-gray-400') => {
  const el = document.getElementById('console-log');
  if (!el) return;
  const t = new Date().toLocaleTimeString('en', { hour12: false });
  el.insertAdjacentHTML('beforeend', `<div class="${cls}"><span class="text-gray-600">${t}</span> ${msg}</div>`);
  el.scrollTop = el.scrollHeight;
  while (el.children.length > 200) el.firstChild.remove();
};

// Grid click → place block
document.addEventListener('click', (e) => {
  const cell = e.target.closest('.iso-cell');
  if (!cell) return;
  const { x, y } = cell.dataset;
  const ws = document.querySelector('[ws-connect]')?.__ws;
  if (ws?.readyState === 1) {
    ws.send(JSON.stringify({ action: 'create_at', x, y }));
    log(`placed block at (${x},${y})`, 'text-cyan-400');
  }
});

// Cursor tracking (throttled ~15fps)
let lastSend = 0;
document.getElementById('iso-scene')?.addEventListener('mousemove', (e) => {
  if (Date.now() - lastSend < 66) return;
  lastSend = Date.now();
  const cell = e.target.closest('.iso-cell');
  if (!cell) return;
  const ws = document.querySelector('[ws-connect]')?.__ws;
  if (ws?.readyState === 1) {
    ws.send(JSON.stringify({ action: 'cursor', x: cell.dataset.x, y: cell.dataset.y }));
  }
});

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
