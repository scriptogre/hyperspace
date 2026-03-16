# Hyperspace

Real-time multiplayer isometric sandbox. Zero application JavaScript.

```
    ╭─────────────────────────────────────────────────────────╮
    │                                                         │
    │           ◆ Alice        ◆ Bob        ◆ Carol           │
    │                                                         │
    │                  ┌──┐                                   │
    │                  │▓▓│                                   │
    │               ┌──┼──┤  ┌──┐                             │
    │               │▒▒│▓▓│  │░░│                             │
    │            ┌──┼──┼──┤  ├──┤                             │
    │            │░░│▒▒│▓▓│  │░░│        ┌──┐                 │
    │         ╱ ╱ ╱├──┼──┤  ├──┤     ╱ ╱│▒▒│                 │
    │        ╱ ╱ ╱ │░░│▒▒│  │░░│    ╱ ╱ ├──┤                 │
    │       ╱ ╱ ╱ ╱├──┼──┘  ├──┘   ╱ ╱ ╱│▒▒│                 │
    │      ╱ ╱ ╱ ╱ │░░│     │░░│  ╱ ╱ ╱ ├──┘                 │
    │     ╱ ╱ ╱ ╱  └──┘     └──┘ ╱ ╱ ╱                       │
    │    ╱ ╱ ╱ ╱             ╱ ╱ ╱ ╱                          │
    │   ╱ ╱ ╱ ╱             ╱ ╱ ╱ ╱     12×12 isometric grid  │
    │                                    CSS 3D transforms     │
    │  Alice joined                      No canvas or WebGL    │
    │  Bob placed a brick                                      │
    │  Carol started dragging                                  │
    │                                                         │
    ╰─────────────────────────────────────────────────────────╯
```

## How It Works

```
  Browser A              SpacetimeDB (Rust → Wasm)              Browser B
  ─────────              ──────────────────────────              ─────────

  click cell
       │
       ▼
  stdb.callReducer ──────► create_brick(x, y)
  ('create_brick',        ┌──────────────────────┐
   [3, 5])                │ INSERT INTO brick     │
        ┌─────────────────│ ...                   │
        │                 │ broadcast()           │──────────────────┐
        │                 │  for each online user │                  │
        │                 │    render(template,   │                  │
        │                 │      viewer=identity) │                  │
        │                 └──────────┬────────────┘                  │
        │                            │                               │
        │           ┌────────────────┴────────────────┐              │
        │           ▼                                 ▼              │
        │   html_broadcast                    html_broadcast         │
        │   ┌─────────────────┐               ┌─────────────────┐   │
        │   │ identity: Alice │               │ identity: Bob   │   │
        │   │ html: "<div..." │               │ html: "<div..." │   │
        │   └────────┬────────┘               └────────┬────────┘   │
        │            │ RLS filter:                      │            │
        │            │ each client only                 │            │
        │            │ gets their own row               │            │
        │            ▼                                  ▼            │
        │   Idiomorph.morph(#app)              Idiomorph.morph(#app) │
        │                                                           │
        ▼                                                           ▼
  ┌──────────────┐                                    ┌──────────────┐
  │ Block appears │                                   │ Block appears │
  │ (your cursor  │                                   │ (your cursor  │
  │  is brighter) │                                   │  is brighter) │
  └──────────────┘                                    └──────────────┘
```

Every mutation — place, delete, drag, move, set name, set color — follows this exact flow. The server re-renders personalized HTML for every connected client on every state change.

## The Entire Interaction Model

```html
<!-- Place a brick: click a grid cell -->
<button hx-on:click="stdb.callReducer('create_brick', [3, 5])">

<!-- Delete a brick: Shift+click -->
<div hx-on:mousedown="
    if (event.shiftKey) { stdb.callReducer('delete_brick', [id]); return; }
    /* otherwise start drag */
">

<!-- Delete mode visuals: pure CSS via data attribute -->
<body hx-on:keydown="if(event.key==='Shift') this.setAttribute('data-delete-mode','')">
<div class="group-data-[delete-mode]/body:group-hover/brick:border-red-500">

<!-- Set name: Enter key -->
<input hx-on:keydown="if(event.key==='Enter') stdb.callReducer('set_name', [this.value])">
```

No application JavaScript files. No `<script>` blocks. Just HTML attributes calling server reducers.

## 3D Blocks in Pure CSS

```
            ┌──────────┐ ◄── top face: translateZ(12px)
           ╱          ╱│     background: var(--color)
          ╱          ╱ │
         └──────────┘  │
         │          │  │ ◄── west wall: rotateY(-90deg)
         │   top    │ ╱      color-mix(var(--color) 45%, black)
         │          │╱
         └──────────┘
              ▲
              │
         south wall: rotateX(-90deg)
         color-mix(var(--color) 65%, black)


    Stacking: translateZ(grid_z * 12px)     Isometric view: rotateX(60deg) rotateZ(-45deg)
```

Three `<div>`s per block. `color-mix()` darkens walls to simulate lighting. The grid container applies a single isometric rotation. No canvas, no WebGL, no SVG.

## Data Model

```
┌─────────────────────────────────────────────────────────────────────┐
│ SpacetimeDB Tables                                                  │
├──────────────────┬──────────────────────────────────────────────────┤
│ Brick            │ id, position{x,y,z}, color, dragged_by?         │
│ User             │ identity, name, color, online                    │
│ Cursor           │ identity, position{x,y,z}                       │
│ Event            │ id, kind, identity, brick_id?, timestamp         │
├──────────────────┼──────────────────────────────────────────────────┤
│ HtmlBroadcast    │ identity, html                                   │
│ (event table)    │ RLS: each client only receives their own row     │
└──────────────────┴──────────────────────────────────────────────────┘
```

## Project Structure

```
src/
  lib.rs          GET / → full HTML page                         13 lines
  models.rs       tables + types                                134 lines
  reducers.rs     mutations + lifecycle + broadcast()            255 lines
  render.rs       MiniJinja template engine                     127 lines
templates/
  index.html.j2   entire UI                                     217 lines
static/js/
  htmx-spacetimedb.js   generic SpacetimeDB ↔ htmx bridge      214 lines
```

## Running

```bash
just up      # start SpacetimeDB, publish module
just down    # stop
just test    # Playwright E2E
just check   # clippy + fmt
```

Open `http://localhost:3000` in multiple tabs.

Requires [SpacetimeDB](https://spacetimedb.com) built locally (see `Justfile`).
