use spacetimedb::{reducer, ReducerContext, Table};
use crate::models::*;
use crate::render;

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

fn log_event(ctx: &ReducerContext, kind: EventKind, brick_id: Option<u64>) {
    ctx.db.event().insert(Event {
        id: 0,
        kind,
        identity: ctx.sender(),
        brick_id,
        timestamp: ctx.timestamp,
    });
}

fn broadcast(ctx: &ReducerContext) {
    for user in ctx.db.user().iter().filter(|u| u.online) {
        let html = render::render_body(&ctx.db, Some(&user.identity));
        // Upsert: delete old row if present, then insert new one
        let _ = ctx.db.html_broadcast().identity().delete(&user.identity);
        ctx.db.html_broadcast().insert(HtmlBroadcast {
            identity: user.identity,
            html,
        });
    }
}

// --- Lifecycle ---

#[reducer(client_connected)]
pub fn on_connect(ctx: &ReducerContext) {
    let identity = ctx.sender();
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
    let identity = ctx.sender();
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

// --- Actions ---

#[reducer]
pub fn create_brick(ctx: &ReducerContext, x: i32, y: i32) {
    let z = ctx.db.brick().iter()
        .filter(|b| b.position.x == x && b.position.y == y)
        .count() as i32;
    if z >= 5 { return; }
    let color = ctx.db.user().identity().find(&ctx.sender())
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
    let brick = ctx.db.brick().id().find(brick_id).ok_or("Not found")?;
    let (x, y) = (brick.position.x, brick.position.y);
    ctx.db.brick().id().delete(brick_id);
    restack_cell(ctx, x, y);
    log_event(ctx, EventKind::BrickDeleted, Some(brick_id));
    broadcast(ctx);
    Ok(())
}

#[reducer]
pub fn set_name(ctx: &ReducerContext, name: String) -> Result<(), String> {
    if name.is_empty() { return Err("Empty name".into()); }
    let user = ctx.db.user().identity().find(ctx.sender()).ok_or("Not found")?;
    ctx.db.user().identity().update(User { name, ..user });
    broadcast(ctx);
    Ok(())
}

#[reducer]
pub fn set_color(ctx: &ReducerContext, color: Color) -> Result<(), String> {
    let user = ctx.db.user().identity().find(ctx.sender()).ok_or("Not found")?;
    ctx.db.user().identity().update(User { color, ..user });
    broadcast(ctx);
    Ok(())
}

#[reducer]
pub fn update_cursor(ctx: &ReducerContext, x: i32, y: i32, z: i32) {
    let cursor = Cursor { identity: ctx.sender(), position: Position { x, y, z } };
    if ctx.db.cursor().identity().find(&ctx.sender()).is_some() {
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
    ctx.db.brick().id().update(Brick { dragged_by: Some(ctx.sender()), ..brick });
    log_event(ctx, EventKind::DragStarted, Some(brick_id));
    broadcast(ctx);
    Ok(())
}

#[reducer]
pub fn end_drag(ctx: &ReducerContext) {
    for brick in ctx.db.brick().iter()
        .filter(|b| b.dragged_by.as_ref() == Some(&ctx.sender()))
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
        if brick.dragged_by.as_ref() != Some(&ctx.sender()) { return; }
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
