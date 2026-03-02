//! SpacetimeDB module — compiled to Wasm, runs inside the database.
#![cfg(target_arch = "wasm32")]

mod models;
mod reducers;
mod routes;
