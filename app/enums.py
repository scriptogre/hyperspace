"""Shared enums used across models and services."""

from enum import StrEnum


class Color(StrEnum):
    """Color for players and bricks."""

    CYAN = "cyan"
    PURPLE = "purple"
    ORANGE = "orange"
    GREEN = "green"
    PINK = "pink"
    YELLOW = "yellow"


class EventType(StrEnum):
    """An entry type in the activity feed."""

    PLAYER_JOINED = "player_joined"
    PLAYER_LEFT = "player_left"
    BRICK_CREATED = "brick_created"
    BRICK_DELETED = "brick_deleted"
    DRAG_STARTED = "drag_started"
    DRAG_ENDED = "drag_ended"

    @property
    def label(self) -> str:
        """Human phrasing shown in the activity feed."""
        return {
            EventType.PLAYER_JOINED: "joined",
            EventType.PLAYER_LEFT: "left",
            EventType.BRICK_CREATED: "placed a brick",
            EventType.BRICK_DELETED: "removed a brick",
            EventType.DRAG_STARTED: "started dragging",
            EventType.DRAG_ENDED: "stopped dragging",
        }[self]
