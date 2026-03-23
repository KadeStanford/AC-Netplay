"""
Tests for game state data classes (client/state.py).
No Dolphin or network connection required.
"""

import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))

import pytest
from state import PlayerState, AppearanceState, GameEvent, TownData


class TestPlayerState:
    def test_default_values(self):
        s = PlayerState()
        assert s.pos_x == 0.0
        assert s.pos_y == 0.0
        assert s.pos_z == 0.0
        assert s.angle == 0.0
        assert s.held_item == 0

    def test_to_dict_structure(self):
        s = PlayerState(pos_x=1.0, pos_y=2.0, pos_z=3.0, angle=0.5,
                        anim=7, anim_frame=3, move_state=1,
                        held_item=0x2009, emote=2)
        d = s.to_dict()
        assert d["pos"] == [1.0, 2.0, 3.0]
        assert d["angle"] == pytest.approx(0.5)
        assert d["anim"] == 7
        assert d["anim_frame"] == 3
        assert d["move_state"] == 1
        assert d["held_item"] == 0x2009
        assert d["emote"] == 2

    def test_roundtrip(self):
        original = PlayerState(pos_x=10.5, pos_y=0.1, pos_z=-3.2,
                               angle=1.5708, anim=3, anim_frame=12,
                               move_state=2, held_item=8201, emote=0)
        d = original.to_dict()
        # Simulate what arrives from server (angle comes as float, pos as list)
        d["type"] = "PLAYER_STATE"
        d["player_id"] = "abc123"
        restored = PlayerState.from_dict(d)
        assert restored.pos_x == pytest.approx(original.pos_x, abs=1e-4)
        assert restored.pos_z == pytest.approx(original.pos_z, abs=1e-4)
        assert restored.held_item == original.held_item

    def test_from_dict_missing_fields(self):
        """from_dict should use safe defaults for missing fields."""
        s = PlayerState.from_dict({})
        assert s.pos_x == 0.0
        assert s.anim == 0

    def test_from_dict_partial_pos(self):
        s = PlayerState.from_dict({"pos": [5.0]})
        assert s.pos_x == 5.0
        assert s.pos_y == 0.0
        assert s.pos_z == 0.0

    def test_lerp_midpoint(self):
        a = PlayerState(pos_x=0.0, pos_z=0.0)
        b = PlayerState(pos_x=10.0, pos_z=10.0)
        mid = PlayerState.lerp(a, b, 0.5)
        assert mid.pos_x == pytest.approx(5.0)
        assert mid.pos_z == pytest.approx(5.0)

    def test_lerp_t0_equals_a(self):
        a = PlayerState(pos_x=1.0, pos_y=2.0, pos_z=3.0)
        b = PlayerState(pos_x=4.0, pos_y=5.0, pos_z=6.0)
        result = PlayerState.lerp(a, b, 0.0)
        assert result.pos_x == pytest.approx(1.0)
        assert result.pos_y == pytest.approx(2.0)
        assert result.pos_z == pytest.approx(3.0)

    def test_lerp_t1_equals_b(self):
        a = PlayerState(pos_x=1.0)
        b = PlayerState(pos_x=9.0)
        result = PlayerState.lerp(a, b, 1.0)
        assert result.pos_x == pytest.approx(9.0)

    def test_lerp_angle_wraps_correctly(self):
        """Angle interpolation should take the shortest path."""
        a = PlayerState(angle=0.1)
        b = PlayerState(angle=2 * math.pi - 0.1)
        # Shortest path is backward (decreasing), about -0.2 / 2 = -0.1 from a
        result = PlayerState.lerp(a, b, 0.5)
        # The midpoint of the short arc should be near 0 (or 2π)
        # both 0.0 and 2π are the same angle
        assert abs(result.angle) < 0.15 or abs(result.angle - 2 * math.pi) < 0.15

    def test_lerp_discrete_fields_take_b(self):
        a = PlayerState(anim=1, anim_frame=0, move_state=0, held_item=0, emote=0)
        b = PlayerState(anim=5, anim_frame=7, move_state=2, held_item=100, emote=3)
        result = PlayerState.lerp(a, b, 0.5)
        assert result.anim == b.anim
        assert result.anim_frame == b.anim_frame
        assert result.move_state == b.move_state
        assert result.held_item == b.held_item
        assert result.emote == b.emote


class TestAppearanceState:
    def test_default_values(self):
        a = AppearanceState()
        assert a.face == 0
        assert a.shirt == 0

    def test_to_dict_roundtrip(self):
        a = AppearanceState(face=3, hair=2, hair_color=1, gender=1,
                            tan=2, shirt=0x1000, hat=0x0200, glasses=0)
        d = a.to_dict()
        b = AppearanceState.from_dict(d)
        assert a == b

    def test_equality(self):
        a = AppearanceState(face=1)
        b = AppearanceState(face=1)
        c = AppearanceState(face=2)
        assert a == b
        assert a != c

    def test_not_equal_to_other_type(self):
        a = AppearanceState()
        assert a != "not an appearance"
        assert a != 42

    def test_from_dict_missing_fields(self):
        a = AppearanceState.from_dict({})
        assert a.face == 0
        assert a.gender == 0


class TestGameEvent:
    def test_item_pickup_roundtrip(self):
        e = GameEvent(event="ITEM_PICKUP", tile_x=10, tile_z=20, item_code=0x2009)
        d = e.to_dict()
        assert d["event"] == "ITEM_PICKUP"
        assert d["tile_x"] == 10
        assert d["tile_z"] == 20
        assert d["item_code"] == 0x2009

    def test_gate_open_has_no_tile_fields(self):
        e = GameEvent(event="GATE_OPEN")
        d = e.to_dict()
        assert "tile_x" not in d
        assert "item_code" not in d

    def test_enter_building_has_building_id(self):
        e = GameEvent(event="ENTER_BUILDING", building_id=3)
        d = e.to_dict()
        assert d["building_id"] == 3

    def test_from_dict(self):
        d = {
            "type": "GAME_EVENT",
            "player_id": "abc",
            "event": "ITEM_DROP",
            "tile_x": 5,
            "tile_z": 9,
            "item_code": 100,
        }
        e = GameEvent.from_dict(d)
        assert e.event == "ITEM_DROP"
        assert e.player_id == "abc"
        assert e.tile_x == 5
        assert e.item_code == 100

    def test_from_dict_defaults(self):
        e = GameEvent.from_dict({})
        assert e.event == ""
        assert e.tile_x == 0

    def test_known_events_set(self):
        for ev in ("ITEM_PICKUP", "ITEM_DROP", "GATE_OPEN", "GATE_CLOSE",
                   "ENTER_BUILDING", "EXIT_BUILDING", "TIME_SYNC"):
            assert ev in GameEvent.KNOWN_EVENTS


class TestTownData:
    """Tests for TownData — the host→visitor town grid transfer."""

    VALID_GRID = bytes(TownData.GRID_SIZE)  # all-zero grid, correct size

    def test_default_is_invalid(self):
        td = TownData()
        assert not td.is_valid()
        assert td.town_name == ""
        assert td.grid_bytes == b""

    def test_valid_grid_size(self):
        td = TownData(town_name="TestTown", grid_bytes=self.VALID_GRID)
        assert td.is_valid()

    def test_invalid_grid_wrong_size(self):
        td = TownData(town_name="TestTown", grid_bytes=b"\x00" * 100)
        assert not td.is_valid()

    def test_grid_size_constant(self):
        assert TownData.GRID_SIZE == 96 * 112 * 2  # 21,504 bytes

    def test_roundtrip_empty_grid(self):
        td = TownData(town_name="MyTown", grid_bytes=self.VALID_GRID)
        d = td.to_dict()
        restored = TownData.from_dict(d)
        assert restored.town_name == "MyTown"
        assert restored.grid_bytes == self.VALID_GRID
        assert restored.is_valid()

    def test_roundtrip_with_items(self):
        """Grid containing non-zero item codes survives base64 round-trip."""
        import struct
        # Build a grid where tile (0,0) has item code 0x2009 and rest are zero
        grid = bytearray(TownData.GRID_SIZE)
        struct.pack_into(">H", grid, 0, 0x2009)
        td = TownData(town_name="Leaf", grid_bytes=bytes(grid))
        restored = TownData.from_dict(td.to_dict())
        assert restored.grid_bytes == bytes(grid)
        assert struct.unpack_from(">H", restored.grid_bytes, 0)[0] == 0x2009

    def test_from_dict_missing_grid(self):
        td = TownData.from_dict({"town_name": "X"})
        assert td.grid_bytes == b""
        assert not td.is_valid()

    def test_from_dict_bad_base64_gives_empty(self):
        td = TownData.from_dict({"town_name": "X", "grid": "!!!not_base64!!!"})
        assert td.grid_bytes == b""

    def test_to_dict_type_tag(self):
        td = TownData(town_name="X", grid_bytes=self.VALID_GRID)
        d = td.to_dict()
        # Server prepends "type" = "TOWN_DATA"; check the payload fields exist
        assert "town_name" in d
        assert "grid" in d
        # Base64 string for all-zero grid should be non-empty
        assert len(d["grid"]) > 0
