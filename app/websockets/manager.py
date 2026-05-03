from fastapi import WebSocket
from typing import Dict, Set
import json


class ConnectionManager:
    def __init__(self):
        # ride_id -> set of WebSocket connections
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # driver_id -> ride_id mapping
        self.driver_rides: Dict[str, str] = {}

    async def connect(self, websocket: WebSocket, ride_id: str):
        await websocket.accept()
        if ride_id not in self.active_connections:
            self.active_connections[ride_id] = set()
        self.active_connections[ride_id].add(websocket)

    def disconnect(self, websocket: WebSocket, ride_id: str):
        if ride_id in self.active_connections:
            self.active_connections[ride_id].discard(websocket)
            if not self.active_connections[ride_id]:
                del self.active_connections[ride_id]

    async def broadcast_to_ride(self, ride_id: str, data: dict):
        if ride_id in self.active_connections:
            dead = set()
            for ws in self.active_connections[ride_id]:
                try:
                    await ws.send_json(data)
                except Exception:
                    dead.add(ws)
            for ws in dead:
                self.active_connections[ride_id].discard(ws)

    async def send_personal(self, websocket: WebSocket, data: dict):
        await websocket.send_json(data)


manager = ConnectionManager()
