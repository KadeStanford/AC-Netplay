# Animal Crossing GameCube — Research Notes

## Game Overview

| Field | Value |
|---|---|
| Title | Animal Crossing |
| Platform | Nintendo GameCube |
| Developer | Nintendo EAD |
| Publisher | Nintendo |
| Region / Game ID | North America — **GAFE01** |
| Japanese counterpart | Doubutsu no Mori+ (GAFJ01) |
| Release | September 15, 2002 (NA) |
| Disc format | GCN GCM/ISO, 1.4 GB |

---

## Game Architecture

### CPU / Memory

The GameCube uses an IBM PowerPC 750CXe ("Gekko") running at 485 MHz with:
- **24 MB main RAM** — mapped at `0x80000000`–`0x817FFFFF` (cached) and `0xC0000000` mirror (uncached)
- **16 MB "Auxiliary" RAM** — mapped at `0x81800000`
- **16 KB L1 cache** + **256 KB L2 cache**

All addresses in this document are **cached virtual addresses** (prefix `0x80`).

### Save System

Animal Crossing stores its save data in the town memory area, which is loaded into RAM on boot and periodically flushed to the memory card.  The in-RAM layout mirrors the on-card layout almost exactly (see [MEMORY_MAP.md](MEMORY_MAP.md)).

Key save data areas:
- **Town data block** — terrain, buried items, placed furniture, letters in the bulletin board
- **Player data blocks** — one per player slot (up to 4), contains appearance, inventory, catalog, letters, patterns
- **NPC data blocks** — the 8 animal villagers living in the town
- **Shop/facility state** — Nook's store level, museum donations, etc.

### Multiplayer in the Original Game

The original game supports two multiplayer modes:

1. **Game Boy Advance link** (via the GBA-GCN cable): A player on a GBA visits an island (`Islander` minigame). Not relevant for netplay.
2. **Memory Card swap**: To visit another player's town, you would copy your player data to a memory card, take it to that person's GameCube, and load it. The game would spawn the visiting player's character as a special NPC. **This is the mechanic AC-Netplay hooks into.**

### The Visitor / Gate System

When a visitor arrives in-game:
- Their character occupies a **visitor player slot** (separate from the town's 4 resident player slots).
- The game reads the visitor's appearance, name, and initial inventory from a special data block loaded into RAM.
- The gate attendant NPC (Copper / Booker) controls gate open/close state.
- A visitor leaving triggers a "farewell" sequence and clears their slot.

**AC-Netplay intercepts this flow**: instead of reading visitor data from a memory card, the client writes the remote player's live state into the visitor slot every frame.

---

## Relevant GameCube Hardware for Netplay

### Broadband Adapter (BBA)

The GameCube had an official Broadband Adapter (DOL-015) for its modem slot. Only a handful of games used it (Phantasy Star Online Episodes I & II, Kirby Air Ride LAN, etc.).

Dolphin emulates the BBA via its `SLIPPI_LAN` and standard socket backends. AC-Netplay **does not** use the in-game BBA stack — instead, the Python client on the host OS handles all networking, reading/writing game state via Dolphin's memory interface.

---

## Key Game Systems

### Actor System

Entities in the world (player characters, animals, dropped items) are represented as **actors** with:
- X / Z world position (Y is height)
- Facing angle
- Animation state
- Actor-type ID

The player character actor is always loaded; visitor character actors are allocated from a pool when the gate is open.

### Item System

Items are stored as **16-bit item codes** (`u16`). The full item table is well-documented by the community ([Animal Crossing Item List](https://nookipedia.com/wiki/List_of_items_in_Animal_Crossing)). Pockets hold 15 items; the house has furniture rooms.

### Pattern System

Custom patterns (designs) are 32×32 pixels, 4-bit color (15 colors + transparent), stored as 512 bytes per pattern. Each player has 8 patterns.

### String Encoding

Text uses a **modified Shift-JIS** encoding in the Japanese version and a custom 8-bit encoding in the NA release (often called "AC encoding"). Character names and town names are fixed-length null-padded strings.

---

## Community Resources

- [TCRF — Animal Crossing (GameCube)](https://tcrf.net/Animal_Crossing)
- [Nookipedia](https://nookipedia.com/) — comprehensive item / NPC databases
- [Animal Crossing Modding Discord](https://discord.gg/ACModding) — active community
- [ACToolkit](https://github.com/Cuyler36/ACToolkit) — save editor, documents save structure
- [Cuyler36's AC documentation](https://github.com/Cuyler36) — most thorough reverse-engineering work
- [Dolphin memory engine](https://github.com/aldelaro5/dolphin-memory-engine) — RAM viewer used for research

---

## Netplay Strategy

### Why Not Standard Dolphin Netplay?

Dolphin's built-in netplay uses **input synchronisation** (frame-by-frame rollback). This works for action games but is unsuitable for Animal Crossing because:
- The game is driven by the **real-time clock** — two players must agree on the in-game time, which drifts.
- Loading screens and scripted sequences have variable length, desynchronizing inputs.
- High latency causes the game to halt waiting for the opponent's input.

### AC-Netplay Approach: State Synchronisation

Rather than syncing inputs, AC-Netplay syncs **high-level game state**:

1. The **host** runs Animal Crossing normally in their own town with the gate open.
2. The **visitor** connects to the relay server in the same room as the host.
3. Upon connection, the host sends a `TOWN_DATA` packet containing their entire
   town grid (terrain + placed items, 21 KB) encoded as Base64.
4. The visitor's client writes the host's town grid into their own Dolphin RAM
   at `0x803C0000`, instantly making the visitor's game render the host's town.
5. The visitor's character is teleported to the gate-arrival position, placing
   them inside the host's town.
6. Both the host and the visitor then continuously exchange `PLAYER_STATE`
   packets at ~30 Hz.  Each client writes the remote player's state into a
   visitor-actor NPC slot in their own game, so both characters are visible in
   the same town simultaneously.

**Result:** Both players are physically present in the host's town at the same
time — the host sees the visitor walking around as a visitor NPC, and the
visitor sees the host's town layout with the host's character also present.

This tolerates up to ~200 ms of network latency without perceptible stuttering
because Animal Crossing's movement pace is slow.

### Synchronisation Points

| Event | Handling |
|---|---|
| Player moves | Position lerped on receiver side |
| Player picks up item | Item removed from town grid on both sides via explicit packet |
| Player drops item | Item added to town grid on both sides |
| Player enters building | Building-enter packet; visitor hidden temporarily |
| Chat message | Relayed as text packet; displayed via Gecko code injection |
| Time-of-day | Host's in-game time is authoritative; client adjusts Dolphin clock |
