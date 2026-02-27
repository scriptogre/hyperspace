//! Broadcasting state to connected browsers via htmx server-commands.
//!
//! Renders the minijinja template and pushes HTML fragments over a broadcast
//! channel. Each connected WebSocket subscriber receives morph updates,
//! console messages, and cursor positions.

use crate::module_bindings::*;
use spacetimedb_sdk::Table;
use std::sync::LazyLock;
use tokio::sync::broadcast;

const GRID_SIZE: i32 = 8;

// --- Template types (needed because SpacetimeDB types don't impl serde::Serialize) ---

#[derive(serde::Serialize)]
pub struct Block {
    id: u64,
    grid_x: i32,
    grid_y: i32,
    color: String,
}

#[derive(serde::Serialize)]
pub struct User {
    name: String,
    color: String,
    online: bool,
}

#[derive(serde::Serialize)]
struct CursorPosition {
    grid_x: i32,
    grid_y: i32,
    color: String,
    name: String,
}

// --- Template engine (cached, loaded once) ---

static TEMPLATES: LazyLock<minijinja::Environment<'static>> = LazyLock::new(|| {
    let source = std::fs::read_to_string(rocket::fs::relative!("templates/index.html.j2"))
        .expect("Failed to read template file");
    let mut engine = minijinja::Environment::new();
    engine.add_template_owned("index", source).expect("Failed to add template");
    engine
});

fn template_context(tables: &RemoteTables) -> minijinja::Value {
    let mut blocks: Vec<Block> = tables.scene_object().iter()
        .map(|object| Block {
            id: object.id,
            grid_x: object.grid_x,
            grid_y: object.grid_y,
            color: object.color.clone(),
        })
        .collect();
    blocks.sort_by_key(|block| block.id);

    let users: Vec<User> = tables.user_info().iter()
        .map(|user| User {
            name: user.name.clone(),
            color: user.color.clone(),
            online: user.online,
        })
        .collect();

    minijinja::context! {
        objects => blocks,
        users => users,
        grid_size => GRID_SIZE,
    }
}

// --- Rendering ---

pub fn render_full_page(tables: &RemoteTables) -> String {
    let template = TEMPLATES.get_template("index").unwrap();
    template.render(template_context(tables)).unwrap()
}

fn render_body_block(tables: &RemoteTables) -> String {
    let template = TEMPLATES.get_template("index").unwrap();
    let mut state = template.eval_to_state(template_context(tables)).unwrap();
    state.render_block("body").unwrap()
}

// --- Broadcast functions ---

pub fn broadcast_morph(broadcaster: &broadcast::Sender<String>, tables: &RemoteTables) {
    let body = render_body_block(tables);
    let _ = broadcaster.send(
        format!("<htmx target=\"#app\" swap=\"morph:innerHTML\">{body}</htmx>")
    );
}

pub fn broadcast_console(broadcaster: &broadcast::Sender<String>, message: &str, color: &str) {
    let event = serde_json::json!({
        "console-log": { "msg": message, "color": color }
    });
    let _ = broadcaster.send(format!("<htmx trigger='{event}'></htmx>"));
}

pub fn broadcast_cursors(broadcaster: &broadcast::Sender<String>, tables: &RemoteTables) {
    let cursors: Vec<CursorPosition> = tables.user_cursor().iter().map(|cursor| {
        let user = tables.user_info().identity().find(&cursor.identity);
        CursorPosition {
            grid_x: cursor.grid_x,
            grid_y: cursor.grid_y,
            color: user.as_ref().map(|u| u.color.clone()).unwrap_or_else(|| "#888".into()),
            name: user.as_ref().map(|u| u.name.clone()).unwrap_or_else(|| "?".into()),
        }
    }).collect();

    let event = serde_json::json!({ "cursor-update": { "cursors": cursors } });
    let _ = broadcaster.send(format!("<htmx trigger='{event}'></htmx>"));
}

pub fn broadcast_state_and_log(
    broadcaster: &broadcast::Sender<String>,
    context: &ReducerEventContext,
    message: &str,
    color: &str,
) {
    broadcast_morph(broadcaster, &context.db);
    broadcast_console(broadcaster, message, color);
}
