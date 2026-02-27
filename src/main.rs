#[macro_use]
extern crate rocket;

mod module_bindings;

use module_bindings::*;
use rocket::fs::FileServer;
use rocket::futures::{SinkExt, StreamExt};
use rocket::response::content::RawHtml;
use rocket::State;
use rocket_ws::Message;
use spacetimedb_sdk::{DbContext, Table, TableWithPrimaryKey};
use std::sync::Arc;
use tokio::sync::broadcast;

const GRID_SIZE: i32 = 8;

#[derive(serde::Serialize)]
struct Block {
    id: u64,
    grid_x: i32,
    grid_y: i32,
    color: String,
}

#[derive(serde::Serialize)]
struct User {
    name: String,
    color: String,
    online: bool,
}

struct AppState {
    database: Arc<DbConnection>,
    broadcaster: broadcast::Sender<String>,
}

// --- Template rendering ---

fn template_engine() -> &'static minijinja::Environment<'static> {
    use std::sync::OnceLock;
    static ENGINE: OnceLock<minijinja::Environment<'static>> = OnceLock::new();
    ENGINE.get_or_init(|| {
        let source = std::fs::read_to_string(rocket::fs::relative!("templates/index.html.j2"))
            .expect("Failed to read template file");
        let mut engine = minijinja::Environment::new();
        engine.add_template_owned("index", source).expect("Failed to add template");
        engine
    })
}

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

fn render_full_page(tables: &RemoteTables) -> String {
    let template = template_engine().get_template("index").unwrap();
    template.render(template_context(tables)).unwrap()
}

fn render_body_block(tables: &RemoteTables) -> String {
    let template = template_engine().get_template("index").unwrap();
    let mut state = template.eval_to_state(template_context(tables)).unwrap();
    state.render_block("body").unwrap()
}

// --- Broadcasting to all connected browsers ---

fn broadcast_morph(broadcaster: &broadcast::Sender<String>, tables: &RemoteTables) {
    let body = render_body_block(tables);
    let _ = broadcaster.send(
        format!("<htmx target=\"#app\" swap=\"morph:innerHTML\">{body}</htmx>")
    );
}

fn broadcast_console(broadcaster: &broadcast::Sender<String>, message: &str, color: &str) {
    let event = serde_json::json!({
        "console-log": { "msg": message, "color": color }
    });
    let _ = broadcaster.send(format!("<htmx trigger='{event}'></htmx>"));
}

fn broadcast_cursors(broadcaster: &broadcast::Sender<String>, tables: &RemoteTables) {
    #[derive(serde::Serialize)]
    struct CursorPosition {
        grid_x: i32,
        grid_y: i32,
        color: String,
        name: String,
    }

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

fn broadcast_state_and_log(
    broadcaster: &broadcast::Sender<String>,
    context: &ReducerEventContext,
    message: &str,
    color: &str,
) {
    broadcast_morph(broadcaster, &context.db);
    broadcast_console(broadcaster, message, color);
}

// --- WebSocket message dispatch ---

fn handle_ws_message(text: &str, database: &DbConnection, broadcaster: &broadcast::Sender<String>) {
    let Ok(message) = serde_json::from_str::<serde_json::Value>(text) else {
        eprintln!("WebSocket: invalid JSON: {text}");
        return;
    };

    if let Some(name) = message.get("set_name").and_then(|v| v.as_str()) {
        let broadcaster = broadcaster.clone();
        let _ = database.reducers.set_name_then(name.to_string(), move |context, _| {
            broadcast_morph(&broadcaster, &context.db);
        });
        return;
    }

    let Some(action) = message.get("action").and_then(|v| v.as_str()) else { return };

    if action == "create" {
        let x = (random_u64() % GRID_SIZE as u64) as i32;
        let y = (random_u64() % GRID_SIZE as u64) as i32;
        let broadcaster = broadcaster.clone();
        let _ = database.reducers.create_object_then(x, y, random_color(), move |context, _| {
            broadcast_state_and_log(&broadcaster, context, &format!("block created at ({x},{y})"), "text-cyan-400");
        });
    } else if let Some(coordinates) = action.strip_prefix("create_at:") {
        let mut parts = coordinates.split(',').filter_map(|s| s.parse::<i32>().ok());
        if let (Some(x), Some(y)) = (parts.next(), parts.next()) {
            let broadcaster = broadcaster.clone();
            let _ = database.reducers.create_object_then(x, y, random_color(), move |context, _| {
                broadcast_state_and_log(&broadcaster, context, &format!("block created at ({x},{y})"), "text-cyan-400");
            });
        }
    } else if let Some(id_string) = action.strip_prefix("delete:") {
        if let Ok(id) = id_string.parse::<u64>() {
            let broadcaster = broadcaster.clone();
            let _ = database.reducers.delete_object_then(id, move |context, _| {
                broadcast_state_and_log(&broadcaster, context, "block deleted", "text-red-400");
            });
        }
    } else if action == "cursor" {
        let x = message.get("x").and_then(|v| v.as_str()).and_then(|s| s.parse().ok()).unwrap_or(0);
        let y = message.get("y").and_then(|v| v.as_str()).and_then(|s| s.parse().ok()).unwrap_or(0);
        let broadcaster = broadcaster.clone();
        let _ = database.reducers.update_cursor_then(x, y, move |context, _| {
            broadcast_cursors(&broadcaster, &context.db);
        });
    }
}

// --- Utilities ---

/// Generate a random u64 using the standard library's random hasher seed.
fn random_u64() -> u64 {
    use std::hash::{BuildHasher, Hasher};
    std::collections::hash_map::RandomState::new().build_hasher().finish()
}

fn random_color() -> String {
    const PALETTE: [&str; 8] = [
        "#ef4444", "#f97316", "#eab308", "#22c55e",
        "#06b6d4", "#3b82f6", "#8b5cf6", "#ec4899",
    ];
    PALETTE[random_u64() as usize % PALETTE.len()].to_string()
}

// --- Routes ---

#[get("/")]
fn index(app: &State<AppState>) -> RawHtml<String> {
    RawHtml(render_full_page(&app.database.db))
}

#[get("/ws")]
fn websocket(ws: rocket_ws::WebSocket, app: &State<AppState>) -> rocket_ws::Channel<'static> {
    let mut receiver = app.broadcaster.subscribe();
    let broadcaster = app.broadcaster.clone();
    let database = Arc::clone(&app.database);

    ws.channel(move |mut stream| Box::pin(async move {
        loop {
            tokio::select! {
                result = receiver.recv() => match result {
                    Ok(html) => {
                        if stream.send(Message::Text(html)).await.is_err() { break }
                    }
                    Err(_) => break,
                },
                incoming = stream.next() => match incoming {
                    Some(Ok(Message::Text(text))) => {
                        handle_ws_message(&text, &database, &broadcaster);
                    }
                    Some(Ok(_)) => {} // ignore binary/ping/pong
                    _ => break,
                },
            }
        }
        Ok(())
    }))
}

// --- Table change callbacks ---

/// Register insert/delete/update callbacks on a table that all call the same handler.
macro_rules! on_table_change {
    ($table:expr, $broadcaster:expr, $handler:expr) => {{
        let broadcaster = $broadcaster.clone();
        $table.on_insert(move |context, _| $handler(&broadcaster, &context.db));
        let broadcaster = $broadcaster.clone();
        $table.on_delete(move |context, _| $handler(&broadcaster, &context.db));
        let broadcaster = $broadcaster.clone();
        $table.on_update(move |context, _, _| $handler(&broadcaster, &context.db));
    }};
}

#[launch]
fn rocket() -> _ {
    let (broadcaster, _) = broadcast::channel::<String>(256);

    let database = DbConnection::builder()
        .with_uri("http://localhost:3000")
        .with_database_name("hyperspace")
        .on_connect(|_context, _identity, _token| {
            println!("Connected to SpacetimeDB");
        })
        .on_connect_error(|_context, _error| {
            eprintln!("SpacetimeDB connection error");
            std::process::exit(1);
        })
        .build()
        .expect("Failed to connect to SpacetimeDB");

    // Scene objects and cursors: broadcast updated state to all browsers.
    // Console messages come from reducer _then callbacks in handle_ws_message.
    on_table_change!(database.db.scene_object(), broadcaster, broadcast_morph);
    on_table_change!(database.db.user_cursor(), broadcaster, broadcast_cursors);

    // User info: also log join/leave to the console.
    {
        let broadcaster_clone = broadcaster.clone();
        database.db.user_info().on_insert(move |context, user| {
            broadcast_morph(&broadcaster_clone, &context.db);
            broadcast_console(&broadcaster_clone, &format!("{} joined", user.name), "text-green-400");
        });
        let broadcaster_clone = broadcaster.clone();
        database.db.user_info().on_delete(move |context, user| {
            broadcast_morph(&broadcaster_clone, &context.db);
            broadcast_console(&broadcaster_clone, &format!("{} left", user.name), "text-gray-400");
        });
        let broadcaster_clone = broadcaster.clone();
        database.db.user_info().on_update(move |context, _, _| {
            broadcast_morph(&broadcaster_clone, &context.db);
        });
    }

    database.subscription_builder()
        .on_applied(|context| {
            println!(
                "Subscribed — {} objects, {} users",
                context.db.scene_object().count(),
                context.db.user_info().count(),
            );
        })
        .subscribe_to_all_tables();

    // Run the SpacetimeDB event loop in a dedicated thread.
    let database = Arc::new(database);
    {
        let database_clone = Arc::clone(&database);
        std::thread::spawn(move || {
            while database_clone.advance_one_message_blocking().is_ok() {}
        });
    }

    rocket::build()
        .manage(AppState { database, broadcaster })
        .mount("/", routes![index, websocket])
        .mount("/static", FileServer::from(rocket::fs::relative!("static")))
}
