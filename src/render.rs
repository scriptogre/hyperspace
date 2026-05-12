use std::sync::LazyLock;

use minijinja::{context, Environment, Value};
use spacetimedb::{Identity, Local, Table};

use crate::models::*;

static TEMPLATES: LazyLock<Environment<'static>> = LazyLock::new(|| {
    let mut env = Environment::new();
    env.add_template("index", include_str!("../templates/index.html.j2"))
        .unwrap();
    env
});

const GRID_SIZE: i32 = 12;
const MAX_RENDERED_LOGS: usize = 10;

fn world_state(db: &Local, viewer: Option<&Identity>) -> minijinja::Value {
    let mut brick_rows: Vec<_> = db.brick().iter().collect();
    brick_rows.sort_by_key(|b| b.id);
    let blocks: Vec<_> = brick_rows
        .into_iter()
        .map(|b| {
            context! {
                id => b.id,
                grid_x => b.position.x,
                grid_y => b.position.y,
                grid_z => b.position.z,
                color => b.color.hex(),
                is_being_dragged => b.dragged_by.is_some(),
            }
        })
        .collect();

    let mut user_rows: Vec<_> = db.user().iter().collect();
    user_rows.sort_by(|a, b| a.name.cmp(&b.name));
    let users: Vec<_> = user_rows
        .into_iter()
        .map(|u| {
            context! {
                name => u.name,
                color => u.color.hex(),
                online => u.online,
            }
        })
        .collect();

    let mut cursor_rows: Vec<_> = db.cursor().iter().collect();
    cursor_rows.sort_by_key(|c| format!("{:?}", c.identity));
    let cursors: Vec<_> = cursor_rows
        .into_iter()
        .map(|c| {
            let user = db.user().identity().find(c.identity);
            let name = user
                .as_ref()
                .map(|u| u.name.clone())
                .unwrap_or_else(|| "?".into());
            let color = user.as_ref().map(|u| u.color.hex()).unwrap_or("#888");
            let session_id = format!("{:?}", c.identity);
            context! {
                name,
                color,
                session_id,
                grid_x => c.position.x,
                grid_y => c.position.y,
                grid_z => c.position.z,
            }
        })
        .collect();

    let mut event_rows: Vec<_> = db.event().iter().collect();
    event_rows.sort_by_key(|e| e.id);
    if event_rows.len() > MAX_RENDERED_LOGS {
        event_rows = event_rows.split_off(event_rows.len() - MAX_RENDERED_LOGS);
    }
    let logs: Vec<_> = event_rows
        .into_iter()
        .map(|e| {
            let user = db.user().identity().find(e.identity);
            let user_name = user.as_ref().map(|u| u.name.clone()).unwrap_or_else(|| "Someone".into());
            let user_color = user.as_ref().map(|u| u.color.hex()).unwrap_or("#888");
            context! {
                id => e.id,
                user_name,
                user_color,
                kind => Value::from_serialize(&e.kind),
            }
        })
        .collect();

    let current_session_id = viewer.map(|id| format!("{:?}", id)).unwrap_or_default();

    let show_player_setup = viewer
        .and_then(|id| db.user().identity().find(id))
        .map(|u| u.name.starts_with("User "))
        .unwrap_or(true);

    context! {
        blocks,
        users,
        cursors,
        logs,
        grid_size => GRID_SIZE,
        current_session_id,
        show_player_setup,
    }
}

/// Render the full HTML page (for GET /).
pub fn render_page(db: &Local, viewer: Option<&Identity>) -> String {
    TEMPLATES
        .get_template("index")
        .unwrap()
        .render(world_state(db, viewer))
        .unwrap()
}

/// Render the inner HTML of #app for morphing via WS.
pub fn render_body(db: &Local, viewer: Option<&Identity>) -> String {
    let tmpl = TEMPLATES.get_template("index").unwrap();
    let state = world_state(db, viewer);
    let mut state_obj = tmpl.eval_to_state(state).unwrap();
    state_obj.render_block("grid").unwrap()
}
