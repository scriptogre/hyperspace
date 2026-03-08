# WebSocket Broadcast via SpacetimeDB Event Tables

## Problem

The app currently uses HTTP POST routes that return morph fragments. This works for the acting user but provides no real-time sync — other users don't see changes until they refresh.

## Solution

Use SpacetimeDB's event tables to broadcast server-rendered HTML to all connected clients over WebSocket. A custom htmx extension wraps the SpacetimeDB TypeScript SDK, keeping the client minimal.

## Architecture

```
Browser                            SpacetimeDB Module
┌────────────────────┐            ┌─────────────────────┐
│ GET / (initial)    │───HTTP────▶│ Route: renders full  │
│                    │◀──HTML─────│ page with all state  │
│                    │            │                      │
│ htmx-stdb ext      │───WS─────▶│ SDK connection       │
│ (SpacetimeDB SDK)  │            │                      │
│                    │            │ client_connected     │
│ User clicks cell   │──reducer──▶│ → creates user       │
│                    │            │ → broadcasts HTML    │
│                    │            │                      │
│ Receives HTML via  │◀──event───│ html_broadcast table │
│ on_insert callback │  table     │ (per-identity rows)  │
│                    │            │                      │
│ idiomorph morphs   │            │ RLS: each client     │
│ the full <body>    │            │ only gets own row    │
└────────────────────┘            └─────────────────────┘
```

## Server Components

### Event table

```rust
#[spacetimedb::table(accessor = html_broadcast, public, event)]
pub struct HtmlBroadcast {
    pub identity: Identity,
    pub html: String,
}
```

Rows exist only during the transaction. Pushed to subscribers on commit, then deleted.

### RLS filter

```rust
#[client_visibility_filter]
const BROADCAST_FILTER: Filter = Filter::Sql(
    "SELECT * FROM html_broadcast WHERE html_broadcast.identity = :sender"
);
```

Each client only receives rows addressed to their identity. Client subscribes with no WHERE clause — server handles filtering.

### Connection lifecycle

```rust
#[reducer(client_connected)]
fn on_connect(ctx: &ReducerContext) { ... }

#[reducer(client_disconnected)]
fn on_disconnect(ctx: &ReducerContext) { ... }
```

`client_connected` creates or reconnects the user (using `ctx.sender` as identity). `client_disconnected` marks offline, cleans up cursor/drags.

### Broadcast function

After every state-changing reducer:

1. Iterate all online users
2. For each, render the template with `current_session_id` = that user's identity
3. Insert `HtmlBroadcast { identity, html }` for each

Template rendering uses the same minijinja setup as HTTP routes (shared `world_state` + `TEMPLATES`).

### Reducers

All existing reducers (`create_brick`, `delete_brick`, `set_name`, `set_color`, `start_drag`, `end_drag`, `move_brick`, `update_cursor`) call `broadcast(ctx)` at the end.

### HTTP routes

GET `/` remains — serves the initial full page. POST routes become unnecessary since all mutations go through reducers via WS. They can stay as fallbacks or be removed.

## Client Components

### htmx-stdb extension

A custom htmx extension (`static/js/htmx-ext-stdb.js`) that:

1. **Connects** to SpacetimeDB via the TS SDK (IIFE bundle)
2. **Subscribes** to `html_broadcast` table (RLS auto-filters)
3. **On `on_insert`**: extracts `html` field, morphs `<body>` content via idiomorph
4. **Intercepts user actions**: elements with `stdb-reducer` attributes trigger reducer calls instead of HTTP requests
5. **Forwards mouse events**: `mouseenter` on grid cells → `update_cursor` reducer
6. **Exposes identity**: makes the connection's identity available so the template or client JS can do self-highlighting

### Required JS assets

- SpacetimeDB TS SDK (IIFE bundle, built from generated bindings)
- htmx (already have)
- idiomorph (already have)
- htmx-ext-stdb.js (new, custom)

### Build step

The TS SDK bindings need to be generated and bundled:
```
spacetime generate --lang typescript --bin-path <wasm> --out-dir client/bindings
cd client && npm run build  # bundles to static/js/bindings.iife.js
```

## Template Changes

Minimal. The template stays the same but:
- `<body>` adds `hx-ext="stdb,morph"` instead of `server-commands,morph`
- Grid cell buttons use `stdb-reducer="create_brick"` + `stdb-args` instead of `hx-post`
- Delete buttons use `stdb-reducer="delete_brick"` + `stdb-args`
- Player setup uses `stdb-reducer="set_name"` / `stdb-reducer="set_color"`
- The WS extension and server-commands scripts are replaced by the STDB SDK bundle + htmx-ext-stdb

## What This Enables

- Real-time sync across all connected clients
- Per-session cursor tracking
- Per-session user identity (name, color)
- Drag-and-drop across clients
- Server-rendered HTML with idiomorph diffing (no client-side rendering logic)

## Files to Create/Modify

| File | Action |
|------|--------|
| `src/models.rs` | Add `HtmlBroadcast` event table, RLS filter |
| `src/reducers.rs` | Add lifecycle reducers, broadcast fn, call broadcast from all mutating reducers |
| `src/routes.rs` | Share template rendering with reducers (move to shared module) |
| `templates/index.html.j2` | Swap hx-post → stdb-reducer attributes |
| `static/js/htmx-ext-stdb.js` | New: custom htmx extension wrapping SpacetimeDB SDK |
| `client/` | New: TS bindings + build config for IIFE bundle |
| `Justfile` | Add client build step |
| `Cargo.toml` | Add `features = ["unstable"]` to spacetimedb dep |
