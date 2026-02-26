# Hyperspace Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a real-time shared isometric playground powered by SpacetimeDB, served as an HDA via Rocket + htmx + idiomorph over a single WebSocket.

**Architecture:** SpacetimeDB (Rust Wasm module) holds all state. A Rocket HTTP server connects as a client via the Rust SDK, mirrors tables in memory, re-renders a single minijinja template on every change, and pushes morphed HTML to browsers via WebSocket. CSS 3D transforms render the isometric view. An integrated debug console shows real-time events.

**Tech Stack:**
- SpacetimeDB 2.0 (Rust Wasm module) — tables + reducers
- Rocket 0.5 + rocket_ws — HTTP/WebSocket server
- rocket_dyn_templates + minijinja — server-side templates
- htmx + WS extension + server-commands + idiomorph — WebSocket-driven DOM morphing
- TailwindCSS v4 CDN — styling
- Playwright — self-verification tests
- Just — task runner

---

### Task 1: Project Scaffold

**Files:**
- Create: `Cargo.toml`
- Create: `src/lib.rs`
- Create: `src/main.rs`
- Create: `Justfile`
- Create: `.gitignore`
- Create: `Rocket.toml`

**Step 1: Create Cargo.toml**

```toml
[package]
name = "hyperspace"
version = "0.1.0"
edition = "2024"

[lib]
crate-type = ["cdylib"]

# SpacetimeDB module (Wasm only)
[target.'cfg(target_arch = "wasm32")'.dependencies]
spacetimedb = "2.0"
log = "0.4"

# Rocket server (native only)
[target.'cfg(not(target_arch = "wasm32"))'.dependencies]
rocket = { version = "0.5", features = ["json"] }
rocket_ws = "0.1"
rocket_dyn_templates = { version = "0.2", features = ["minijinja"] }
spacetimedb-sdk = "1.0"
tokio = { version = "1", features = ["full"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
```

**Step 2: Create stub lib.rs**

```rust
//! SpacetimeDB module — compiled to Wasm, runs inside the database.
```

**Step 3: Create stub main.rs**

```rust
#[macro_use]
extern crate rocket;

#[get("/")]
fn index() -> &'static str {
    "hyperspace"
}

#[launch]
fn rocket() -> _ {
    rocket::build().mount("/", routes![index])
}
```

**Step 4: Create Rocket.toml**

```toml
[default]
address = "0.0.0.0"
port = 8080
template_dir = "templates"

[debug]
log_level = "normal"
```

**Step 5: Create .gitignore**

```gitignore
/target
.spacetime/
node_modules/
test-results/
```

**Step 6: Create Justfile**

```just
spacetime := env('HOME') / ".local/bin/spacetime"
module_name := "hyperspace"

# Start SpacetimeDB + publish module + run Rocket server
default: spacetimedb generate
    cargo run

# Ensure SpacetimeDB is installed, running, and module is deployed
spacetimedb:
    #!/usr/bin/env bash
    set -euo pipefail
    command -v "{{spacetime}}" &>/dev/null || \
        (echo "Installing SpacetimeDB..." && curl -sSf https://install.spacetimedb.com | sh)
    if nc -z 127.0.0.1 3000 2>/dev/null; then
        echo "SpacetimeDB already running on port 3000"
    else
        "{{spacetime}}" start 2>/dev/null &
        echo "Waiting for SpacetimeDB..."
        for i in $(seq 1 30); do
            if nc -z 127.0.0.1 3000 2>/dev/null; then break; fi
            sleep 0.5
        done
        if ! nc -z 127.0.0.1 3000 2>/dev/null; then
            echo "ERROR: SpacetimeDB failed to start"
            exit 1
        fi
    fi
    "{{spacetime}}" publish {{module_name}} --project-path . --yes --delete-data

# Regenerate client bindings after module changes
generate:
    "{{spacetime}}" generate --lang rust --project-path . --out-dir src/module_bindings --yes

# Wipe database and redeploy
reset:
    "{{spacetime}}" publish {{module_name}} --project-path . --yes --delete-data

# Run Playwright tests (server must be running)
test:
    npx playwright test

# Lint
check:
    cargo clippy -- -D warnings
    cargo fmt --all -- --check
```

**Step 7: Verify stub compiles**

Run: `cargo check`

Expected: Compiles successfully.

**Step 8: Init git and commit**

```bash
git init
git add Cargo.toml src/lib.rs src/main.rs Justfile .gitignore Rocket.toml
git commit -m "Scaffold project with Cargo.toml, Rocket stub, and Justfile"
```

---

### Task 2: SpacetimeDB Module

**Files:**
- Modify: `src/lib.rs`

**Step 1: Write tables and reducers**

```rust
use spacetimedb::{reducer, Identity, ReducerContext, Table, Timestamp};

// --- Tables ---

#[spacetimedb::table(accessor = scene_object, public)]
pub struct SceneObject {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub grid_x: i32,
    pub grid_y: i32,
    pub color: String,
    pub owner: Identity,
}

#[spacetimedb::table(accessor = user_cursor, public)]
pub struct UserCursor {
    #[primary_key]
    pub identity: Identity,
    pub grid_x: i32,
    pub grid_y: i32,
    pub last_seen: Timestamp,
}

#[spacetimedb::table(accessor = user_info, public)]
pub struct UserInfo {
    #[primary_key]
    pub identity: Identity,
    pub name: String,
    pub color: String,
    pub online: bool,
}

// --- Lifecycle ---

#[reducer(client_connected)]
pub fn client_connected(ctx: &ReducerContext) {
    let colors = ["#22d3ee", "#a78bfa", "#fb923c", "#4ade80", "#f472b6", "#facc15"];
    let idx = ctx.db.user_info().count() as usize % colors.len();

    if let Some(user) = ctx.db.user_info().identity().find(ctx.sender()) {
        ctx.db.user_info().identity().update(UserInfo { online: true, ..user });
    } else {
        ctx.db.user_info().insert(UserInfo {
            identity: ctx.sender(),
            name: format!("User {}", ctx.db.user_info().count() + 1),
            color: colors[idx].to_string(),
            online: true,
        });
    }
}

#[reducer(client_disconnected)]
pub fn client_disconnected(ctx: &ReducerContext) {
    if let Some(user) = ctx.db.user_info().identity().find(ctx.sender()) {
        ctx.db.user_info().identity().update(UserInfo { online: false, ..user });
    }
    ctx.db.user_cursor().identity().delete(ctx.sender());
}

// --- Reducers ---

#[reducer]
pub fn create_object(ctx: &ReducerContext, grid_x: i32, grid_y: i32, color: String) {
    ctx.db.scene_object().insert(SceneObject {
        id: 0,
        grid_x,
        grid_y,
        color,
        owner: ctx.sender(),
    });
}

#[reducer]
pub fn move_object(ctx: &ReducerContext, id: u64, grid_x: i32, grid_y: i32) -> Result<(), String> {
    let obj = ctx.db.scene_object().id().find(id).ok_or("Not found")?;
    if obj.owner != ctx.sender() { return Err("Not owner".into()); }
    ctx.db.scene_object().id().update(SceneObject { grid_x, grid_y, ..obj });
    Ok(())
}

#[reducer]
pub fn delete_object(ctx: &ReducerContext, id: u64) -> Result<(), String> {
    let obj = ctx.db.scene_object().id().find(id).ok_or("Not found")?;
    if obj.owner != ctx.sender() { return Err("Not owner".into()); }
    ctx.db.scene_object().id().delete(id);
    Ok(())
}

#[reducer]
pub fn update_cursor(ctx: &ReducerContext, grid_x: i32, grid_y: i32) {
    let cursor = UserCursor {
        identity: ctx.sender(),
        grid_x,
        grid_y,
        last_seen: ctx.timestamp,
    };
    if ctx.db.user_cursor().identity().find(ctx.sender()).is_some() {
        ctx.db.user_cursor().identity().update(cursor);
    } else {
        ctx.db.user_cursor().insert(cursor);
    }
}

#[reducer]
pub fn set_name(ctx: &ReducerContext, name: String) -> Result<(), String> {
    if name.is_empty() { return Err("Empty name".into()); }
    let user = ctx.db.user_info().identity().find(ctx.sender()).ok_or("Not found")?;
    ctx.db.user_info().identity().update(UserInfo { name, ..user });
    Ok(())
}
```

**Step 2: Verify Wasm compilation**

Run: `rustup target add wasm32-unknown-unknown && cargo build --lib --target wasm32-unknown-unknown`

Expected: Compiles successfully.

**Step 3: Deploy to local SpacetimeDB**

Run: `just spacetimedb`

Expected: Module publishes. Verify with:
```bash
~/.local/bin/spacetime call hyperspace create_object '[3, 2, "#22d3ee"]'
~/.local/bin/spacetime sql hyperspace "SELECT * FROM scene_object"
```

**Step 4: Generate client bindings**

Run: `just generate`

Expected: `src/module_bindings/` directory created with generated Rust types.

**Step 5: Commit**

```bash
git add src/lib.rs src/module_bindings/
git commit -m "Add SpacetimeDB module and generate client bindings"
```

---

### Task 3: Rocket Server with SpacetimeDB Connection

**Files:**
- Modify: `src/main.rs`

**Step 1: Write the Rocket server with SpacetimeDB client**

```rust
#[macro_use]
extern crate rocket;

mod module_bindings;

use module_bindings::DbConnection;
use rocket::fs::FileServer;
use rocket::State;
use rocket_dyn_templates::{context, Template};
use spacetimedb_sdk::DbContext;
use std::sync::Arc;
use tokio::sync::broadcast;

struct App {
    db: DbConnection,
    tx: broadcast::Sender<String>,
}

#[get("/")]
fn index(app: &State<App>) -> Template {
    let objects: Vec<_> = app.db.db().scene_object().iter()
        .map(|o| context! { id => o.id, grid_x => o.grid_x, grid_y => o.grid_y, color => &o.color })
        .collect();
    let users: Vec<_> = app.db.db().user_info().iter()
        .map(|u| context! { name => &u.name, color => &u.color, online => u.online })
        .collect();

    Template::render("index", context! {
        objects => objects,
        users => users,
        grid_size => 8,
    })
}

#[launch]
fn rocket() -> _ {
    let (tx, _) = broadcast::channel::<String>(256);

    let db = DbConnection::builder()
        .with_uri("http://localhost:3000")
        .with_module_name("hyperspace")
        .on_connect(|_ctx, identity, _token| {
            println!("Connected to SpacetimeDB as {identity:?}");
        })
        .on_connect_error(|err| {
            eprintln!("SpacetimeDB connection error: {err}");
            std::process::exit(1);
        })
        .build()
        .expect("Failed to connect to SpacetimeDB");

    db.subscription_builder()
        .on_applied(|ctx| {
            println!(
                "Subscribed — {} objects, {} users",
                ctx.db().scene_object().count(),
                ctx.db().user_info().count(),
            );
        })
        .subscribe_to_all_tables();

    // Run SDK event loop in background
    let db_bg = db.clone();
    tokio::spawn(async move { db_bg.run_async().await.unwrap() });

    let app = App { db, tx };

    rocket::build()
        .manage(app)
        .attach(Template::fairing())
        .mount("/", routes![index])
        .mount("/static", FileServer::from("static"))
}
```

**Step 2: Create a minimal template**

Create `templates/index.html.j2`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Hyperspace</title>
</head>
<body>
  <h1>Hyperspace</h1>
  <p>{{ objects | length }} objects, {{ users | length }} users</p>
  <ul>
  {% for obj in objects %}
    <li style="color: {{ obj.color }}">Block at ({{ obj.grid_x }}, {{ obj.grid_y }})</li>
  {% endfor %}
  </ul>
</body>
</html>
```

Note: minijinja uses `.j2` extension by default with `rocket_dyn_templates`. Verify during implementation — it may use `.html.j2` or `.j2`. Check `rocket_dyn_templates` minijinja docs for the expected file extension.

**Step 3: Verify end-to-end**

Run: `just` (starts SpacetimeDB + publishes module + runs Rocket)

Open: http://localhost:8080

Expected: Shows "0 objects, 0 users" (or however many exist from prior CLI testing).

Insert via CLI: `~/.local/bin/spacetime call hyperspace create_object '[1, 1, "#22d3ee"]'`

Refresh page: Should show 1 object.

**Step 4: Commit**

```bash
git add src/main.rs templates/
git commit -m "Wire Rocket to SpacetimeDB with template rendering"
```

---

### Task 4: Full HTML Template + Tailwind + Debug Console

**Files:**
- Modify: `templates/index.html.j2`
- Create: `static/css/isometric.css`
- Create: `static/js/scene.js`

**Step 1: Write the full template**

Replace `templates/index.html.j2`:

```html
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Hyperspace</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: {
            surface: { DEFAULT: '#1a2332', light: '#243447', lighter: '#2d4055' },
          },
          fontFamily: { mono: ['JetBrains Mono', 'monospace'] },
        }
      }
    }
  </script>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/static/css/isometric.css">
  <script src="/static/js/vendor/htmx.min.js"></script>
  <script src="/static/js/vendor/htmx-ext-ws.js"></script>
  <script src="/static/js/vendor/idiomorph-ext.min.js"></script>
  <script src="/static/js/vendor/server-commands.js"></script>
</head>
<body class="bg-surface text-gray-200 font-mono h-screen flex overflow-hidden"
      hx-ext="ws,server-commands,morph">

  {# === Sidebar === #}
  <aside class="w-56 bg-surface-light flex flex-col border-r border-white/10 shrink-0">
    <div class="p-4 border-b border-white/10">
      <h1 class="text-lg font-bold text-white tracking-tight">Hyperspace</h1>
      <p class="text-[10px] text-gray-500 mt-0.5">real-time shared space</p>
    </div>

    <div class="p-3 flex-1 overflow-y-auto">
      <div class="text-[10px] uppercase tracking-widest text-gray-500 mb-2 px-1">Online</div>
      {% for user in users %}{% if user.online %}
      <div class="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-white/5">
        <span class="w-2 h-2 rounded-full shrink-0" style="background:{{ user.color }}"></span>
        <span class="text-sm truncate">{{ user.name }}</span>
      </div>
      {% endif %}{% endfor %}

      <div class="text-[10px] uppercase tracking-widest text-gray-500 mt-4 mb-2 px-1">
        Blocks · {{ objects | length }}
      </div>
      {% for obj in objects %}
      <div class="flex items-center justify-between px-2 py-1 rounded hover:bg-white/5 text-xs group">
        <div class="flex items-center gap-2">
          <span class="w-2 h-2 rounded-sm shrink-0" style="background:{{ obj.color }}"></span>
          <span class="text-gray-400">({{ obj.grid_x }},{{ obj.grid_y }})</span>
        </div>
        <button ws-send name="action" value="delete:{{ obj.id }}"
                class="text-gray-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition">×</button>
      </div>
      {% endfor %}
    </div>
  </aside>

  {# === Main === #}
  <main class="flex-1 flex flex-col min-w-0" ws-connect="/ws">

    {# Isometric viewport #}
    <div class="flex-1 relative overflow-hidden bg-surface" id="grid-viewport">
      <div class="iso-scene" id="iso-scene">
        <div class="iso-grid">
          {% for row in range(end=grid_size) %}{% for col in range(end=grid_size) %}
          <div class="iso-cell" data-x="{{ col }}" data-y="{{ row }}"
               style="--col:{{ col }};--row:{{ row }}"></div>
          {% endfor %}{% endfor %}
        </div>
        {% for obj in objects %}
        <div class="iso-block" style="--col:{{ obj.grid_x }};--row:{{ obj.grid_y }};--color:{{ obj.color }}"></div>
        {% endfor %}
      </div>
    </div>

    {# Debug console #}
    <div class="h-40 bg-surface-light border-t border-white/10 flex flex-col shrink-0">
      <div class="flex items-center justify-between px-3 py-1 border-b border-white/10">
        <span class="text-[10px] uppercase tracking-widest text-gray-500">Console</span>
        <div class="flex items-center gap-1.5">
          <span class="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse"></span>
          <span class="text-[10px] text-gray-500">live</span>
        </div>
      </div>
      <div id="console-log" class="flex-1 overflow-y-auto p-2 text-[11px] leading-relaxed space-y-px"></div>
    </div>

    {# Toolbar #}
    <div class="flex items-center gap-2 px-3 py-2 border-t border-white/10 bg-surface shrink-0">
      <button ws-send name="action" value="create"
              class="px-3 py-1 text-xs rounded bg-cyan-500/20 text-cyan-400 hover:bg-cyan-500/30 transition">
        + Block
      </button>
      <input ws-send name="set_name" placeholder="Set name..."
             class="bg-surface-lighter border border-white/10 rounded px-2 py-1 text-xs
                    placeholder-gray-600 focus:outline-none focus:border-cyan-500/50 w-36">
    </div>
  </main>

</body>
<script src="/static/js/scene.js" type="module"></script>
</html>
```

**Step 2: Create isometric CSS**

Create `static/css/isometric.css`:

```css
.iso-scene {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
}

.iso-grid {
  display: grid;
  transform: rotateX(60deg) rotateZ(-45deg);
  transform-style: preserve-3d;
}

.iso-cell {
  width: 64px;
  height: 64px;
  border: 1px solid rgba(255,255,255,0.04);
  background: rgba(255,255,255,0.015);
  grid-column: calc(var(--col) + 1);
  grid-row: calc(var(--row) + 1);
  cursor: pointer;
  transition: background 0.15s;
}

.iso-cell:hover {
  background: rgba(34,211,238,0.08);
  border-color: rgba(34,211,238,0.15);
}

.iso-block {
  position: absolute;
  width: 64px;
  height: 64px;
  background: var(--color);
  opacity: 0.8;
  border: 1px solid rgba(255,255,255,0.15);
  box-shadow: 0 0 24px color-mix(in srgb, var(--color) 25%, transparent);
  transform: rotateX(60deg) rotateZ(-45deg);
  left: calc(var(--col) * 64px);
  top: calc(var(--row) * 64px);
  pointer-events: none;
  transition: left 0.15s ease, top 0.15s ease;
}

.iso-cursor {
  position: absolute;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--color);
  border: 2px solid white;
  transform: rotateX(60deg) rotateZ(-45deg);
  left: calc(var(--col) * 64px + 27px);
  top: calc(var(--row) * 64px + 27px);
  pointer-events: none;
  transition: left 0.1s, top 0.1s;
  z-index: 10;
}

.iso-label {
  position: absolute;
  bottom: calc(100% + 4px);
  left: 50%;
  transform: translateX(-50%) rotateZ(45deg) rotateX(-60deg);
  white-space: nowrap;
  font-size: 9px;
  background: rgba(26,35,50,0.9);
  padding: 1px 5px;
  border-radius: 3px;
  border: 1px solid rgba(255,255,255,0.1);
  color: white;
  font-family: 'JetBrains Mono', monospace;
}
```

**Step 3: Create scene.js**

Create `static/js/scene.js`:

```javascript
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
```

**Step 4: Verify the styled page loads**

Run: `just`

Open: http://localhost:8080

Expected: Dark UI with sidebar, isometric grid, debug console, toolbar. No data yet but layout is correct.

**Step 5: Commit**

```bash
git add templates/ static/
git commit -m "Add full HTML template with Tailwind, isometric grid, and debug console"
```

---

### Task 5: Vendor htmx Extensions

**Files:**
- Create: `static/js/vendor/htmx.min.js`
- Create: `static/js/vendor/htmx-ext-ws.js`
- Create: `static/js/vendor/idiomorph-ext.min.js`
- Create: `static/js/vendor/server-commands.js`

**Step 1: Download dependencies**

```bash
mkdir -p static/js/vendor
curl -sL https://unpkg.com/htmx.org/dist/htmx.min.js -o static/js/vendor/htmx.min.js
curl -sL https://unpkg.com/htmx-ext-ws/ws.js -o static/js/vendor/htmx-ext-ws.js
curl -sL https://unpkg.com/idiomorph/dist/idiomorph-ext.min.js -o static/js/vendor/idiomorph-ext.min.js
```

**Step 2: Get server-commands from your fork**

```bash
curl -sL https://raw.githubusercontent.com/scriptogre/htmx-extensions/feature/server-commands/src/server-commands/server-commands.js \
  -o static/js/vendor/server-commands.js
```

If URL fails, copy from your local clone of the htmx-extensions fork.

**Step 3: Verify no 404s in browser**

Open: http://localhost:8080, check DevTools Network tab. All JS files should load.

**Step 4: Commit**

```bash
git add static/js/vendor/
git commit -m "Vendor htmx, WS extension, idiomorph, and server-commands"
```

---

### Task 6: WebSocket Broadcast Hub

This is the core real-time feature. Rocket's `rocket_ws` with `WebSocket::channel()` gives us a split sender/receiver pair, allowing us to push server-initiated messages.

**Files:**
- Modify: `src/main.rs`

**Step 1: Add WebSocket route and broadcast logic**

Update `src/main.rs` to add WebSocket handling, broadcast on table changes, and handle incoming client messages:

```rust
#[macro_use]
extern crate rocket;

mod module_bindings;

use module_bindings::DbConnection;
use rocket::fs::FileServer;
use rocket::State;
use rocket_dyn_templates::{context, Template};
use rocket_ws as ws;
use serde_json::Value;
use spacetimedb_sdk::DbContext;
use tokio::sync::broadcast;

const GRID_SIZE: i32 = 8;

struct App {
    db: DbConnection,
    tx: broadcast::Sender<String>,
}

impl App {
    fn render_body(&self) -> String {
        // Build context from live SpacetimeDB mirror
        let objects: Vec<_> = self.db.db().scene_object().iter()
            .map(|o| serde_json::json!({
                "id": o.id, "grid_x": o.grid_x, "grid_y": o.grid_y, "color": o.color
            }))
            .collect();
        let users: Vec<_> = self.db.db().user_info().iter()
            .map(|u| serde_json::json!({
                "name": u.name, "color": u.color, "online": u.online
            }))
            .collect();

        // Use minijinja directly for body rendering (outside Rocket's Template responder)
        let mut env = minijinja::Environment::new();
        env.set_source(minijinja::Source::from_path("templates"));
        let tmpl = env.get_template("index.html.j2").unwrap();
        tmpl.render(minijinja::context! {
            objects => objects,
            users => users,
            grid_size => GRID_SIZE,
        }).unwrap()
    }

    fn broadcast_morph(&self) {
        let body = self.render_body();
        let _ = self.tx.send(format!("<htmx target=\"body\" swap=\"morph\">{body}</htmx>"));
    }

    fn broadcast_console(&self, msg: &str, color: &str) {
        let escaped = msg.replace('\"', "\\\"");
        let _ = self.tx.send(format!(
            "<htmx trigger='{{\"console-log\": {{\"msg\": \"{escaped}\", \"color\": \"{color}\"}}}}'></htmx>"
        ));
    }

    fn broadcast_cursors(&self) {
        let data: Vec<_> = self.db.db().user_cursor().iter().map(|c| {
            let u = self.db.db().user_info().identity().find(c.identity);
            serde_json::json!({
                "grid_x": c.grid_x, "grid_y": c.grid_y,
                "color": u.as_ref().map(|u| u.color.as_str()).unwrap_or("#888"),
                "name": u.as_ref().map(|u| u.name.as_str()).unwrap_or("?"),
            })
        }).collect();
        let json = serde_json::to_string(&data).unwrap();
        let _ = self.tx.send(format!(
            "<htmx trigger='{{\"cursor-update\": {{\"cursors\": {json}}}}}'></htmx>"
        ));
    }
}

#[get("/")]
fn index(app: &State<App>) -> Template {
    let objects: Vec<_> = app.db.db().scene_object().iter()
        .map(|o| context! { id => o.id, grid_x => o.grid_x, grid_y => o.grid_y, color => &o.color })
        .collect();
    let users: Vec<_> = app.db.db().user_info().iter()
        .map(|u| context! { name => &u.name, color => &u.color, online => u.online })
        .collect();
    Template::render("index", context! { objects, users, grid_size => GRID_SIZE })
}

#[get("/ws")]
fn websocket(ws: ws::WebSocket, app: &State<App>) -> ws::Channel<'static> {
    let mut rx = app.tx.subscribe();
    let db = app.db.clone();

    ws.channel(move |mut stream| Box::pin(async move {
        use rocket_ws::stream::StreamExt;
        use rocket_ws::Message;

        loop {
            tokio::select! {
                // Server → browser: broadcast messages
                Ok(msg) = rx.recv() => {
                    if stream.send(Message::Text(msg)).await.is_err() { break; }
                }
                // Browser → server: user actions
                Some(Ok(Message::Text(text))) = stream.next() => {
                    if let Ok(data) = serde_json::from_str::<Value>(&text) {
                        handle_action(&db, &data);
                    }
                }
                else => break,
            }
        }
        Ok(())
    }))
}

fn handle_action(db: &DbConnection, data: &Value) {
    match data.get("action").and_then(|v| v.as_str()) {
        Some("create") => {
            let color = db.db().user_info().iter().next()
                .map(|u| u.color.clone()).unwrap_or("#22d3ee".into());
            let _ = db.reducers().create_object(GRID_SIZE / 2, GRID_SIZE / 2, color);
        }
        Some("cursor") => {
            if let (Some(x), Some(y)) = (
                data.get("x").and_then(|v| v.as_str()).and_then(|s| s.parse().ok()),
                data.get("y").and_then(|v| v.as_str()).and_then(|s| s.parse().ok()),
            ) {
                let _ = db.reducers().update_cursor(x, y);
            }
        }
        Some(a) if a.starts_with("delete:") => {
            if let Ok(id) = a[7..].parse::<u64>() {
                let _ = db.reducers().delete_object(id);
            }
        }
        Some("create_at") => {
            if let (Some(x), Some(y)) = (
                data.get("x").and_then(|v| v.as_str()).and_then(|s| s.parse().ok()),
                data.get("y").and_then(|v| v.as_str()).and_then(|s| s.parse().ok()),
            ) {
                let color = db.db().user_info().iter().next()
                    .map(|u| u.color.clone()).unwrap_or("#22d3ee".into());
                let _ = db.reducers().create_object(x, y, color);
            }
        }
        _ => {}
    }

    if let Some(name) = data.get("set_name").and_then(|v| v.as_str()) {
        if !name.is_empty() {
            let _ = db.reducers().set_name(name.to_string());
        }
    }
}

#[launch]
fn rocket() -> _ {
    let (tx, _) = broadcast::channel::<String>(256);

    let db = DbConnection::builder()
        .with_uri("http://localhost:3000")
        .with_module_name("hyperspace")
        .on_connect(|_ctx, identity, _token| {
            println!("Connected to SpacetimeDB as {identity:?}");
        })
        .on_connect_error(|err| {
            eprintln!("SpacetimeDB error: {err}");
            std::process::exit(1);
        })
        .build()
        .expect("Failed to connect");

    db.subscription_builder()
        .on_applied(|ctx| {
            println!("Subscribed — {} objects, {} users",
                ctx.db().scene_object().count(), ctx.db().user_info().count());
        })
        .subscribe_to_all_tables();

    let db_bg = db.clone();
    tokio::spawn(async move { db_bg.run_async().await.unwrap() });

    // Register table change callbacks → broadcast to browsers
    let app = App { db: db.clone(), tx };

    // Note: These closures capture `app` clones. The SpacetimeDB SDK fires them
    // whenever the local mirror updates. We re-render + broadcast.
    let a = App { db: db.clone(), tx: app.tx.clone() };
    db.db().scene_object().on_insert(move |_ctx, obj| {
        a.broadcast_morph();
        a.broadcast_console(&format!("block created at ({},{})", obj.grid_x, obj.grid_y), "text-cyan-400");
    });
    let a = App { db: db.clone(), tx: app.tx.clone() };
    db.db().scene_object().on_delete(move |_ctx, obj| {
        a.broadcast_morph();
        a.broadcast_console(&format!("block deleted at ({},{})", obj.grid_x, obj.grid_y), "text-orange-400");
    });
    let a = App { db: db.clone(), tx: app.tx.clone() };
    db.db().scene_object().on_update(move |_ctx, _old, new| {
        a.broadcast_morph();
        a.broadcast_console(&format!("block moved to ({},{})", new.grid_x, new.grid_y), "text-purple-400");
    });
    let a = App { db: db.clone(), tx: app.tx.clone() };
    db.db().user_info().on_insert(move |_ctx, user| {
        a.broadcast_morph();
        a.broadcast_console(&format!("{} joined", user.name), "text-green-400");
    });
    let a = App { db: db.clone(), tx: app.tx.clone() };
    db.db().user_info().on_update(move |_ctx, old, new| {
        if old.online != new.online {
            a.broadcast_morph();
            let status = if new.online { "online" } else { "offline" };
            a.broadcast_console(&format!("{} went {status}", new.name), "text-gray-400");
        }
        if old.name != new.name {
            a.broadcast_morph();
            a.broadcast_console(&format!("renamed to {}", new.name), "text-gray-400");
        }
    });
    let a = App { db: db.clone(), tx: app.tx.clone() };
    db.db().user_cursor().on_insert(move |_ctx, _c| { a.broadcast_cursors(); });
    let a = App { db: db.clone(), tx: app.tx.clone() };
    db.db().user_cursor().on_update(move |_ctx, _old, _new| { a.broadcast_cursors(); });

    rocket::build()
        .manage(app)
        .attach(Template::fairing())
        .mount("/", routes![index, websocket])
        .mount("/static", FileServer::from("static"))
}
```

**Important implementation notes:**
- The `render_body` method creates a fresh minijinja `Environment` each call. This is not ideal for performance. During implementation, consider caching the environment or using `rocket_dyn_templates`' internal engine. For the PoC this is fine.
- The `App` struct needs to be `Send + Sync` for Rocket's `manage()`. `DbConnection` is `Clone + Send + Sync`, and `broadcast::Sender` is too. Should work.
- The `ws.channel()` API may have slightly different ergonomics in rocket_ws 0.1 than shown. Adjust based on actual API during implementation.

**Step 2: Verify real-time updates**

Run: `just`

Open two browser tabs to http://localhost:8080

In one tab, click "+ Block"

Expected:
- Block appears in both tabs' sidebars without refresh
- Debug console in both tabs shows "block created at (4,4)"
- Isometric grid shows the block

**Step 3: Test via CLI too**

```bash
~/.local/bin/spacetime call hyperspace create_object '[2, 3, "#a78bfa"]'
```

Expected: Both tabs update with the new purple block.

**Step 4: Commit**

```bash
git add src/main.rs
git commit -m "Add WebSocket broadcast with real-time morph and console events"
```

---

### Task 7: Playwright Test Setup

**Files:**
- Create: `package.json`
- Create: `playwright.config.ts`
- Create: `tests/e2e/hyperspace.spec.ts`

**Step 1: Initialize Playwright**

```bash
npm init -y
npm install -D @playwright/test
npx playwright install chromium
```

**Step 2: Create playwright.config.ts**

```typescript
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 15_000,
  use: {
    baseURL: 'http://localhost:8080',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
});
```

**Step 3: Create e2e tests**

Create `tests/e2e/hyperspace.spec.ts`:

```typescript
import { test, expect } from '@playwright/test';

test('page loads with layout', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('text=Hyperspace')).toBeVisible();
  await expect(page.locator('.iso-grid')).toBeVisible();
  await expect(page.locator('#console-log')).toBeVisible();
});

test('websocket connects', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#console-log')).toContainText('connected', { timeout: 5000 });
});

test('add block button works', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#console-log:has-text("connected")');
  await page.click('button:has-text("+ Block")');
  await expect(page.locator('.iso-block')).toBeVisible({ timeout: 3000 });
});

test('multi-user sync', async ({ browser }) => {
  const [c1, c2] = await Promise.all([browser.newContext(), browser.newContext()]);
  const [p1, p2] = await Promise.all([c1.newPage(), c2.newPage()]);
  await Promise.all([p1.goto('http://localhost:8080'), p2.goto('http://localhost:8080')]);
  await Promise.all([
    p1.waitForSelector('#console-log:has-text("connected")'),
    p2.waitForSelector('#console-log:has-text("connected")'),
  ]);

  // Place block in page 1
  await p1.click('.iso-cell[data-x="2"][data-y="2"]');

  // Verify in page 2
  await expect(p2.locator('text=(2,2)')).toBeVisible({ timeout: 5000 });

  await Promise.all([c1.close(), c2.close()]);
});

test('screenshot', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('.iso-grid');
  await page.waitForTimeout(500);
  await page.screenshot({ path: 'test-results/hyperspace.png', fullPage: true });
});
```

**Step 4: Run tests (server must be running in another terminal)**

```bash
npx playwright test
```

Expected: All tests pass.

**Step 5: Commit**

```bash
git add package.json playwright.config.ts tests/
git commit -m "Add Playwright e2e tests"
```

---

### Task 8: Visual Polish (CSS Iteration)

**Files:**
- Modify: `static/css/isometric.css`

**Step 1: Take a screenshot and iterate**

```bash
npx playwright test -g "screenshot"
open test-results/hyperspace.png
```

Review and adjust CSS until:
- Grid forms a clean isometric diamond pattern centered in the viewport
- Blocks sit cleanly on grid cells with colored glow
- The overall feel matches the dark teal Clan-like aesthetic from the reference images

This task is iterative — adjust values, take screenshot, repeat.

Key CSS tuning points:
- `rotateX` / `rotateZ` angles for the isometric projection
- Cell size, border opacity
- Block positioning (must align with cells)
- Scene centering in viewport
- Shadow/glow intensity

**Step 2: Commit when satisfied**

```bash
git add static/css/isometric.css
git commit -m "Polish isometric CSS to match target aesthetic"
```

---

### Task 9: Simplification Pass 1 — Code

**Files:** All `.rs` and `.js` files

**Step 1: Review every file**

For each file, ask:
- Every import used?
- Every function called?
- Can any logic be shorter without losing clarity?
- Unnecessary abstractions?

Targets:
- `src/lib.rs` — ~80 lines
- `src/main.rs` — ~200 lines
- `static/js/scene.js` — ~50 lines
- `static/css/isometric.css` — ~60 lines
- `templates/index.html.j2` — ~100 lines
- **Total: ~500 lines of application code**

**Step 2: Run tests**

```bash
npx playwright test
```

All must pass.

**Step 3: Commit**

```bash
git add -A
git commit -m "Simplification pass: reduce and clarify"
```

---

### Task 10: Simplification Pass 2 — Template & CSS

**Files:** `templates/index.html.j2`, `static/css/isometric.css`

**Step 1: Minimize template**

- Remove unnecessary wrapper divs
- Simplify Tailwind class lists
- Ensure every element earns its place

**Step 2: Minimize CSS**

- Replace CSS with Tailwind utilities where possible
- Remove unused rules

**Step 3: Run tests + screenshot**

```bash
npx playwright test
```

**Step 4: Commit**

```bash
git add -A
git commit -m "Final simplification: minimal template and CSS"
```

---

### Task 11: Final Verification + Screenshot

**Step 1: Full test run**

```bash
npx playwright test
```

All pass.

**Step 2: Line count check**

```bash
find src templates static -name '*.rs' -o -name '*.js' -o -name '*.css' -o -name '*.j2' | \
  grep -v vendor | xargs wc -l | sort -n
```

Total should be around 500 lines.

**Step 3: Final screenshot**

```bash
npx playwright test -g "screenshot"
```

Review `test-results/hyperspace.png`. This is the demo screenshot.

**Step 4: Commit**

```bash
git add -A
git commit -m "Final verification: all tests pass, demo ready"
```

---

## File Summary

| File | Purpose | ~Lines |
|------|---------|--------|
| `Cargo.toml` | Dependencies (target-gated) | 25 |
| `Rocket.toml` | Server config | 8 |
| `Justfile` | Task runner | 35 |
| `src/lib.rs` | SpacetimeDB module (tables + reducers) | 80 |
| `src/main.rs` | Rocket server (routes, WS, broadcast) | 200 |
| `src/module_bindings/` | Generated client types | (auto) |
| `templates/index.html.j2` | Single page template | 100 |
| `static/css/isometric.css` | CSS isometric transforms | 60 |
| `static/js/scene.js` | Grid interaction + console | 50 |
| `static/js/vendor/` | htmx, idiomorph, server-commands | (vendored) |
| `tests/e2e/hyperspace.spec.ts` | Playwright tests | 50 |

**Total application code: ~500 lines.**

## Open Risks

1. **SpacetimeDB Rust client SDK + Tokio compatibility**: The SDK claims Tokio support but we need to verify `run_async()` works inside Rocket's Tokio runtime. If issues arise, fall back to `run_threaded()`.

2. **rocket_ws channel API**: The exact `ws.channel()` API and its interaction with `tokio::select!` needs verification. May need `futures::StreamExt` instead of `rocket_ws::stream::StreamExt`.

3. **rocket_dyn_templates minijinja feature**: Verify the template file extension (`.j2`, `.html.j2`, or `.jinja`) that minijinja expects. Check docs during implementation.

4. **Render body outside Rocket context**: The `broadcast_morph` callbacks need to render templates outside of a Rocket request context. Using raw minijinja directly (not `rocket_dyn_templates::Template`) may be needed for this. The plan accounts for this.

5. **server-commands + htmx core PR**: The extension works for swap and trigger, which is all we need. Navigation features (redirect, push-url) won't work without the core PR, but we don't use them.

6. **Single crate `#[cfg]` gating**: If `spacetime publish` or `cargo build --lib --target wasm32` has issues with the native deps in Cargo.toml, split into a Cargo workspace as fallback.
