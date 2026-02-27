//! SpacetimeDB module — compiled to Wasm, runs inside the database.
#![cfg(target_arch = "wasm32")]

use spacetimedb::{reducer, ReducerContext, Table, Timestamp};

// --- Tables ---

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

#[spacetimedb::table(accessor = user_cursor, public)]
pub struct UserCursor {
    #[primary_key]
    pub session_id: String,
    pub grid_x: i32,
    pub grid_y: i32,
    pub last_seen: Timestamp,
    pub dragging_block_id: u64,
}

#[spacetimedb::table(accessor = user_info, public)]
pub struct UserInfo {
    #[primary_key]
    pub session_id: String,
    pub name: String,
    pub color: String,
    pub online: bool,
}

#[spacetimedb::table(accessor = console_log, public)]
pub struct ConsoleLog {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub message: String,
    pub color: String,
}

const COLORS: [&str; 6] = ["#22d3ee", "#a78bfa", "#fb923c", "#4ade80", "#f472b6", "#facc15"];
const MAX_LOG_ENTRIES: usize = 50;

fn add_log(ctx: &ReducerContext, message: String, color: &str) {
    ctx.db.console_log().insert(ConsoleLog {
        id: 0,
        message,
        color: color.to_string(),
    });

    // Trim old entries to keep the log bounded.
    let count = ctx.db.console_log().count() as usize;
    if count > MAX_LOG_ENTRIES {
        let mut entries: Vec<_> = ctx.db.console_log().iter().collect();
        entries.sort_by_key(|entry| entry.id);
        for entry in entries.into_iter().take(count - MAX_LOG_ENTRIES) {
            ctx.db.console_log().id().delete(entry.id);
        }
    }
}

// --- Session lifecycle (called by Rocket server per WebSocket connection) ---

#[reducer]
pub fn join(ctx: &ReducerContext, session_id: String) {
    let color_index = ctx.db.user_info().count() as usize % COLORS.len();

    if let Some(existing) = ctx.db.user_info().session_id().find(&session_id) {
        ctx.db.user_info().session_id().update(UserInfo { online: true, ..existing });
    } else {
        let name = format!("User {}", ctx.db.user_info().count() + 1);
        add_log(ctx, format!("{name} joined"), "text-green-400");
        ctx.db.user_info().insert(UserInfo {
            session_id,
            name,
            color: COLORS[color_index].to_string(),
            online: true,
        });
    }
}

#[reducer]
pub fn leave(ctx: &ReducerContext, session_id: String) {
    if let Some(existing) = ctx.db.user_info().session_id().find(&session_id) {
        add_log(ctx, format!("{} left", existing.name), "text-gray-400");
        ctx.db.user_info().session_id().update(UserInfo { online: false, ..existing });
    }
    if ctx.db.user_cursor().session_id().find(&session_id).is_some() {
        ctx.db.user_cursor().session_id().delete(&session_id);
    }
}

// --- Reducers ---

#[reducer]
pub fn create_object(ctx: &ReducerContext, session_id: String, grid_x: i32, grid_y: i32) {
    let grid_z = ctx.db.scene_object().iter()
        .filter(|obj| obj.grid_x == grid_x && obj.grid_y == grid_y)
        .count() as i32;
    if grid_z >= 5 { return; }
    let color = ctx.db.user_info().session_id().find(&session_id)
        .map(|user| user.color.clone())
        .unwrap_or_else(|| "#888".to_string());
    ctx.db.scene_object().insert(SceneObject { id: 0, grid_x, grid_y, grid_z, color });
    add_log(ctx, format!("block created at ({grid_x},{grid_y})"), "text-cyan-400");
}

#[reducer]
pub fn delete_object(ctx: &ReducerContext, id: u64) -> Result<(), String> {
    ctx.db.scene_object().id().find(id).ok_or("Not found")?;
    ctx.db.scene_object().id().delete(id);
    add_log(ctx, "block deleted".to_string(), "text-red-400");
    Ok(())
}

#[reducer]
pub fn update_cursor(ctx: &ReducerContext, session_id: String, grid_x: i32, grid_y: i32) {
    let dragging_block_id = ctx.db.user_cursor().session_id().find(&session_id)
        .map(|c| c.dragging_block_id)
        .unwrap_or(0);
    let cursor = UserCursor {
        session_id: session_id.clone(),
        grid_x,
        grid_y,
        last_seen: ctx.timestamp,
        dragging_block_id,
    };
    if ctx.db.user_cursor().session_id().find(&session_id).is_some() {
        ctx.db.user_cursor().session_id().update(cursor);
    } else {
        ctx.db.user_cursor().insert(cursor);
    }
}

#[reducer]
pub fn set_name(ctx: &ReducerContext, session_id: String, name: String) -> Result<(), String> {
    if name.is_empty() {
        return Err("Empty name".into());
    }
    let user = ctx.db.user_info().session_id().find(&session_id).ok_or("Not found")?;
    ctx.db.user_info().session_id().update(UserInfo { name, ..user });
    Ok(())
}

#[reducer]
pub fn set_color(ctx: &ReducerContext, session_id: String, color: String) -> Result<(), String> {
    let user = ctx.db.user_info().session_id().find(&session_id).ok_or("Not found")?;
    ctx.db.user_info().session_id().update(UserInfo { color, ..user });
    Ok(())
}

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
                id: block.id, grid_x: block.grid_x, grid_y: block.grid_y,
                grid_z: new_z, color: block.color,
            });
        }
    }
}

#[reducer]
pub fn handle_mouseenter(ctx: &ReducerContext, session_id: String, grid_x: i32, grid_y: i32) {
    let dragging_block_id = ctx.db.user_cursor().session_id().find(&session_id)
        .map(|c| c.dragging_block_id)
        .unwrap_or(0);

    // Update cursor position
    let cursor = UserCursor {
        session_id: session_id.clone(),
        grid_x,
        grid_y,
        last_seen: ctx.timestamp,
        dragging_block_id,
    };
    if ctx.db.user_cursor().session_id().find(&session_id).is_some() {
        ctx.db.user_cursor().session_id().update(cursor);
    } else {
        ctx.db.user_cursor().insert(cursor);
    }

    // If dragging, move block to new cell
    if dragging_block_id > 0 {
        if let Some(block) = ctx.db.scene_object().id().find(dragging_block_id) {
            let src_x = block.grid_x;
            let src_y = block.grid_y;

            // Compute new z at destination (top of stack)
            let new_z = ctx.db.scene_object().iter()
                .filter(|obj| obj.grid_x == grid_x && obj.grid_y == grid_y)
                .count() as i32;

            // Move the block
            ctx.db.scene_object().id().delete(block.id);
            ctx.db.scene_object().insert(SceneObject {
                id: block.id,
                grid_x,
                grid_y,
                grid_z: new_z,
                color: block.color,
            });

            // Restack the source cell
            restack_cell(ctx, src_x, src_y);
        }
    }
}

#[reducer]
pub fn handle_pointerdown(ctx: &ReducerContext, session_id: String, grid_x: i32, grid_y: i32) {
    // Find topmost block at cell
    let topmost = ctx.db.scene_object().iter()
        .filter(|obj| obj.grid_x == grid_x && obj.grid_y == grid_y)
        .max_by_key(|obj| obj.grid_z);

    if let Some(block) = topmost {
        // Start dragging
        let cursor = UserCursor {
            session_id: session_id.clone(),
            grid_x,
            grid_y,
            last_seen: ctx.timestamp,
            dragging_block_id: block.id,
        };
        if ctx.db.user_cursor().session_id().find(&session_id).is_some() {
            ctx.db.user_cursor().session_id().update(cursor);
        } else {
            ctx.db.user_cursor().insert(cursor);
        }
    } else {
        // Empty cell — create a new block
        create_object(ctx, session_id, grid_x, grid_y);
    }
}

#[reducer]
pub fn handle_pointerup(ctx: &ReducerContext, session_id: String) {
    if let Some(existing) = ctx.db.user_cursor().session_id().find(&session_id) {
        ctx.db.user_cursor().session_id().update(UserCursor {
            dragging_block_id: 0,
            ..existing
        });
    }
}
