# Drag & Drop + Stackable Blocks

## Goal

Make Hyperspace more interactive by adding drag & drop block movement and vertical stacking. Showcase SpacetimeDB's real-time sync capabilities — other users see blocks sliding across the grid as they're dragged, and towers rising as blocks stack.

## Interaction Model

All client logic is eliminated. The browser is a dumb event pipe. SpacetimeDB reducers handle all decisions.

### Client → Server Messages

One `ws-send` on `#grid-viewport` with event delegation:

```html
<div id="grid-viewport"
     ws-send
     hx-trigger="mouseenter from:[data-x], pointerdown, pointerup from:document"
     hx-vals="js:{action: event.type, ...event.target.closest('[data-x]')?.dataset}">
```

Three message types, all using raw `event.type` as the action:

| Message | When | Data |
|---------|------|------|
| `{action: "mouseenter", x, y}` | Mouse enters a grid cell | Cell coordinates |
| `{action: "pointerdown", x, y}` | Mouse button pressed on grid | Cell coordinates |
| `{action: "pointerup"}` | Mouse button released anywhere | None (coordinates optional) |

### Server-Side Logic (SpacetimeDB Reducers)

The server maintains drag state per user on the `UserCursor` table:

- **`mouseenter`** at (x,y): Update cursor position. If user is dragging a block, move it to (x,y) — this is how real-time drag works (block follows cursor cell-by-cell).
- **`pointerdown`** at (x,y): Check if a block exists at (x,y). If yes, pick it up (set `dragging_block_id` on cursor). If no, create a new block.
- **`pointerup`**: Clear `dragging_block_id`. Drop the block wherever it currently is.

## Data Model Changes

### SceneObject — add `grid_z`

```rust
pub struct SceneObject {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub grid_x: i32,
    pub grid_y: i32,
    pub grid_z: i32,  // NEW: height in stack (0 = ground)
    pub color: String,
}
```

### UserCursor — add `dragging_block_id`

```rust
pub struct UserCursor {
    #[primary_key]
    pub session_id: String,
    pub grid_x: i32,
    pub grid_y: i32,
    pub last_seen: Timestamp,
    pub dragging_block_id: Option<u64>,  // NEW: block being dragged
}
```

### New/Modified Reducers

- **`handle_mouseenter(session_id, x, y)`**: Update cursor. If dragging, move block to (x,y) at top of stack.
- **`handle_pointerdown(session_id, x, y)`**: If block at (x,y), start drag (pick up topmost). Else create block.
- **`handle_pointerup(session_id)`**: End drag, clear `dragging_block_id`.

Existing `create_object` and `update_cursor` get absorbed into these. `delete_object` stays for sidebar delete.

## Stacking

- Max stack height: 5 blocks per cell.
- When a block is placed (created or dropped), it gets `grid_z = count of existing blocks at that cell`.
- When the topmost block is picked up, it's removed from the stack (others stay).
- Dragging a block onto a full stack (5 high) is rejected — block stays where it was.

### Visual Rendering

Each stacked block offsets upward in screen space. In the isometric grid, a block at `grid_z=1` gets `translateY(-20px)` relative to `grid_z=0`. Higher blocks render on top via z-index.

```
Stack of 3 at (2,3):

     ┌──┐  ← z=2 (offset -40px, z-index highest)
     │  │
  ┌──┐  │  ← z=1 (offset -20px)
  │  │──┘
  │  │     ← z=0 (on grid)
  └──┘
```

Block template changes:
```html
<div id="block-{{ block.id }}"
     style="grid-column: {{ block.grid_x + 1 }};
            grid-row: {{ block.grid_y + 1 }};
            translate: 0 {{ block.grid_z * -20 }}px;
            z-index: {{ block.grid_z }};">
```

## Delete scene.js

`static/js/scene.js` is deleted entirely. The `<script src="/static/js/scene.js">` tag is removed from the template. All interaction is handled by the single `hx-vals` / `hx-trigger` on `#grid-viewport`.

## Template Changes

### Grid viewport (single interaction handler)

```html
<div id="grid-viewport"
     class="flex-1 relative overflow-hidden bg-surface select-none"
     ws-send
     hx-trigger="mouseenter from:[data-x], pointerdown, pointerup from:document"
     hx-vals="js:{action: event.type, ...event.target.closest('[data-x]')?.dataset}">
```

### Cell buttons (dumb hit targets)

```html
<button data-x="{{ col }}" data-y="{{ row }}"
        class="size-16 border border-white/[0.04] ..."
        style="grid-column: {{ col + 1 }}; grid-row: {{ row + 1 }}">
</button>
```

No `ws-send`, no `hx-trigger`, no `name`/`value` on cells. They're just `data-x`/`data-y` targets for event delegation.

### Block divs (visual, no pointer-events-none)

Remove `pointer-events-none` so pointerdown can detect blocks. Add `data-x`/`data-y` so `closest('[data-x]')` finds them during pointer events.

```html
<div id="block-{{ block.id }}"
     data-x="{{ block.grid_x }}" data-y="{{ block.grid_y }}"
     class="size-16 opacity-85 ..."
     style="grid-column: ...; grid-row: ...; translate: 0 {{ block.grid_z * -20 }}px; z-index: {{ block.grid_z }};">
</div>
```

## Server Message Handling

`handle_browser_message` in `main.rs` changes:

```rust
match action {
    "mouseenter" => mouseenter(session_id, x, y),
    "pointerdown" => pointerdown(session_id, x, y),
    "pointerup" => pointerup(session_id),
    _ => { /* existing: set_name, delete:id, create (random) */ }
}
```

Coordinates `x` and `y` are read from the JSON message as separate fields (no more `cursor:x,y` or `create_at:x,y` format for these actions).

## What Stays The Same

- Sidebar block list with delete buttons
- "+ Block" button for random placement
- Name setting
- Console log
- Cursor rendering (isometric projection math)
- Per-session users with unique colors
- Morph-based rendering pipeline

## Risks

- **htmx `hx-vals` with spread**: `...event.target.closest('[data-x]')?.dataset` is untested with htmx. May need fallback.
- **Morph during drag**: If a morph update replaces the grid mid-drag, pointer events may behave unexpectedly. Idiomorph should preserve elements by ID, but worth testing.
- **Rapid mouseenter during drag**: Many WebSocket messages. The broadcast/render pipeline needs to keep up. SpacetimeDB should handle this fine — that's the demo.
