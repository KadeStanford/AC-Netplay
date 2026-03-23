"""
Tests for the relay server room management (server/room.py).
No actual WebSocket connections — uses mock websocket objects.
"""

import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import pytest
from unittest.mock import AsyncMock, MagicMock

from room import Player, Room, RoomManager


def make_player(player_id: str, name: str = "Alice", town: str = "Test") -> Player:
    ws = AsyncMock()
    ws.send = AsyncMock()
    ws.remote_address = ("127.0.0.1", 9000)
    return Player(player_id=player_id, player_name=name, town_name=town, websocket=ws)


@pytest.fixture
def manager():
    return RoomManager(max_rooms=5, max_players=4)


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class TestPlayer:
    def test_to_dict(self):
        p = make_player("id1", "Bob", "Leafton")
        d = p.to_dict()
        assert d["player_id"] == "id1"
        assert d["player_name"] == "Bob"
        assert d["town_name"] == "Leafton"
        assert "appearance" in d

    def test_appearance_default_empty(self):
        p = make_player("id1")
        assert p.appearance == {}


class TestRoomManager:
    @pytest.mark.asyncio
    async def test_create_room_on_first_join(self, manager):
        p = make_player("p1", "Alice")
        result = await manager.join_room(p, "TestRoom", "")
        assert isinstance(result, Room)
        assert result.name == "TestRoom"
        assert result.host_id == "p1"
        assert "p1" in result.players

    @pytest.mark.asyncio
    async def test_second_player_joins_existing_room(self, manager):
        p1 = make_player("p1", "Alice")
        p2 = make_player("p2", "Bob")
        await manager.join_room(p1, "TestRoom", "")
        result = await manager.join_room(p2, "TestRoom", "")
        assert isinstance(result, Room)
        assert len(result.players) == 2

    @pytest.mark.asyncio
    async def test_room_full_error(self, manager):
        players = [make_player(f"p{i}", f"Player{i}") for i in range(5)]
        room_name = "FullRoom"
        for i, p in enumerate(players[:4]):
            r = await manager.join_room(p, room_name, "")
            assert isinstance(r, Room), f"Player {i} should join successfully"
        # 5th player should be rejected
        result = await manager.join_room(players[4], room_name, "")
        assert result == "ROOM_FULL"

    @pytest.mark.asyncio
    async def test_wrong_password(self, manager):
        p1 = make_player("p1", "Alice")
        p2 = make_player("p2", "Bob")
        await manager.join_room(p1, "SecureRoom", "correct")
        result = await manager.join_room(p2, "SecureRoom", "wrong")
        assert result == "WRONG_PASSWORD"

    @pytest.mark.asyncio
    async def test_correct_password_allowed(self, manager):
        p1 = make_player("p1", "Alice")
        p2 = make_player("p2", "Bob")
        await manager.join_room(p1, "SecureRoom", "secret")
        result = await manager.join_room(p2, "SecureRoom", "secret")
        assert isinstance(result, Room)

    @pytest.mark.asyncio
    async def test_duplicate_name_rejected(self, manager):
        p1 = make_player("p1", "Alice")
        p2 = make_player("p2", "Alice")  # same name
        await manager.join_room(p1, "TestRoom", "")
        result = await manager.join_room(p2, "TestRoom", "")
        assert result == "NAME_TAKEN"

    @pytest.mark.asyncio
    async def test_remove_player_sends_left_message(self, manager):
        p1 = make_player("p1", "Alice")
        p2 = make_player("p2", "Bob")
        room = await manager.join_room(p1, "TestRoom", "")
        await manager.join_room(p2, "TestRoom", "")
        await manager.remove_player(room, p1)
        # p2 should have received PLAYER_LEFT
        calls = [json.loads(call.args[0]) for call in p2.websocket.send.call_args_list]
        left_msgs = [c for c in calls if c.get("type") == "PLAYER_LEFT"]
        assert any(m["player_id"] == "p1" for m in left_msgs)

    @pytest.mark.asyncio
    async def test_empty_room_destroyed(self, manager):
        p1 = make_player("p1", "Alice")
        room = await manager.join_room(p1, "TestRoom", "")
        await manager.remove_player(room, p1)
        assert "TestRoom" not in manager._rooms

    @pytest.mark.asyncio
    async def test_host_transferred_on_host_leave(self, manager):
        p1 = make_player("p1", "Alice")
        p2 = make_player("p2", "Bob")
        room = await manager.join_room(p1, "TestRoom", "")
        await manager.join_room(p2, "TestRoom", "")
        assert room.host_id == "p1"
        await manager.remove_player(room, p1)
        assert room.host_id == "p2"

    @pytest.mark.asyncio
    async def test_max_rooms_limit(self, manager):
        for i in range(5):
            p = make_player(f"p{i}", f"Player{i}")
            await manager.join_room(p, f"Room{i}", "")
        # 6th room should fail
        p_extra = make_player("extra", "Extra")
        result = await manager.join_room(p_extra, "ExtraRoom", "")
        assert result == "INTERNAL"

    @pytest.mark.asyncio
    async def test_broadcast_excludes_sender(self, manager):
        p1 = make_player("p1", "Alice")
        p2 = make_player("p2", "Bob")
        p3 = make_player("p3", "Carol")
        room = await manager.join_room(p1, "TestRoom", "")
        await manager.join_room(p2, "TestRoom", "")
        await manager.join_room(p3, "TestRoom", "")

        p1.websocket.send.reset_mock()
        p2.websocket.send.reset_mock()
        p3.websocket.send.reset_mock()

        msg = {"type": "TEST", "data": "hello"}
        await manager.broadcast(room, msg, exclude="p1")

        # p1 should NOT receive; p2 and p3 should
        p1.websocket.send.assert_not_called()
        p2.websocket.send.assert_called_once()
        p3.websocket.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_empty_room(self, manager):
        """Broadcast to an empty room should not raise."""
        room = Room(name="Empty")
        await manager.broadcast(room, {"type": "TEST"})
