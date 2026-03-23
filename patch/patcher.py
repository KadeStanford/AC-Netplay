"""
GameCube DOL file patcher.

A GameCube ISO/GCM contains a main.dol executable at a fixed offset within
the disc image. This module:
  1. Locates main.dol inside the ISO
  2. Parses the DOL header to map GameCube virtual addresses → file offsets
  3. Applies byte-level patches with optional "original bytes" verification
  4. Writes the patched bytes back to the ISO in-place

DOL format reference:
  https://wiki.tockdom.com/wiki/DOL_(File_Format)
"""

from __future__ import annotations

import struct
from typing import Optional


# GameCube ISO layout constants
GCM_DOL_OFFSET_PTR = 0x0420   # u32 at byte 0x420 of the disc image


class DolHeader:
    """Parsed DOL header."""

    # DOL header is 256 bytes
    # 7 text sections + 11 data sections, each with offset/address/size
    # followed by BSS address, BSS size, entry point

    SECTION_COUNT = 18  # 7 text + 11 data
    HEADER_SIZE = 0x100

    def __init__(self, data: bytes) -> None:
        if len(data) < self.HEADER_SIZE:
            raise ValueError("DOL header too small")
        # File offsets for each section
        self.offsets = struct.unpack_from(">18I", data, 0x00)
        # Load addresses (GC virtual addresses)
        self.addresses = struct.unpack_from(">18I", data, 0x48)
        # Section sizes
        self.sizes = struct.unpack_from(">18I", data, 0x90)
        # BSS
        self.bss_addr = struct.unpack_from(">I", data, 0xD8)[0]
        self.bss_size = struct.unpack_from(">I", data, 0xDC)[0]
        # Entry point
        self.entry = struct.unpack_from(">I", data, 0xE0)[0]

    def gc_va_to_file_offset(self, gc_va: int) -> Optional[int]:
        """
        Convert a GameCube virtual address to a byte offset within the DOL file.
        Returns None if the address is not in any section.
        """
        for i in range(self.SECTION_COUNT):
            sec_addr = self.addresses[i]
            sec_size = self.sizes[i]
            sec_off = self.offsets[i]
            if sec_addr == 0 or sec_size == 0:
                continue
            if sec_addr <= gc_va < sec_addr + sec_size:
                return sec_off + (gc_va - sec_addr)
        return None


class DolPatcher:
    """
    Patches the main.dol executable inside a GameCube ISO in-place.
    """

    def __init__(self, iso_path: str) -> None:
        self.iso_path = iso_path
        self._fh = None
        self._dol_iso_offset: Optional[int] = None
        self._dol_header: Optional[DolHeader] = None

    def open(self) -> None:
        self._fh = open(self.iso_path, "r+b")
        self._locate_dol()

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> DolPatcher:
        self.open()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def _locate_dol(self) -> None:
        """Read the DOL file offset from the GCM disc header."""
        self._fh.seek(GCM_DOL_OFFSET_PTR)
        raw = self._fh.read(4)
        if len(raw) < 4:
            raise ValueError("ISO too small to read DOL offset pointer")
        self._dol_iso_offset = struct.unpack(">I", raw)[0]

        # Read DOL header
        self._fh.seek(self._dol_iso_offset)
        header_data = self._fh.read(DolHeader.HEADER_SIZE)
        self._dol_header = DolHeader(header_data)

    def apply(self, gc_va: int, original: bytes, patched: bytes) -> None:
        """
        Apply a patch at GameCube virtual address *gc_va*.

        *original*: expected bytes at that location (for safety verification).
        *patched*:  replacement bytes.

        Raises ValueError if the address is not in the DOL or if the existing
        bytes do not match *original*.
        """
        if len(original) != len(patched):
            raise ValueError("original and patched must have the same length")

        dol_rel_offset = self._dol_header.gc_va_to_file_offset(gc_va)
        if dol_rel_offset is None:
            raise ValueError(
                f"GC VA 0x{gc_va:08X} not found in any DOL section"
            )

        iso_abs_offset = self._dol_iso_offset + dol_rel_offset
        self._fh.seek(iso_abs_offset)
        existing = self._fh.read(len(original))

        if existing != original:
            raise ValueError(
                f"Bytes at 0x{gc_va:08X} do not match expected value. "
                f"Expected {original.hex()}, found {existing.hex()}. "
                "Wrong game version?"
            )

        self._fh.seek(iso_abs_offset)
        self._fh.write(patched)
