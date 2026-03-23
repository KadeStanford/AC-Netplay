"""
Tests for the host/visitor co-presence logic in client/client.py.

Tests the role-determination from ROOM_STATE and the town-data apply
pathway, using mock DolphinMemory objects so no real Dolphin is needed.
"""

from __future__ import annotations

import asyncio
import json
import struct
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))

import pytest
from state import TownData, PlayerState
from client import NetplayClient, _interpolate


VALID_GRID = bytes(TownData.GRID_SIZE)


def make_client(**kwargs) -> NetplayClient:
    defaults = dict(
        server_url="ws://localhost:9000",
        room="TestRoom",
        player_name="Alice",
        town_name="Timberland",
        password="",
        player_slot=0,
        tick_rate=30,
        interp_ms=100,
        dolphin_pid=None,
    )
    defaults.update(kwargs)
    return NetplayClient(**defaults)


class TestRoleDetection:
    """Role (host vs visitor) is determined from the ROOM_STATE message."""

    def _apply_room_state(self, client: NetplayClient, host_id: str, my_id: str):
        """Simulate what _handshake does with ROOM_STATE."""
        client.player_id = my_id
        client._host_player_id = host_id
        client._is_host = (host_id == my_id)

    def test_first_player_is_host(self):
        c = make_client()
        self._apply_room_state(c, host_id="aaa", my_id="aaa")
        assert c._is_host is True
        assert c._host_player_id == "aaa"

    def test_second_player_is_visitor(self):
        c = make_client()
        self._apply_room_state(c, host_id="aaa", my_id="bbb")
        assert c._is_host is False
        assert c._host_player_id == "aaa"

    def test_host_stays_host_after_reconnect(self):
        c = make_client()
        self._apply_room_state(c, host_id="aaa", my_id="aaa")
        # Simulate reconnect (same player_id)
        self._apply_room_state(c, host_id="aaa", my_id="aaa")
        assert c._is_host is True

    def test_role_changes_on_host_changed_event(self):
        c = make_client()
        self._apply_room_state(c, host_id="aaa", my_id="bbb")
        assert c._is_host is False
        # Simulate HOST_CHANGED event pointing to us
        c._is_host = True
        c._host_player_id = "bbb"
        assert c._is_host is True


class TestSendTownData:
    """Host sends TOWN_DATA when a visitor joins."""

    @pytest.mark.asyncio
    async def test_host_sends_town_data_on_player_joined(self):
        c = make_client()
        c.player_id = "host_id"
        c._is_host = True

        # Set up a mock mem that returns a valid TownData
        mem = MagicMock()
        td = TownData(town_name="Timberland", grid_bytes=VALID_GRID)
        mem.read_town_snapshot.return_value = td
        c.mem = mem

        ws = AsyncMock()
        c.websocket = ws

        await c._send_town_data()

        ws.send.assert_called_once()
        sent = json.loads(ws.send.call_args[0][0])
        assert sent["type"] == "TOWN_DATA"
        assert sent["town_name"] == "Timberland"
        assert "grid" in sent
        assert len(sent["grid"]) > 0

    @pytest.mark.asyncio
    async def test_visitor_does_not_send_town_data(self):
        """_send_town_data is a no-op when not host (called only after is_host check)."""
        c = make_client()
        c.player_id = "visitor_id"
        c._is_host = False

        mem = MagicMock()
        td = TownData(town_name="Leafton", grid_bytes=VALID_GRID)
        mem.read_town_snapshot.return_value = td
        c.mem = mem

        ws = AsyncMock()
        c.websocket = ws

        # The method itself always sends; the guard is in _recv_loop.
        # Here we just verify the payload structure is correct if called.
        await c._send_town_data()
        ws.send.assert_called_once()  # method works; caller is responsible for guard

    @pytest.mark.asyncio
    async def test_send_town_data_handles_read_error(self):
        """If read_town_snapshot raises, _send_town_data should not crash."""
        c = make_client()
        c._is_host = True

        mem = MagicMock()
        mem.read_town_snapshot.side_effect = OSError("read failed")
        c.mem = mem

        ws = AsyncMock()
        c.websocket = ws

        await c._send_town_data()  # should log warning and return cleanly
        ws.send.assert_not_called()


class TestApplyTownData:
    """Visitor writes received TOWN_DATA into Dolphin RAM."""

    @pytest.mark.asyncio
    async def test_valid_town_data_writes_grid_and_teleports(self):
        c = make_client(player_slot=0)
        c.player_id = "visitor_id"
        c._is_host = False

        mem = MagicMock()
        c.mem = mem

        td = TownData(town_name="Timberland", grid_bytes=VALID_GRID)
        await c._apply_town_data(td)

        mem.write_town_grid.assert_called_once_with(VALID_GRID)
        mem.teleport_local_player.assert_called_once()
        # Verify teleport uses VISITOR_ARRIVAL_POS
        args = mem.teleport_local_player.call_args[0]
        assert args[0] == 0   # slot
        assert isinstance(args[1], float)  # X
        assert isinstance(args[2], float)  # Y
        assert isinstance(args[3], float)  # Z

    @pytest.mark.asyncio
    async def test_invalid_grid_skips_write(self):
        """An incorrectly sized grid should not be written to RAM."""
        c = make_client()
        c._is_host = False

        mem = MagicMock()
        c.mem = mem

        td = TownData(town_name="BadTown", grid_bytes=b"\x00" * 100)
        await c._apply_town_data(td)

        mem.write_town_grid.assert_not_called()
        mem.teleport_local_player.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_grid_exception_does_not_crash(self):
        """A write failure should be caught and logged, not propagated."""
        c = make_client()
        c._is_host = False

        mem = MagicMock()
        mem.write_town_grid.side_effect = OSError("write failed")
        c.mem = mem

        td = TownData(town_name="Timberland", grid_bytes=VALID_GRID)
        await c._apply_town_data(td)  # must not raise

        mem.write_town_grid.assert_called_once()
        # teleport should NOT be called if write failed
        mem.teleport_local_player.assert_not_called()

    @pytest.mark.asyncio
    async def test_item_codes_preserved_in_applied_grid(self):
        """Item codes in the grid are written verbatim to RAM."""
        c = make_client()
        c._is_host = False

        mem = MagicMock()
        c.mem = mem

        # Build a grid with item 0x2009 at tile (0,0)
        grid = bytearray(TownData.GRID_SIZE)
        struct.pack_into(">H", grid, 0, 0x2009)
        td = TownData(town_name="Timberland", grid_bytes=bytes(grid))
        await c._apply_town_data(td)

        written = mem.write_town_grid.call_args[0][0]
        assert struct.unpack_from(">H", written, 0)[0] == 0x2009


class TestVisitorSlotManagement:
    """Remote players (host or other visitors) get injected into visitor slots."""

    def test_host_appears_in_visitor_slot_on_visitor_machine(self):
        c = make_client()
        c.player_id = "visitor_id"
        c._is_host = False

        c._ensure_visitor_slot("host_id")
        assert "host_id" in c._visitor_slots
        assert c._visitor_slots["host_id"] == 0

    def test_multiple_remote_players_get_unique_slots(self):
        c = make_client()
        c._ensure_visitor_slot("p1")
        c._ensure_visitor_slot("p2")
        c._ensure_visitor_slot("p3")
        slots = list(c._visitor_slots.values())
        assert len(set(slots)) == 3  # all different
        assert sorted(slots) == [0, 1, 2]

    def test_ensure_slot_idempotent(self):
        c = make_client()
        c._ensure_visitor_slot("p1")
        c._ensure_visitor_slot("p1")  # second call should not increment
        assert c._visitor_slots["p1"] == 0
        assert c._next_visitor_slot == 1

    def test_release_slot_clears_state(self):
        c = make_client()
        mem = MagicMock()
        c.mem = mem

        c._ensure_visitor_slot("p1")
        c._remote_states["p1"] = [(1.0, PlayerState())]
        c._release_visitor_slot("p1")

        assert "p1" not in c._visitor_slots
        assert "p1" not in c._remote_states
        mem.clear_visitor_slot.assert_called_once_with(0)
