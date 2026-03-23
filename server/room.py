"""
Room and player management for the AC-Netplay relay server.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

import websockets
from websockets.asyncio.server import ServerConnection

logger = logging.getLogger("ac_netplay.room")


@dataclass
class Player:
    """Represents a connected player."""

    player_id: str
    player_name: str
    town_name: str
    websocket: ServerConnection
    appearance: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "player_name": self.player_name,
            "town_name": self.town_name,
            "appearance": self.appearance,
        }


@dataclass
class Room:
    """A named multiplayer session."""

    name: str
    password: str = ""
    host_id: str = ""
    # player_id → Player
    players: dict[str, Player] = field(default_factory=dict)


class RoomManager:
    """Creates, manages, and destroys rooms."""

    def __init__(self, max_rooms: int = 100, max_players: int = 4) -> None:
        self.max_rooms = max_rooms
        self.max_players = max_players
        # room_name → Room
        self._rooms: dict[str, Room] = {}
        self._lock = asyncio.Lock()

    async def join_room(
        self, player: Player, room_name: str, password: str
    ) -> Room | str:
        """
        Add *player* to *room_name*.

        Returns the Room on success or an error-code string on failure.
        """
        async with self._lock:
            if room_name not in self._rooms:
                if len(self._rooms) >= self.max_rooms:
                    return "INTERNAL"
                room = Room(name=room_name, password=password, host_id=player.player_id)
                self._rooms[room_name] = room
                logger.info("Room '%s' created by %s", room_name, player.player_id)
            else:
                room = self._rooms[room_name]

            if room.password and room.password != password:
                return "WRONG_PASSWORD"
            if len(room.players) >= self.max_players:
                return "ROOM_FULL"
            if any(p.player_name == player.player_name for p in room.players.values()):
                return "NAME_TAKEN"

            room.players[player.player_id] = player
            logger.debug("Player %s added to room '%s' (%d/%d)",
                         player.player_id, room_name, len(room.players), self.max_players)
            return room

    async def remove_player(self, room: Room, player: Player) -> None:
        async with self._lock:
            room.players.pop(player.player_id, None)
            logger.info("Player %s left room '%s' (%d remaining)",
                        player.player_id, room.name, len(room.players))

            await self.broadcast(room, {
                "type": "PLAYER_LEFT",
                "player_id": player.player_id,
                "reason": "disconnected",
            })

            if not room.players:
                self._rooms.pop(room.name, None)
                logger.info("Room '%s' destroyed (empty)", room.name)
            elif room.host_id == player.player_id:
                # Transfer host to first remaining player
                new_host = next(iter(room.players.values()))
                room.host_id = new_host.player_id
                await self.broadcast(room, {
                    "type": "GAME_EVENT",
                    "event": "HOST_CHANGED",
                    "player_id": new_host.player_id,
                })
                logger.info("Room '%s' host transferred to %s", room.name, new_host.player_id)

    async def broadcast(
        self,
        room: Room,
        message: dict,
        exclude: Optional[str] = None,
    ) -> None:
        """Send *message* to all players in *room* except *exclude*."""
        data = json.dumps(message)
        recipients = [
            p for pid, p in room.players.items() if pid != exclude
        ]
        if not recipients:
            return
        results = await asyncio.gather(
            *(self._safe_send(p.websocket, data) for p in recipients),
            return_exceptions=True,
        )
        for p, result in zip(recipients, results):
            if isinstance(result, Exception):
                logger.debug("Failed to send to %s: %s", p.player_id, result)

    @staticmethod
    async def _safe_send(ws: ServerConnection, data: str) -> None:
        try:
            await ws.send(data)
        except websockets.exceptions.ConnectionClosed:
            pass
