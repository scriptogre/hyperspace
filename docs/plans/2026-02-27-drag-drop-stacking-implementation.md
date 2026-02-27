# Drag & Drop + Stackable Blocks Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add drag & drop block movement and vertical stacking to Hyperspace, with all logic server-side and zero JavaScript files.

**Architecture:** Browser sends raw pointer events (`mouseenter`, `pointerdown`, `pointerup`) via a single `hx-vals` on `#grid-viewport`. SpacetimeDB reducers decide what each event means based on server-side drag state. Blocks gain a `grid_z` field for stacking, rendered as vertical offsets in the isometric view.

**Tech Stack:** SpacetimeDB (Wasm module), Rocket (WebSocket server), htmx (ws-send + hx-vals), Playwright (e2e tests)

---

### Task 1: Add `grid_z` to SceneObject and `dragging_block_id` to UserCursor

**Files:**
- Modify: `src/lib.rs:8-16` (SceneObject struct)
- Modify: `src/lib.rs:18-25` (UserCursor struct)
- Modify: `src/lib.rs:99-106` (create_object reducer)

**Step 1: Add `grid_z: i32` field to SceneObject**

In `src/lib.rs`, add `grid_z` after `grid_y`:

```rust
#[spacetimedb::table(accessor = scene_object, public)]
pub struct SceneObject {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub grid_x: i32,
    pub grid_y: i32,
    pub grid_z: i32,
    pub color: String,
}
```

**Step 2: Add `dragging_block_id` field to UserCursor**

```rust
#[spacetimedb::table(accessor = user_cursor, public)]
pub struct UserCursor {
    #[primary_key]
    pub session_id: String,
    pub grid_x: i32,
    pub grid_y: i32,
    pub last_seen: Timestamp,
    pub dragging_block_id: u64,  // 0 = not dragging
}
```

Note: SpacetimeDB may not support `Option<u64>` well in all contexts. Use `0` as sentinel for "not dragging" since auto_inc IDs start at 1.

**Step 3: Update `create_object` reducer to compute `grid_z`**

```rust
#[reducer]
pub fn create_object(ctx: &ReducerContext, session_id: String, grid_x: i32, grid_y: i32) {
    let user = ctx.db.user_info().session_id().find(&session_id);
    let color = user.map(|u| u.color.clone()).unwrap_or_else(|| "#22d3ee".to_string());

    let grid_z = ctx.db.scene_object().iter()
        .filter(|obj| obj.grid_x == grid_x && obj.grid_y == grid_y)
        .count() as i32;

    if grid_z >= 5 {
        return; // Stack full
    }

    ctx.db.scene_object().insert(SceneObject {
        id: 0, grid_x, grid_y, grid_z, color: color.clone(),
    });
    add_log(ctx, format!("block created at ({grid_x},{grid_y})"), "text-cyan-400");
}
```

**Step 4: Update `update_cursor` to preserve `dragging_block_id`**

In the `update_cursor` reducer, make sure the upsert preserves the existing `dragging_block_id`:

```rust
#[reducer]
pub fn update_cursor(ctx: &ReducerContext, session_id: String, grid_x: i32, grid_y: i32) {
    let dragging = ctx.db.user_cursor().session_id().find(&session_id)
        .map(|c| c.dragging_block_id)
        .unwrap_or(0);

    ctx.db.user_cursor().session_id().delete(session_id.clone());
    ctx.db.user_cursor().insert(UserCursor {
        session_id,
        grid_x,
        grid_y,
        last_seen: ctx.timestamp,
        dragging_block_id: dragging,
    });
}
```

**Step 5: Build Wasm module and publish**

Run:
```bash
just build-wasm
just spacetimedb  # or: spacetime publish --project-path . hyperspace
```

Expected: Compiles and publishes without error. Schema migration applies.

**Step 6: Regenerate client bindings**

Run:
```bash
just generate
```

Expected: New bindings in `src/module_bindings/` include `grid_z` and `dragging_block_id`.

**Step 7: Commit**

```bash
git add src/lib.rs src/module_bindings/
git commit -m "Add grid_z to SceneObject and dragging_block_id to UserCursor"
```

---

### Task 2: Add new server-side event reducers

**Files:**
- Modify: `src/lib.rs` (add `handle_mouseenter`, `handle_pointerdown`, `handle_pointerup` reducers)

**Step 1: Add `handle_mouseenter` reducer**

This replaces `update_cursor`. Updates cursor position, and if dragging, moves the block:

```rust
#[reducer]
pub fn handle_mouseenter(ctx: &ReducerContext, session_id: String, grid_x: i32, grid_y: i32) {
    let existing = ctx.db.user_cursor().session_id().find(&session_id);
    let dragging = existing.as_ref().map(|c| c.dragging_block_id).unwrap_or(0);

    // Update cursor position
    if existing.is_some() {
        ctx.db.user_cursor().session_id().delete(session_id.clone());
    }
    ctx.db.user_cursor().insert(UserCursor {
        session_id,
        grid_x,
        grid_y,
        last_seen: ctx.timestamp,
        dragging_block_id: dragging,
    });

    // If dragging a block, move it to new position
    if dragging > 0 {
        if let Some(block) = ctx.db.scene_object().id().find(dragging) {
            // Don't move if already at this position
            if block.grid_x == grid_x && block.grid_y == grid_y {
                return;
            }

            // Compute z at target cell
            let target_z = ctx.db.scene_object().iter()
                .filter(|obj| obj.grid_x == grid_x && obj.grid_y == grid_y && obj.id != dragging)
                .count() as i32;

            if target_z >= 5 {
                return; // Target stack full
            }

            // Remove and reinsert with new position
            ctx.db.scene_object().id().delete(dragging);
            ctx.db.scene_object().insert(SceneObject {
                id: dragging,
                grid_x,
                grid_y,
                grid_z: target_z,
                color: block.color,
            });

            // Restack the source cell (fill gaps in z)
            restack_cell(ctx, block.grid_x, block.grid_y);
        }
    }
}
```

**Step 2: Add `restack_cell` helper**

When a block is removed from a stack, fill gaps in z-ordering:

```rust
fn restack_cell(ctx: &ReducerContext, grid_x: i32, grid_y: i32) {
    let mut blocks: Vec<_> = ctx.db.scene_object().iter()
        .filter(|obj| obj.grid_x == grid_x && obj.grid_y == grid_y)
        .collect();
    blocks.sort_by_key(|b| b.grid_z);

    for (i, block) in blocks.into_iter().enumerate() {
        let new_z = i as i32;
        if block.grid_z != new_z {
            ctx.db.scene_object().id().delete(block.id);
            ctx.db.scene_object().insert(SceneObject {
                id: block.id,
                grid_x: block.grid_x,
                grid_y: block.grid_y,
                grid_z: new_z,
                color: block.color,
            });
        }
    }
}
```

**Step 3: Add `handle_pointerdown` reducer**

Block at cursor? Pick it up. Empty cell? Create a block.

```rust
#[reducer]
pub fn handle_pointerdown(ctx: &ReducerContext, session_id: String, grid_x: i32, grid_y: i32) {
    // Find topmost block at this cell
    let topmost = ctx.db.scene_object().iter()
        .filter(|obj| obj.grid_x == grid_x && obj.grid_y == grid_y)
        .max_by_key(|obj| obj.grid_z);

    if let Some(block) = topmost {
        // Pick up the block — set dragging state
        if let Some(cursor) = ctx.db.user_cursor().session_id().find(&session_id) {
            ctx.db.user_cursor().session_id().delete(session_id.clone());
            ctx.db.user_cursor().insert(UserCursor {
                session_id,
                grid_x: cursor.grid_x,
                grid_y: cursor.grid_y,
                last_seen: ctx.timestamp,
                dragging_block_id: block.id,
            });
        }
    } else {
        // Empty cell — create a block
        create_object(ctx, session_id, grid_x, grid_y);
    }
}
```

**Step 4: Add `handle_pointerup` reducer**

```rust
#[reducer]
pub fn handle_pointerup(ctx: &ReducerContext, session_id: String) {
    if let Some(cursor) = ctx.db.user_cursor().session_id().find(&session_id) {
        if cursor.dragging_block_id > 0 {
            ctx.db.user_cursor().session_id().delete(session_id.clone());
            ctx.db.user_cursor().insert(UserCursor {
                session_id,
                grid_x: cursor.grid_x,
                grid_y: cursor.grid_y,
                last_seen: ctx.timestamp,
                dragging_block_id: 0,
            });
        }
    }
}
```

**Step 5: Build and publish**

```bash
just build-wasm
spacetime publish --project-path . hyperspace
just generate
```

**Step 6: Commit**

```bash
git add src/lib.rs src/module_bindings/
git commit -m "Add mouseenter/pointerdown/pointerup reducers with drag & stack logic"
```

---

### Task 3: Update server message handling

**Files:**
- Modify: `src/main.rs:69-120` (handle_browser_message)

**Step 1: Add new action handlers to `handle_browser_message`**

Replace the `"cursor"` action handler with `"mouseenter"`, and add `"pointerdown"` and `"pointerup"`:

```rust
} else if action == "mouseenter" {
    let x = message.get("x").and_then(|v| v.as_str()).and_then(|s| s.parse().ok()).unwrap_or(0);
    let y = message.get("y").and_then(|v| v.as_str()).and_then(|s| s.parse().ok()).unwrap_or(0);
    let broadcaster = broadcaster.clone();
    let _ = database.reducers.handle_mouseenter_then(session_id.to_string(), x, y, move |_, _| {
        notify_refresh(&broadcaster);
    });
} else if action == "pointerdown" {
    let x = message.get("x").and_then(|v| v.as_str()).and_then(|s| s.parse().ok()).unwrap_or(0);
    let y = message.get("y").and_then(|v| v.as_str()).and_then(|s| s.parse().ok()).unwrap_or(0);
    let broadcaster = broadcaster.clone();
    let _ = database.reducers.handle_pointerdown_then(session_id.to_string(), x, y, move |_, _| {
        notify_refresh(&broadcaster);
    });
} else if action == "pointerup" {
    let broadcaster = broadcaster.clone();
    let _ = database.reducers.handle_pointerup_then(session_id.to_string(), move |_, _| {
        notify_refresh(&broadcaster);
    });
}
```

Keep existing `"create"`, `"create_at:*"`, and `"delete:*"` handlers — the sidebar "+ Block" and delete buttons still use them.

Remove the old `"cursor"` handler.

**Step 2: Build and verify**

```bash
cargo build
```

Expected: Compiles with new reducer bindings.

**Step 3: Commit**

```bash
git add src/main.rs
git commit -m "Wire mouseenter/pointerdown/pointerup actions to new reducers"
```

---

### Task 4: Update broadcast rendering for stacking

**Files:**
- Modify: `src/broadcast.rs:17-22` (Block struct)
- Modify: `src/broadcast.rs:57-104` (template_context)

**Step 1: Add `grid_z` to Block struct**

```rust
#[derive(serde::Serialize)]
pub struct Block {
    id: u64,
    grid_x: i32,
    grid_y: i32,
    grid_z: i32,
    color: String,
}
```

**Step 2: Update `template_context` block mapping**

```rust
let mut blocks: Vec<Block> = tables.scene_object().iter()
    .map(|object| Block {
        id: object.id,
        grid_x: object.grid_x,
        grid_y: object.grid_y,
        grid_z: object.grid_z,
        color: object.color.clone(),
    })
    .collect();
blocks.sort_by_key(|block| (block.id, block.grid_z));
```

**Step 3: Build and verify**

```bash
cargo build
```

**Step 4: Commit**

```bash
git add src/broadcast.rs
git commit -m "Add grid_z to broadcast Block struct"
```

---

### Task 5: Rewrite template — event delegation + stacking visuals

**Files:**
- Modify: `templates/index.html.j2` (grid-viewport, cells, blocks, remove scene.js)

**Step 1: Update `#grid-viewport` with ws-send and hx-vals**

Replace the grid viewport div (line 72):

```html
<div class="flex-1 relative overflow-hidden bg-surface select-none" id="grid-viewport"
     ws-send
     hx-trigger="mouseenter from:[data-x], pointerdown, pointerup from:document"
     hx-vals="js:{action: event.type, ...event.target.closest('[data-x]')?.dataset}">
```

Key additions: `select-none` (prevent text selection during drag), `ws-send`, `hx-trigger`, `hx-vals`.

**Step 2: Simplify cell buttons — remove ws-send and action**

Cells become dumb hit targets:

```html
{% for row in range(grid_size) %}
  {% for col in range(grid_size) %}
  <button class="size-16 border border-white/[0.04] bg-white/[0.015] cursor-pointer
                 transition-colors duration-150 hover:bg-cyan-400/[0.08] hover:border-cyan-400/15"
          data-x="{{ col }}" data-y="{{ row }}"
          style="grid-column: {{ col + 1 }}; grid-row: {{ row + 1 }}">
  </button>
  {% endfor %}
{% endfor %}
```

Removed: `hx-trigger="click"`, `ws-send`, `name="action"`, `value="create_at:..."`.

**Step 3: Update block divs — add `data-x`/`data-y`, stacking offset, remove pointer-events-none**

```html
{% for block in blocks %}
<div id="block-{{ block.id }}"
     data-x="{{ block.grid_x }}" data-y="{{ block.grid_y }}"
     class="size-16 opacity-85 starting:opacity-0 starting:scale-75
            border border-white/20
            transition-[opacity,transform] duration-200 ease-out
            shadow-[0_0_20px_color-mix(in_srgb,var(--color)_30%,transparent),inset_0_1px_0_rgba(255,255,255,0.25),inset_0_-1px_0_rgba(0,0,0,0.2)]"
     style="grid-column: {{ block.grid_x + 1 }}; grid-row: {{ block.grid_y + 1 }};
            --color: {{ block.color }}; background: var(--color);
            translate: 0 {{ block.grid_z * -20 }}px;
            z-index: {{ block.grid_z + 1 }}">
</div>
{% endfor %}
```

Changes: removed `pointer-events-none`, added `data-x`/`data-y`, added `translate` for stacking offset, added `z-index` for stacking order.

**Step 4: Delete scene.js script tag**

Remove line 170: `<script src="/static/js/scene.js" type="module"></script>`

**Step 5: Delete scene.js file**

```bash
rm static/js/scene.js
```

**Step 6: Restart server and verify page loads**

```bash
pkill -f 'target/debug/hyperspace'; sleep 1; cargo run &
sleep 3; curl -s http://localhost:8080 | head -20
```

**Step 7: Commit**

```bash
git add templates/index.html.j2
git rm static/js/scene.js
git commit -m "Replace scene.js with hx-vals event delegation, add stacking visuals"
```

---

### Task 6: Update sidebar block list to show height

**Files:**
- Modify: `templates/index.html.j2` (sidebar blocks section)

**Step 1: Show z-level in sidebar entries**

Update the sidebar block entries to indicate stack height when > 0:

```html
{% for block in blocks %}
<div class="flex items-center justify-between px-2 py-1 rounded hover:bg-white/5 text-xs group">
  <div class="flex items-center gap-2">
    <span class="w-2 h-2 rounded-sm shrink-0" style="background: {{ block.color }}"></span>
    <span class="text-gray-400">
      ({{ block.grid_x }}, {{ block.grid_y }}){% if block.grid_z > 0 %} z{{ block.grid_z }}{% endif %}
    </span>
  </div>
  <button hx-trigger="click" ws-send name="action" value="delete:{{ block.id }}"
          class="text-gray-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition">
    &times;
  </button>
</div>
{% endfor %}
```

**Step 2: Commit**

```bash
git add templates/index.html.j2
git commit -m "Show stack height in sidebar block list"
```

---

### Task 7: Update existing tests for new interaction model

**Files:**
- Modify: `tests/e2e/hyperspace.spec.ts`
- Modify: `tests/e2e/interactive-walkthrough.spec.ts`
- Modify: `tests/e2e/cursor-test.spec.ts`

**Step 1: Fix cell click selectors**

Cells no longer have `hx-trigger="click" ws-send`. Clicking a cell now triggers `pointerdown` on the grid viewport (via event delegation). Playwright's `page.click('[data-x="2"][data-y="3"]')` fires a pointerdown + pointerup, which the server interprets as "create block at (2,3)" if the cell is empty. So most click tests should still work.

However, the `button:has-text("+ Block")` still uses the old `ws-send name="action" value="create"` pattern directly. That stays.

Test each existing test and fix selectors as needed. The main changes:
- Remove `[data-x][data-x="2"]` double-attribute selectors (simplify to `[data-x="2"][data-y="3"]`)
- Verify block creation still works via pointerdown/pointerup delegation

**Step 2: Run all tests**

```bash
npx playwright test --reporter=line
```

Fix any failures. The key concern: does `page.click()` on a cell trigger the `pointerdown` event that bubbles to `#grid-viewport`? It should — Playwright's click synthesizes real pointer events.

**Step 3: Commit**

```bash
git add tests/e2e/
git commit -m "Update e2e tests for event delegation interaction model"
```

---

### Task 8: Add drag & drop e2e test

**Files:**
- Create: `tests/e2e/drag-test.spec.ts`

**Step 1: Write drag & drop test**

```typescript
import { test, expect } from '@playwright/test';

test('drag block to new position', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (err) => errors.push(err.message));

  await page.goto('/');
  await page.waitForSelector('#console-log:has-text("joined")');

  // Create a block at (3,3) by clicking
  const blocksBefore = await page.locator('[id^="block-"]').count();
  await page.click('[data-x="3"][data-y="3"]');
  await expect(page.locator('[id^="block-"]')).toHaveCount(blocksBefore + 1, { timeout: 5000 });
  await expect(page.locator('aside')).toContainText('(3, 3)');

  // Drag it: mousedown on the block, hover over intermediate cells, mouseup
  const block = page.locator('[id^="block-"]').last();
  await block.dispatchEvent('pointerdown');
  await page.waitForTimeout(200);

  // Move across cells
  await page.hover('[data-x="4"][data-y="3"]');
  await page.waitForTimeout(200);
  await page.hover('[data-x="5"][data-y="3"]');
  await page.waitForTimeout(200);

  // Release
  await page.dispatchEvent('body', 'pointerup');
  await page.waitForTimeout(500);

  // Block should now be at (5,3) not (3,3)
  await expect(page.locator('aside')).toContainText('(5, 3)');

  expect(errors).toEqual([]);
});
```

**Step 2: Run and verify**

```bash
npx playwright test tests/e2e/drag-test.spec.ts --reporter=line
```

**Step 3: Commit**

```bash
git add tests/e2e/drag-test.spec.ts
git commit -m "Add drag & drop e2e test"
```

---

### Task 9: Add stacking e2e test

**Files:**
- Create: `tests/e2e/stacking-test.spec.ts`

**Step 1: Write stacking test**

```typescript
import { test, expect } from '@playwright/test';

test('blocks stack when created at same position', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (err) => errors.push(err.message));

  await page.goto('/');
  await page.waitForSelector('#console-log:has-text("joined")');

  const blocksBefore = await page.locator('[id^="block-"]').count();

  // Create 3 blocks at same cell
  await page.click('[data-x="4"][data-y="4"]');
  await expect(page.locator('[id^="block-"]')).toHaveCount(blocksBefore + 1, { timeout: 5000 });
  await page.click('[data-x="4"][data-y="4"]');
  await expect(page.locator('[id^="block-"]')).toHaveCount(blocksBefore + 2, { timeout: 5000 });
  await page.click('[data-x="4"][data-y="4"]');
  await expect(page.locator('[id^="block-"]')).toHaveCount(blocksBefore + 3, { timeout: 5000 });

  // All three should appear in sidebar at (4, 4)
  const entries = page.locator('aside', { hasText: '(4, 4)' });
  await expect(entries).toContainText('z1');
  await expect(entries).toContainText('z2');

  // Screenshot to verify visual stacking
  await page.screenshot({ path: 'test-results/stacking.png', fullPage: true });

  expect(errors).toEqual([]);
});

test('stack height capped at 5', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#console-log:has-text("joined")');

  const blocksBefore = await page.locator('[id^="block-"]').count();

  // Create 6 blocks at same cell — only 5 should succeed
  for (let i = 0; i < 6; i++) {
    await page.click('[data-x="2"][data-y="2"]');
    await page.waitForTimeout(300);
  }

  // Should have exactly 5 new blocks (6th rejected)
  await expect(page.locator('[id^="block-"]')).toHaveCount(blocksBefore + 5, { timeout: 5000 });
});
```

**Step 2: Run and verify**

```bash
npx playwright test tests/e2e/stacking-test.spec.ts --reporter=line
```

**Step 3: Commit**

```bash
git add tests/e2e/stacking-test.spec.ts
git commit -m "Add stacking e2e tests"
```

---

### Task 10: Multi-user drag sync test

**Files:**
- Create: `tests/e2e/drag-sync-test.spec.ts`

**Step 1: Write multi-user drag visibility test**

```typescript
import { test, expect } from '@playwright/test';

test('other user sees block move during drag', async ({ browser }) => {
  const errors: string[] = [];
  const c1 = await browser.newContext();
  const c2 = await browser.newContext();
  const p1 = await c1.newPage();
  const p2 = await c2.newPage();
  p1.on('pageerror', (err) => errors.push('p1: ' + err.message));
  p2.on('pageerror', (err) => errors.push('p2: ' + err.message));

  await Promise.all([p1.goto('http://localhost:8080'), p2.goto('http://localhost:8080')]);
  await Promise.all([
    p1.waitForSelector('#console-log:has-text("joined")'),
    p2.waitForSelector('#console-log:has-text("joined")'),
  ]);

  // p1 creates a block at (2,2)
  const before = await p2.locator('[id^="block-"]').count();
  await p1.click('[data-x="2"][data-y="2"]');
  await expect(p2.locator('[id^="block-"]')).toHaveCount(before + 1, { timeout: 5000 });

  // p1 drags the block to (4,2)
  await p1.locator('[data-x="2"][data-y="2"] ~ [id^="block-"]').first().dispatchEvent('pointerdown');
  await p1.waitForTimeout(200);
  await p1.hover('[data-x="3"][data-y="2"]');
  await p1.waitForTimeout(300);
  await p1.hover('[data-x="4"][data-y="2"]');
  await p1.waitForTimeout(300);
  await p1.dispatchEvent('body', 'pointerup');
  await p1.waitForTimeout(500);

  // p2 should see block at (4,2)
  await expect(p2.locator('aside')).toContainText('(4, 2)', { timeout: 5000 });

  // Screenshot
  await p2.screenshot({ path: 'test-results/drag-sync.png', fullPage: true });

  expect(errors).toEqual([]);
  await Promise.all([c1.close(), c2.close()]);
});
```

**Step 2: Run and verify**

```bash
npx playwright test tests/e2e/drag-sync-test.spec.ts --reporter=line
```

**Step 3: Commit**

```bash
git add tests/e2e/drag-sync-test.spec.ts
git commit -m "Add multi-user drag sync e2e test"
```

---

### Task 11: Visual polish and full test run

**Step 1: Run all tests**

```bash
npx playwright test --reporter=line
```

Expected: All tests pass (original 12 + new drag/stacking tests).

**Step 2: Visual check — take screenshots**

Run screenshot test and inspect results:

```bash
npx playwright test tests/e2e/hyperspace.spec.ts -g "screenshot"
```

Open `test-results/hyperspace.png` and verify:
- Blocks render correctly
- Stacked blocks show vertical offset
- No visual regressions

**Step 3: Final commit**

```bash
git add -A
git commit -m "Drag & drop + stackable blocks: complete implementation"
```
