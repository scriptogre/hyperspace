//! SpacetimeDB module — compiled to Wasm, runs inside the database.

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
