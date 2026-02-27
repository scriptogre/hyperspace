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
    pub color: String,
}

#[spacetimedb::table(accessor = user_cursor, public)]
pub struct UserCursor {
    #[primary_key]
    pub session_id: String,
    pub grid_x: i32,
    pub grid_y: i32,
    pub last_seen: Timestamp,
}

#[spacetimedb::table(accessor = user_info, public)]
pub struct UserInfo {
    #[primary_key]
    pub session_id: String,
    pub name: String,
    pub color: String,
    pub online: bool,
}

const COLORS: [&str; 6] = ["#22d3ee", "#a78bfa", "#fb923c", "#4ade80", "#f472b6", "#facc15"];

// --- Session lifecycle (called by Rocket server per WebSocket connection) ---

#[reducer]
pub fn join(ctx: &ReducerContext, session_id: String) {
    let color_index = ctx.db.user_info().count() as usize % COLORS.len();

    if let Some(existing) = ctx.db.user_info().session_id().find(&session_id) {
        ctx.db.user_info().session_id().update(UserInfo { online: true, ..existing });
    } else {
        ctx.db.user_info().insert(UserInfo {
            session_id,
            name: format!("User {}", ctx.db.user_info().count() + 1),
            color: COLORS[color_index].to_string(),
            online: true,
        });
    }
}

#[reducer]
pub fn leave(ctx: &ReducerContext, session_id: String) {
    if let Some(existing) = ctx.db.user_info().session_id().find(&session_id) {
        ctx.db.user_info().session_id().update(UserInfo { online: false, ..existing });
    }
    if ctx.db.user_cursor().session_id().find(&session_id).is_some() {
        ctx.db.user_cursor().session_id().delete(&session_id);
    }
}

// --- Reducers ---

#[reducer]
pub fn create_object(ctx: &ReducerContext, session_id: String, grid_x: i32, grid_y: i32) {
    let color = ctx.db.user_info().session_id().find(&session_id)
        .map(|user| user.color.clone())
        .unwrap_or_else(|| "#888".to_string());
    ctx.db.scene_object().insert(SceneObject { id: 0, grid_x, grid_y, color });
}

#[reducer]
pub fn delete_object(ctx: &ReducerContext, id: u64) -> Result<(), String> {
    ctx.db.scene_object().id().find(id).ok_or("Not found")?;
    ctx.db.scene_object().id().delete(id);
    Ok(())
}

#[reducer]
pub fn update_cursor(ctx: &ReducerContext, session_id: String, grid_x: i32, grid_y: i32) {
    let cursor = UserCursor {
        session_id: session_id.clone(),
        grid_x,
        grid_y,
        last_seen: ctx.timestamp,
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
