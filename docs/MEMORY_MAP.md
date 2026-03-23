# Animal Crossing (GAFE01) — Memory Map

All addresses are **cached virtual addresses** as seen from the GameCube CPU  
(`0x80000000` base). In Dolphin, subtract `0x80000000` to get the offset from  
the start of emulated RAM (i.e. Dolphin's `mem1` buffer).

> **Note**: These offsets were researched using Dolphin's memory viewer and  
> Cheat Engine against Dolphin's process. Addresses marked ⚠️ need additional  
> verification. Community sources: ACToolkit, TCRF, Cuyler36's documentation.

---

## Memory Layout Overview

```
0x80000000  System / OS area (IPL, OS globals)
0x80003000  Game boot globals
0x80007000  DOL static data / BSS
0x803A0000  Town data base ──────────────────────────────────┐
0x803A7200  Player 1 data block                              │
0x803A9400  Player 2 data block                              │ Save data
0x803AB600  Player 3 data block                              │ mirror in RAM
0x803AD800  Player 4 data block                              │
0x803B0000  NPC villager table (8 × 0x2000 bytes)           │
0x803C0000  Town grid / acre item data                       │
0x803D0000  Building / facility state                        ┘
0x80400000  Actor heap (dynamic objects)
0x80600000  Heap / stack area
0x817FFFFF  End of MEM1
```

---

## Player Data Block (per player, 0x2200 bytes each)

Base address: `PLAYER_BASE[n]` where n = 0..3

| Offset | Size | Type | Description |
|---|---|---|---|
| `+0x0000` | 2 | u16 | Player ID (internal) |
| `+0x0002` | 8 | char[8] | Player name (AC encoding, null-padded) |
| `+0x000A` | 6 | char[6] | Town name |
| `+0x0010` | 2 | u16 | Gender (0 = boy, 1 = girl) |
| `+0x0012` | 1 | u8 | Face type (0–7) |
| `+0x0013` | 1 | u8 | Hair type |
| `+0x0014` | 1 | u8 | Hair color |
| `+0x0015` | 1 | u8 | Tan level |
| `+0x0016` | 2 | u16 | Shirt item code |
| `+0x0018` | 2 | u16 | Hat item code |
| `+0x001A` | 2 | u16 | Glasses item code |
| `+0x001C` | 4 | u32 | Bells (money) |
| `+0x0020` | 30 | u16[15] | Pocket inventory (15 item slots) |
| `+0x003E` | 2 | u16 | Held item (item in hand right now) |
| `+0x0040` | 4096 | u16[2048] | Main inventory / storage |
| `+0x1040` | 512 | bytes[8][64] | 8 custom patterns (64 bytes each) |
| `+0x1240` | 256 | bytes | Letter inbox |
| `+0x1340` | 64 | u16[32] | Catalog flags (which items seen) |
| `+0x1380` | 4 | u32 | Total play time (seconds) |
| `+0x1384` | 4 | u32 | Total bells earned |

---

## Player Actor (real-time, changes every frame)

The player actor struct lives in the actor heap. Its address varies each boot  
but can be found via a stable pointer chain.

**Pointer chain (Player 1):**

```
[0x803FFFE0] → actor_manager_ptr
actor_manager_ptr + 0x14  → player_actor_list_ptr
player_actor_list_ptr + 0x00 → player_1_actor_ptr
```

| Offset from actor base | Size | Type | Description |
|---|---|---|---|
| `+0x00` | 4 | u32 | Actor type ID (0x0001 for player) |
| `+0x04` | 4 | u32 | Flags |
| `+0x08` | 4 | f32 | World X position (meters) |
| `+0x0C` | 4 | f32 | World Y position (height) |
| `+0x10` | 4 | f32 | World Z position (meters) |
| `+0x14` | 4 | f32 | Facing angle (radians) |
| `+0x18` | 4 | f32 | Velocity X |
| `+0x1C` | 4 | f32 | Velocity Z |
| `+0x20` | 2 | u16 | Current animation ID |
| `+0x22` | 1 | u8 | Animation frame |
| `+0x23` | 1 | u8 | Movement state (0=idle, 1=walk, 2=run, 3=tool) |
| `+0x24` | 2 | u16 | Held item code |
| `+0x26` | 2 | u16 | Tool animation (0=none, 1=axe, 2=rod…) |
| `+0x28` | 1 | u8 | Emote ID (0 = none) |
| `+0x29` | 1 | u8 | Player slot index |

---

## Visitor Slot (remote player NPC)

When a visitor is in the town, the game allocates a visitor actor.  
AC-Netplay writes remote player state here.

**Visitor actor base** (⚠️ offset verified in v1.0 US only):

```
0x803FFFF0 → visitor_actor_list_ptr
visitor_actor_list_ptr + 0x00 → visitor_slot_0_ptr   (first visitor)
visitor_actor_list_ptr + 0x04 → visitor_slot_1_ptr   (second visitor)
```

The visitor actor has the **same layout** as the player actor above, plus:

| Offset | Size | Type | Description |
|---|---|---|---|
| `+0x2A` | 8 | char[8] | Visitor name |
| `+0x32` | 6 | char[6] | Visitor town name |
| `+0x38` | 1 | u8 | Visitor face type |
| `+0x39` | 1 | u8 | Visitor hair type |
| `+0x3A` | 1 | u8 | Visitor hair color |
| `+0x3B` | 1 | u8 | Visitor gender |
| `+0x3C` | 2 | u16 | Visitor shirt |

---

## Gate / Multiplayer State

| Address | Size | Type | Description |
|---|---|---|---|
| `0x803B8000` | 1 | u8 | Gate state: 0=closed, 1=open, 2=visitor arriving |
| `0x803B8001` | 1 | u8 | Number of current visitors (0–4) |
| `0x803B8002` | 1 | u8 | Local player slot of gate opener |
| `0x803B8010` | 4 | u32 | Visitor arrival timer |
| `0x803B8020` | 8×4 | u32[8] | Visitor actor ptr table |

---

## Town Grid

The town is divided into **7×6 acres**, each acre being **16×16 squares**.  
Total town size: 112 × 96 squares.

| Address | Layout | Description |
|---|---|---|
| `0x803C0000` | u16[96][112] | Item code per tile (0x0000 = empty) |
| `0x803D0000` | u8[96][112] | Tile flags (buried item, footprint, etc.) |

---

## Time / Date

| Address | Size | Type | Description |
|---|---|---|---|
| `0x80000000` | 4 | u32 | OS timer (ticks since boot) |
| `0x803A6F80` | 1 | u8 | Hour (0–23) |
| `0x803A6F81` | 1 | u8 | Minute |
| `0x803A6F82` | 1 | u8 | Second |
| `0x803A6F83` | 1 | u8 | Day of month |
| `0x803A6F84` | 1 | u8 | Month (1–12) |
| `0x803A6F86` | 2 | u16 | Year |

---

## Music / Shop / Misc

| Address | Size | Description |
|---|---|---|
| `0x803D1000` | 1 | Nook's store level (0–4) |
| `0x803D1004` | 1 | Museum wings unlocked flags |
| `0x803D1010` | 2 | Current background music track ID |
| `0x803D1020` | 4 | Day of week (0=Sun) |

---

## Notes on Address Stability

- The **player data blocks** and **town grid** addresses are stable across sessions (they are loaded from memory card to the same RAM location every boot).
- **Actor addresses** (player, visitor, NPCs) change each boot and must be resolved at runtime via pointer chains.
- All multi-byte values are **big-endian** (PowerPC convention).
