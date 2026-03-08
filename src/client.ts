import { DbConnection, SubscriptionBuilder } from './module_bindings';
import { Color } from './module_bindings/types';

const COLOR_MAP: Record<string, { tag: string }> = {
  '#67e8f9': { tag: 'Cyan' },
  '#a78bfa': { tag: 'Purple' },
  '#fb923c': { tag: 'Orange' },
  '#34d399': { tag: 'Green' },
  '#f472b6': { tag: 'Pink' },
  '#fbbf24': { tag: 'Yellow' },
};

const conn = DbConnection.builder()
  .withUri('ws://localhost:3000')
  .withDatabaseName('hyperspace')
  .onConnect((ctx, identity, token) => {
    console.log('[hyperspace] connected', identity.toHexString());
    localStorage.setItem('stdb_token', token);

    new SubscriptionBuilder(ctx.conn)
      .onApplied(() => console.log('[hyperspace] subscribed'))
      .subscribe('SELECT * FROM html_broadcast');
  })
  .onError((_ctx, err) => console.error('[hyperspace] error', err))
  .onDisconnect(() => console.log('[hyperspace] disconnected'))
  .withToken(localStorage.getItem('stdb_token') || undefined)
  .build();

// Morph server-rendered HTML into #app on broadcast
conn.db.html_broadcast.onInsert((_ctx, row) => {
  const app = document.getElementById('app');
  if (app && row.html) {
    if (typeof (window as any).Idiomorph !== 'undefined') {
      (window as any).Idiomorph.morph(app, row.html, { morphStyle: 'innerHTML' });
    } else {
      app.innerHTML = row.html;
    }
  }
});

// Expose reducer calls globally for onclick handlers in server-rendered HTML
(window as any).hyperspace = {
  createBrick(x: number, y: number) {
    conn.reducers.createBrick(x, y);
  },
  deleteBrick(id: number) {
    conn.reducers.deleteBrick(BigInt(id));
  },
  setName(name: string) {
    conn.reducers.setName(name);
  },
  setColor(hex: string) {
    const mapped = COLOR_MAP[hex];
    if (mapped) {
      conn.reducers.setColor({ tag: mapped.tag } as any);
    }
  },
  startDrag(id: number) {
    conn.reducers.startDrag(BigInt(id));
  },
  endDrag() {
    conn.reducers.endDrag();
  },
  moveBrick(id: number, x: number, y: number) {
    conn.reducers.moveBrick(BigInt(id), x, y);
  },
  updateCursor(x: number, y: number, z: number) {
    conn.reducers.updateCursor(x, y, z);
  },
};
