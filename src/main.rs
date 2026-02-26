#[macro_use]
extern crate rocket;

mod module_bindings;

use module_bindings::*;
use rocket::fs::FileServer;
use rocket::futures::{SinkExt, StreamExt};
use rocket::State;
use rocket_dyn_templates::{context, Template};
use rocket_ws::Message;
use spacetimedb_sdk::{DbContext, Table, TableWithPrimaryKey};
use std::sync::Arc;
use tokio::sync::broadcast;

const GRID_SIZE: i32 = 8;

#[derive(serde::Serialize)]
struct ObjCtx { id: u64, grid_x: i32, grid_y: i32, color: String }

#[derive(serde::Serialize)]
struct UserCtx { name: String, color: String, online: bool }

struct App {
    db: Arc<DbConnection>,
    tx: broadcast::Sender<String>,
}

// --- Broadcast helpers ---

fn render_body(db: &RemoteTables) -> String {
    let objects: Vec<ObjCtx> = db.scene_object().iter()
        .map(|o| ObjCtx { id: o.id, grid_x: o.grid_x, grid_y: o.grid_y, color: o.color.clone() })
        .collect();
    let users: Vec<UserCtx> = db.user_info().iter()
        .map(|u| UserCtx { name: u.name.clone(), color: u.color.clone(), online: u.online })
        .collect();

    let template_src = std::fs::read_to_string("templates/index.html.j2")
        .expect("Failed to read template file");
    let mut env = minijinja::Environment::new();
    env.add_template("index", &template_src).expect("Failed to add template");
    let tmpl = env.get_template("index").unwrap();
    let mut state = tmpl.eval_to_state(minijinja::context! {
        objects => objects,
        users => users,
        grid_size => GRID_SIZE,
    }).unwrap();
    state.render_block("body").unwrap()
}

fn broadcast_morph(tx: &broadcast::Sender<String>, db: &RemoteTables) {
    let body = render_body(db);
    let _ = tx.send(format!("<htmx target=\"#app\" swap=\"morph:innerHTML\">{body}</htmx>"));
}

fn broadcast_console(tx: &broadcast::Sender<String>, msg: &str, color: &str) {
    let escaped = msg.replace('"', "\\\"");
    let _ = tx.send(format!(
        "<htmx trigger='{{\"console-log\": {{\"msg\": \"{escaped}\", \"color\": \"{color}\"}}}}'></htmx>"
    ));
}

fn broadcast_cursors(tx: &broadcast::Sender<String>, db: &RemoteTables) {
    #[derive(serde::Serialize)]
    struct Cursor { grid_x: i32, grid_y: i32, color: String, name: String }

    let data: Vec<Cursor> = db.user_cursor().iter().map(|c| {
        let u = db.user_info().identity().find(&c.identity);
        Cursor {
            grid_x: c.grid_x,
            grid_y: c.grid_y,
            color: u.as_ref().map(|u| u.color.clone()).unwrap_or_else(|| "#888".into()),
            name: u.as_ref().map(|u| u.name.clone()).unwrap_or_else(|| "?".into()),
        }
    }).collect();
    let json = serde_json::to_string(&data).unwrap();
    let _ = tx.send(format!(
        "<htmx trigger='{{\"cursor-update\": {{\"cursors\": {json}}}}}'></htmx>"
    ));
}

/// Dispatch a browser message to SpacetimeDB reducers.
fn handle_ws_message(text: &str, db: &DbConnection) {
    let Ok(val) = serde_json::from_str::<serde_json::Value>(text) else {
        eprintln!("WS: invalid JSON: {text}");
        return;
    };

    // {"set_name": "Alice"}
    if let Some(name) = val.get("set_name").and_then(|v| v.as_str()) {
        let _ = db.reducers.set_name(name.to_string());
        return;
    }

    // {"action": "..."}
    if let Some(action) = val.get("action").and_then(|v| v.as_str()) {
        if action == "create" {
            // Random position on grid
            let x = (random_u64() % GRID_SIZE as u64) as i32;
            let y = (random_u64() % GRID_SIZE as u64) as i32;
            let _ = db.reducers.create_object(x, y, random_color());
        } else if let Some(coords) = action.strip_prefix("create_at:") {
            // "create_at:3,2" from grid cell click
            let mut parts = coords.split(',').filter_map(|s| s.parse::<i32>().ok());
            if let (Some(x), Some(y)) = (parts.next(), parts.next()) {
                let _ = db.reducers.create_object(x, y, random_color());
            }
        } else if let Some(id_str) = action.strip_prefix("delete:") {
            if let Ok(id) = id_str.parse::<u64>() {
                let _ = db.reducers.delete_object(id);
            }
        } else if action == "cursor" {
            let x = val.get("x").and_then(|v| v.as_str()).and_then(|s| s.parse().ok()).unwrap_or(0);
            let y = val.get("y").and_then(|v| v.as_str()).and_then(|s| s.parse().ok()).unwrap_or(0);
            let _ = db.reducers.update_cursor(x, y);
        }
    }
}

fn random_u64() -> u64 {
    use std::collections::hash_map::RandomState;
    use std::hash::{BuildHasher, Hasher};
    let s = RandomState::new();
    let mut h = s.build_hasher();
    h.write_u8(0);
    h.finish()
}

fn random_color() -> String {
    let colors = [
        "#ef4444", "#f97316", "#eab308", "#22c55e",
        "#06b6d4", "#3b82f6", "#8b5cf6", "#ec4899",
    ];
    colors[(random_u64() as usize) % colors.len()].to_string()
}

// --- Routes ---

#[get("/")]
fn index(app: &State<App>) -> Template {
    let objects: Vec<_> = app.db.db.scene_object().iter()
        .map(|o| context! { id: o.id, grid_x: o.grid_x, grid_y: o.grid_y, color: o.color.clone() })
        .collect();
    let users: Vec<_> = app.db.db.user_info().iter()
        .map(|u| context! { name: u.name.clone(), color: u.color.clone(), online: u.online })
        .collect();

    Template::render("index", context! {
        objects: objects,
        users: users,
        grid_size: GRID_SIZE,
    })
}

#[get("/ws")]
fn websocket(ws: rocket_ws::WebSocket, app: &State<App>) -> rocket_ws::Channel<'static> {
    let mut rx = app.tx.subscribe();
    let db = Arc::clone(&app.db);

    ws.channel(move |mut stream| Box::pin(async move {
        loop {
            tokio::select! {
                result = rx.recv() => {
                    match result {
                        Ok(msg) => {
                            if stream.send(Message::Text(msg)).await.is_err() {
                                break;
                            }
                        }
                        Err(_) => break,
                    }
                }
                msg = stream.next() => {
                    match msg {
                        Some(Ok(Message::Text(text))) => {
                            handle_ws_message(&text, &db);
                        }
                        Some(Ok(_)) => {} // ignore binary/ping/pong
                        _ => break,
                    }
                }
            }
        }
        Ok(())
    }))
}

#[launch]
fn rocket() -> _ {
    let (tx, _) = broadcast::channel::<String>(256);

    let db = DbConnection::builder()
        .with_uri("http://localhost:3000")
        .with_database_name("hyperspace")
        .on_connect(|_ctx, _identity, _token| {
            println!("Connected to SpacetimeDB");
        })
        .on_connect_error(|_ctx, _err| {
            eprintln!("SpacetimeDB connection error");
            std::process::exit(1);
        })
        .build()
        .expect("Failed to connect to SpacetimeDB");

    // Register table change callbacks
    {
        // scene_object: on_insert
        let tx_clone = tx.clone();
        db.db.scene_object().on_insert(move |ctx, obj| {
            broadcast_morph(&tx_clone, &ctx.db);
            broadcast_console(
                &tx_clone,
                &format!("block created at ({},{})", obj.grid_x, obj.grid_y),
                "text-cyan-400",
            );
        });

        // scene_object: on_delete
        let tx_clone = tx.clone();
        db.db.scene_object().on_delete(move |ctx, obj| {
            broadcast_morph(&tx_clone, &ctx.db);
            broadcast_console(
                &tx_clone,
                &format!("block deleted at ({},{})", obj.grid_x, obj.grid_y),
                "text-red-400",
            );
        });

        // scene_object: on_update
        let tx_clone = tx.clone();
        db.db.scene_object().on_update(move |ctx, _old, obj| {
            broadcast_morph(&tx_clone, &ctx.db);
            broadcast_console(
                &tx_clone,
                &format!("block moved to ({},{})", obj.grid_x, obj.grid_y),
                "text-yellow-400",
            );
        });

        // user_info: on_insert
        let tx_clone = tx.clone();
        db.db.user_info().on_insert(move |ctx, user| {
            broadcast_morph(&tx_clone, &ctx.db);
            broadcast_console(
                &tx_clone,
                &format!("{} joined", user.name),
                "text-green-400",
            );
        });

        // user_info: on_delete
        let tx_clone = tx.clone();
        db.db.user_info().on_delete(move |ctx, user| {
            broadcast_morph(&tx_clone, &ctx.db);
            broadcast_console(
                &tx_clone,
                &format!("{} left", user.name),
                "text-gray-400",
            );
        });

        // user_info: on_update
        let tx_clone = tx.clone();
        db.db.user_info().on_update(move |ctx, _old, user| {
            broadcast_morph(&tx_clone, &ctx.db);
            broadcast_console(
                &tx_clone,
                &format!("{} updated", user.name),
                "text-blue-400",
            );
        });

        // user_cursor: on_insert
        let tx_clone = tx.clone();
        db.db.user_cursor().on_insert(move |ctx, _cursor| {
            broadcast_cursors(&tx_clone, &ctx.db);
        });

        // user_cursor: on_update
        let tx_clone = tx.clone();
        db.db.user_cursor().on_update(move |ctx, _old, _cursor| {
            broadcast_cursors(&tx_clone, &ctx.db);
        });

        // user_cursor: on_delete
        let tx_clone = tx.clone();
        db.db.user_cursor().on_delete(move |ctx, _cursor| {
            broadcast_cursors(&tx_clone, &ctx.db);
        });
    }

    db.subscription_builder()
        .on_applied(|ctx| {
            println!(
                "Subscribed — {} objects, {} users",
                ctx.db.scene_object().count(),
                ctx.db.user_info().count(),
            );
        })
        .subscribe_to_all_tables();

    // Run SDK event loop in background
    let _db_handle = db.run_threaded();

    let app = App { db: Arc::new(db), tx };

    rocket::build()
        .manage(app)
        .attach(Template::fairing())
        .mount("/", routes![index, websocket])
        .mount("/static", FileServer::from("static"))
}
