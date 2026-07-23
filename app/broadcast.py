"""Broadcast rendered templates to connected subscribers."""

import asyncio
from collections.abc import AsyncIterator

_subscribers: dict[asyncio.Event, dict[str, bytes]] = {}


def publish_template(template_name: str, html: bytes) -> None:
    """Publish a rendered template to every subscriber."""
    for notified, pending in tuple(_subscribers.items()):
        pending[template_name] = html
        notified.set()


async def subscribe_to_templates() -> AsyncIterator[tuple[str, bytes]]:
    notified = asyncio.Event()
    pending: dict[str, bytes] = {}
    _subscribers[notified] = pending

    try:
        while True:
            await notified.wait()
            notified.clear()
            while pending:
                yield pending.popitem()
    finally:
        del _subscribers[notified]
