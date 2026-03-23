"""
AC-Netplay relay server.

Relays player state, game events, and chat messages between connected players
in the same room. Runs as a plain asyncio/websockets WebSocket server.

Usage:
    python server.py [--host 0.0.0.0] [--port 9000] [--log-level INFO]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
import uuid
from typing import Optional

import websockets
from websockets.asyncio.server import ServerConnection

from room import RoomManager, Room, Player

logger = logging.getLogger("ac_netplay.server")

PROTOCOL_VERSION = "1.0"
MAX_MESSAGE_BYTES = 65536  # 64 KB — accommodates TOWN_DATA (~28 KB base64)

# Rate-limit buckets (messages/second) per message type
RATE_LIMITS: dict[str, float] = {
    "PLAYER_STATE": 60.0,
    "GAME_EVENT": 10.0,
    "CHAT": 2.0,
    "TOWN_DATA": 1.0,   # bulk one-time message; once per second max
    "__default__": 5.0,
}


class RateLimiter:
    """Simple token-bucket rate limiter per (player_id, message_type) pair."""

    def __init__(self) -> None:
        # { key: (tokens, last_refill_time) }
        self._buckets: dict[str, tuple[float, float]] = {}

    def is_allowed(self, key: str, rate: float) -> bool:
        """Return True if the action is allowed, False if rate-limited."""
        now = time.monotonic()
        tokens, last = self._buckets.get(key, (rate, now))
        elapsed = now - last
        tokens = min(rate, tokens + elapsed * rate)
        if tokens < 1.0:
            self._buckets[key] = (tokens, now)
            return False
        self._buckets[key] = (tokens - 1.0, now)
        return True


class NetplayServer:
    """Manages all WebSocket connections and delegates to RoomManager."""

    def __init__(self, max_rooms: int = 100, max_players: int = 4) -> None:
        self.room_manager = RoomManager(max_rooms=max_rooms, max_players=max_players)
        self.rate_limiter = RateLimiter()

    async def handle_connection(self, websocket: ServerConnection) -> None:
        player_id = str(uuid.uuid4())[:8]
        player: Optional[Player] = None
        room: Optional[Room] = None
        remote = websocket.remote_address
        logger.info("New connection from %s (id=%s)", remote, player_id)

        try:
            # --- HELLO handshake ---
            raw = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            msg = self._parse(raw)
            if msg is None or msg.get("type") != "HELLO":
                await self._send_error(websocket, "BAD_VERSION", "Expected HELLO as first message")
                return
            if msg.get("version") != PROTOCOL_VERSION:
                await self._send_error(websocket, "BAD_VERSION",
                                       f"Server requires protocol version {PROTOCOL_VERSION}")
                return

            player_name = str(msg.get("player_name", "Anon"))[:8]
            town_name = str(msg.get("town_name", "???"))[:6]
            player = Player(
                player_id=player_id,
                player_name=player_name,
                town_name=town_name,
                websocket=websocket,
            )

            await websocket.send(json.dumps({
                "type": "WELCOME",
                "player_id": player_id,
                "server_version": PROTOCOL_VERSION,
                "motd": "Welcome to AC-Netplay!",
            }))
            logger.info("Player '%s' from town '%s' connected (id=%s)",
                        player_name, town_name, player_id)

            # --- Main message loop ---
            async for raw_msg in websocket:
                if len(raw_msg) > MAX_MESSAGE_BYTES:
                    await self._send_error(websocket, "INTERNAL", "Message too large")
                    continue

                msg = self._parse(raw_msg)
                if msg is None:
                    continue

                msg_type = msg.get("type", "")

                # Rate limiting
                rate = RATE_LIMITS.get(msg_type, RATE_LIMITS["__default__"])
                rl_key = f"{player_id}:{msg_type}"
                if not self.rate_limiter.is_allowed(rl_key, rate):
                    await self._send_error(websocket, "RATE_LIMITED",
                                           f"Rate limit exceeded for {msg_type}")
                    continue

                if msg_type == "JOIN_ROOM":
                    room = await self._handle_join(websocket, player, msg)

                elif msg_type == "LEAVE_ROOM":
                    if room and player:
                        await self.room_manager.remove_player(room, player)
                        room = None

                elif msg_type in ("PLAYER_STATE", "APPEARANCE", "GAME_EVENT", "CHAT", "TOWN_DATA"):
                    if room and player:
                        await self._relay(room, player, msg)
                    else:
                        await self._send_error(websocket, "INTERNAL",
                                               "Not in a room")

                elif msg_type == "BYE":
                    break

        except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError):
            pass
        except Exception:
            logger.exception("Unhandled error for player %s", player_id)
        finally:
            if room and player:
                await self.room_manager.remove_player(room, player)
            logger.info("Connection closed for player %s", player_id)

    async def _handle_join(
        self,
        websocket: ServerConnection,
        player: Player,
        msg: dict,
    ) -> Optional[Room]:
        room_name = str(msg.get("room", ""))[:32]
        password = str(msg.get("password", ""))

        if not room_name:
            await self._send_error(websocket, "INTERNAL", "Room name required")
            return None

        result = await self.room_manager.join_room(player, room_name, password)
        if isinstance(result, str):
            # Error code returned
            await self._send_error(websocket, result, f"Could not join room: {result}")
            return None

        room: Room = result
        # Send current room state to joining player
        await websocket.send(json.dumps({
            "type": "ROOM_STATE",
            "room": room.name,
            "host": room.host_id,
            "players": [p.to_dict() for p in room.players.values()],
        }))
        # Broadcast join event to existing members
        await self.room_manager.broadcast(room, {
            "type": "PLAYER_JOINED",
            "player_id": player.player_id,
            "player_name": player.player_name,
            "town_name": player.town_name,
            "appearance": player.appearance,
        }, exclude=player.player_id)
        logger.info("Player %s joined room '%s'", player.player_id, room_name)
        return room

    async def _relay(self, room: Room, sender: Player, msg: dict) -> None:
        """Forward a message from sender to all other players in the room."""
        msg["player_id"] = sender.player_id
        if msg.get("type") == "APPEARANCE":
            sender.appearance = {k: msg.get(k) for k in
                                  ("face", "hair", "hair_color", "gender",
                                   "tan", "shirt", "hat", "glasses")}
        if msg.get("type") == "CHAT":
            msg["player_name"] = sender.player_name
        await self.room_manager.broadcast(room, msg, exclude=sender.player_id)

    @staticmethod
    async def _send_error(
        websocket: ServerConnection, code: str, message: str
    ) -> None:
        try:
            await websocket.send(json.dumps({
                "type": "ERROR",
                "code": code,
                "message": message,
            }))
        except websockets.exceptions.ConnectionClosed:
            pass

    @staticmethod
    def _parse(raw: str | bytes) -> Optional[dict]:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None


async def main(args: argparse.Namespace) -> None:
    server_obj = NetplayServer(
        max_rooms=args.max_rooms,
        max_players=args.max_players,
    )

    async with websockets.serve(
        server_obj.handle_connection,
        host=args.host,
        port=args.port,
        ping_interval=20,
        ping_timeout=30,
    ):
        logger.info("AC-Netplay relay server listening on %s:%d", args.host, args.port)
        await asyncio.Future()  # run forever


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AC-Netplay relay server")
    p.add_argument("--host", default="0.0.0.0", help="Bind address")
    p.add_argument("--port", type=int, default=9000, help="TCP port")
    p.add_argument("--max-rooms", type=int, default=100)
    p.add_argument("--max-players", type=int, default=4)
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p.parse_args()


if __name__ == "__main__":
    _args = parse_args()
    logging.basicConfig(
        level=getattr(logging, _args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(main(_args))
