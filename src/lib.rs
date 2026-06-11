#![cfg(target_arch = "wasm32")]

mod models;
mod reducers;
mod render;

use spacetimedb::http::{Body, HandlerContext, Request, Response, Router};

#[spacetimedb::http::handler]
fn index(ctx: &mut HandlerContext, _req: Request) -> Response {
    let html = ctx.with_tx(|tx| render::render_page(&tx.db, None));
    Response::builder()
        .header("content-type", "text/html; charset=utf-8")
        .body(Body::from_bytes(html))
        .unwrap()
}

#[spacetimedb::http::router]
fn router() -> Router {
    Router::new().get("/", index)
}
