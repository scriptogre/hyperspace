# Hyperspace

A real-time multiplayer isometric sandbox where players place, drag, and stack 3D blocks on a shared 12x12 grid — built with **zero application JavaScript**.

Every pixel you see is server-rendered HTML. Every interaction is a declarative attribute. The server is the single source of truth, and the client just morphs what it's told.

## What It Does

- **Place blocks** — click any grid cell to stack a colored 3D brick (up to 5 high)
- **Drag blocks** — grab and move bricks between cells in real time
- **Delete blocks** — hold Shift and click to remove (cursor turns to crosshair, borders glow red)
- **See other players** — live cursors, player list, and an event log of everything happening
- **Pick a name and color** — personalize on first join, reflected immediately for everyone

All of this happens across multiple browser tabs or devices simultaneously, with sub-second sync.

## The Architecture

This is a **server-driven hypermedia** app. There is no client-side state, no React, no virtual DOM diffing, no API calls. The entire UI lifecycle is:

```
1. User clicks a grid cell
2. Inline handler calls stdb.callReducer('create_brick', [x, y])
3. WebSocket sends the call to SpacetimeDB
4. Rust reducer runs: inserts a Brick row, then calls broadcast()
5. broadcast() renders the Jinja2 template once per connected user
6. Each user's personalized HTML is inserted into the html_broadcast event table
7. SpacetimeDB pushes the row to that user's WebSocket (RLS-filtered)
8. htmx-spacetimedb.js receives the HTML and Idiomorph morphs #app
9. The block appears — with 3D CSS transforms, hover effects, and all
```

Every reducer — create, delete, drag, move, set name, set color — ends with `broadcast(ctx)`. The server re-renders the world for every connected client on every state change.

### Why Per-User Rendering?

The template is personalized. Your cursor is brighter than others. Your name badge has a colored border. The setup prompt only shows for new users. This is impossible with a single broadcast — each client gets HTML tailored to their identity.

```rust
fn broadcast(ctx: &ReducerContext) {
    for user in ctx.db.user().iter().filter(|u| u.online) {
        let html = render::render_body(&ctx.db, Some(&user.identity));
        let _ = ctx.db.html_broadcast().identity().delete(user.identity);
        ctx.db.html_broadcast().insert(HtmlBroadcast {
            identity: user.identity,
            html,
        });
    }
}
```

## The Stack

| Layer | Role |
|---|---|
| **SpacetimeDB** | Database + WebSocket server + reducer execution, all in one. Compiles Rust to Wasm and runs it at the edge. |
| **MiniJinja** | Server-side HTML rendering. Templates are embedded at compile time via `include_str!`. |
| **htmx** | Declarative HTML attributes (`hx-on:*`, `ws-send`, `hx-vals`) for user interactions. |
| **htmx-spacetimedb.js** | Generic bridge (~200 lines) connecting htmx to SpacetimeDB's WebSocket protocol. Reusable across any project. |
| **Idiomorph** | DOM morphing that preserves focus, scroll position, CSS transitions, and form state during full-page updates. |
| **Tailwind CSS v4** | All styling, including 3D transforms, hover states, transitions, and conditional visual effects via `data-*` selectors. |
| **Playwright** | E2E tests covering multi-user sync, drag-and-drop, and WebSocket lifecycle. |

## How the 3D Works

The isometric view is pure CSS — no canvas, no WebGL, no SVG:

```css
/* The grid container is rotated into isometric perspective */
.grid-container {
    transform: rotateX(60deg) rotateZ(-45deg);
    transform-style: preserve-3d;
}
```

Each block is three divs (top face, south wall, west wall) with CSS 3D transforms:

```html
<!-- Top face — lifted by depth -->
<div style="background: var(--color); transform: translateZ(12px)">

<!-- South wall — rotated down from bottom edge -->
<div style="background: color-mix(in srgb, var(--color) 65%, black);
            transform-origin: bottom; transform: rotateX(-90deg)">

<!-- West wall — rotated left from left edge -->
<div style="background: color-mix(in srgb, var(--color) 45%, black);
            transform-origin: left; transform: rotateY(-90deg)">
```

Stacking is a `translateZ` offset: `transform: translateZ({{ block.grid_z * 12 }}px)`. The walls get progressively darker using `color-mix()` to simulate lighting.

## Data Model

Five tables, all in Rust, all in SpacetimeDB:

```rust
Brick    { id, position: {x, y, z}, color, dragged_by: Option<Identity> }
User     { identity, name, color, online }
Cursor   { identity, position: {x, y, z} }
Event    { id, kind, identity, brick_id, timestamp }

// Ephemeral — RLS-filtered so each client only sees their own row
HtmlBroadcast { identity, html }
```

The `HtmlBroadcast` table is the key innovation. It's an event table (rows are ephemeral) with a client visibility filter:

```rust
#[client_visibility_filter]
const BROADCAST_FILTER: Filter =
    Filter::Sql("SELECT * FROM html_broadcast WHERE html_broadcast.identity = :sender");
```

Clients subscribe to `SELECT * FROM html_broadcast` and SpacetimeDB ensures they only receive rows addressed to their identity. No client-side filtering needed.

## Interactions Are Declarative

There is no application JavaScript. Interactions are expressed entirely as HTML attributes:

**Click to place a brick:**
```html
<button hx-on:click="stdb.callReducer('create_brick', [{{ col }}, {{ row }}])">
```

**Shift+click to delete:**
```html
<div hx-on:mousedown="
    if (event.shiftKey) { stdb.callReducer('delete_brick', [id]); return; }
    /* ...otherwise start drag... */
">
```

**Hold Shift for delete mode (CSS-only visual change):**
```html
<body hx-on:keydown="if(event.key==='Shift') document.body?.setAttribute('data-delete-mode','')">

<!-- Blocks respond with Tailwind's group-data selector -->
<div class="group-data-[delete-mode]/body:group-hover/brick:border-red-500">
```

**Set name on Enter:**
```html
<input hx-on:keydown="if(event.key==='Enter') stdb.callReducer('set_name', [this.value])">
```

## Project Structure

```
src/
  lib.rs          — HTTP route: GET / returns full page
  models.rs       — Tables (Brick, User, Cursor, Event, HtmlBroadcast) and types
  reducers.rs     — All mutations + lifecycle hooks + broadcast()
  render.rs       — MiniJinja template engine, world_state() context builder
templates/
  index.html.j2   — The entire UI: 12x12 grid, 3D blocks, cursors, HUD, event log
static/js/
  htmx-spacetimedb.js  — Generic htmx extension for SpacetimeDB WebSocket protocol
  vendor/               — htmx, Idiomorph
tests/e2e/
  hyperspace.spec.ts    — Playwright tests: multi-user, drag-drop, WebSocket lifecycle
```

~530 lines of Rust. ~220 lines of template. ~210 lines of bridge JS. Zero lines of application JS.

## Running

Requires [SpacetimeDB](https://spacetimedb.com) built locally (see `Justfile` for path conventions).

```bash
just up      # Start SpacetimeDB, publish the module
just down    # Stop SpacetimeDB
just test    # Run Playwright E2E tests
just check   # Clippy + fmt
```

The app runs at `http://localhost:3000`. Open multiple tabs to see multiplayer sync.
