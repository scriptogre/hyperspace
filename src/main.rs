#[macro_use]
extern crate rocket;

mod module_bindings;

use module_bindings::*;
use rocket::fs::FileServer;
use rocket::State;
use rocket_dyn_templates::{context, Template};
use spacetimedb_sdk::{DbContext, Table};
use tokio::sync::broadcast;

struct App {
    db: DbConnection,
    _tx: broadcast::Sender<String>,
}

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
        grid_size: 8,
    })
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

    let app = App { db, _tx: tx };

    rocket::build()
        .manage(app)
        .attach(Template::fairing())
        .mount("/", routes![index])
        .mount("/static", FileServer::from("static"))
}
