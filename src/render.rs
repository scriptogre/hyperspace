use std::sync::LazyLock;

use minijinja::{context, Environment};
use spacetimedb::{Identity, Local, Table};

use crate::models::*;

static TEMPLATES: LazyLock<Environment<'static>> = LazyLock::new(|| {
    let mut env = Environment::new();
    env.add_template("index", include_str!("../templates/index.html.j2"))
        .unwrap();
    env
});

fn world_state(db: &Local, viewer: Option<&Identity>) -> minijinja::Value {
    let blocks: Vec<_> = db.brick().iter().map(|b| {
        context! {
            id => b.id,
            grid_x => b.position.x,
            grid_y => b.position.y,
            grid_z => b.position.z,
            color => b.color.hex(),
            is_being_dragged => b.dragged_by.is_some(),
        }
    }).collect();

    let users: Vec<_> = db.user().iter().map(|u| {
        context! {
            name => u.name,
            color => u.color.hex(),
            online => u.online,
        }
    }).collect();

    let cursors: Vec<_> = db.cursor().iter().map(|c| {
        let user = db.user().identity().find(&c.identity);
        let name = user.as_ref().map(|u| u.name.clone()).unwrap_or_else(|| "?".into());
        let color = user.as_ref().map(|u| u.color.hex()).unwrap_or("#888");
        context! {
            name,
            color,
            session_id => format!("{:?}", c.identity),
            grid_x => c.position.x,
            grid_y => c.position.y,
            grid_z => c.position.z,
        }
    }).collect();

    let logs: Vec<_> = db.event().iter().map(|e| {
        let user_name = db.user().identity().find(&e.identity)
            .map(|u| u.name.clone())
            .unwrap_or_else(|| "Someone".into());
        context! {
            id => e.id,
            message => format!("{} {}", user_name, e.kind.label()),
            color => e.kind.css_color(),
        }
    }).collect();

    let current_session_id = viewer
        .map(|id| format!("{:?}", id))
        .unwrap_or_default();

    let show_player_setup = viewer
        .and_then(|id| db.user().identity().find(id))
        .map(|u| u.name.starts_with("User "))
        .unwrap_or(true);

    context! {
        blocks,
        users,
        cursors,
        logs,
        grid_size => 12,
        current_session_id,
        show_player_setup,
    }
}

/// Render the full HTML page (for GET /).
pub fn render_page(db: &Local, viewer: Option<&Identity>) -> String {
    TEMPLATES.get_template("index").unwrap()
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
