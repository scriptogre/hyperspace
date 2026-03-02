use spacetimedb::{reducer, ReducerContext, Table};
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

#[reducer]
pub fn connect_user(ctx: &ReducerContext, user_id: u64) {
    let db = &ctx.db;
    if let Some(existing) = db.user().id().find(&user_id) {
        db.user().id().update(User { online: true, ..existing });
    } else {
        let name = format!("User {}", db.user().count() + 1);
        db.user().insert(User {
            id: user_id,
            name,
            color: Color::random(ctx),
            online: true,
        });
    }
    ctx.db.event().insert(Event { id: 0, kind: EventKind::UserConnected, user_id, brick_id: None, timestamp: ctx.timestamp });
}

#[reducer]
pub fn disconnect_user(ctx: &ReducerContext, user_id: u64) {
    let db = &ctx.db;
    if let Some(existing) = db.user().id().find(&user_id) {
        db.user().id().update(User { online: false, ..existing });
    }
    if db.cursor().user_id().find(&user_id).is_some() {
        db.cursor().user_id().delete(&user_id);
    }
    for brick in db.brick().iter().filter(|b| b.dragged_by == Some(user_id)).collect::<Vec<_>>() {
        db.brick().id().update(Brick { dragged_by: None, ..brick });
    }
    ctx.db.event().insert(Event { id: 0, kind: EventKind::UserDisconnected, user_id, brick_id: None, timestamp: ctx.timestamp });
}

#[reducer]
pub fn create_brick(ctx: &ReducerContext, user_id: u64, x: i32, y: i32) {
    let db = &ctx.db;
    let z = db.brick().iter()
        .filter(|b| b.position.x == x && b.position.y == y)
        .count() as i32;
    if z >= 5 { return; }
    let color = db.user().id().find(&user_id)
        .map(|u| u.color)
        .unwrap_or(Color::Cyan);
    db.brick().insert(Brick {
        id: 0,
        position: Position { x, y, z },
        color,
        dragged_by: None,
    });
    ctx.db.event().insert(Event { id: 0, kind: EventKind::BrickCreated, user_id, brick_id: None, timestamp: ctx.timestamp });
}

#[reducer]
pub fn delete_brick(ctx: &ReducerContext, user_id: u64, brick_id: u64) -> Result<(), String> {
    ctx.db.brick().id().find(brick_id).ok_or("Not found")?;
    ctx.db.brick().id().delete(brick_id);
    ctx.db.event().insert(Event { id: 0, kind: EventKind::BrickDeleted, user_id, brick_id: Some(brick_id), timestamp: ctx.timestamp });
    Ok(())
}

#[reducer]
pub fn set_name(ctx: &ReducerContext, user_id: u64, name: String) -> Result<(), String> {
    if name.is_empty() { return Err("Empty name".into()); }
    let user = ctx.db.user().id().find(user_id).ok_or("Not found")?;
    ctx.db.user().id().update(User { name, ..user });
    Ok(())
}

#[reducer]
pub fn set_color(ctx: &ReducerContext, user_id: u64, color: Color) -> Result<(), String> {
    let user = ctx.db.user().id().find(user_id).ok_or("Not found")?;
    ctx.db.user().id().update(User { color, ..user });
    Ok(())
}

#[reducer]
pub fn update_cursor(ctx: &ReducerContext, user_id: u64, x: i32, y: i32, z: i32) {
    let cursor = Cursor { user_id, position: Position { x, y, z } };
    if ctx.db.cursor().user_id().find(&user_id).is_some() {
        ctx.db.cursor().user_id().update(cursor);
    } else {
        ctx.db.cursor().insert(cursor);
    }
}

#[reducer]
pub fn start_drag(ctx: &ReducerContext, user_id: u64, brick_id: u64) -> Result<(), String> {
    let brick = ctx.db.brick().id().find(brick_id).ok_or("Not found")?;
    if brick.dragged_by.is_some() { return Err("Already being dragged".into()); }
    ctx.db.brick().id().update(Brick { dragged_by: Some(user_id), ..brick });
    ctx.db.event().insert(Event { id: 0, kind: EventKind::DragStarted, user_id, brick_id: Some(brick_id), timestamp: ctx.timestamp });
    Ok(())
}

#[reducer]
pub fn end_drag(ctx: &ReducerContext, user_id: u64) {
    for brick in ctx.db.brick().iter().filter(|b| b.dragged_by == Some(user_id)).collect::<Vec<_>>() {
        ctx.db.brick().id().update(Brick { dragged_by: None, ..brick });
        ctx.db.event().insert(Event { id: 0, kind: EventKind::DragEnded, user_id, brick_id: Some(brick.id), timestamp: ctx.timestamp });
    }
}

#[reducer]
pub fn move_brick(ctx: &ReducerContext, user_id: u64, brick_id: u64, x: i32, y: i32) {
    if let Some(brick) = ctx.db.brick().id().find(brick_id) {
        if brick.dragged_by != Some(user_id) { return; }
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
}
