"""
Tests for the in-game room browser feature.

Covers:
  - RoomEntry dataclass (state.py)
  - RoomManager.list_rooms() (server/room.py)
  - Server LIST_ROOMS / ROOM_LIST message handling (server/server.py)
  - DolphinMemory room-browser helpers (client/dolphin_memory.py)
  - NetplayClient browse mode: _browse_and_join, _handle_room_list,
    _hello, _join_room separation, APPEARANCE-after-room-join ordering

No real Dolphin process or network connection is needed — all external
dependencies are mocked.
"""

from __future__ import annotations

import asyncio
import json
import struct
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import pytest
from state import RoomEntry, TownData
from client import NetplayClient, STATION_APPROACH_Z_THRESHOLD
from room import Player, Room, RoomManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_client(**kwargs) -> NetplayClient:
    defaults = dict(
        server_url="ws://localhost:9000",
        player_name="Alice",
        town_name="Timberland",
        room="",           # browse mode by default in these tests
        password="",
        player_slot=0,
        tick_rate=30,
        interp_ms=100,
        dolphin_pid=None,
    )
    defaults.update(kwargs)
    return NetplayClient(**defaults)


def make_player(player_id: str, name: str = "Alice", town: str = "Test") -> Player:
    ws = AsyncMock()
    ws.send = AsyncMock()
    ws.remote_address = ("127.0.0.1", 9000)
    return Player(player_id=player_id, player_name=name, town_name=town, websocket=ws)


WELCOME_MSG = json.dumps({"type": "WELCOME", "player_id": "test123",
                          "server_version": "1.0"})
ROOM_STATE_MSG = json.dumps({
    "type": "ROOM_STATE",
    "room": "AliceTown",
    "host": "test123",
    "players": [{"player_id": "test123", "player_name": "Alice",
                 "town_name": "Timberland", "appearance": {}}],
})


# ---------------------------------------------------------------------------
# RoomEntry dataclass
# ---------------------------------------------------------------------------

class TestRoomEntry:
    def test_default_values(self):
        r = RoomEntry()
        assert r.room_name == ""
        assert r.town_name == ""
        assert r.host_name == ""
        assert r.player_count == 0
        assert r.max_players == 4
        assert r.has_password is False

    def test_to_dict_structure(self):
        r = RoomEntry(room_name="AliceTown", town_name="Timberland",
                      host_name="Alice", player_count=2, max_players=4,
                      has_password=False)
        d = r.to_dict()
        assert d["room_name"] == "AliceTown"
        assert d["town_name"] == "Timberland"
        assert d["host_name"] == "Alice"
        assert d["player_count"] == 2
        assert d["max_players"] == 4
        assert d["has_password"] is False

    def test_from_dict_roundtrip(self):
        original = RoomEntry(room_name="X", town_name="Y", host_name="Z",
                             player_count=3, max_players=4, has_password=True)
        restored = RoomEntry.from_dict(original.to_dict())
        assert restored.room_name == "X"
        assert restored.town_name == "Y"
        assert restored.host_name == "Z"
        assert restored.player_count == 3
        assert restored.has_password is True

    def test_from_dict_missing_fields_use_defaults(self):
        r = RoomEntry.from_dict({})
        assert r.room_name == ""
        assert r.player_count == 0
        assert r.max_players == 4
        assert r.has_password is False

    def test_from_dict_coerces_types(self):
        r = RoomEntry.from_dict({"player_count": "3", "has_password": 1})
        assert r.player_count == 3
        assert r.has_password is True


# ---------------------------------------------------------------------------
# RoomManager.list_rooms()
# ---------------------------------------------------------------------------

class TestRoomManagerListRooms:
    @pytest.fixture
    def manager(self):
        return RoomManager(max_rooms=10, max_players=4)

    @pytest.mark.asyncio
    async def test_empty_server_returns_empty_list(self, manager):
        assert manager.list_rooms() == []

    @pytest.mark.asyncio
    async def test_single_room_appears_in_list(self, manager):
        p = make_player("h1", "Alice", "Timberland")
        await manager.join_room(p, "AliceTown", "")
        rooms = manager.list_rooms()
        assert len(rooms) == 1
        r = rooms[0]
        assert r["room_name"] == "AliceTown"
        assert r["town_name"] == "Timberland"
        assert r["host_name"] == "Alice"
        assert r["player_count"] == 1
        assert r["has_password"] is False

    @pytest.mark.asyncio
    async def test_password_room_flagged(self, manager):
        p = make_player("h1", "Alice", "Timberland")
        await manager.join_room(p, "SecretRoom", "hunter2")
        rooms = manager.list_rooms()
        assert rooms[0]["has_password"] is True

    @pytest.mark.asyncio
    async def test_multiple_rooms_all_listed(self, manager):
        for i in range(3):
            p = make_player(f"h{i}", f"Player{i}", f"Town{i}")
            await manager.join_room(p, f"Room{i}", "")
        assert len(manager.list_rooms()) == 3

    @pytest.mark.asyncio
    async def test_player_count_reflects_members(self, manager):
        p1 = make_player("h1", "Alice", "Timberland")
        p2 = make_player("h2", "Bob", "Leafton")
        await manager.join_room(p1, "SharedRoom", "")
        await manager.join_room(p2, "SharedRoom", "")
        rooms = manager.list_rooms()
        assert rooms[0]["player_count"] == 2

    @pytest.mark.asyncio
    async def test_destroyed_room_not_listed(self, manager):
        p = make_player("h1", "Alice", "Timberland")
        room = await manager.join_room(p, "TempRoom", "")
        await manager.remove_player(room, p)
        assert manager.list_rooms() == []


# ---------------------------------------------------------------------------
# Client._handle_room_list() — updates _available_rooms and writes to memory
# ---------------------------------------------------------------------------

class TestHandleRoomList:
    def test_empty_list_clears_available_rooms(self):
        c = make_client()
        c._available_rooms = [RoomEntry(room_name="old")]
        c._handle_room_list([])
        assert c._available_rooms == []

    def test_list_populated_from_dicts(self):
        c = make_client()
        c._handle_room_list([
            {"room_name": "AliceTown", "town_name": "Timberland",
             "host_name": "Alice", "player_count": 1, "has_password": False},
            {"room_name": "BobTown", "town_name": "Leafton",
             "host_name": "Bob", "player_count": 2, "has_password": True},
        ])
        assert len(c._available_rooms) == 2
        assert c._available_rooms[0].room_name == "AliceTown"
        assert c._available_rooms[1].has_password is True

    def test_writes_to_dolphin_memory_when_mem_attached(self):
        c = make_client()
        mem = MagicMock()
        c.mem = mem
        c._handle_room_list([
            {"room_name": "R1", "town_name": "T1", "host_name": "H1",
             "player_count": 1, "has_password": False},
        ])
        mem.write_room_browser_list.assert_called_once()
        written = mem.write_room_browser_list.call_args[0][0]
        assert len(written) == 1
        assert written[0].room_name == "R1"

    def test_memory_write_error_does_not_crash(self):
        c = make_client()
        mem = MagicMock()
        mem.write_room_browser_list.side_effect = OSError("write failed")
        c.mem = mem
        c._handle_room_list([{"room_name": "X"}])  # must not raise


# ---------------------------------------------------------------------------
# Client._browse_and_join() — the core in-game joining flow
#
# Key things proven here:
#   1. APPEARANCE is NOT sent before room join (would be rejected by server)
#   2. ROOM_LIST is received directly (not via _recv_loop which isn't running)
#   3. join_trigger being set causes _join_room to be called
#   4. Invalid trigger index is safely ignored
# ---------------------------------------------------------------------------

class TestBrowseAndJoin:
    def _make_ws(self, messages: list[str]) -> AsyncMock:
        """
        Build a mock WebSocket whose recv() returns each message in turn,
        then raises asyncio.TimeoutError (simulating the 0.1s timeout expiring).
        """
        ws = AsyncMock()
        ws.send = AsyncMock()
        side_effects = list(messages) + [asyncio.TimeoutError()] * 100
        ws.recv = AsyncMock(side_effect=side_effects)
        return ws

    @pytest.mark.asyncio
    async def test_appearance_not_sent_during_browse(self):
        """
        _browse_and_join must NOT send APPEARANCE — that belongs to
        _connect_and_loop, which sends it only after _join_room completes.
        Sending APPEARANCE before joining a room would trigger a server-side
        'Not in a room' error.
        """
        c = make_client()

        # No rooms available, trigger set immediately with idx=0 pointing at
        # a valid entry
        c._available_rooms = [RoomEntry(room_name="AliceTown")]
        mem = MagicMock()
        mem.read_player_pos.return_value = (56.0, 0.0, 85.0)  # near station
        mem.read_room_browser_trigger.return_value = True
        mem.read_room_browser_selection.return_value = 0
        c.mem = mem

        ws = AsyncMock()
        ws.send = AsyncMock()
        # recv raises TimeoutError every call (no ROOM_LIST to process)
        ws.recv = AsyncMock(side_effect=asyncio.TimeoutError())

        # Patch _join_room so it doesn't try to do real I/O
        joined = []
        async def fake_join_room(ws_, room, password):
            joined.append(room)
        c._join_room = fake_join_room

        await c._browse_and_join(ws)

        # APPEARANCE must not have been sent by _browse_and_join
        appearance_sends = [
            call for call in ws.send.call_args_list
            if json.loads(call.args[0]).get("type") == "APPEARANCE"
        ]
        assert appearance_sends == [], (
            "APPEARANCE was sent inside _browse_and_join — it must only be "
            "sent AFTER the room is joined, in _connect_and_loop"
        )

    @pytest.mark.asyncio
    async def test_room_list_received_directly(self):
        """
        _browse_and_join reads ROOM_LIST from the WebSocket itself and
        populates _available_rooms, because _recv_loop is not running yet.
        The test exits naturally by making the trigger fire right after the
        room list is received (no task-cancellation timing needed).
        """
        c = make_client()
        c._available_rooms = []

        room_list_msg = json.dumps({
            "type": "ROOM_LIST",
            "rooms": [{"room_name": "AliceTown", "town_name": "Timberland",
                       "host_name": "Alice", "player_count": 1,
                       "has_password": False}],
        })

        mem = MagicMock()
        mem.read_player_pos.return_value = (56.0, 0.0, 85.0)

        # Trigger fires as soon as _available_rooms is non-empty (set by _handle_room_list)
        mem.read_room_browser_trigger.side_effect = (
            lambda: len(c._available_rooms) > 0
        )
        mem.read_room_browser_selection.return_value = 0
        c.mem = mem

        # recv: first call returns ROOM_LIST, subsequent calls raise TimeoutError
        # We use a regular (non-async) side_effect to avoid AsyncMock coroutine quirks.
        call_count = [0]
        def recv_fn():
            call_count[0] += 1
            if call_count[0] == 1:
                return room_list_msg
            raise asyncio.TimeoutError()

        ws = AsyncMock()
        ws.send = AsyncMock()
        ws.recv = AsyncMock(side_effect=recv_fn)

        joined = []
        async def fake_join_room(ws_, room, password):
            joined.append(room)
        c._join_room = fake_join_room

        # Loop exits naturally: ROOM_LIST received → trigger fires → join → return
        await c._browse_and_join(ws)

        assert len(c._available_rooms) == 1
        assert c._available_rooms[0].room_name == "AliceTown"
        assert joined == ["AliceTown"]

    @pytest.mark.asyncio
    async def test_join_trigger_causes_join_room_call(self):
        """When join_trigger is set, _join_room is called with the chosen room."""
        c = make_client()
        c._available_rooms = [
            RoomEntry(room_name="AliceTown", town_name="Timberland"),
            RoomEntry(room_name="BobTown",   town_name="Leafton"),
        ]

        mem = MagicMock()
        mem.read_player_pos.return_value = (56.0, 0.0, 85.0)
        mem.read_room_browser_trigger.return_value = True
        mem.read_room_browser_selection.return_value = 1   # select BobTown
        c.mem = mem

        ws = AsyncMock()
        ws.recv = AsyncMock(side_effect=asyncio.TimeoutError())

        joined = []
        async def fake_join_room(ws_, room, password):
            joined.append(room)
        c._join_room = fake_join_room

        await c._browse_and_join(ws)

        assert joined == ["BobTown"]
        assert c.room == "BobTown"
        mem.set_room_browser_active.assert_called_with(False)
        mem.clear_room_browser_trigger.assert_called()

    @pytest.mark.asyncio
    async def test_invalid_trigger_index_ignored(self):
        """
        An out-of-range selection index clears the trigger and waits for the
        next valid selection.  The loop must not join on a bad index.
        We verify this by:
          1st trigger: bad index (99)  → cleared, no join
          2nd trigger: valid index (0) → join occurs, loop exits
        """
        c = make_client()
        c._available_rooms = [RoomEntry(room_name="AliceTown")]

        trigger_count = [0]

        def trigger_fn():
            trigger_count[0] += 1
            # Both iterations report trigger=True; selection index differs
            return True

        def selection_fn():
            if trigger_count[0] == 1:
                return 99   # out of range on first check
            return 0        # valid on second check

        mem = MagicMock()
        mem.read_player_pos.return_value = (56.0, 0.0, 85.0)
        mem.read_room_browser_trigger.side_effect = trigger_fn
        mem.read_room_browser_selection.side_effect = selection_fn
        c.mem = mem

        ws = AsyncMock()
        ws.send = AsyncMock()
        ws.recv = AsyncMock(side_effect=asyncio.TimeoutError())

        joined = []
        async def fake_join(ws_, room, password):
            joined.append(room)
        c._join_room = fake_join

        # Loop exits naturally on second trigger (valid index)
        await c._browse_and_join(ws)

        assert joined == ["AliceTown"], "Should join on second trigger (valid index)"
        # clear_room_browser_trigger must have been called at least twice:
        # once for the bad index and once for the successful join
        assert mem.clear_room_browser_trigger.call_count >= 2

    @pytest.mark.asyncio
    async def test_overlay_activates_near_station(self):
        """
        The browser overlay is shown when pos_z >= STATION_APPROACH_Z_THRESHOLD
        and hidden when the player is far from the station (low Z).
        Z increases going north in AC GCube; the train station is at the north.

        The loop exits naturally: trigger fires on the third iteration after
        both positions have been observed.
        """
        c = make_client()
        c._available_rooms = [RoomEntry(room_name="AliceTown")]

        set_active_calls = []
        pos_iter = [0]

        mem = MagicMock()

        def pos_side_effect(slot):
            pos_iter[0] += 1
            if pos_iter[0] == 1:
                return (56.0, 0.0, 10.0)   # far south — below threshold
            return (56.0, 0.0, 85.0)        # near station — above threshold

        trigger_calls = [0]

        def trigger_fn():
            trigger_calls[0] += 1
            # Fire the trigger on the 3rd iteration so we see both positions first
            return trigger_calls[0] >= 3

        mem.read_player_pos.side_effect = pos_side_effect
        mem.set_room_browser_active.side_effect = lambda v: set_active_calls.append(v)
        mem.read_room_browser_trigger.side_effect = trigger_fn
        mem.read_room_browser_selection.return_value = 0
        c.mem = mem

        ws = AsyncMock()
        ws.send = AsyncMock()
        # recv always raises TimeoutError — no messages to process
        ws.recv = AsyncMock(side_effect=asyncio.TimeoutError())

        joined = []
        async def fake_join(ws_, room, password):
            joined.append(room)
        c._join_room = fake_join

        # Loop exits naturally on the 3rd trigger check
        await c._browse_and_join(ws)

        assert joined == ["AliceTown"]
        assert False in set_active_calls, "Overlay should be hidden far from station"
        assert True in set_active_calls, "Overlay should be shown near the station"

    @pytest.mark.asyncio
    async def test_station_threshold_value_is_high_z(self):
        """
        In AC GameCube world-space, Z increases northward.
        The train station is at the northern edge, so STATION_APPROACH_Z_THRESHOLD
        must be a HIGH value (near the 96-tile northern boundary), not a low one.
        """
        assert STATION_APPROACH_Z_THRESHOLD >= 60.0, (
            f"Expected threshold >= 60 (high Z = north/train station), "
            f"got {STATION_APPROACH_Z_THRESHOLD}"
        )


# ---------------------------------------------------------------------------
# Client._hello() — separate from _join_room
# ---------------------------------------------------------------------------

class TestHello:
    @pytest.mark.asyncio
    async def test_hello_assigns_player_id(self):
        c = make_client()
        mem = MagicMock()
        c.mem = mem

        ws = AsyncMock()
        ws.recv = AsyncMock(return_value=WELCOME_MSG)

        await c._hello(ws)

        assert c.player_id == "test123"

    @pytest.mark.asyncio
    async def test_hello_error_raises(self):
        c = make_client()
        mem = MagicMock()
        c.mem = mem

        ws = AsyncMock()
        ws.recv = AsyncMock(return_value=json.dumps(
            {"type": "ERROR", "code": "BAD_VERSION", "message": "bad"}
        ))

        with pytest.raises(RuntimeError, match="Server rejected HELLO"):
            await c._hello(ws)

    @pytest.mark.asyncio
    async def test_hello_does_not_send_appearance(self):
        """
        _hello must only send HELLO and wait for WELCOME.
        APPEARANCE must not be sent — the server rejects it before room join.
        """
        c = make_client()
        mem = MagicMock()
        c.mem = mem

        ws = AsyncMock()
        ws.recv = AsyncMock(return_value=WELCOME_MSG)

        await c._hello(ws)

        sent_types = [json.loads(call.args[0])["type"]
                      for call in ws.send.call_args_list]
        assert sent_types == ["HELLO"], (
            f"_hello should only send HELLO, but sent: {sent_types}"
        )


# ---------------------------------------------------------------------------
# DolphinMemory room-browser helpers
# ---------------------------------------------------------------------------

class TestDolphinMemoryRoomBrowser:
    """
    Tests for the new room-browser memory helpers.  We test them via a
    subclass that stubs _read/_write with a local bytearray so no real
    process memory access is needed.
    """

    def _make_mem(self):
        """Return a DolphinMemory instance backed by a local buffer."""
        from dolphin_memory import (
            DolphinMemory, ROOM_BROWSER_BASE, GC_MEM1_BASE, GC_MEM1_SIZE,
        )

        buf = bytearray(GC_MEM1_SIZE)

        class StubMem(DolphinMemory):
            def __init__(self_inner):
                self_inner._pid = 0
                self_inner._mem1_host_base = 0
                self_inner._system = "Linux"
                self_inner._mem_path = None
                self_inner._maps_path = None

            def _read(self_inner, gc_addr, size):
                off = gc_addr - GC_MEM1_BASE
                return bytes(buf[off:off + size])

            def _write(self_inner, gc_addr, data):
                off = gc_addr - GC_MEM1_BASE
                buf[off:off + len(data)] = data

        return StubMem(), buf

    def test_write_room_browser_list_count(self):
        mem, buf = self._make_mem()
        from dolphin_memory import ROOM_BROWSER_BASE, ROOM_BROWSER_COUNT_OFF
        entries = [RoomEntry(room_name="R1", town_name="T1", host_name="H1",
                             player_count=2),
                   RoomEntry(room_name="R2", town_name="T2", host_name="H2",
                             player_count=1)]
        mem.write_room_browser_list(entries)
        count = buf[ROOM_BROWSER_BASE - 0x80000000 + ROOM_BROWSER_COUNT_OFF]
        assert count == 2

    def test_write_room_browser_list_clears_unused_slots(self):
        mem, buf = self._make_mem()
        from dolphin_memory import (
            ROOM_BROWSER_BASE, ROOM_BROWSER_ENTRY_OFF, ROOM_BROWSER_ENTRY_SIZE,
            GC_MEM1_BASE,
        )
        # First write 3 entries
        entries3 = [RoomEntry(room_name=f"R{i}") for i in range(3)]
        mem.write_room_browser_list(entries3)
        # Then write 1 entry — slots 1, 2, 3 should be zeroed
        mem.write_room_browser_list([RoomEntry(room_name="OnlyOne")])

        base_off = ROOM_BROWSER_BASE - GC_MEM1_BASE
        # Slot 0 should contain the "OnlyOne" room_name at entry offset +16 (4 bytes)
        slot0_start = base_off + ROOM_BROWSER_ENTRY_OFF
        room_name_bytes = buf[slot0_start + 16: slot0_start + 20]
        assert room_name_bytes == b"Only", (
            f"Slot 0 room_name bytes should be b'Only' (first 4 chars of 'OnlyOne'), "
            f"got {room_name_bytes!r}"
        )
        for slot in range(1, 4):
            entry_start = base_off + ROOM_BROWSER_ENTRY_OFF + slot * ROOM_BROWSER_ENTRY_SIZE
            assert buf[entry_start:entry_start + ROOM_BROWSER_ENTRY_SIZE] == \
                   bytearray(ROOM_BROWSER_ENTRY_SIZE), \
                   f"Slot {slot} should be cleared"

    def test_read_room_browser_trigger_true(self):
        mem, buf = self._make_mem()
        from dolphin_memory import ROOM_BROWSER_BASE, ROOM_BROWSER_TRIGGER_OFF, GC_MEM1_BASE
        buf[ROOM_BROWSER_BASE - GC_MEM1_BASE + ROOM_BROWSER_TRIGGER_OFF] = 1
        assert mem.read_room_browser_trigger() is True

    def test_read_room_browser_trigger_false(self):
        mem, buf = self._make_mem()
        from dolphin_memory import ROOM_BROWSER_BASE, ROOM_BROWSER_TRIGGER_OFF, GC_MEM1_BASE
        buf[ROOM_BROWSER_BASE - GC_MEM1_BASE + ROOM_BROWSER_TRIGGER_OFF] = 0
        assert mem.read_room_browser_trigger() is False

    def test_clear_room_browser_trigger(self):
        mem, buf = self._make_mem()
        from dolphin_memory import ROOM_BROWSER_BASE, ROOM_BROWSER_TRIGGER_OFF, GC_MEM1_BASE
        buf[ROOM_BROWSER_BASE - GC_MEM1_BASE + ROOM_BROWSER_TRIGGER_OFF] = 1
        mem.clear_room_browser_trigger()
        assert buf[ROOM_BROWSER_BASE - GC_MEM1_BASE + ROOM_BROWSER_TRIGGER_OFF] == 0

    def test_set_room_browser_active_true(self):
        mem, buf = self._make_mem()
        from dolphin_memory import ROOM_BROWSER_BASE, ROOM_BROWSER_ACTIVE_OFF, GC_MEM1_BASE
        mem.set_room_browser_active(True)
        assert buf[ROOM_BROWSER_BASE - GC_MEM1_BASE + ROOM_BROWSER_ACTIVE_OFF] == 1

    def test_set_room_browser_active_false(self):
        mem, buf = self._make_mem()
        from dolphin_memory import ROOM_BROWSER_BASE, ROOM_BROWSER_ACTIVE_OFF, GC_MEM1_BASE
        mem.set_room_browser_active(True)
        mem.set_room_browser_active(False)
        assert buf[ROOM_BROWSER_BASE - GC_MEM1_BASE + ROOM_BROWSER_ACTIVE_OFF] == 0

    def test_read_room_browser_selection(self):
        mem, buf = self._make_mem()
        from dolphin_memory import ROOM_BROWSER_BASE, ROOM_BROWSER_SEL_OFF, GC_MEM1_BASE
        buf[ROOM_BROWSER_BASE - GC_MEM1_BASE + ROOM_BROWSER_SEL_OFF] = 2
        assert mem.read_room_browser_selection() == 2

    def test_write_room_browser_list_max_4_entries(self):
        """More than 4 entries should be silently capped at 4."""
        mem, buf = self._make_mem()
        from dolphin_memory import ROOM_BROWSER_BASE, ROOM_BROWSER_COUNT_OFF, GC_MEM1_BASE
        entries = [RoomEntry(room_name=f"R{i}") for i in range(6)]
        mem.write_room_browser_list(entries)
        count = buf[ROOM_BROWSER_BASE - GC_MEM1_BASE + ROOM_BROWSER_COUNT_OFF]
        assert count == 4
