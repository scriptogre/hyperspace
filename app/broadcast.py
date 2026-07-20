"""Broadcast database changes to connected clients."""

import asyncio

SEND_QUEUE_MAX = 64

clients: dict[str, asyncio.Queue[str]] = {}


def subscribe(token: str) -> asyncio.Queue[str]:
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=SEND_QUEUE_MAX)
    clients[token] = queue
    return queue


def unsubscribe(token: str) -> None:
    clients.pop(token, None)


def notify(table: str) -> None:
    for queue in list(clients.values()):
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(table)
