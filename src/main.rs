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

// --- Template helpers ---

fn cached_env() -> &'static minijinja::Environment<'static> {
    use std::sync::OnceLock;
    static ENV: OnceLock<minijinja::Environment<'static>> = OnceLock::new();
    ENV.get_or_init(|| {
        let src = std::fs::read_to_string("templates/index.html.j2")
            .expect("Failed to read template file");
        let mut env = minijinja::Environment::new();
        env.add_template_owned("index", src).expect("Failed to add template");
        env
    })
}

fn build_context(db: &RemoteTables) -> (Vec<ObjCtx>, Vec<UserCtx>) {
    let mut objects: Vec<ObjCtx> = db.scene_object().iter()
        .map(|o| ObjCtx { id: o.id, grid_x: o.grid_x, grid_y: o.grid_y, color: o.color.clone() })
        .collect();
    objects.sort_by_key(|o| o.id);
    let users = db.user_info().iter()
        .map(|u| UserCtx { name: u.name.clone(), color: u.color.clone(), online: u.online })
        .collect();
    (objects, users)
}

fn render_body(db: &RemoteTables) -> String {
    let (objects, users) = build_context(db);
    let tmpl = cached_env().get_template("index").unwrap();
    let mut state = tmpl.eval_to_state(minijinja::context! {
        objects => objects, users => users, grid_size => GRID_SIZE,
    }).unwrap();
    state.render_block("body").unwrap()
}

// --- Broadcast helpers ---

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

fn on_reducer_done(tx: &broadcast::Sender<String>, ctx: &ReducerEventContext, msg: &str, color: &str) {
    broadcast_morph(tx, &ctx.db);
    broadcast_console(tx, msg, color);
}

// --- WS dispatch ---

fn handle_ws_message(text: &str, db: &DbConnection, tx: &broadcast::Sender<String>) {
    let Ok(val) = serde_json::from_str::<serde_json::Value>(text) else {
        eprintln!("WS: invalid JSON: {text}");
        return;
    };

    if let Some(name) = val.get("set_name").and_then(|v| v.as_str()) {
        let tx = tx.clone();
        let _ = db.reducers.set_name_then(name.to_string(), move |ctx, _| {
            broadcast_morph(&tx, &ctx.db);
        });
        return;
    }

    let Some(action) = val.get("action").and_then(|v| v.as_str()) else { return };

    if action == "create" {
        let x = (random_u64() % GRID_SIZE as u64) as i32;
        let y = (random_u64() % GRID_SIZE as u64) as i32;
        let tx = tx.clone();
        let _ = db.reducers.create_object_then(x, y, random_color(), move |ctx, _| {
            on_reducer_done(&tx, ctx, &format!("block created at ({x},{y})"), "text-cyan-400");
        });
    } else if let Some(coords) = action.strip_prefix("create_at:") {
        let mut parts = coords.split(',').filter_map(|s| s.parse::<i32>().ok());
        if let (Some(x), Some(y)) = (parts.next(), parts.next()) {
            let tx = tx.clone();
            let _ = db.reducers.create_object_then(x, y, random_color(), move |ctx, _| {
                on_reducer_done(&tx, ctx, &format!("block created at ({x},{y})"), "text-cyan-400");
            });
        }
    } else if let Some(id_str) = action.strip_prefix("delete:") {
        if let Ok(id) = id_str.parse::<u64>() {
            let tx = tx.clone();
            let _ = db.reducers.delete_object_then(id, move |ctx, _| {
                on_reducer_done(&tx, ctx, &format!("block deleted"), "text-red-400");
            });
        }
    } else if action == "cursor" {
        let x = val.get("x").and_then(|v| v.as_str()).and_then(|s| s.parse().ok()).unwrap_or(0);
        let y = val.get("y").and_then(|v| v.as_str()).and_then(|s| s.parse().ok()).unwrap_or(0);
        let tx = tx.clone();
        let _ = db.reducers.update_cursor_then(x, y, move |ctx, _| {
            broadcast_cursors(&tx, &ctx.db);
        });
    }
}

fn random_u64() -> u64 {
    use std::hash::{BuildHasher, Hasher};
    std::collections::hash_map::RandomState::new().build_hasher().finish()
}

fn random_color() -> String {
    const COLORS: [&str; 8] = [
        "#ef4444", "#f97316", "#eab308", "#22c55e",
        "#06b6d4", "#3b82f6", "#8b5cf6", "#ec4899",
    ];
    COLORS[(random_u64() as usize) % COLORS.len()].to_string()
}

// --- Routes ---

#[get("/")]
fn index(app: &State<App>) -> Template {
    let (objects, users) = build_context(&app.db.db);
    Template::render("index", context! { objects: objects, users: users, grid_size: GRID_SIZE })
}

#[get("/ws")]
fn websocket(ws: rocket_ws::WebSocket, app: &State<App>) -> rocket_ws::Channel<'static> {
    let mut rx = app.tx.subscribe();
    let tx = app.tx.clone();
    let db = Arc::clone(&app.db);

    ws.channel(move |mut stream| Box::pin(async move {
        loop {
            tokio::select! {
                result = rx.recv() => match result {
                    Ok(msg) => if stream.send(Message::Text(msg)).await.is_err() { break },
                    Err(_) => break,
                },
                msg = stream.next() => match msg {
                    Some(Ok(Message::Text(text))) => handle_ws_message(&text, &db, &tx),
                    Some(Ok(_)) => {}
                    _ => break,
                },
            }
        }
        Ok(())
    }))
}

/// Register table-change callbacks that broadcast to all connected websocket clients.
macro_rules! on_table_change {
    ($table:expr, $tx:expr, $handler:expr) => {{
        let tx = $tx.clone();
        $table.on_insert(move |ctx, _| $handler(&tx, &ctx.db));
        let tx = $tx.clone();
        $table.on_delete(move |ctx, _| $handler(&tx, &ctx.db));
        let tx = $tx.clone();
        $table.on_update(move |ctx, _, _| $handler(&tx, &ctx.db));
    }};
}

#[launch]
fn rocket() -> _ {
    let (tx, _) = broadcast::channel::<String>(256);

    let db = DbConnection::builder()
        .with_uri("http://localhost:3000")
        .with_database_name("hyperspace")
        .on_connect(|_ctx, _identity, _token| println!("Connected to SpacetimeDB"))
        .on_connect_error(|_ctx, _err| {
            eprintln!("SpacetimeDB connection error");
            std::process::exit(1);
        })
        .build()
        .expect("Failed to connect to SpacetimeDB");

    // Table change callbacks — morph/cursor broadcasts for multi-user sync.
    // Console messages come from reducer _then callbacks in handle_ws_message.
    on_table_change!(db.db.scene_object(), tx, broadcast_morph);
    on_table_change!(db.db.user_cursor(), tx, broadcast_cursors);

    // user_info needs extra console broadcasts for join/leave
    {
        let tx_clone = tx.clone();
        db.db.user_info().on_insert(move |ctx, user| {
            broadcast_morph(&tx_clone, &ctx.db);
            broadcast_console(&tx_clone, &format!("{} joined", user.name), "text-green-400");
        });
        let tx_clone = tx.clone();
        db.db.user_info().on_delete(move |ctx, user| {
            broadcast_morph(&tx_clone, &ctx.db);
            broadcast_console(&tx_clone, &format!("{} left", user.name), "text-gray-400");
        });
        let tx_clone = tx.clone();
        db.db.user_info().on_update(move |ctx, _, _| broadcast_morph(&tx_clone, &ctx.db));
    }

    db.subscription_builder()
        .on_applied(|ctx| {
            println!("Subscribed — {} objects, {} users",
                ctx.db.scene_object().count(), ctx.db.user_info().count());
        })
        .subscribe_to_all_tables();

    let db_arc = Arc::new(db);
    {
        let db_clone = Arc::clone(&db_arc);
        std::thread::spawn(move || {
            while db_clone.advance_one_message_blocking().is_ok() {}
        });
    }

    rocket::build()
        .manage(App { db: db_arc, tx })
        .attach(Template::fairing())
        .mount("/", routes![index, websocket])
        .mount("/static", FileServer::from("static"))
}
