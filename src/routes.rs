use std::sync::LazyLock;

use minijinja::{context, Environment};
use spacetimedb::{get, post, Html, Redirect, RouteContext, Table};

use crate::models::*;

// --- Template engine ---

static TEMPLATES: LazyLock<Environment<'static>> = LazyLock::new(|| {
    let mut env = Environment::new();
    env.add_template("index", include_str!("../templates/index.html.j2"))
        .unwrap();
    env
});

fn render(name: &str, ctx: minijinja::Value) -> String {
    TEMPLATES
        .get_template(name)
        .unwrap()
        .render(ctx)
        .unwrap()
}

// --- View types (serializable for templates) ---

#[derive(serde::Serialize)]
struct BrickView {
    id: u64,
    x: i32,
    y: i32,
    z: i32,
    color: String,
    dragged_by: Option<u64>,
}

#[derive(serde::Serialize)]
struct UserView {
    id: u64,
    name: String,
    color: String,
    online: bool,
}

#[derive(serde::Serialize)]
struct CursorView {
    user_id: u64,
    x: i32,
    y: i32,
    z: i32,
    color: String,
    name: String,
}

#[derive(serde::Serialize)]
struct EventView {
    id: u64,
    kind: String,
    user_id: u64,
    brick_id: Option<u64>,
}

fn color_name(c: &Color) -> &str {
    match c {
        Color::Cyan => "Cyan",
        Color::Purple => "Purple",
        Color::Orange => "Orange",
        Color::Green => "Green",
        Color::Pink => "Pink",
        Color::Yellow => "Yellow",
    }
}

fn event_kind_name(k: &EventKind) -> &str {
    match k {
        EventKind::UserConnected => "UserConnected",
        EventKind::UserDisconnected => "UserDisconnected",
        EventKind::BrickCreated => "BrickCreated",
        EventKind::BrickDeleted => "BrickDeleted",
        EventKind::DragStarted => "DragStarted",
        EventKind::DragEnded => "DragEnded",
    }
}

fn world_state(ctx: &RouteContext) -> minijinja::Value {
    let bricks: Vec<BrickView> = ctx
        .db
        .brick()
        .iter()
        .map(|b| BrickView {
            id: b.id,
            x: b.position.x,
            y: b.position.y,
            z: b.position.z,
            color: color_name(&b.color).to_string(),
            dragged_by: b.dragged_by,
        })
        .collect();

    let users: Vec<UserView> = ctx
        .db
        .user()
        .iter()
        .map(|u| UserView {
            id: u.id,
            name: u.name.clone(),
            color: color_name(&u.color).to_string(),
            online: u.online,
        })
        .collect();

    let cursors: Vec<CursorView> = ctx
        .db
        .cursor()
        .iter()
        .filter_map(|c| {
            let user = ctx.db.user().id().find(&c.user_id)?;
            Some(CursorView {
                user_id: c.user_id,
                x: c.position.x,
                y: c.position.y,
                z: c.position.z,
                color: color_name(&user.color).to_string(),
                name: user.name.clone(),
            })
        })
        .collect();

    let events: Vec<EventView> = ctx
        .db
        .event()
        .iter()
        .map(|e| EventView {
            id: e.id,
            kind: event_kind_name(&e.kind).to_string(),
            user_id: e.user_id,
            brick_id: e.brick_id,
        })
        .collect();

    context! {
        bricks,
        users,
        cursors,
        events,
        grid_size => 12,
        current_user_id => 0u64,
    }
}

// --- Routes ---

#[get("/")]
fn index(ctx: &RouteContext) -> Html {
    Html(render("index", world_state(ctx)))
}

#[post("/brick")]
fn create_brick(ctx: &RouteContext) -> Redirect {
    let x: i32 = ctx
        .request
        .form_field("x")
        .and_then(|v| v.parse().ok())
        .unwrap_or(0);
    let y: i32 = ctx
        .request
        .form_field("y")
        .and_then(|v| v.parse().ok())
        .unwrap_or(0);

    let z = ctx
        .db
        .brick()
        .iter()
        .filter(|b| b.position.x == x && b.position.y == y)
        .count() as i32;

    if z < 5 {
        let color = Color::Cyan; // Default color without user context
        ctx.db.brick().insert(Brick {
            id: 0,
            position: Position { x, y, z },
            color,
            dragged_by: None,
        });
    }

    Redirect::to("/")
}

#[post("/brick/:id/delete")]
fn delete_brick(ctx: &RouteContext) -> Redirect {
    let id: u64 = ctx
        .request
        .path_param("id")
        .and_then(|v| v.parse().ok())
        .unwrap_or(0);

    if ctx.db.brick().id().find(id).is_some() {
        ctx.db.brick().id().delete(id);
    }

    Redirect::to("/")
}
