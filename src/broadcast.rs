//! Broadcasting state to connected browsers via htmx morph updates.
//!
//! Renders the minijinja template and pushes HTML fragments over a broadcast
//! channel. Each connected WebSocket subscriber receives morph updates that
//! include the grid, sidebar, cursors, and console log.

use crate::module_bindings::*;
use spacetimedb_sdk::Table;
use std::sync::LazyLock;
use tokio::sync::broadcast;

const GRID_SIZE: i32 = 12;

// --- Template types (needed because SpacetimeDB types don't impl serde::Serialize) ---

#[derive(serde::Serialize)]
pub struct Block {
    id: u64,
    grid_x: i32,
    grid_y: i32,
    grid_z: i32,
    color: String,
    is_being_dragged: bool,
}

#[derive(serde::Serialize)]
pub struct User {
    name: String,
    color: String,
    online: bool,
}

#[derive(serde::Serialize)]
struct Cursor {
    session_id: String,
    grid_x: i32,
    grid_y: i32,
    color: String,
    name: String,
}

#[derive(serde::Serialize)]
struct LogEntry {
    id: u64,
    message: String,
    color: String,
}

// --- Template engine (cached 2s for live editing without per-render disk reads) ---

use std::sync::Mutex;
use std::time::Instant;

static TEMPLATE_CACHE: LazyLock<Mutex<(minijinja::Environment<'static>, Instant)>> =
    LazyLock::new(|| {
        Mutex::new((load_template_from_disk(), Instant::now()))
    });

fn load_template_from_disk() -> minijinja::Environment<'static> {
    let source = std::fs::read_to_string(rocket::fs::relative!("templates/index.html.j2"))
        .expect("Failed to read template file");
    let mut env = minijinja::Environment::new();
    env.add_template_owned("index", source).expect("Failed to add template");
    env
}

fn load_template() -> minijinja::Environment<'static> {
    let mut cache = TEMPLATE_CACHE.lock().unwrap();
    if cache.1.elapsed().as_secs() >= 2 {
        *cache = (load_template_from_disk(), Instant::now());
    }
    cache.0.clone()
}

fn template_context(tables: &RemoteTables, current_session_id: &str) -> minijinja::Value {
    // Collect IDs of blocks being dragged by any user
    let dragged_ids: std::collections::HashSet<u64> = tables.user_cursor().iter()
        .filter(|c| c.dragging_block_id > 0)
        .map(|c| c.dragging_block_id)
        .collect();

    let mut blocks: Vec<Block> = tables.scene_object().iter()
        .map(|object| Block {
            id: object.id,
            grid_x: object.grid_x,
            grid_y: object.grid_y,
            grid_z: object.grid_z,
            color: object.color.clone(),
            is_being_dragged: dragged_ids.contains(&object.id),
        })
        .collect();
    blocks.sort_by_key(|block| (block.id, block.grid_z));

    let users: Vec<User> = tables.user_info().iter()
        .map(|user| User {
            name: user.name.clone(),
            color: user.color.clone(),
            online: user.online,
        })
        .collect();

    let cursors: Vec<Cursor> = tables.user_cursor().iter().filter_map(|cursor| {
        let user = tables.user_info().session_id().find(&cursor.session_id)?;
        Some(Cursor {
            session_id: cursor.session_id.clone(),
            grid_x: cursor.grid_x,
            grid_y: cursor.grid_y,
            color: user.color.clone(),
            name: user.name.clone(),
        })
    }).collect();

    let mut logs: Vec<LogEntry> = tables.console_log().iter()
        .map(|entry| LogEntry {
            id: entry.id,
            message: entry.message.clone(),
            color: entry.color.clone(),
        })
        .collect();
    logs.sort_by_key(|entry| entry.id);

    minijinja::context! {
        blocks => blocks,
        users => users,
        cursors => cursors,
        logs => logs,
        grid_size => GRID_SIZE,
        current_session_id => current_session_id,
    }
}

// --- Rendering ---

pub fn render_full_page(tables: &RemoteTables) -> String {
    let env = load_template();
    let template = env.get_template("index").unwrap();
    template.render(template_context(tables, "")).unwrap()
}

pub fn render_morph_for_session(tables: &RemoteTables, session_id: &str) -> String {
    let env = load_template();
    let template = env.get_template("index").unwrap();
    let ctx = template_context(tables, session_id);
    let grid = {
        let mut state = template.eval_to_state(ctx.clone()).unwrap();
        state.render_block("grid").unwrap()
    };
    let console = {
        let mut state = template.eval_to_state(ctx).unwrap();
        state.render_block("console").unwrap()
    };

    format!(
        "<htmx target=\"#app\" swap=\"morph:innerHTML\">{grid}</htmx>\
         <htmx target=\"#console-morph\" swap=\"morph:innerHTML\">{console}</htmx>"
    )
}

// --- Broadcast ---

/// Send a "refresh" signal — each WebSocket renders its own personalized HTML.
pub fn notify_refresh(broadcaster: &broadcast::Sender<String>) {
    let _ = broadcaster.send(String::new());
}
