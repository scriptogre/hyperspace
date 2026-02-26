# Hyperspace: Design Document

A real-time shared isometric playground powered by SpacetimeDB, served as a Hypermedia-Driven Application. Designed as a minimal, elegant boilerplate for building HDA apps with SpacetimeDB.

## Architecture

```
Browser (htmx + idiomorph + CSS isometric)
    | Single WebSocket
Rocket HTTP Server (minijinja templates, TailwindCSS v4 CDN)
    | Binary WebSocket (BSATN)
SpacetimeDB (Rust Wasm module)
```

SpacetimeDB holds all state and logic. Rocket connects as a client, mirrors tables in memory, re-renders a single minijinja template on every change, and pushes morphed HTML to browsers via WebSocket. Idiomorph diffs the DOM. CSS 3D transforms render the isometric view — no WebGL needed.

## Data Flow

**Page load:** `GET /` → Rocket reads SpacetimeDB mirror → renders template → browser opens WebSocket.

**User action (place block):** Browser `ws-send` → Rocket calls reducer → SpacetimeDB updates → pushes to Rocket → re-renders template → `<htmx target="body" swap="morph">` broadcast to all browsers → idiomorph patches DOM.

**Cursor movement (high frequency):** Browser sends position → Rocket calls `update_cursor` → SpacetimeDB pushes → Rocket sends `<htmx trigger='{"cursor-update": {...}}'>` → JS handler moves cursor markers. No DOM morph.

## Tech Stack

| Layer | Tech |
|-------|------|
| Database + Logic | SpacetimeDB 2.0 (Rust Wasm module) |
| HTTP/WS Server | Rocket 0.5 + rocket_ws |
| Templates | minijinja (via rocket_dyn_templates) |
| Hypermedia | htmx + WS extension + server-commands + idiomorph |
| Styling | TailwindCSS v4 CDN, JetBrains Mono |
| 3D Rendering | CSS 3D transforms (isometric) |
| Testing | Playwright (headless Chromium) |
| Task Runner | Just |

## Visual Design

Dark teal aesthetic inspired by the Clan network visualizer. Isometric grid with colored blocks, floating monospace labels, integrated debug console. Single dark theme.

## Project Structure

```
hyperspace/
├── Cargo.toml              # single crate, target-gated deps
├── Rocket.toml             # server config
├── Justfile                # just → starts everything
├── src/
│   ├── lib.rs              # SpacetimeDB module (tables + reducers)
│   ├── main.rs             # Rocket server (routes, WS hub, callbacks)
│   └── module_bindings/    # generated client types
├── templates/
│   └── index.html.j2       # single page template
├── static/
│   ├── css/isometric.css   # CSS isometric transforms
│   ├── js/scene.js         # grid interaction + console (~50 lines)
│   └── js/vendor/          # htmx, idiomorph, server-commands
├── tests/e2e/
│   └── hyperspace.spec.ts  # Playwright tests
└── docs/plans/
```

## Design Principles

1. **~500 lines total.** Every line earns its place.
2. **Single template.** One file, rendered declaratively, morphed by idiomorph.
3. **Single WebSocket.** All browser↔server comms through one connection.
4. **HTML-first.** Isometric scene is CSS, not canvas. Morphable.
5. **Simplification passes.** After it works, obsessively reduce without losing function.
