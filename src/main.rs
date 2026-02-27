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
    let database = Arc::clone(&app.database);

    let _ = database.reducers.join(session_id.clone());

    ws.channel(move |mut stream| Box::pin(async move {
        loop {
            tokio::select! {
                result = receiver.recv() => match result {
                    Ok(_) => {
                        // Coalesce: drain any queued notifications so we render once
                        while receiver.try_recv().is_ok() {}
                        let html = render_morph_for_session(&database.db, &session_id);
                        if stream.send(Message::Text(html)).await.is_err() { break }
                    }
                    Err(_) => break,
                },
                incoming = stream.next() => match incoming {
                    Some(Ok(Message::Text(text))) => {
                        handle_browser_message(&text, &session_id, &database);
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
) {
    let Ok(message) = serde_json::from_str::<serde_json::Value>(text) else {
        eprintln!("WebSocket: invalid JSON: {text}");
        return;
    };

    if let Some(name) = message.get("set_name").and_then(|v| v.as_str()) {
        let _ = database.reducers.set_name(session_id.to_string(), name.to_string());
        return;
    }

    if let Some(color) = message.get("set_color").and_then(|v| v.as_str()) {
        let _ = database.reducers.set_color(session_id.to_string(), color.to_string());
        return;
    }

    let Some(action) = message.get("action").and_then(|v| v.as_str()) else { return };

    if action == "create" {
        let x = (random_u64() % 8) as i32;
        let y = (random_u64() % 8) as i32;
        let _ = database.reducers.create_object(session_id.to_string(), x, y);
    } else if let Some(coordinates) = action.strip_prefix("create_at:") {
        let mut parts = coordinates.split(',').filter_map(|s| s.parse::<i32>().ok());
        if let (Some(x), Some(y)) = (parts.next(), parts.next()) {
            let _ = database.reducers.create_object(session_id.to_string(), x, y);
        }
    } else if let Some(id_string) = action.strip_prefix("delete:") {
        if let Ok(id) = id_string.parse::<u64>() {
            let _ = database.reducers.delete_object(id);
        }
    } else if action == "mouseenter" || action == "pointerdown" {
        let x = message.get("x").and_then(|v| v.as_str()).and_then(|s| s.parse().ok());
        let y = message.get("y").and_then(|v| v.as_str()).and_then(|s| s.parse().ok());
        if let (Some(x), Some(y)) = (x, y) {
            if action == "mouseenter" {
                let _ = database.reducers.handle_mouseenter(session_id.to_string(), x, y);
            } else {
                let _ = database.reducers.handle_pointerdown(session_id.to_string(), x, y);
            }
        }
    } else if action == "pointerup" {
        let _ = database.reducers.handle_pointerup(session_id.to_string());
    }
}

// --- Startup ---

/// Register insert/delete/update callbacks on a table that all broadcast a morph update.
macro_rules! on_table_change {
    ($table:expr, $broadcaster:expr) => {{
        let broadcaster = $broadcaster.clone();
        $table.on_insert(move |_context, _| notify_refresh(&broadcaster));
        let broadcaster = $broadcaster.clone();
        $table.on_delete(move |_context, _| notify_refresh(&broadcaster));
        let broadcaster = $broadcaster.clone();
        $table.on_update(move |_context, _, _| notify_refresh(&broadcaster));
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

    on_table_change!(database.db.scene_object(), broadcaster);
    on_table_change!(database.db.user_cursor(), broadcaster);
    on_table_change!(database.db.user_info(), broadcaster);
    on_table_change!(database.db.console_log(), broadcaster);

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
