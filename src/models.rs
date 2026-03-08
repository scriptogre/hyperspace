use spacetimedb::{Identity, ReducerContext, SpacetimeType, Timestamp};
use spacetimedb::Filter;
use spacetimedb::rand::Rng;

// --- Custom types ---

#[derive(SpacetimeType, Clone, Copy)]
pub enum Color {
    Cyan,
    Purple,
    Orange,
    Green,
    Pink,
    Yellow,
}

impl Color {
    pub const ALL: [Color; 6] = [
        Color::Cyan, Color::Purple, Color::Orange,
        Color::Green, Color::Pink, Color::Yellow,
    ];

    pub fn hex(&self) -> &str {
        match self {
            Color::Cyan => "#22d3ee",
            Color::Purple => "#a78bfa",
            Color::Orange => "#fb923c",
            Color::Green => "#4ade80",
            Color::Pink => "#f472b6",
            Color::Yellow => "#facc15",
        }
    }

    pub fn random(ctx: &ReducerContext) -> Color {
        Color::ALL[ctx.rng().r#gen::<usize>() % Color::ALL.len()]
    }
}

#[derive(SpacetimeType)]
pub struct Position {
    pub x: i32,
    pub y: i32,
    pub z: i32,
}

#[derive(SpacetimeType)]
pub enum EventKind {
    UserConnected,
    UserDisconnected,
    BrickCreated,
    BrickDeleted,
    DragStarted,
    DragEnded,
}

impl EventKind {
    pub fn label(&self) -> &str {
        match self {
            EventKind::UserConnected => "joined",
            EventKind::UserDisconnected => "left",
            EventKind::BrickCreated => "placed a brick",
            EventKind::BrickDeleted => "removed a brick",
            EventKind::DragStarted => "started dragging",
            EventKind::DragEnded => "stopped dragging",
        }
    }

    pub fn css_color(&self) -> &str {
        match self {
            EventKind::UserConnected => "text-green-400",
            EventKind::UserDisconnected => "text-gray-500",
            EventKind::BrickCreated => "text-cyan-400",
            EventKind::BrickDeleted => "text-red-400",
            EventKind::DragStarted | EventKind::DragEnded => "text-yellow-400",
        }
    }
}

// --- Tables ---

#[spacetimedb::table(accessor = brick, public)]
pub struct Brick {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub position: Position,
    pub color: Color,
    pub dragged_by: Option<Identity>,
}

#[spacetimedb::table(accessor = user, public)]
pub struct User {
    #[primary_key]
    pub identity: Identity,
    pub name: String,
    pub color: Color,
    pub online: bool,
}

#[spacetimedb::table(accessor = cursor, public)]
pub struct Cursor {
    #[primary_key]
    pub identity: Identity,
    pub position: Position,
}

#[spacetimedb::table(accessor = event, public)]
pub struct Event {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub kind: EventKind,
    pub identity: Identity,
    pub brick_id: Option<u64>,
    pub timestamp: Timestamp,
}

// --- Event table for broadcasting rendered HTML ---

#[spacetimedb::table(accessor = html_broadcast, public)]
pub struct HtmlBroadcast {
    #[primary_key]
    pub identity: Identity,
    pub html: String,
}

#[spacetimedb::client_visibility_filter]
const BROADCAST_FILTER: Filter = Filter::Sql(
    "SELECT * FROM html_broadcast WHERE html_broadcast.identity = :sender"
);
