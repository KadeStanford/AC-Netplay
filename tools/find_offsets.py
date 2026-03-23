"""
AC-Netplay offset discovery helper.

Scans Dolphin's emulated RAM for known Animal Crossing data patterns to verify
or discover memory offsets. Useful when working with a different game revision.

Usage:
    python find_offsets.py [--pid PID] [--scan-player] [--scan-gate]

The tool searches for distinguishing byte sequences and reports addresses.
"""

from __future__ import annotations

import argparse
import sys
import os
import struct

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))

from dolphin_memory import DolphinMemory, GC_MEM1_BASE, GC_MEM1_SIZE

# Patterns to search for (bytes, description)
# These are stable multi-byte sequences that uniquely identify code locations.
KNOWN_PATTERNS: list[dict] = [
    {
        "name": "Gate state struct",
        "bytes": bytes.fromhex("00000000FFFFFFFF"),
        "note": "First 8 bytes of the gate state area when gate is closed and no visitors",
    },
    {
        "name": "NPC table header",
        "bytes": bytes.fromhex("4E504300"),  # "NPC\x00"
        "note": "Magic string at start of NPC table",
    },
    {
        "name": "Player slot 0 marker",
        "bytes": bytes.fromhex("504C5952"),  # "PLYR"
        "note": "4-byte magic at start of player data block",
    },
]


def scan_pattern(mem: DolphinMemory, pattern: bytes, chunk_size: int = 0x10000) -> list[int]:
    """Brute-force scan MEM1 for *pattern*. Returns list of GC virtual addresses."""
    found = []
    step = GC_MEM1_SIZE // chunk_size
    for i in range(step):
        gc_addr = GC_MEM1_BASE + i * chunk_size
        try:
            data = mem._read(gc_addr, min(chunk_size + len(pattern), GC_MEM1_SIZE - i * chunk_size))
        except (OSError, ValueError):
            continue
        offset = 0
        while True:
            idx = data.find(pattern, offset)
            if idx == -1:
                break
            found.append(gc_addr + idx)
            offset = idx + 1
    return found


def run(args: argparse.Namespace) -> None:
    print("AC-Netplay Offset Discovery Tool")
    print("Attaching to Dolphin...")
    mem = DolphinMemory(pid=args.pid)
    try:
        mem.attach()
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)
    print(f"Attached. Game ID: {mem.read_game_id()}\n")

    patterns_to_scan = KNOWN_PATTERNS
    if args.pattern:
        patterns_to_scan = [{"name": "Custom", "bytes": bytes.fromhex(args.pattern), "note": ""}]

    for p in patterns_to_scan:
        print(f"Scanning for '{p['name']}' ({p['bytes'].hex()})...")
        hits = scan_pattern(mem, p["bytes"])
        if hits:
            for addr in hits:
                print(f"  Found at GC VA: 0x{addr:08X}")
        else:
            print("  Not found.")
        if p.get("note"):
            print(f"  Note: {p['note']}")
        print()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AC-Netplay offset discovery")
    p.add_argument("--pid", type=int, default=None, help="Dolphin PID")
    p.add_argument("--pattern", default=None,
                   help="Hex byte pattern to search for (e.g. DEADBEEF)")
    return p.parse_args()


if __name__ == "__main__":
    run(parse_args())
