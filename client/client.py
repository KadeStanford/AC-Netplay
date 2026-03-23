"""
AC-Netplay client — main entry point.

Bridges the local Dolphin process (reading/writing emulated GameCube RAM)
with the AC-Netplay relay server. Run this alongside Dolphin while playing
Animal Crossing (GAFE01).

Usage (in-game browse mode — discover and join towns from within the game):
    python client.py --server ws://HOST:9000 --name YourName

Usage (direct-join mode — join a specific room by name):
    python client.py --server ws://HOST:9000 --room MyTown --name YourName
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from typing import Optional

import websockets

from dolphin_memory import DolphinMemory, VISITOR_ARRIVAL_POS
from state import PlayerState, AppearanceState, GameEvent, TownData, RoomEntry

logger = logging.getLogger("ac_netplay.client")

PROTOCOL_VERSION = "1.0"
RECONNECT_DELAY_S = 5.0

# Z-coordinate at which the player is considered to be near the train station
# (northern edge of town).  In AC GameCube world-space, Z increases going
# north, so the train station sits at high Z values (≥ this threshold).
STATION_APPROACH_Z_THRESHOLD = 70.0

# How often (seconds) to refresh the room list while browsing in-game
ROOM_LIST_REFRESH_S = 5.0


class NetplayClient:
    """Reads local game state from Dolphin and exchanges it with the server."""

    def __init__(
        self,
        server_url: str,
        player_name: str,
        town_name: str,
        room: str = "",
        password: str = "",
        player_slot: int = 0,
        tick_rate: int = 30,
        interp_ms: int = 100,
        dolphin_pid: Optional[int] = None,
    ) -> None:
        self.server_url = server_url
        self.room = room          # empty string → browse mode
        self.player_name = player_name
        self.town_name = town_name
        self.password = password
        self.player_slot = player_slot
        self.tick_rate = tick_rate
        self.interp_ms = interp_ms
        self.dolphin_pid = dolphin_pid

        self.mem: Optional[DolphinMemory] = None
        self.websocket = None
        self.player_id: Optional[str] = None

        # Role in the current session: True = hosting the town, False = visiting
        self._is_host: bool = False
        self._host_player_id: Optional[str] = None

        # { player_id: list of (ts, PlayerState) } — interpolation buffer
        self._remote_states: dict[str, list[tuple[float, PlayerState]]] = {}
        # { player_id: AppearanceState }
        self._remote_appearances: dict[str, AppearanceState] = {}
        # visitor slot index assignment { player_id: slot_index }
        self._visitor_slots: dict[str, int] = {}
        self._next_visitor_slot = 0

        # Available rooms received from the server during browse mode
        self._available_rooms: list[RoomEntry] = []

        self._seq = 0

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Connect to Dolphin, then connect to server and run the main loop."""
        logger.info("Attaching to Dolphin...")
        self.mem = DolphinMemory(pid=self.dolphin_pid)
        self.mem.attach()
        game_id = self.mem.read_game_id()
        logger.info("Verified game ID: %s", game_id)
        if game_id != "GAFE01":
            logger.warning(
                "Game ID is '%s', expected 'GAFE01'. Offsets may be wrong.", game_id
            )

        if not self.room:
            logger.info(
                "No --room specified.  Running in in-game browse mode: "
                "walk to the train station in Animal Crossing to see available towns."
            )

        while True:
            try:
                await self._connect_and_loop()
            except (websockets.exceptions.ConnectionClosed,
                    OSError,
                    asyncio.TimeoutError) as exc:
                logger.warning("Disconnected (%s). Reconnecting in %.0fs…",
                               exc, RECONNECT_DELAY_S)
                await asyncio.sleep(RECONNECT_DELAY_S)

    # ------------------------------------------------------------------
    # Connection & main loop
    # ------------------------------------------------------------------

    async def _connect_and_loop(self) -> None:
        async with websockets.connect(self.server_url) as ws:
            self.websocket = ws
            logger.info("Connected to %s", self.server_url)

            # Phase 1: HELLO → WELCOME (no room required yet)
            await self._hello(ws)

            # Phase 2: Join a room — either directly or via in-game browser
            if not self.room:
                # Browse mode: _browse_and_join polls the WS itself for ROOM_LIST
                # responses (recv_loop is not running yet) and calls _join_room
                # once the player makes a selection.
                await self._browse_and_join(ws)
            else:
                await self._join_room(ws, self.room, self.password)

            # Phase 3: Send initial appearance — only valid after joining a room
            appearance = self.mem.read_appearance(self.player_slot)
            await ws.send(json.dumps({"type": "APPEARANCE", **appearance.to_dict()}))

            # Phase 4: Main gameplay loops
            await asyncio.gather(
                self._send_loop(ws),
                self._recv_loop(ws),
                self._apply_remote_loop(),
            )

    async def _hello(self, ws: websockets.WebSocketClientProtocol) -> None:
        """Send HELLO and wait for the server's WELCOME (player_id assignment)."""
        await ws.send(json.dumps({
            "type": "HELLO",
            "version": PROTOCOL_VERSION,
            "player_name": self.player_name,
            "town_name": self.town_name,
            "platform": "dolphin",
        }))
        msg = json.loads(await ws.recv())
        if msg.get("type") == "ERROR":
            raise RuntimeError(f"Server rejected HELLO: {msg.get('message')}")
        self.player_id = msg["player_id"]
        logger.info("Assigned player_id=%s", self.player_id)

    async def _handshake(self, ws: websockets.WebSocketClientProtocol) -> None:
        """
        Full handshake for direct-join mode: HELLO → WELCOME → JOIN_ROOM → APPEARANCE.

        This is a convenience wrapper used in tests; the production path calls
        _hello(), _join_room(), and sends APPEARANCE separately so browse mode
        can insert its own step between HELLO and JOIN_ROOM.
        """
        await self._hello(ws)
        await self._join_room(ws, self.room, self.password)
        appearance = self.mem.read_appearance(self.player_slot)
        await ws.send(json.dumps({"type": "APPEARANCE", **appearance.to_dict()}))

    async def _join_room(
        self, ws: websockets.WebSocketClientProtocol, room: str, password: str
    ) -> None:
        """Send JOIN_ROOM and process the server's ROOM_STATE reply."""
        await ws.send(json.dumps({
            "type": "JOIN_ROOM",
            "room": room,
            "password": password,
        }))
        msg = json.loads(await ws.recv())
        if msg.get("type") == "ERROR":
            raise RuntimeError(f"Could not join room: {msg.get('message')}")
        player_count = len(msg.get("players", []))
        logger.info("Joined room '%s' (%d player(s))", room, player_count)

        # Determine role: host if the room's host_id is our own player_id.
        self._host_player_id = msg.get("host")
        self._is_host = (self._host_player_id == self.player_id)
        logger.info("Role: %s", "host" if self._is_host else "visitor")

        # Pre-populate visitor slots for players already in the room
        for p in msg.get("players", []):
            pid = p.get("player_id")
            if pid and pid != self.player_id:
                self._ensure_visitor_slot(pid)
                if p.get("appearance"):
                    self._remote_appearances[pid] = AppearanceState.from_dict(
                        p["appearance"]
                    )

    # ------------------------------------------------------------------
    # In-game browse mode — discover rooms then join from within the game
    # ------------------------------------------------------------------

    async def _browse_and_join(self, ws: websockets.WebSocketClientProtocol) -> None:
        """
        Run the in-game room browser until the player selects a town to visit.

        The key design constraint: ``_recv_loop`` is not running yet when this
        is called, so this method reads WebSocket messages itself using
        ``asyncio.wait_for(ws.recv(), timeout=0.1)``.  This gives a ~10 Hz
        polling cadence while keeping the event loop free.

        Behaviour:
        1. Send LIST_ROOMS; receive ROOM_LIST directly and write room entries
           to Dolphin RAM so the Gecko-code overlay can display them.
        2. Set ``browser_active = 1`` in GC memory when the player's Z
           coordinate is near the train station (north = high Z).
        3. When the Gecko code writes ``join_trigger = 1`` (player pressed A),
           call _join_room() with the chosen room and return.
        4. Refresh the room list every ROOM_LIST_REFRESH_S seconds.
        """
        logger.info(
            "In-game browse mode active — walk to the train station (north of town) "
            "to see available towns, then use D-pad + A to join one"
        )
        last_refresh = 0.0

        while True:
            now = time.monotonic()

            # Periodically send LIST_ROOMS
            if now - last_refresh >= ROOM_LIST_REFRESH_S:
                try:
                    await ws.send(json.dumps({"type": "LIST_ROOMS"}))
                except Exception as exc:
                    logger.debug("LIST_ROOMS send error: %s", exc)
                last_refresh = now

            # Receive the next pending WebSocket message with a short timeout.
            # Because _recv_loop is not yet running, we read directly here so
            # ROOM_LIST responses are not silently dropped.
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.1)
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    msg = {}
                if msg.get("type") == "ROOM_LIST":
                    self._handle_room_list(msg.get("rooms", []))
            except asyncio.TimeoutError:
                pass  # normal — no message arrived in this 100 ms window

            if self.mem:
                # Activate the overlay when player is near the train station.
                # In AC GameCube world-space, Z increases going north; the
                # train station sits at the northern edge (high Z values).
                try:
                    _, _, pos_z = self.mem.read_player_pos(self.player_slot)
                    near_station = pos_z >= STATION_APPROACH_Z_THRESHOLD
                    self.mem.set_room_browser_active(near_station)
                except Exception:
                    pass

                # Check if the player confirmed a room selection in-game
                try:
                    if self.mem.read_room_browser_trigger():
                        idx = self.mem.read_room_browser_selection()
                        if 0 <= idx < len(self._available_rooms):
                            chosen = self._available_rooms[idx]
                            self.mem.clear_room_browser_trigger()
                            self.mem.set_room_browser_active(False)
                            logger.info(
                                "In-game selection: joining '%s' (town '%s')",
                                chosen.room_name, chosen.town_name,
                            )
                            self.room = chosen.room_name
                            await self._join_room(ws, chosen.room_name, "")
                            return
                        else:
                            # Index out of range — clear stale trigger and wait
                            self.mem.clear_room_browser_trigger()
                except Exception as exc:
                    logger.debug("browse trigger read error: %s", exc)

    def _handle_room_list(self, rooms_raw: list[dict]) -> None:
        """
        Process the ROOM_LIST payload from the server.

        Updates the in-memory room list and writes it to Dolphin RAM so
        the Gecko-code overlay can display the available towns.
        """
        self._available_rooms = [RoomEntry.from_dict(r) for r in rooms_raw]
        logger.info(
            "Room list updated: %d room(s) available",
            len(self._available_rooms),
        )
        for i, r in enumerate(self._available_rooms):
            logger.debug(
                "  [%d] %s — town: %s, players: %d/%d%s",
                i, r.room_name, r.town_name, r.player_count, r.max_players,
                " (password)" if r.has_password else "",
            )
        if self.mem:
            try:
                self.mem.write_room_browser_list(self._available_rooms)
            except Exception as exc:
                logger.debug("write_room_browser_list error: %s", exc)

    # ------------------------------------------------------------------
    # Send loop — reads local state and sends to server
    # ------------------------------------------------------------------

    async def _send_loop(self, ws: websockets.WebSocketClientProtocol) -> None:
        interval = 1.0 / self.tick_rate
        prev_appearance: Optional[AppearanceState] = None

        while True:
            t0 = time.monotonic()

            if self.mem:
                state = self.mem.read_player_state(self.player_slot)
                self._seq += 1
                await ws.send(json.dumps({
                    "type": "PLAYER_STATE",
                    "seq": self._seq,
                    "ts": time.time(),
                    **state.to_dict(),
                }))

                # Send appearance update only when changed
                appearance = self.mem.read_appearance(self.player_slot)
                if appearance != prev_appearance:
                    await ws.send(json.dumps({
                        "type": "APPEARANCE",
                        **appearance.to_dict(),
                    }))
                    prev_appearance = appearance

            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0.0, interval - elapsed))

    # ------------------------------------------------------------------
    # Receive loop — handles messages from server
    # ------------------------------------------------------------------

    async def _recv_loop(self, ws: websockets.WebSocketClientProtocol) -> None:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")
            pid = msg.get("player_id")

            if msg_type == "PLAYER_STATE" and pid:
                state = PlayerState.from_dict(msg)
                ts = float(msg.get("ts", time.time()))
                buf = self._remote_states.setdefault(pid, [])
                buf.append((ts, state))
                # Keep only the last 10 samples
                if len(buf) > 10:
                    buf.pop(0)

            elif msg_type == "APPEARANCE" and pid:
                self._remote_appearances[pid] = AppearanceState.from_dict(msg)
                self._ensure_visitor_slot(pid)

            elif msg_type == "GAME_EVENT" and pid:
                await self._handle_game_event(GameEvent.from_dict(msg))

            elif msg_type == "CHAT" and pid:
                logger.info("[Chat] %s: %s",
                            msg.get("player_name", pid), msg.get("text", ""))

            elif msg_type == "PLAYER_JOINED":
                logger.info("Player joined: %s (%s)", msg.get("player_name"), pid)
                self._ensure_visitor_slot(pid)
                # If we are the host, immediately send our town data so the
                # joining visitor's game can render our town.
                if self._is_host and self.mem:
                    await self._send_town_data()

            elif msg_type == "TOWN_DATA":
                # Visitor receives the host's town snapshot.
                if not self._is_host and self.mem:
                    td = TownData.from_dict(msg)
                    await self._apply_town_data(td)

            elif msg_type == "ROOM_LIST":
                self._handle_room_list(msg.get("rooms", []))

            elif msg_type == "PLAYER_LEFT":
                logger.info("Player left: %s", pid)
                self._release_visitor_slot(pid)

    # ------------------------------------------------------------------
    # Apply remote state loop — writes remote players into Dolphin RAM
    # ------------------------------------------------------------------

    async def _apply_remote_loop(self) -> None:
        interval = 1.0 / self.tick_rate
        while True:
            t0 = time.monotonic()
            now = time.time()
            interp_target = now - self.interp_ms / 1000.0

            if self.mem:
                for pid, slot in list(self._visitor_slots.items()):
                    # Write appearance
                    if pid in self._remote_appearances:
                        self.mem.write_visitor_appearance(
                            slot, self._remote_appearances[pid]
                        )

                    # Interpolate position
                    buf = self._remote_states.get(pid, [])
                    state = _interpolate(buf, interp_target)
                    if state:
                        self.mem.write_visitor_state(slot, state)

            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0.0, interval - elapsed))

    # ------------------------------------------------------------------
    # Game event handling
    # ------------------------------------------------------------------

    async def _handle_game_event(self, event: GameEvent) -> None:
        if not self.mem:
            return
        if event.event == "ITEM_PICKUP":
            self.mem.clear_tile_item(event.tile_x, event.tile_z)
        elif event.event == "ITEM_DROP":
            self.mem.set_tile_item(event.tile_x, event.tile_z, event.item_code)
        elif event.event == "GATE_OPEN":
            self.mem.write_gate_state(1)
        elif event.event == "GATE_CLOSE":
            self.mem.write_gate_state(0)
        elif event.event == "HOST_CHANGED":
            # Server transferred host role to us (e.g. original host disconnected)
            if event.player_id == self.player_id:
                self._is_host = True
                self._host_player_id = self.player_id
                logger.info("We became the new host")

    # ------------------------------------------------------------------
    # Town data helpers
    # ------------------------------------------------------------------

    async def _send_town_data(self) -> None:
        """
        (Host only) Read current town data from RAM and broadcast to room.

        Called automatically when a new visitor joins so their game can
        render the host's town immediately.
        """
        if not self.mem or not self.websocket:
            return
        try:
            td = self.mem.read_town_snapshot(self.player_slot)
        except Exception as exc:
            logger.warning("Could not read town snapshot: %s", exc)
            return
        payload = {"type": "TOWN_DATA", **td.to_dict()}
        await self.websocket.send(json.dumps(payload))
        logger.info(
            "Sent town data to room (town='%s', grid=%d bytes)",
            td.town_name, len(td.grid_bytes),
        )

    async def _apply_town_data(self, td: TownData) -> None:
        """
        (Visitor only) Write the host's town data into our Dolphin RAM.

        This makes the visitor's game render the host's town instead of
        their own, achieving true co-presence in the same town.
        """
        if not self.mem:
            return
        if not td.is_valid():
            logger.warning(
                "Received TOWN_DATA with invalid grid size (%d bytes, expected %d)",
                len(td.grid_bytes), TownData.GRID_SIZE,
            )
            return
        try:
            self.mem.write_town_grid(td.grid_bytes)
            logger.info(
                "Applied host town grid (town='%s', %d bytes)",
                td.town_name, len(td.grid_bytes),
            )
        except Exception as exc:
            logger.warning("write_town_grid failed: %s", exc)
            return

        # Teleport our character to the arrival point in the host's town
        x, y, z = VISITOR_ARRIVAL_POS
        self.mem.teleport_local_player(self.player_slot, x, y, z)
        logger.info(
            "Teleported to host town arrival position (%.1f, %.1f, %.1f)", x, y, z
        )

    # ------------------------------------------------------------------
    # Visitor slot management
    # ------------------------------------------------------------------

    def _ensure_visitor_slot(self, player_id: str) -> None:
        if player_id not in self._visitor_slots:
            self._visitor_slots[player_id] = self._next_visitor_slot
            self._next_visitor_slot += 1
            logger.debug("Assigned visitor slot %d to %s",
                         self._visitor_slots[player_id], player_id)

    def _release_visitor_slot(self, player_id: str) -> None:
        slot = self._visitor_slots.pop(player_id, None)
        self._remote_states.pop(player_id, None)
        self._remote_appearances.pop(player_id, None)
        if slot is not None and self.mem:
            self.mem.clear_visitor_slot(slot)
            logger.debug("Released visitor slot %d from %s", slot, player_id)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _interpolate(
    buf: list[tuple[float, PlayerState]], target_ts: float
) -> Optional[PlayerState]:
    """
    Linear interpolation between the two states bracketing *target_ts*.
    Returns None if the buffer has fewer than 2 entries.
    """
    if len(buf) < 1:
        return None
    if len(buf) == 1:
        return buf[0][1]

    # Find the two samples that bracket target_ts
    before = buf[0]
    after = buf[-1]
    for i in range(len(buf) - 1):
        if buf[i][0] <= target_ts <= buf[i + 1][0]:
            before = buf[i]
            after = buf[i + 1]
            break

    dt = after[0] - before[0]
    if dt < 1e-6:
        return after[1]

    t = max(0.0, min(1.0, (target_ts - before[0]) / dt))
    return PlayerState.lerp(before[1], after[1], t)


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AC-Netplay client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "In-game browse mode (omit --room):\n"
            "  Start the client without --room, then walk to the train station\n"
            "  (north of town) inside Animal Crossing.  Available towns will\n"
            "  appear on-screen and you can navigate with D-pad + A to join one.\n\n"
            "Direct-join mode (specify --room):\n"
            "  python client.py --server ws://HOST:9000 --room MyTown --name YourName"
        ),
    )
    p.add_argument("--server", default="ws://localhost:9000", help="Relay server URL")
    p.add_argument("--room", default="",
                   help="Room to join directly (omit to use in-game browse mode)")
    p.add_argument("--name", required=True, help="Your player name (max 8 chars)")
    p.add_argument("--password", default="", help="Room password")
    p.add_argument("--player-slot", type=int, default=0, help="Player slot (0–3)")
    p.add_argument("--tick-rate", type=int, default=30, help="State updates per second")
    p.add_argument("--interp-ms", type=int, default=100,
                   help="Interpolation buffer in ms")
    p.add_argument("--dolphin-pid", type=int, default=None,
                   help="Dolphin process ID (auto-detected if not set)")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p.parse_args()


async def _main(args: argparse.Namespace) -> None:
    client = NetplayClient(
        server_url=args.server,
        room=args.room,
        player_name=args.name[:8],
        town_name="",  # will be read from memory after attach
        password=args.password,
        player_slot=args.player_slot,
        tick_rate=args.tick_rate,
        interp_ms=args.interp_ms,
        dolphin_pid=args.dolphin_pid,
    )
    await client.run()


if __name__ == "__main__":
    _args = parse_args()
    logging.basicConfig(
        level=getattr(logging, _args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(_main(_args))
