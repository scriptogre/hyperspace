# WebSocket Broadcast Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace HTTP POST mutations with WebSocket-based reducer calls, broadcasting server-rendered HTML to all clients via SpacetimeDB event tables.

**Architecture:** Reducers mutate state then render the minijinja template per connected user, inserting the HTML into an event table. SpacetimeDB pushes each row to the matching client (via RLS). A custom htmx extension receives the HTML and morphs the DOM with idiomorph. Initial page load stays as HTTP GET.

**Tech Stack:** SpacetimeDB (Rust wasm module), minijinja templates, SpacetimeDB TypeScript SDK (IIFE bundle via Vite), custom htmx extension, idiomorph.

---

### Task 1: Refactor models to use Identity instead of u64

The User table currently uses `id: u64` which was set manually. With WebSocket connections, SpacetimeDB provides an `Identity` per client via `ctx.sender`. All tables referencing users must switch to `Identity`.

**Files:**
- Modify: `src/models.rs`

**Step 1: Update imports and User table**

```rust
use spacetimedb::{Identity, ReducerContext, SpacetimeType, Timestamp};
use spacetimedb::rand::Rng;
```

Change `User` table:
```rust
#[spacetimedb::table(accessor = user, public)]
pub struct User {
    #[primary_key]
    pub identity: Identity,
    pub name: String,
    pub color: Color,
    pub online: bool,
}
```

**Step 2: Update Brick, Cursor, Event tables**

```rust
#[spacetimedb::table(accessor = brick, public)]
pub struct Brick {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub position: Position,
    pub color: Color,
    pub dragged_by: Option<Identity>,
}

#[spacetimedb::table(accessor = cursor, public)]
pub struct Cursor {
    #[primary_key]
    pub identity: Identity,
    pub position: Position,
}

#[spacetimedb::table(accessor = event, public)]
pub struct Event {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub kind: EventKind,
    pub identity: Identity,
    pub brick_id: Option<u64>,
    pub timestamp: Timestamp,
}
```

**Step 3: Add HtmlBroadcast event table**

Enable the unstable feature in `Cargo.toml`:
```toml
spacetimedb = { path = "../SpacetimeDB/crates/bindings", features = ["unstable"] }
```

Add to `src/models.rs`:
```rust
use spacetimedb::client_visibility_filter::Filter;

#[spacetimedb::table(accessor = html_broadcast, public, event)]
pub struct HtmlBroadcast {
    pub identity: Identity,
    pub html: String,
}

#[spacetimedb::client_visibility_filter]
const BROADCAST_FILTER: Filter = Filter::Sql(
    "SELECT * FROM html_broadcast WHERE html_broadcast.identity = :sender"
);
```

**Step 4: Verify build**

Run: `cargo build --lib --target wasm32-unknown-unknown --release`
Expected: Fails — reducers.rs and routes.rs still reference old field names. That's expected, we fix them next.

**Step 5: Commit**
```
git add Cargo.toml src/models.rs
git commit -m "Refactor models: Identity keys, add HtmlBroadcast event table with RLS"
```

---

### Task 2: Refactor reducers to use ctx.sender and add lifecycle hooks

Remove explicit `user_id` parameters from all reducers. Use `ctx.sender` (Identity) instead. Replace `connect_user`/`disconnect_user` with `#[reducer(client_connected)]`/`#[reducer(client_disconnected)]` lifecycle hooks.

**Files:**
- Modify: `src/reducers.rs`

**Step 1: Update imports and helper**

```rust
use spacetimedb::{reducer, Identity, ReducerContext, Table};
use crate::models::*;

fn restack_cell(ctx: &ReducerContext, x: i32, y: i32) {
    let mut bricks: Vec<_> = ctx.db.brick().iter()
        .filter(|b| b.position.x == x && b.position.y == y)
        .collect();
    bricks.sort_by_key(|b| b.position.z);
    for (i, brick) in bricks.into_iter().enumerate() {
        let new_z = i as i32;
        if brick.position.z != new_z {
            ctx.db.brick().id().delete(brick.id);
            ctx.db.brick().insert(Brick {
                position: Position { x, y, z: new_z },
                ..brick
            });
        }
    }
}
```

**Step 2: Replace lifecycle reducers**

```rust
#[reducer(client_connected)]
pub fn on_connect(ctx: &ReducerContext) {
    let identity = ctx.sender;
    if let Some(existing) = ctx.db.user().identity().find(&identity) {
        ctx.db.user().identity().update(User { online: true, ..existing });
    } else {
        let name = format!("User {}", ctx.db.user().count() + 1);
        ctx.db.user().insert(User {
            identity,
            name,
            color: Color::random(ctx),
            online: true,
        });
    }
    log_event(ctx, EventKind::UserConnected, None);
    broadcast(ctx);
}

#[reducer(client_disconnected)]
pub fn on_disconnect(ctx: &ReducerContext) {
    let identity = ctx.sender;
    if let Some(existing) = ctx.db.user().identity().find(&identity) {
        ctx.db.user().identity().update(User { online: false, ..existing });
    }
    if ctx.db.cursor().identity().find(&identity).is_some() {
        ctx.db.cursor().identity().delete(&identity);
    }
    for brick in ctx.db.brick().iter()
        .filter(|b| b.dragged_by.as_ref() == Some(&identity))
        .collect::<Vec<_>>()
    {
        ctx.db.brick().id().update(Brick { dragged_by: None, ..brick });
    }
    log_event(ctx, EventKind::UserDisconnected, None);
    broadcast(ctx);
}
```

**Step 3: Refactor all other reducers**

Remove `user_id` parameter from all reducers, use `ctx.sender`:

```rust
#[reducer]
pub fn create_brick(ctx: &ReducerContext, x: i32, y: i32) {
    let z = ctx.db.brick().iter()
        .filter(|b| b.position.x == x && b.position.y == y)
        .count() as i32;
    if z >= 5 { return; }
    let color = ctx.db.user().identity().find(&ctx.sender)
        .map(|u| u.color)
        .unwrap_or(Color::Cyan);
    ctx.db.brick().insert(Brick {
        id: 0,
        position: Position { x, y, z },
        color,
        dragged_by: None,
    });
    log_event(ctx, EventKind::BrickCreated, None);
    broadcast(ctx);
}

#[reducer]
pub fn delete_brick(ctx: &ReducerContext, brick_id: u64) -> Result<(), String> {
    ctx.db.brick().id().find(brick_id).ok_or("Not found")?;
    ctx.db.brick().id().delete(brick_id);
    log_event(ctx, EventKind::BrickDeleted, Some(brick_id));
    broadcast(ctx);
    Ok(())
}

#[reducer]
pub fn set_name(ctx: &ReducerContext, name: String) -> Result<(), String> {
    if name.is_empty() { return Err("Empty name".into()); }
    let user = ctx.db.user().identity().find(ctx.sender).ok_or("Not found")?;
    ctx.db.user().identity().update(User { name, ..user });
    broadcast(ctx);
    Ok(())
}

#[reducer]
pub fn set_color(ctx: &ReducerContext, color: Color) -> Result<(), String> {
    let user = ctx.db.user().identity().find(ctx.sender).ok_or("Not found")?;
    ctx.db.user().identity().update(User { color, ..user });
    broadcast(ctx);
    Ok(())
}

#[reducer]
pub fn update_cursor(ctx: &ReducerContext, x: i32, y: i32, z: i32) {
    let cursor = Cursor { identity: ctx.sender, position: Position { x, y, z } };
    if ctx.db.cursor().identity().find(&ctx.sender).is_some() {
        ctx.db.cursor().identity().update(cursor);
    } else {
        ctx.db.cursor().insert(cursor);
    }
    broadcast(ctx);
}

#[reducer]
pub fn start_drag(ctx: &ReducerContext, brick_id: u64) -> Result<(), String> {
    let brick = ctx.db.brick().id().find(brick_id).ok_or("Not found")?;
    if brick.dragged_by.is_some() { return Err("Already being dragged".into()); }
    ctx.db.brick().id().update(Brick { dragged_by: Some(ctx.sender), ..brick });
    log_event(ctx, EventKind::DragStarted, Some(brick_id));
    broadcast(ctx);
    Ok(())
}

#[reducer]
pub fn end_drag(ctx: &ReducerContext) {
    for brick in ctx.db.brick().iter()
        .filter(|b| b.dragged_by.as_ref() == Some(&ctx.sender))
        .collect::<Vec<_>>()
    {
        ctx.db.brick().id().update(Brick { dragged_by: None, ..brick });
        log_event(ctx, EventKind::DragEnded, Some(brick.id));
    }
    broadcast(ctx);
}

#[reducer]
pub fn move_brick(ctx: &ReducerContext, brick_id: u64, x: i32, y: i32) {
    if let Some(brick) = ctx.db.brick().id().find(brick_id) {
        if brick.dragged_by.as_ref() != Some(&ctx.sender) { return; }
        let src_x = brick.position.x;
        let src_y = brick.position.y;
        let new_z = ctx.db.brick().iter()
            .filter(|b| b.position.x == x && b.position.y == y)
            .count() as i32;
        ctx.db.brick().id().delete(brick.id);
        ctx.db.brick().insert(Brick {
            position: Position { x, y, z: new_z },
            ..brick
        });
        restack_cell(ctx, src_x, src_y);
    }
    broadcast(ctx);
}
```

**Step 4: Add helper functions (log_event, broadcast stubs)**

```rust
fn log_event(ctx: &ReducerContext, kind: EventKind, brick_id: Option<u64>) {
    ctx.db.event().insert(Event {
        id: 0,
        kind,
        identity: ctx.sender,
        brick_id,
        timestamp: ctx.timestamp,
    });
}

fn broadcast(_ctx: &ReducerContext) {
    // Stub — implemented in Task 3 after template rendering is shared
}
```

**Step 5: Verify build**

Run: `cargo build --lib --target wasm32-unknown-unknown --release`
Expected: May fail on routes.rs (still references old field names). Fix in Task 3.

**Step 6: Commit**
```
git add src/reducers.rs
git commit -m "Refactor reducers: use ctx.sender Identity, add lifecycle hooks"
```

---

### Task 3: Share template rendering between routes and reducers, implement broadcast

Move the template engine and `world_state` into a shared module so both HTTP routes and WS reducers can render HTML. Implement the `broadcast()` function.

**Files:**
- Create: `src/render.rs`
- Modify: `src/routes.rs`
- Modify: `src/reducers.rs`
- Modify: `src/lib.rs`

**Step 1: Create src/render.rs**

Extract template rendering from routes.rs into a shared module. The key difference: routes use `RouteContext` (has `ctx.db`) and reducers use `ReducerContext` (has `ctx.db`). Both provide the same `Local` db accessor via the `Table` trait. We need a function that takes just the db accessor.

```rust
use std::sync::LazyLock;

use minijinja::{context, Environment};
use spacetimedb::{Identity, Table};

use crate::models::*;

pub static TEMPLATES: LazyLock<Environment<'static>> = LazyLock::new(|| {
    let mut env = Environment::new();
    env.add_template("index", include_str!("../templates/index.html.j2"))
        .unwrap();
    env
});

/// Build the template context from current DB state.
/// `current_identity` is the identity of the user this render is for (for is_self checks).
pub fn world_context<Acc: BrickTableAccess + UserTableAccess + CursorTableAccess + EventTableAccess>(
    db: &Acc,
    current_identity: Option<Identity>,
) -> minijinja::Value {
    // ... see step 2
}
```

Actually, the `Table` trait in SpacetimeDB generates accessor traits per table. We need to figure out the right trait bounds. The simpler approach: just accept a closure or build the context from collected data.

**Simpler approach — collect data into Vecs first:**

```rust
use std::sync::LazyLock;
use minijinja::{context, Environment};
use spacetimedb::Identity;
use crate::models::*;

pub static TEMPLATES: LazyLock<Environment<'static>> = LazyLock::new(|| {
    let mut env = Environment::new();
    env.add_template("index", include_str!("../templates/index.html.j2"))
        .unwrap();
    env
});

pub struct WorldState {
    pub blocks: Vec<minijinja::Value>,
    pub users: Vec<minijinja::Value>,
    pub cursors: Vec<minijinja::Value>,
    pub logs: Vec<minijinja::Value>,
}

impl WorldState {
    pub fn to_context(&self, current_identity: &str) -> minijinja::Value {
        context! {
            blocks => self.blocks,
            users => self.users,
            cursors => self.cursors,
            logs => self.logs,
            grid_size => 12,
            current_session_id => current_identity,
        }
    }
}

pub fn render_page(state: &WorldState, current_identity: &str) -> String {
    let ctx = state.to_context(current_identity);
    TEMPLATES.get_template("index").unwrap().render(ctx).unwrap()
}

pub fn render_body(state: &WorldState, current_identity: &str) -> String {
    let tmpl = TEMPLATES.get_template("index").unwrap();
    let ctx = state.to_context(current_identity);
    let mut s = tmpl.eval_to_state(ctx).unwrap();
    s.render_block("body").unwrap()
}
```

This approach is clunky. Even simpler — just make `world_state` a function that takes the raw table data and an identity string. Both routes and reducers call it the same way, they just source the data differently.

**Actually simplest: keep one function that takes iterators and builds context. Both RouteContext and ReducerContext have `.db` with identical table accessors.**

Let's use a macro-less approach. Since both `RouteContext.db` and `ReducerContext.db` have the same `brick()`, `user()`, `cursor()`, `event()` methods (they both return `Local`), we can write a generic function:

```rust
use std::sync::LazyLock;
use minijinja::{context, Environment};
use spacetimedb::{Identity, Table};
use crate::models::*;

static TEMPLATES: LazyLock<Environment<'static>> = LazyLock::new(|| {
    let mut env = Environment::new();
    env.add_template("index", include_str!("../templates/index.html.j2"))
        .unwrap();
    env
});

pub fn world_state(db: &spacetimedb::Local, current_identity: Option<&Identity>) -> minijinja::Value {
    let blocks: Vec<_> = db.brick().iter().map(|b| {
        context! {
            id => b.id,
            grid_x => b.position.x,
            grid_y => b.position.y,
            grid_z => b.position.z,
            color => b.color.hex(),
            is_being_dragged => b.dragged_by.is_some(),
        }
    }).collect();

    let users: Vec<_> = db.user().iter().map(|u| {
        context! {
            name => u.name,
            color => u.color.hex(),
            online => u.online,
        }
    }).collect();

    let cursors: Vec<_> = db.cursor().iter().filter_map(|c| {
        let user = db.user().identity().find(&c.identity)?;
        let is_self = current_identity == Some(&c.identity);
        Some(context! {
            session_id => c.identity.to_hex(),
            grid_x => c.position.x,
            grid_y => c.position.y,
            name => user.name,
            color => user.color.hex(),
            is_self => is_self,
        })
    }).collect();

    let logs: Vec<_> = db.event().iter().map(|e| {
        let user_name = db.user().identity().find(&e.identity)
            .map(|u| u.name.clone())
            .unwrap_or_else(|| format!("User"));
        context! {
            id => e.id,
            message => format!("{} {}", user_name, e.kind.label()),
            color => e.kind.css_color(),
        }
    }).collect();

    context! {
        blocks,
        users,
        cursors,
        logs,
        grid_size => 12,
        current_session_id => current_identity.map(|i| i.to_hex()).unwrap_or_default(),
    }
}

pub fn render_page(db: &spacetimedb::Local, current_identity: Option<&Identity>) -> String {
    let ctx = world_state(db, current_identity);
    TEMPLATES.get_template("index").unwrap().render(ctx).unwrap()
}

pub fn render_body(db: &spacetimedb::Local, current_identity: Option<&Identity>) -> String {
    let tmpl = TEMPLATES.get_template("index").unwrap();
    let ctx = world_state(db, current_identity);
    let mut state = tmpl.eval_to_state(ctx).unwrap();
    state.render_block("body").unwrap()
}
```

**Note:** Check whether `spacetimedb::Local` is the right type. Both `RouteContext.db` and `ReducerContext.db` are typed as `Local` (from `spacetimedb::Local`). Verify during implementation.

**Step 2: Update src/routes.rs**

Simplify to just import from render:

```rust
use spacetimedb::{get, Html, RouteContext, Table};
use crate::render;

#[get("/")]
fn index(ctx: &RouteContext) -> Html {
    Html(render::render_page(&ctx.db, None))
}
```

Remove all POST routes — mutations now go through WS reducers. The GET route doesn't need identity since no user is "connected" via HTTP.

**Step 3: Update src/lib.rs**

```rust
#![cfg(target_arch = "wasm32")]

mod models;
mod reducers;
mod render;
mod routes;
```

**Step 4: Implement broadcast in src/reducers.rs**

```rust
use crate::render;

fn broadcast(ctx: &ReducerContext) {
    for user in ctx.db.user().iter().filter(|u| u.online) {
        let html = render::render_body(&ctx.db, Some(&user.identity));
        ctx.db.html_broadcast().insert(HtmlBroadcast {
            identity: user.identity,
            html,
        });
    }
}
```

**Step 5: Verify build**

Run: `cargo build --lib --target wasm32-unknown-unknown --release`
Expected: PASS

**Step 6: Commit**
```
git add src/render.rs src/routes.rs src/reducers.rs src/lib.rs
git commit -m "Share template rendering, implement broadcast via event table"
```

---

### Task 4: Update template for WS-driven interactions

Change the template so user actions trigger reducer calls (via the htmx-stdb extension) instead of HTTP POSTs. Add a `{% block body %}` wrapper so `render_body()` can extract it.

**Files:**
- Modify: `templates/index.html.j2`

**Key changes:**

1. Wrap everything inside `<body>` in `{% block body %}...{% endblock %}`
2. Replace `hx-post="/brick"` on grid cells with `stdb-reducer="create_brick"` + `stdb-args`
3. Replace `hx-post="/brick/ID/delete"` on brick tops with `stdb-reducer="delete_brick"` + `stdb-args`
4. Replace player setup `hx-post` with `stdb-reducer="set_name"` / `stdb-reducer="set_color"`
5. Replace `hx-ext="server-commands,morph"` with `hx-ext="stdb,morph"`
6. Replace vendor script tags: remove `htmx-ext-ws.js` and `server-commands.js`, add `bindings.iife.js` and `htmx-ext-stdb.js`
7. Add `data-stdb-host` and `data-stdb-module` attributes on body for the extension to read

**Full template:** Write during implementation. Key patterns:

Grid cell button:
```html
<button stdb-reducer="create_brick" stdb-args='{"x": {{ col }}, "y": {{ row }}}'
        class="size-16 border ..." data-x="{{ col }}" data-y="{{ row }}"
        style="grid-column: {{ col + 1 }}; grid-row: {{ row + 1 }}">
</button>
```

Delete button:
```html
<button stdb-reducer="delete_brick" stdb-args='{"brick_id": {{ block.id }}}'
        class="size-16 border ...">
</button>
```

**Step 1: Rewrite template with stdb-reducer attributes**

See full template in the implementation.

**Step 2: Verify build** (template is included at compile time via `include_str!`)

Run: `cargo build --lib --target wasm32-unknown-unknown --release`

**Step 3: Commit**
```
git add templates/index.html.j2
git commit -m "Update template for WS reducer calls via htmx-stdb extension"
```

---

### Task 5: Set up TypeScript client build

Generate SpacetimeDB TypeScript bindings and bundle them into an IIFE that can be loaded via `<script>` tag.

**Files:**
- Create: `client/package.json`
- Create: `client/tsconfig.json`
- Create: `client/vite.config.ts`
- Create: `client/src/main.ts` (thin entry — just re-exports DbConnection and tables)
- Modify: `Justfile` (add generate + build steps)
- Modify: `.gitignore`

**Step 1: Create client/package.json**

```json
{
  "name": "hyperspace-client",
  "private": true,
  "type": "module",
  "scripts": {
    "build": "vite build"
  },
  "dependencies": {
    "spacetimedb": "file:../SpacetimeDB/crates/bindings-typescript"
  },
  "devDependencies": {
    "typescript": "~5.6.2",
    "vite": "^7.1.5"
  }
}
```

**Note:** The `spacetimedb` dependency points at the local SpacetimeDB checkout's TypeScript bindings, matching the Rust crate's local path dependency.

**Step 2: Create client/vite.config.ts**

```typescript
import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    lib: {
      entry: 'src/main.ts',
      name: 'Hyperspace',
      formats: ['iife'],
      fileName: () => 'bindings.iife.js',
    },
    outDir: '../static/js',
    emptyOutDir: false,
  },
});
```

**Step 3: Create client/tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "esModuleInterop": true,
    "outDir": "dist"
  },
  "include": ["src"]
}
```

**Step 4: Create client/src/main.ts**

This is the entry point that re-exports what the htmx extension needs:

```typescript
export { DbConnection } from './module_bindings';
export * as tables from './module_bindings';
```

**Step 5: Generate bindings and build**

```bash
# Generate TypeScript bindings from the wasm module
spacetimedb-cli generate --lang typescript \
    --bin-path target/wasm32-unknown-unknown/release/hyperspace.wasm \
    --out-dir client/src/module_bindings --yes

# Install deps and build IIFE
cd client && npm install && npm run build
```

This produces `static/js/bindings.iife.js`.

**Step 6: Update Justfile**

Add a `client` recipe and update `default`:

```justfile
# Build TypeScript client bindings
client: build-wasm
    "{{spacetime}}" generate --lang typescript \
        --bin-path {{wasm_path}} --out-dir client/src/module_bindings --yes
    cd client && npm install && npm run build

# Build and deploy module
default: spacetimedb client
```

**Step 7: Update .gitignore**

Add:
```
client/node_modules/
client/src/module_bindings/
```

**Step 8: Verify**

Run: `just client`
Expected: `static/js/bindings.iife.js` is generated.

**Step 9: Commit**
```
git add client/package.json client/tsconfig.json client/vite.config.ts client/src/main.ts
git add Justfile .gitignore
git commit -m "Add TypeScript client build for SpacetimeDB IIFE bundle"
```

---

### Task 6: Create the htmx-stdb extension

Write a custom htmx extension that:
- Connects to SpacetimeDB via the bundled SDK
- Subscribes to the `html_broadcast` event table
- Morphs the DOM on `on_insert`
- Intercepts `stdb-reducer` attribute clicks and calls reducers

**Files:**
- Create: `static/js/htmx-ext-stdb.js`

**Step 1: Write the extension**

```javascript
(function() {
  // The IIFE bundle exposes Hyperspace.DbConnection and Hyperspace.tables
  const { DbConnection, tables } = window.Hyperspace;

  let conn = null;

  htmx.defineExtension('stdb', {
    init: function(api) {
      const body = document.body;
      const host = body.dataset.stdbHost || 'ws://localhost:3000';
      const dbName = body.dataset.stdbModule || 'hyperspace';
      const tokenKey = `${host}/${dbName}/auth_token`;

      conn = DbConnection.builder()
        .withUri(host)
        .withDatabaseName(dbName)
        .withToken(localStorage.getItem(tokenKey) || undefined)
        .onConnect((connection, identity, token) => {
          localStorage.setItem(tokenKey, token);
          console.log('[stdb] connected:', identity.toHexString());

          // Subscribe to the broadcast event table
          connection.subscriptionBuilder()
            .onApplied(() => {
              console.log('[stdb] subscription applied');
            })
            .subscribe(tables.html_broadcast);

          // When broadcast HTML arrives, morph the body
          connection.db.html_broadcast.onInsert((ctx, row) => {
            const parser = new DOMParser();
            const doc = parser.parseFromString(row.html, 'text/html');
            const newBody = doc.body;
            if (newBody && document.body) {
              Idiomorph.morph(document.body, newBody, {
                morphStyle: 'innerHTML',
              });
            }
          });
        })
        .onDisconnect(() => {
          console.log('[stdb] disconnected');
        })
        .build();
    },

    onEvent: function(name, evt) {
      if (name !== 'htmx:click' && name !== 'click') return;

      const elt = evt.target.closest('[stdb-reducer]');
      if (!elt || !conn) return;

      evt.preventDefault();
      evt.stopPropagation();

      const reducer = elt.getAttribute('stdb-reducer');
      const argsStr = elt.getAttribute('stdb-args');
      const args = argsStr ? JSON.parse(argsStr) : {};

      console.log('[stdb] calling reducer:', reducer, args);

      if (conn.reducers[reducer]) {
        conn.reducers[reducer](args);
      } else {
        console.error('[stdb] unknown reducer:', reducer);
      }

      return false; // prevent htmx from processing
    },
  });
})();
```

**Note:** The exact API for calling reducers and subscribing may need adjustment during implementation. Check the generated bindings for exact method signatures. The `Idiomorph` global is available from `idiomorph-ext.min.js` — verify it exposes a global or if we need the standalone version.

**Step 2: Verify file exists**

`ls static/js/htmx-ext-stdb.js`

**Step 3: Commit**
```
git add static/js/htmx-ext-stdb.js
git commit -m "Add htmx-stdb extension for SpacetimeDB WebSocket integration"
```

---

### Task 7: Integration — build, deploy, and test

**Step 1: Full build**

```bash
just  # builds wasm, deploys module, generates + builds client
```

**Step 2: Manual smoke test**

Open `http://localhost:3000/` in browser. Check:
- Page loads with grid, HUD, console, player setup bar
- Browser console shows `[stdb] connected: <identity>`
- Click grid cell → brick appears (no page refresh)
- Click brick top → brick disappears
- Open second tab → changes sync between tabs
- Set name → name appears in HUD

**Step 3: Fix issues**

Likely issues to debug during integration:
- The `Idiomorph` global may not be exposed by `idiomorph-ext.min.js` (it's an htmx extension, not standalone). May need to download `idiomorph.min.js` (standalone) separately, or use `htmx.config.useTemplateFragments`.
- Reducer call syntax may differ from `conn.reducers.create_brick({x, y})`. Check generated bindings.
- The `stdb-reducer` click interception may need to use htmx's `htmx:beforeRequest` event instead of raw click.
- The `body` block rendering may need adjustment — `render_block("body")` requires the template to have `{% block body %}...{% endblock %}` around the body content.
- `spacetimedb::Local` may not be the right type for the db parameter in `render.rs`. Check the actual type of `ReducerContext.db` and `RouteContext.db`.

**Step 4: Update E2E tests**

The Playwright tests need updates for the new architecture:
- Remove references to `localhost:8080` (now `localhost:3000`)
- Tests expecting WebSocket "joined" messages may need to check for `[stdb] connected` or similar
- Tests expecting `button:has-text("+ Block")` need that button added to the template
- Tests expecting `aside` sidebar need that added to the template
- Multi-user sync test should now work (event table broadcast)

**Step 5: Commit**
```
git add -A
git commit -m "Integration: WS broadcast working with htmx-stdb extension"
```

---

### Task 8: Template polish — add missing UI elements for tests

The E2E tests expect UI elements that the current template doesn't have. Add them.

**Files:**
- Modify: `templates/index.html.j2`

**Missing elements (from test expectations):**
- `h1:has-text("Hyperspace")` — add an h1 heading
- `button:has-text("+ Block")` — add a random-position block button
- `aside` with block list showing `(x, y)` per block, with hover-to-delete buttons
- Console messages: "joined", "block created at (x,y)", "block deleted"

**Console message format changes in src/models.rs:**
- `EventKind::UserConnected` label → `"joined"`
- `EventKind::BrickCreated` label → needs position info. Either change the label function or format the message differently in `render.rs`.

**Step 1: Add h1, aside, + Block button to template**
**Step 2: Update event message formatting**
**Step 3: Verify tests pass**

Run: `just test`

**Step 4: Commit**
```
git add templates/index.html.j2 src/models.rs
git commit -m "Add missing UI elements for E2E test compatibility"
```
