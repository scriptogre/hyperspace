#[macro_use]
extern crate rocket;

mod broadcast;
mod module_bindings;
mod utils;

use broadcast::*;
use module_bindings::*;
use utils::*;
use rocket::fs::FileServer;
use rocket::futures::{SinkExt, StreamExt};
use rocket::response::content::RawHtml;
use rocket::State;
use rocket_ws::Message;
use spacetimedb_sdk::{DbContext, Table, TableWithPrimaryKey};
use std::sync::Arc;
use tokio::sync;

// --- Application state ---

struct AppState {
    database: Arc<DbConnection>,
    broadcaster: sync::broadcast::Sender<String>,
}

// --- Routes ---

#[get("/")]
fn index(app: &State<AppState>) -> RawHtml<String> {
    RawHtml(render_full_page(&app.database.db))
}

#[get("/ws")]
fn websocket(ws: rocket_ws::WebSocket, app: &State<AppState>) -> rocket_ws::Channel<'static> {
    let session_id = format!("{:016x}", random_u64());
    let mut receiver = app.broadcaster.subscribe();
    let broadcaster = app.broadcaster.clone();
    let database = Arc::clone(&app.database);

    let _ = database.reducers.join(session_id.clone());

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
                        handle_browser_message(&text, &session_id, &database, &broadcaster);
                    }
                    Some(Ok(_)) => {}
                    _ => break,
                },
            }
        }
        let _ = database.reducers.leave(session_id);
        Ok(())
    }))
}

// --- WebSocket message dispatch ---

fn handle_browser_message(
    text: &str,
    session_id: &str,
    database: &DbConnection,
    broadcaster: &sync::broadcast::Sender<String>,
) {
    let Ok(message) = serde_json::from_str::<serde_json::Value>(text) else {
        eprintln!("WebSocket: invalid JSON: {text}");
        return;
    };

    if let Some(name) = message.get("set_name").and_then(|v| v.as_str()) {
        let broadcaster = broadcaster.clone();
        let _ = database.reducers.set_name_then(session_id.to_string(), name.to_string(), move |context, _| {
            broadcast_morph(&broadcaster, &context.db);
        });
        return;
    }

    let Some(action) = message.get("action").and_then(|v| v.as_str()) else { return };

    if action == "create" {
        let x = (random_u64() % 8) as i32;
        let y = (random_u64() % 8) as i32;
        let broadcaster = broadcaster.clone();
        let _ = database.reducers.create_object_then(session_id.to_string(), x, y, move |context, _| {
            broadcast_state_and_log(&broadcaster, context, &format!("block created at ({x},{y})"), "text-cyan-400");
        });
    } else if let Some(coordinates) = action.strip_prefix("create_at:") {
        let mut parts = coordinates.split(',').filter_map(|s| s.parse::<i32>().ok());
        if let (Some(x), Some(y)) = (parts.next(), parts.next()) {
            let broadcaster = broadcaster.clone();
            let _ = database.reducers.create_object_then(session_id.to_string(), x, y, move |context, _| {
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
        let _ = database.reducers.update_cursor_then(session_id.to_string(), x, y, move |context, _| {
            broadcast_cursors(&broadcaster, &context.db);
        });
    }
}

// --- Startup ---

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
    let (broadcaster, _) = sync::broadcast::channel::<String>(256);

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
