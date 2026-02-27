function appendToConsole(message, colorClass = 'text-gray-400') {
  const consoleElement = document.getElementById('console-log');
  if (!consoleElement) return;

  const timestamp = new Date().toLocaleTimeString('en', { hour12: false });
  consoleElement.insertAdjacentHTML('beforeend',
    `<div class="${colorClass}"><span class="text-gray-600">${timestamp}</span> ${message}</div>`
  );
  consoleElement.scrollTop = consoleElement.scrollHeight;

  while (consoleElement.children.length > 200) {
    consoleElement.firstChild.remove();
  }
}

// Server events → console
document.body.addEventListener('console-log', (event) => {
  appendToConsole(event.detail?.msg ?? '?', event.detail?.color ?? 'text-gray-400');
});

// Server cursor updates → position fixed overlays on grid cells
document.body.addEventListener('cursor-update', (event) => {
  document.querySelectorAll('.iso-cursor').forEach(element => element.remove());

  const cursors = event.detail?.cursors ?? [];
  for (const cursor of cursors) {
    const cell = document.querySelector(`.iso-cell[data-x="${cursor.grid_x}"][data-y="${cursor.grid_y}"]`);
    if (!cell) continue;

    const cellRect = cell.getBoundingClientRect();
    const centerX = cellRect.left + cellRect.width / 2;
    const centerY = cellRect.top + cellRect.height / 2;

    document.body.insertAdjacentHTML('beforeend',
      `<div class="iso-cursor" style="left:${centerX}px;top:${centerY}px;transform:translate(-50%,-100%);--color:${cursor.color}">
        <div class="iso-cursor-dot"></div>
        <span class="iso-label">${cursor.name}</span>
      </div>`
    );
  }
});

// Capture the WebSocket wrapper when htmx opens the connection
let socketWrapper = null;

document.body.addEventListener('htmx:wsOpen', (event) => {
  socketWrapper = event.detail?.socketWrapper;
  appendToConsole('connected', 'text-green-400');
});

document.body.addEventListener('htmx:wsClose', () => {
  socketWrapper = null;
  appendToConsole('disconnected', 'text-red-400');
});

// Cursor tracking — send grid position on mousemove, deduplicating same-cell moves
let lastCursorKey = '';

document.addEventListener('mousemove', (event) => {
  const cell = event.target.closest('.iso-cell');
  if (!cell) return;

  const key = `${cell.dataset.x},${cell.dataset.y}`;
  if (key === lastCursorKey) return;
  lastCursorKey = key;

  socketWrapper?.send(JSON.stringify({
    action: 'cursor',
    x: cell.dataset.x,
    y: cell.dataset.y,
  }));
});

appendToConsole('initialized', 'text-gray-500');
