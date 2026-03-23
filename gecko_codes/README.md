# Gecko Codes — Documentation

## What are Gecko codes?

Gecko codes are a patching system for GameCube and Wii games, originally implemented in GeckoOS (a homebrew boot loader). Dolphin Emulator has built-in support for them under **Properties → Gecko Codes**.

Each code line is a pair of 32-bit hex values: an **address** and a **value/payload**. The leading "code type" nibble of the address selects the operation:

| Type | Prefix | Operation |
|---|---|---|
| `00` | `0x00` | 8-bit RAM write |
| `02` | `0x02` | 16-bit RAM write |
| `04` | `0x04` | 32-bit RAM write |
| `06` | `0x06` | Write byte string |
| `C2` | `0xC2` | Insert ASM code |
| `E0` | `0xE0` | Full ASM codelist |

Addresses are relative to the GC virtual address space (`0x80000000` base).

---

## AC-Netplay Code Summary

| Code | Purpose |
|---|---|
| Gate Auto-Open | Opens the gate so visitors can enter without talking to Copper |
| 4-Player Visitor Slots | Raises the game's internal max-visitor count from 1 to 4 |
| Skip Memory Card Visitor Check | Allows visitor data to come from RAM (written by client) instead of a memory card |
| Visitor Name Injection | Copies remote player names from the netplay buffer into visitor actor |
| Suppress Visitor Card Error | Prevents an error screen when no visitor memory card is present |
| Chat Buffer Clear | Zeroes the chat overlay buffer on boot |
| Time Sync Enable | Prevents the game's RTC from overwriting the host-synced time |

---

## Enabling in Dolphin

1. Right-click **Animal Crossing** in Dolphin's game list.
2. Select **Properties** → **Gecko Codes** tab.
3. Click **Add New Code**.
4. Paste each `$CodeName` block (including the hex lines) one at a time.
5. Check the checkbox next to each code to enable it.
6. Click **Apply** and close.

---

## Verifying Code Addresses

The addresses in `ac_netplay.txt` were researched against **GAFE01 v1.0** (North America, revision 0). If your ISO is a different revision:

1. Open Dolphin's **Memory** view (via **View → Memory**).
2. Search for the byte pattern near the expected address to confirm it matches.
3. Update the address in the code if needed.

The [dolphin-memory-engine](https://github.com/aldelaro5/dolphin-memory-engine) tool is also useful for scanning and verifying addresses while the game runs.

---

## Code Development Notes

The ASM insert in **Visitor Name Injection** (code type `C2`) works as follows:

```asm
; Load visitor name scratch buffer pointer (0x803BFF00)
lis  r3, 0x8003
ori  r3, r3, 0x8000
; Load 4 bytes of name from scratch buffer at offset 0
lwz  r7, 0xFF00(r3)
stw  r7, 0(r4)          ; r4 = visitor actor name field ptr (set by game)
lwz  r6, 0xFF04(r3)
stw  r6, 4(r4)
lwz  r5, 0xFF08(r3)
stw  r5, 8(r4)
lwz  r4, 0x3F0C(r3)
stw  r4, 8(r4)
nop
```

The client writes the remote player's name (8 bytes, AC encoding) to `0x803BFF00` before the visitor spawn routine runs.
