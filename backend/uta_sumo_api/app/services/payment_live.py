"""Authenticated WebSocket fan-out for administrative payment updates."""
from __future__ import annotations

import asyncio
import threading

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect


class PaymentUpdateConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._loop_guard = threading.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept(subprotocol="uta-payment-updates")
        async with self._lock:
            with self._loop_guard:
                self._event_loop = asyncio.get_running_loop()
            self._connections.add(websocket)
        await websocket.send_json({"type": "connected"})

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
            if not self._connections:
                with self._loop_guard:
                    self._event_loop = None

    async def broadcast(self, payload: dict) -> None:
        async with self._lock:
            clients = tuple(self._connections)
        if not clients:
            return
        results = await asyncio.gather(
            *(self._send_one(client, payload) for client in clients),
            return_exceptions=True,
        )
        failed = {client for client, result in zip(clients, results) if isinstance(result, Exception)}
        if failed:
            async with self._lock:
                self._connections.difference_update(failed)
                if not self._connections:
                    with self._loop_guard:
                        self._event_loop = None

    @staticmethod
    async def _send_one(websocket: WebSocket, payload: dict) -> None:
        await asyncio.wait_for(websocket.send_json(payload), timeout=5)

    def broadcast_from_sync_route(self, payload: dict) -> None:
        """Dispatch safely from FastAPI sync endpoints running in a worker thread."""
        with self._loop_guard:
            loop = self._event_loop
        if loop is None or not loop.is_running():
            return
        future = asyncio.run_coroutine_threadsafe(self.broadcast(payload), loop)
        try:
            future.result(timeout=6)
        except Exception:
            future.cancel()


payment_update_connections = PaymentUpdateConnectionManager()
