"""
Game state data classes for AC-Netplay.

These classes represent the data exchanged between players via the relay server.
All fields use Python-native types; serialisation to/from JSON dicts is handled
by to_dict() / from_dict() class methods.
"""

from __future__ import annotations

import base64
import math
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass
class PlayerState:
    """Real-time actor state (position, animation, held item)."""

    pos_x: float = 0.0
    pos_y: float = 0.0
    pos_z: float = 0.0
    angle: float = 0.0
    anim: int = 0
    anim_frame: int = 0
    move_state: int = 0
    held_item: int = 0
    emote: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pos": [self.pos_x, self.pos_y, self.pos_z],
            "angle": self.angle,
            "anim": self.anim,
            "anim_frame": self.anim_frame,
            "move_state": self.move_state,
            "held_item": self.held_item,
            "emote": self.emote,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PlayerState:
        pos = d.get("pos", [0.0, 0.0, 0.0])
        return cls(
            pos_x=float(pos[0]) if len(pos) > 0 else 0.0,
            pos_y=float(pos[1]) if len(pos) > 1 else 0.0,
            pos_z=float(pos[2]) if len(pos) > 2 else 0.0,
            angle=float(d.get("angle", 0.0)),
            anim=int(d.get("anim", 0)),
            anim_frame=int(d.get("anim_frame", 0)),
            move_state=int(d.get("move_state", 0)),
            held_item=int(d.get("held_item", 0)),
            emote=int(d.get("emote", 0)),
        )

    @staticmethod
    def lerp(a: PlayerState, b: PlayerState, t: float) -> PlayerState:
        """Linear interpolation between two states."""

        def lf(av: float, bv: float) -> float:
            return av + (bv - av) * t

        def angle_lerp(av: float, bv: float) -> float:
            """Shortest-path angle interpolation."""
            diff = (bv - av + math.pi) % (2 * math.pi) - math.pi
            return av + diff * t

        return PlayerState(
            pos_x=lf(a.pos_x, b.pos_x),
            pos_y=lf(a.pos_y, b.pos_y),
            pos_z=lf(a.pos_z, b.pos_z),
            angle=angle_lerp(a.angle, b.angle),
            anim=b.anim,           # discrete; no lerp
            anim_frame=b.anim_frame,
            move_state=b.move_state,
            held_item=b.held_item,
            emote=b.emote,
        )


@dataclass
class AppearanceState:
    """Player visual appearance (read from save data, changes infrequently)."""

    face: int = 0
    hair: int = 0
    hair_color: int = 0
    gender: int = 0
    tan: int = 0
    shirt: int = 0
    hat: int = 0
    glasses: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "face": self.face,
            "hair": self.hair,
            "hair_color": self.hair_color,
            "gender": self.gender,
            "tan": self.tan,
            "shirt": self.shirt,
            "hat": self.hat,
            "glasses": self.glasses,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AppearanceState:
        return cls(
            face=int(d.get("face", 0)),
            hair=int(d.get("hair", 0)),
            hair_color=int(d.get("hair_color", 0)),
            gender=int(d.get("gender", 0)),
            tan=int(d.get("tan", 0)),
            shirt=int(d.get("shirt", 0)),
            hat=int(d.get("hat", 0)),
            glasses=int(d.get("glasses", 0)),
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AppearanceState):
            return False
        return asdict(self) == asdict(other)


@dataclass
class GameEvent:
    """A discrete in-game event (item pickup, gate open, etc.)."""

    event: str = ""
    player_id: str = ""
    tile_x: int = 0
    tile_z: int = 0
    item_code: int = 0
    building_id: int = 0

    KNOWN_EVENTS = frozenset({
        "ITEM_PICKUP",
        "ITEM_DROP",
        "ITEM_BURY",
        "ITEM_DIG",
        "ENTER_BUILDING",
        "EXIT_BUILDING",
        "GATE_OPEN",
        "GATE_CLOSE",
        "TIME_SYNC",
        "HOST_CHANGED",
    })

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": "GAME_EVENT", "event": self.event}
        if self.event in ("ITEM_PICKUP", "ITEM_DROP", "ITEM_BURY", "ITEM_DIG"):
            d["tile_x"] = self.tile_x
            d["tile_z"] = self.tile_z
            d["item_code"] = self.item_code
        if self.event in ("ENTER_BUILDING", "EXIT_BUILDING"):
            d["building_id"] = self.building_id
        return d

    @classmethod
    def from_dict(cls, d: dict) -> GameEvent:
        return cls(
            event=str(d.get("event", "")),
            player_id=str(d.get("player_id", "")),
            tile_x=int(d.get("tile_x", 0)),
            tile_z=int(d.get("tile_z", 0)),
            item_code=int(d.get("item_code", 0)),
            building_id=int(d.get("building_id", 0)),
        )


@dataclass
class TownData:
    """
    Snapshot of the host's town sent to the visitor at connection time.

    Contains the town grid (terrain + surface items) and the town name so
    that the visitor's Dolphin instance can render the host's town.

    The *grid_bytes* field holds the raw town grid read from GC RAM:
    96 rows × 112 tiles × 2 bytes (big-endian u16 item codes) = 21,504 bytes.
    It is serialised as a Base64 string for JSON transport.
    """

    town_name: str = ""
    grid_bytes: bytes = field(default_factory=bytes)

    # Expected grid size: TOWN_HEIGHT × TOWN_WIDTH × sizeof(u16)
    GRID_SIZE: int = 96 * 112 * 2  # 21,504 bytes

    def to_dict(self) -> dict[str, Any]:
        return {
            "town_name": self.town_name,
            "grid": base64.b64encode(self.grid_bytes).decode("ascii"),
        }

    @classmethod
    def from_dict(cls, d: dict) -> TownData:
        raw = d.get("grid", "")
        try:
            grid_bytes = base64.b64decode(raw) if raw else b""
        except Exception:
            grid_bytes = b""
        return cls(
            town_name=str(d.get("town_name", "")),
            grid_bytes=grid_bytes,
        )

    def is_valid(self) -> bool:
        """Return True if the grid payload is the correct size."""
        return len(self.grid_bytes) == self.GRID_SIZE
