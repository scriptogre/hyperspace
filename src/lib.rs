//! SpacetimeDB module — compiled to Wasm, runs inside the database.
#![cfg(target_arch = "wasm32")]

mod models;
mod reducers;
mod render;

use spacetimedb::{get, Html, HttpRequest, ProcedureContext};

#[get("/")]
fn index(ctx: &mut ProcedureContext, _req: HttpRequest) -> Html {
    ctx.with_tx(|tx| Html(render::render_page(&tx.db, None)))
}
