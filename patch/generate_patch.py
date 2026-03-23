"""
AC-Netplay xdelta patch generator.

Applies the same changes as the Gecko codes directly to the game's main.dol
executable inside an Animal Crossing (GAFE01) ISO/GCM file, then creates an
xdelta3 binary diff between the original and patched ISO.

Usage:
    python generate_patch.py --iso GAFE01.iso [--out ac_netplay.xdelta]

Requirements:
    - xdelta3 installed and in PATH  (https://github.com/jmacd/xdelta)
    - gciso Python package (for ISO manipulation)

The resulting .xdelta file can be distributed and applied by end-users with:
    xdelta3 -d -s original.iso ac_netplay.xdelta patched.iso
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import shutil
import struct
import subprocess
import sys
import tempfile

from patcher import DolPatcher

logger = logging.getLogger("ac_netplay.generate_patch")

# SHA-1 of the original GAFE01 v1.0 ISO
KNOWN_ISO_SHA1 = "3a6b4f2e8c1d9e0a7f5b3c2d4e6a8b0c1e3f5a7b"  # placeholder

# Patches to apply: (dol_offset, original_bytes, patched_bytes, description)
# dol_offset is the byte offset within main.dol (not the GC virtual address).
# These were calculated by mapping GC virtual addresses to DOL file offsets.
#
# GC VA → DOL offset mapping:
#   text sections start at DOL offset determined by DOL header section table.
#   main.dol for GAFE01 text section 0: loaded at 0x80003100, file offset 0x100.
#   dol_offset = (gc_va - load_addr) + file_offset
#
# See patcher.py for the DOL structure and offset resolution.

PATCHES: list[dict] = [
    {
        "description": "Skip memory card visitor check (NOP branch)",
        "gc_va": 0x803D1420,
        "original": bytes.fromhex("40820050"),   # bne +0x50
        "patched": bytes.fromhex("60000000"),    # nop
    },
    {
        "description": "Suppress visitor card error display (NOP call)",
        "gc_va": 0x803D1800,
        "original": bytes.fromhex("4BFFB201"),   # bl <show_error>
        "patched": bytes.fromhex("60000000"),    # nop
    },
    {
        "description": "Allow up to 4 visitor slots (write 4 to limit)",
        "gc_va": 0x803B8004,
        "original": bytes.fromhex("01010101"),
        "patched": bytes.fromhex("04040404"),
    },
    {
        "description": "Time sync: NOP RTC write to game-time",
        "gc_va": 0x803A6F7C,
        "original": bytes.fromhex("9003002C"),   # stw r0, 0x2C(r3)
        "patched": bytes.fromhex("60000000"),    # nop
    },
]


def sha1_file(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_xdelta3() -> None:
    if not shutil.which("xdelta3"):
        logger.error(
            "xdelta3 not found in PATH. "
            "Install from https://github.com/jmacd/xdelta-gpl/releases"
        )
        sys.exit(1)


def generate_patch(iso_path: str, out_path: str) -> None:
    logger.info("Reading ISO: %s", iso_path)
    iso_sha1 = sha1_file(iso_path)
    logger.info("SHA-1: %s", iso_sha1)
    if iso_sha1.lower() != KNOWN_ISO_SHA1.lower():
        logger.warning(
            "ISO SHA-1 does not match known GAFE01 v1.0 checksum. "
            "Proceeding anyway — patches may fail if offsets differ."
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        patched_iso = os.path.join(tmpdir, "patched.iso")
        shutil.copy2(iso_path, patched_iso)

        patcher = DolPatcher(patched_iso)
        patcher.open()

        applied = 0
        for patch in PATCHES:
            try:
                patcher.apply(
                    gc_va=patch["gc_va"],
                    original=patch["original"],
                    patched=patch["patched"],
                )
                logger.info("Applied: %s", patch["description"])
                applied += 1
            except ValueError as e:
                logger.warning("Skipped patch '%s': %s", patch["description"], e)

        patcher.close()
        logger.info("Applied %d/%d patches", applied, len(PATCHES))

        logger.info("Generating xdelta patch → %s", out_path)
        subprocess.run(
            ["xdelta3", "-e", "-s", iso_path, patched_iso, out_path],
            check=True,
        )
        logger.info("Done. Patch size: %d bytes", os.path.getsize(out_path))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate AC-Netplay xdelta patch")
    p.add_argument("--iso", required=True, help="Path to original GAFE01 ISO/GCM")
    p.add_argument("--out", default="ac_netplay.xdelta", help="Output patch file")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    check_xdelta3()
    generate_patch(args.iso, args.out)
