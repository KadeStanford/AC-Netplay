"""
Dolphin memory interface for AC-Netplay.

Reads and writes the emulated GameCube RAM of a running Dolphin process.
Supports Linux (/proc/<pid>/mem), Windows (ReadProcessMemory via ctypes),
and macOS (vm_read via ctypes).

All addresses use the GameCube virtual address space (0x80000000 base).
Only MEM1 (24 MB, 0x80000000–0x817FFFFF) is accessed.
"""

from __future__ import annotations

import logging
import os
import platform
import struct
from typing import Optional

import psutil

from state import PlayerState, AppearanceState, TownData

logger = logging.getLogger("ac_netplay.dolphin_memory")

# GameCube MEM1: 24 MB starting at GC virtual address 0x80000000
GC_MEM1_BASE = 0x80000000
GC_MEM1_SIZE = 0x01800000  # 24 MB

GAME_ID_OFFSET = 0x00000000  # 6 bytes at start of MEM1

# Player data base addresses (stable, from save data loaded into RAM)
PLAYER_BASE = [
    0x803A7200,
    0x803A9400,
    0x803AB600,
    0x803AD800,
]

# Visitor actor list pointer (resolved at runtime)
VISITOR_LIST_PTR_ADDR = 0x803FFFF0

# Gate state byte
GATE_STATE_ADDR = 0x803B8000

# Town grid (u16 per tile, big-endian)
TOWN_GRID_ADDR = 0x803C0000
TOWN_WIDTH = 112   # tiles
TOWN_HEIGHT = 96   # tiles

# Total byte size of the town grid in RAM
TOWN_GRID_SIZE = TOWN_WIDTH * TOWN_HEIGHT * 2  # 21,504 bytes

# World-space position where a visitor's character is placed when the host
# town data is applied.  This is near the train-station / gate entrance in
# the southern-centre of the town map.
VISITOR_ARRIVAL_POS = (56.0, 0.0, 80.0)  # (X, Y, Z)

# In-memory actor pointer chain for local player
ACTOR_MANAGER_PTR_ADDR = 0x803FFFE0

# Offsets within a player data block
OFF_NAME = 0x0002         # char[8]
OFF_TOWN = 0x000A         # char[6]
OFF_GENDER = 0x0010       # u16
OFF_FACE = 0x0012         # u8
OFF_HAIR = 0x0013         # u8
OFF_HAIR_COLOR = 0x0014   # u8
OFF_TAN = 0x0015          # u8
OFF_SHIRT = 0x0016        # u16
OFF_HAT = 0x0018          # u16
OFF_GLASSES = 0x001A      # u16

# Offsets within an actor struct (position etc.)
ACT_POS_X = 0x08     # f32
ACT_POS_Y = 0x0C     # f32
ACT_POS_Z = 0x10     # f32
ACT_ANGLE = 0x14     # f32
ACT_ANIM = 0x20      # u16
ACT_ANIM_FRAME = 0x22  # u8
ACT_MOVE_STATE = 0x23  # u8
ACT_HELD_ITEM = 0x24   # u16
ACT_EMOTE = 0x28       # u8

# Visitor actor extra offsets (beyond ACT_*)
ACT_VISIT_NAME = 0x2A       # char[8]
ACT_VISIT_TOWN = 0x32       # char[6]
ACT_VISIT_FACE = 0x38       # u8
ACT_VISIT_HAIR = 0x39       # u8
ACT_VISIT_HAIR_COLOR = 0x3A # u8
ACT_VISIT_GENDER = 0x3B     # u8
ACT_VISIT_SHIRT = 0x3C      # u16


class DolphinMemory:
    """
    Thin wrapper around OS-level process memory access for Dolphin.

    The Dolphin process keeps its emulated MEM1 at a fixed *host* virtual
    address that we discover by scanning for the GameCube game-ID magic bytes.
    """

    GAME_ID = b"GAFE01"

    def __init__(self, pid: Optional[int] = None) -> None:
        self._pid = pid
        self._mem1_host_base: Optional[int] = None  # host VA of GC MEM1[0]
        self._system = platform.system()

        if self._system == "Windows":
            self._init_windows()
        elif self._system == "Linux":
            self._mem_path: Optional[str] = None
            self._maps_path: Optional[str] = None
        # macOS handled via /proc-like vm_region calls

    # ------------------------------------------------------------------
    # Windows initialisation (lazy import)
    # ------------------------------------------------------------------

    def _init_windows(self) -> None:
        import ctypes
        import ctypes.wintypes as wt
        self._kernel32 = ctypes.windll.kernel32
        PROCESS_VM_READ = 0x0010
        PROCESS_VM_WRITE = 0x0020
        PROCESS_VM_OPERATION = 0x0008
        PROCESS_QUERY_INFORMATION = 0x0400
        access = (PROCESS_VM_READ | PROCESS_VM_WRITE |
                  PROCESS_VM_OPERATION | PROCESS_QUERY_INFORMATION)
        if self._pid:
            self._hproc = self._kernel32.OpenProcess(access, False, self._pid)

    # ------------------------------------------------------------------
    # Attach / detect
    # ------------------------------------------------------------------

    def attach(self) -> None:
        """Find the Dolphin process and locate emulated MEM1 in host memory."""
        if self._pid is None:
            self._pid = self._find_dolphin_pid()
        logger.info("Attaching to Dolphin PID %d", self._pid)

        if self._system == "Linux":
            self._mem_path = f"/proc/{self._pid}/mem"
            self._maps_path = f"/proc/{self._pid}/maps"
            self._mem1_host_base = self._scan_mem1_linux()
        elif self._system == "Windows":
            self._mem1_host_base = self._scan_mem1_windows()
        elif self._system == "Darwin":
            self._mem1_host_base = self._scan_mem1_macos()
        else:
            raise RuntimeError(f"Unsupported platform: {self._system}")

        if self._mem1_host_base is None:
            raise RuntimeError(
                "Could not locate GameCube MEM1 in Dolphin's address space. "
                "Make sure Animal Crossing is loaded past the title screen."
            )
        logger.info("MEM1 host base: 0x%X", self._mem1_host_base)

    @staticmethod
    def _find_dolphin_pid() -> int:
        for proc in psutil.process_iter(["pid", "name"]):
            name = (proc.info["name"] or "").lower()
            if "dolphin" in name:
                logger.debug("Found Dolphin: %s (PID %d)", proc.info["name"], proc.info["pid"])
                return proc.info["pid"]
        raise RuntimeError(
            "Could not find Dolphin process. Is Dolphin running with a game loaded?"
        )

    # ------------------------------------------------------------------
    # Platform-specific MEM1 location
    # ------------------------------------------------------------------

    def _scan_mem1_linux(self) -> Optional[int]:
        """
        Parse /proc/<pid>/maps to find the 24 MB anonymous mapping that
        contains the GameCube game ID at offset 0.
        """
        try:
            with open(self._maps_path, "r") as f:
                lines = f.readlines()
        except OSError as e:
            raise RuntimeError(f"Cannot read {self._maps_path}: {e}") from e

        for line in lines:
            parts = line.split()
            if len(parts) < 5:
                continue
            addr_range = parts[0]
            perms = parts[1]
            if "r" not in perms:
                continue
            start_s, end_s = addr_range.split("-")
            start = int(start_s, 16)
            end = int(end_s, 16)
            size = end - start
            # MEM1 is exactly 24 MB (or sometimes mapped as 32 MB by Dolphin)
            if size not in (0x01800000, 0x02000000):
                continue
            # Verify game ID
            try:
                data = self._linux_read(start, 6)
                if data[:6] == self.GAME_ID:
                    return start
            except OSError:
                continue
        return None

    def _scan_mem1_windows(self) -> Optional[int]:
        """Walk the Windows virtual address space looking for the game ID."""
        import ctypes
        import ctypes.wintypes as wt

        class MEMORY_BASIC_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BaseAddress", ctypes.c_ulonglong),
                ("AllocationBase", ctypes.c_ulonglong),
                ("AllocationProtect", wt.DWORD),
                ("__alignment1", wt.DWORD),
                ("RegionSize", ctypes.c_ulonglong),
                ("State", wt.DWORD),
                ("Protect", wt.DWORD),
                ("Type", wt.DWORD),
                ("__alignment2", wt.DWORD),
            ]

        mbi = MEMORY_BASIC_INFORMATION()
        addr = 0
        MEM_COMMIT = 0x1000
        PAGE_READWRITE = 0x04

        while True:
            ret = self._kernel32.VirtualQueryEx(
                self._hproc, ctypes.c_void_p(addr),
                ctypes.byref(mbi), ctypes.sizeof(mbi)
            )
            if ret == 0:
                break
            if (mbi.State == MEM_COMMIT and
                    mbi.Protect == PAGE_READWRITE and
                    mbi.RegionSize in (0x01800000, 0x02000000)):
                try:
                    data = self._windows_read(mbi.BaseAddress, 6)
                    if data[:6] == self.GAME_ID:
                        return mbi.BaseAddress
                except OSError:
                    pass
            addr = mbi.BaseAddress + mbi.RegionSize
            if addr >= 0x7FFFFFFFFFFF:
                break
        return None

    def _scan_mem1_macos(self) -> Optional[int]:
        """
        On macOS, use the Mach VM API to scan regions.
        For simplicity, we fall back to reading /proc-like via libSystem.
        """
        import ctypes
        libc = ctypes.CDLL("libc.dylib", use_errno=True)
        # Minimal implementation: delegate to a helper that uses task_for_pid
        # For now, raise a clear error pointing users to a workaround.
        raise NotImplementedError(
            "macOS memory access requires the terminal app to be granted access "
            "to Dolphin under System Preferences → Security & Privacy → Privacy "
            "→ Developer Tools (macOS 13+). "
            "See docs/SETUP.md § 'Part 1 — Dolphin Configuration' for details."
        )

    # ------------------------------------------------------------------
    # Low-level read / write
    # ------------------------------------------------------------------

    def _gc_to_host(self, gc_addr: int) -> int:
        """Convert a GC virtual address to a host process virtual address."""
        if gc_addr < GC_MEM1_BASE or gc_addr >= GC_MEM1_BASE + GC_MEM1_SIZE:
            raise ValueError(f"GC address 0x{gc_addr:08X} outside MEM1")
        return self._mem1_host_base + (gc_addr - GC_MEM1_BASE)

    def _read(self, gc_addr: int, size: int) -> bytes:
        host_addr = self._gc_to_host(gc_addr)
        if self._system == "Linux":
            return self._linux_read(host_addr, size)
        if self._system == "Windows":
            return self._windows_read(host_addr, size)
        raise NotImplementedError(f"_read not implemented for {self._system}")

    def _write(self, gc_addr: int, data: bytes) -> None:
        host_addr = self._gc_to_host(gc_addr)
        if self._system == "Linux":
            self._linux_write(host_addr, data)
        elif self._system == "Windows":
            self._windows_write(host_addr, data)
        else:
            raise NotImplementedError(f"_write not implemented for {self._system}")

    def _linux_read(self, host_addr: int, size: int) -> bytes:
        with open(self._mem_path, "rb") as f:
            f.seek(host_addr)
            return f.read(size)

    def _linux_write(self, host_addr: int, data: bytes) -> None:
        with open(self._mem_path, "r+b") as f:
            f.seek(host_addr)
            f.write(data)

    def _windows_read(self, host_addr: int, size: int) -> bytes:
        import ctypes
        buf = (ctypes.c_char * size)()
        read = ctypes.c_size_t(0)
        ok = self._kernel32.ReadProcessMemory(
            self._hproc, ctypes.c_void_p(host_addr),
            buf, size, ctypes.byref(read)
        )
        if not ok:
            raise OSError(f"ReadProcessMemory failed at 0x{host_addr:X}")
        return bytes(buf[:read.value])

    def _windows_write(self, host_addr: int, data: bytes) -> None:
        import ctypes
        written = ctypes.c_size_t(0)
        ok = self._kernel32.WriteProcessMemory(
            self._hproc, ctypes.c_void_p(host_addr),
            data, len(data), ctypes.byref(written)
        )
        if not ok:
            raise OSError(f"WriteProcessMemory failed at 0x{host_addr:X}")

    # ------------------------------------------------------------------
    # Typed read helpers (big-endian, GC convention)
    # ------------------------------------------------------------------

    def read_u8(self, gc_addr: int) -> int:
        return struct.unpack(">B", self._read(gc_addr, 1))[0]

    def read_u16(self, gc_addr: int) -> int:
        return struct.unpack(">H", self._read(gc_addr, 2))[0]

    def read_u32(self, gc_addr: int) -> int:
        return struct.unpack(">I", self._read(gc_addr, 4))[0]

    def read_f32(self, gc_addr: int) -> float:
        return struct.unpack(">f", self._read(gc_addr, 4))[0]

    def read_str(self, gc_addr: int, length: int) -> str:
        raw = self._read(gc_addr, length)
        return raw.rstrip(b"\x00").decode("latin-1", errors="replace")

    def write_u8(self, gc_addr: int, value: int) -> None:
        self._write(gc_addr, struct.pack(">B", value & 0xFF))

    def write_u16(self, gc_addr: int, value: int) -> None:
        self._write(gc_addr, struct.pack(">H", value & 0xFFFF))

    def write_f32(self, gc_addr: int, value: float) -> None:
        self._write(gc_addr, struct.pack(">f", value))

    def write_str(self, gc_addr: int, text: str, length: int) -> None:
        encoded = text.encode("latin-1", errors="replace")[:length]
        padded = encoded.ljust(length, b"\x00")
        self._write(gc_addr, padded)

    # ------------------------------------------------------------------
    # Game-specific reads
    # ------------------------------------------------------------------

    def read_game_id(self) -> str:
        return self._read(GC_MEM1_BASE, 6).decode("ascii", errors="replace")

    def _resolve_player_actor(self, slot: int) -> Optional[int]:
        """Resolve the actor base address for player *slot* via pointer chain."""
        try:
            mgr = self.read_u32(ACTOR_MANAGER_PTR_ADDR)
            if mgr < GC_MEM1_BASE or mgr >= GC_MEM1_BASE + GC_MEM1_SIZE:
                return None
            player_list = self.read_u32(mgr + 0x14)
            if player_list < GC_MEM1_BASE:
                return None
            actor_ptr = self.read_u32(player_list + slot * 4)
            if actor_ptr < GC_MEM1_BASE:
                return None
            return actor_ptr
        except (OSError, struct.error, ValueError):
            return None

    def _resolve_visitor_actor(self, slot: int) -> Optional[int]:
        """Resolve the visitor actor base address for visitor *slot*."""
        try:
            visitor_list = self.read_u32(VISITOR_LIST_PTR_ADDR)
            if visitor_list < GC_MEM1_BASE:
                return None
            actor_ptr = self.read_u32(visitor_list + slot * 4)
            if actor_ptr < GC_MEM1_BASE:
                return None
            return actor_ptr
        except (OSError, struct.error, ValueError):
            return None

    def read_player_state(self, slot: int = 0) -> PlayerState:
        """Read the local player's real-time actor state."""
        actor = self._resolve_player_actor(slot)
        if actor is None:
            return PlayerState()
        try:
            return PlayerState(
                pos_x=self.read_f32(actor + ACT_POS_X),
                pos_y=self.read_f32(actor + ACT_POS_Y),
                pos_z=self.read_f32(actor + ACT_POS_Z),
                angle=self.read_f32(actor + ACT_ANGLE),
                anim=self.read_u16(actor + ACT_ANIM),
                anim_frame=self.read_u8(actor + ACT_ANIM_FRAME),
                move_state=self.read_u8(actor + ACT_MOVE_STATE),
                held_item=self.read_u16(actor + ACT_HELD_ITEM),
                emote=self.read_u8(actor + ACT_EMOTE),
            )
        except (OSError, struct.error, ValueError):
            return PlayerState()

    def read_appearance(self, slot: int = 0) -> AppearanceState:
        """Read player appearance from save data block."""
        base = PLAYER_BASE[slot]
        try:
            return AppearanceState(
                face=self.read_u8(base + OFF_FACE),
                hair=self.read_u8(base + OFF_HAIR),
                hair_color=self.read_u8(base + OFF_HAIR_COLOR),
                gender=self.read_u16(base + OFF_GENDER),
                tan=self.read_u8(base + OFF_TAN),
                shirt=self.read_u16(base + OFF_SHIRT),
                hat=self.read_u16(base + OFF_HAT),
                glasses=self.read_u16(base + OFF_GLASSES),
            )
        except (OSError, struct.error, ValueError):
            return AppearanceState()

    def read_town_name(self, slot: int = 0) -> str:
        base = PLAYER_BASE[slot]
        return self.read_str(base + OFF_TOWN, 6)

    # ------------------------------------------------------------------
    # Game-specific writes
    # ------------------------------------------------------------------

    def write_visitor_state(self, slot: int, state: PlayerState) -> None:
        """Write a remote player's state into visitor actor slot *slot*."""
        actor = self._resolve_visitor_actor(slot)
        if actor is None:
            return
        try:
            self.write_f32(actor + ACT_POS_X, state.pos_x)
            self.write_f32(actor + ACT_POS_Y, state.pos_y)
            self.write_f32(actor + ACT_POS_Z, state.pos_z)
            self.write_f32(actor + ACT_ANGLE, state.angle)
            self.write_u16(actor + ACT_ANIM, state.anim)
            self.write_u8(actor + ACT_ANIM_FRAME, state.anim_frame)
            self.write_u8(actor + ACT_MOVE_STATE, state.move_state)
            self.write_u16(actor + ACT_HELD_ITEM, state.held_item)
            self.write_u8(actor + ACT_EMOTE, state.emote)
        except (OSError, struct.error, ValueError) as e:
            logger.debug("write_visitor_state slot=%d: %s", slot, e)

    def write_visitor_appearance(self, slot: int, app: AppearanceState) -> None:
        """Write remote player appearance into visitor actor slot *slot*."""
        actor = self._resolve_visitor_actor(slot)
        if actor is None:
            return
        try:
            self.write_u8(actor + ACT_VISIT_FACE, app.face)
            self.write_u8(actor + ACT_VISIT_HAIR, app.hair)
            self.write_u8(actor + ACT_VISIT_HAIR_COLOR, app.hair_color)
            self.write_u8(actor + ACT_VISIT_GENDER, app.gender & 0xFF)
            self.write_u16(actor + ACT_VISIT_SHIRT, app.shirt)
        except (OSError, struct.error, ValueError) as e:
            logger.debug("write_visitor_appearance slot=%d: %s", slot, e)

    def write_gate_state(self, state: int) -> None:
        """Set the gate open (1) or closed (0)."""
        self.write_u8(GATE_STATE_ADDR, state & 0xFF)

    def clear_visitor_slot(self, slot: int) -> None:
        """Zero out a visitor actor to hide the character."""
        actor = self._resolve_visitor_actor(slot)
        if actor is None:
            return
        try:
            self.write_f32(actor + ACT_POS_X, 0.0)
            self.write_f32(actor + ACT_POS_Y, -9999.0)
            self.write_f32(actor + ACT_POS_Z, 0.0)
        except (OSError, struct.error, ValueError):
            pass

    def clear_tile_item(self, tile_x: int, tile_z: int) -> None:
        """Remove an item from the town grid tile."""
        addr = TOWN_GRID_ADDR + (tile_z * TOWN_WIDTH + tile_x) * 2
        self.write_u16(addr, 0x0000)

    def set_tile_item(self, tile_x: int, tile_z: int, item_code: int) -> None:
        """Place an item on the town grid tile."""
        addr = TOWN_GRID_ADDR + (tile_z * TOWN_WIDTH + tile_x) * 2
        self.write_u16(addr, item_code)

    # ------------------------------------------------------------------
    # Town snapshot — read / write the full town grid
    # ------------------------------------------------------------------

    def read_town_grid(self) -> bytes:
        """Read the full town grid from GC RAM (21,504 bytes, big-endian u16 array)."""
        return self._read(TOWN_GRID_ADDR, TOWN_GRID_SIZE)

    def write_town_grid(self, data: bytes) -> None:
        """
        Write a complete town grid into GC RAM.

        *data* must be exactly TOWN_GRID_SIZE (21,504) bytes.
        This immediately updates the terrain / surface items the game renders.
        """
        if len(data) != TOWN_GRID_SIZE:
            raise ValueError(
                f"Town grid must be {TOWN_GRID_SIZE} bytes, got {len(data)}"
            )
        self._write(TOWN_GRID_ADDR, data)

    def read_town_snapshot(self, slot: int = 0) -> "TownData":
        """
        Read the current town grid and town name into a :class:`TownData` object.

        Used by the *host* to capture and send their town to a joining visitor.
        """
        return TownData(
            town_name=self.read_town_name(slot),
            grid_bytes=self.read_town_grid(),
        )

    def teleport_local_player(
        self, slot: int, x: float, y: float, z: float
    ) -> None:
        """
        Set the local player's world-space position.

        Used on the *visitor* side to place the visitor's character at the
        correct arrival spot in the host's town after town data is applied.
        """
        actor = self._resolve_player_actor(slot)
        if actor is None:
            logger.debug("teleport_local_player: actor not found for slot %d", slot)
            return
        try:
            self.write_f32(actor + ACT_POS_X, x)
            self.write_f32(actor + ACT_POS_Y, y)
            self.write_f32(actor + ACT_POS_Z, z)
        except (OSError, struct.error, ValueError) as e:
            logger.debug("teleport_local_player slot=%d: %s", slot, e)
