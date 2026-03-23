"""
AC-Netplay memory monitor — live Dolphin RAM viewer / debugger.

Continuously reads and displays key Animal Crossing game state from a running
Dolphin process. Useful for verifying memory offsets and debugging netplay.

Usage:
    python memory_monitor.py [--pid PID] [--slot 0] [--rate 10]
"""

from __future__ import annotations

import argparse
import sys
import time
import os

# Allow running from the tools/ directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))

from dolphin_memory import DolphinMemory, GATE_STATE_ADDR, PLAYER_BASE
from state import PlayerState, AppearanceState


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def monitor(mem: DolphinMemory, slot: int, rate: int) -> None:
    interval = 1.0 / rate
    print("AC-Netplay Memory Monitor  (Ctrl+C to quit)\n")

    while True:
        t0 = time.monotonic()
        try:
            state = mem.read_player_state(slot)
            app = mem.read_appearance(slot)
            town = mem.read_town_name(slot)
            gate = mem.read_u8(GATE_STATE_ADDR)

            clear_screen()
            print(f"=== AC-Netplay Memory Monitor === (slot {slot})\n")
            print(f"  Game ID    : {mem.read_game_id()}")
            print(f"  Town       : {town!r}")
            print(f"  Gate state : {gate} ({'OPEN' if gate else 'CLOSED'})")
            print()
            print("  Player State:")
            print(f"    Position  : ({state.pos_x:.2f}, {state.pos_y:.2f}, {state.pos_z:.2f})")
            print(f"    Angle     : {state.angle:.4f} rad")
            print(f"    Anim      : {state.anim} (frame {state.anim_frame})")
            print(f"    Move state: {state.move_state}")
            print(f"    Held item : 0x{state.held_item:04X}")
            print(f"    Emote     : {state.emote}")
            print()
            print("  Appearance:")
            print(f"    Face      : {app.face}  Hair: {app.hair}  Hair color: {app.hair_color}")
            print(f"    Gender    : {'Girl' if app.gender else 'Boy'}  Tan: {app.tan}")
            print(f"    Shirt     : 0x{app.shirt:04X}  Hat: 0x{app.hat:04X}")
            print()
            print(f"  [Refreshing at {rate} Hz — Ctrl+C to quit]")
        except Exception as exc:
            print(f"\nRead error: {exc}")

        elapsed = time.monotonic() - t0
        time.sleep(max(0.0, interval - elapsed))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AC-Netplay memory monitor")
    p.add_argument("--pid", type=int, default=None, help="Dolphin PID (auto-detect)")
    p.add_argument("--slot", type=int, default=0, help="Player slot (0–3)")
    p.add_argument("--rate", type=int, default=10, help="Refresh rate (Hz)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    mem = DolphinMemory(pid=args.pid)
    try:
        mem.attach()
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)
    try:
        monitor(mem, args.slot, args.rate)
    except KeyboardInterrupt:
        print("\nMonitor stopped.")
