"""
Tests for the DOL patcher (patch/patcher.py).
Uses in-memory fake ISO data — no real game files needed.
"""

import struct
import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "patch"))

import pytest
from patcher import DolHeader, DolPatcher, GCM_DOL_OFFSET_PTR


def make_dol_header(text_offset=0x200, text_addr=0x80003000, text_size=0x1000) -> bytes:
    """
    Build a minimal DOL header with one text section.
    text_offset: file offset of the section within the DOL
    text_addr:   GC virtual load address
    text_size:   section size in bytes
    """
    data = bytearray(DolHeader.HEADER_SIZE)
    # Text section 0 file offset at header offset 0x00
    struct.pack_into(">I", data, 0x00, text_offset)
    # Text section 0 load address at header offset 0x48
    struct.pack_into(">I", data, 0x48, text_addr)
    # Text section 0 size at header offset 0x90
    struct.pack_into(">I", data, 0x90, text_size)
    # Entry point
    struct.pack_into(">I", data, 0xE0, text_addr)
    return bytes(data)


def make_fake_iso(dol_file_offset: int = 0x1000) -> bytes:
    """
    Build a minimal fake GCM/ISO image containing:
    - A DOL offset pointer at GCM_DOL_OFFSET_PTR
    - A fake DOL at dol_file_offset with one text section
    """
    iso_size = 0x10000
    iso = bytearray(iso_size)

    # Write DOL offset pointer into the disc header
    struct.pack_into(">I", iso, GCM_DOL_OFFSET_PTR, dol_file_offset)

    # Build DOL
    # Our fake DOL has: header (256 bytes) + text section content
    dol_header = make_dol_header(
        text_offset=0x100,   # 256 bytes into the DOL file
        text_addr=0x80003000,
        text_size=0x0800,
    )
    iso[dol_file_offset: dol_file_offset + len(dol_header)] = dol_header

    # Fill the text section with a recognisable pattern
    text_start_in_iso = dol_file_offset + 0x100
    for i in range(0x0800):
        iso[text_start_in_iso + i] = (i & 0xFF)

    return bytes(iso)


@pytest.fixture
def iso_file(tmp_path):
    """Write a fake ISO to a temp file and return the path."""
    data = make_fake_iso()
    p = tmp_path / "fake.iso"
    p.write_bytes(data)
    return str(p)


class TestDolHeader:
    def test_gc_va_to_file_offset_in_section(self):
        header_data = make_dol_header(
            text_offset=0x100, text_addr=0x80003000, text_size=0x1000
        )
        h = DolHeader(header_data)
        # GC VA 0x80003000 should map to DOL offset 0x100
        assert h.gc_va_to_file_offset(0x80003000) == 0x100
        # GC VA 0x80003010 → DOL offset 0x110
        assert h.gc_va_to_file_offset(0x80003010) == 0x110

    def test_gc_va_out_of_section_returns_none(self):
        header_data = make_dol_header(
            text_offset=0x100, text_addr=0x80003000, text_size=0x1000
        )
        h = DolHeader(header_data)
        # Address before the section
        assert h.gc_va_to_file_offset(0x80002FFF) is None
        # Address after the section
        assert h.gc_va_to_file_offset(0x80004000) is None

    def test_header_too_small_raises(self):
        with pytest.raises(ValueError, match="too small"):
            DolHeader(b"\x00" * 10)


class TestDolPatcher:
    def test_apply_patch_succeeds(self, iso_file):
        # The text section content at GC VA 0x80003000 is byte 0x00, 0x01, 0x02, 0x03…
        original = bytes([0x00, 0x01, 0x02, 0x03])
        patched = bytes([0x60, 0x00, 0x00, 0x00])
        with DolPatcher(iso_file) as dp:
            dp.apply(gc_va=0x80003000, original=original, patched=patched)
        # Verify the patch was written
        with open(iso_file, "rb") as f:
            f.seek(0x1000 + 0x100)  # dol_file_offset + text section offset
            assert f.read(4) == patched

    def test_apply_patch_wrong_original_raises(self, iso_file):
        wrong_original = bytes([0xDE, 0xAD, 0xBE, 0xEF])
        with DolPatcher(iso_file) as dp:
            with pytest.raises(ValueError, match="do not match"):
                dp.apply(gc_va=0x80003000,
                         original=wrong_original,
                         patched=bytes([0x60, 0x00, 0x00, 0x00]))

    def test_apply_patch_bad_address_raises(self, iso_file):
        with DolPatcher(iso_file) as dp:
            with pytest.raises(ValueError, match="not found in any DOL section"):
                dp.apply(gc_va=0x90000000,
                         original=b"\x00\x00\x00\x00",
                         patched=b"\x60\x00\x00\x00")

    def test_apply_patch_length_mismatch_raises(self, iso_file):
        with DolPatcher(iso_file) as dp:
            with pytest.raises(ValueError, match="same length"):
                dp.apply(gc_va=0x80003000,
                         original=b"\x00\x01",
                         patched=b"\x60\x00\x00\x00")

    def test_context_manager_closes_file(self, iso_file):
        dp = DolPatcher(iso_file)
        with dp:
            pass
        assert dp._fh is None
