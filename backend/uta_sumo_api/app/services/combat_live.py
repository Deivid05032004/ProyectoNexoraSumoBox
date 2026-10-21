"""In-process WebSocket fan-out for the selected live combat."""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect


class LiveCombatConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._loop_guard = threading.Lock()

    async def connect(self, websocket: WebSocket, snapshot_loader: Callable[[], dict]) -> None:
        await websocket.accept()
        async with self._lock:
            # Locking the initial read and registration prevents an update from
            # falling between the first snapshot and the broadcast subscription.
            initial_snapshot = await asyncio.to_thread(snapshot_loader)
            with self._loop_guard:
                self._event_loop = asyncio.get_running_loop()
            self._connections.add(websocket)
            try:
                await websocket.send_json(initial_snapshot)
            except (WebSocketDisconnect, RuntimeError):
                self._connections.discard(websocket)
                raise

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
            if not self._connections:
                with self._loop_guard:
                    self._event_loop = None

    async def broadcast(self, snapshot: dict) -> None:
        async with self._lock:
            clients = tuple(self._connections)
        if not clients:
            return
        results = await asyncio.gather(
            *(self._send_one(client, snapshot) for client in clients),
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
    async def _send_one(websocket: WebSocket, snapshot: dict) -> None:
        await asyncio.wait_for(websocket.send_json(snapshot), timeout=5)

    def broadcast_from_sync_route(self, snapshot: dict) -> None:
        """Awaitable dispatch for FastAPI sync routes running in a worker thread."""
        with self._loop_guard:
            loop = self._event_loop
        if loop is None or not loop.is_running():
            return
        future = asyncio.run_coroutine_threadsafe(self.broadcast(snapshot), loop)
        try:
            future.result(timeout=6)
        except Exception:
            future.cancel()


live_combat_connections = LiveCombatConnectionManager()
