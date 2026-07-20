"""Wake connected clients when database state changes."""

import asyncio

clients: dict[str, asyncio.Event] = {}


def subscribe(token: str) -> asyncio.Event:
    update = asyncio.Event()
    update.set()
    clients[token] = update
    return update


def unsubscribe(token: str) -> None:
    clients.pop(token, None)


def notify(_table: str) -> None:
    for update in list(clients.values()):
        update.set()
