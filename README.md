# AC-Netplay

**Online multiplayer mod for Animal Crossing (GameCube / GAFE01)**

AC-Netplay enables real-time internet multiplayer for the North American GameCube release of *Animal Crossing* (2002). Two or more players can visit each other's towns over the internet while both are running the game in the [Dolphin emulator](https://dolphin-emu.org/).

---

## How It Works

```
Player A (Dolphin)          Relay Server          Player B (Dolphin)
      │                          │                        │
      │── ac-netplay-client ──►  │  ◄── ac-netplay-client ─│
      │   (reads/writes          │      (reads/writes       │
      │    Dolphin RAM)          │       Dolphin RAM)       │
      │                          │                        │
      │  player state / town ──► │ ──► player state / town │
      │  data packets            │     data packets         │
```

The **AC-Netplay client** runs alongside Dolphin on each player's PC. It reads player position, appearance, and inventory data directly from Dolphin's emulated GameCube RAM, sends that state to a central **relay server**, and writes the received state of remote players into the visiting-player NPC slots already present in the game.

Optionally, **Gecko codes** can be applied via Dolphin's cheat system to add deeper hooks (gate auto-open, visitor name injection, etc.).

---

## Features

| Feature | Status |
|---|---|
| Player position sync | ✅ Implemented |
| Player appearance sync | ✅ Implemented |
| Inventory / item sync | ✅ Implemented |
| Chat messages | ✅ Implemented |
| Gate auto-open code | ✅ Gecko code provided |
| Visitor name injection | ✅ Gecko code provided |
| xdelta patch generation | ✅ Tool provided |
| Self-hosted relay server | ✅ Implemented |

---

## Quick Start

### Requirements

- [Dolphin 5.0+](https://dolphin-emu.org/) (Windows / macOS / Linux)
- Python 3.10+
- An **unmodified** Animal Crossing (US, GAFE01) ISO or GCM

### 1 — Apply Gecko codes (recommended)

Copy the contents of [`gecko_codes/ac_netplay.txt`](gecko_codes/ac_netplay.txt) into Dolphin's cheat manager for GAFE01, then enable all codes.

### 2 — (Optional) Generate an xdelta patch

If you want a binary patch instead of Gecko codes:

```bash
cd patch
pip install -r requirements.txt
python generate_patch.py --iso path/to/GAFE01.iso
```

Apply the resulting `ac_netplay.xdelta` with [xdelta3](https://github.com/jmacd/xdelta):

```bash
xdelta3 -d -s original.iso ac_netplay.xdelta patched.iso
```

### 3 — Start the relay server (host only)

```bash
cd server
pip install -r requirements.txt
python server.py --port 9000
```

Open port 9000 (TCP) in your firewall / router. Share your public IP with friends.

### 4 — Connect each player

```bash
cd client
pip install -r requirements.txt
python client.py --server ws://<HOST_IP>:9000 --room MyTown --name YourName
```

Both players join the same `--room`. The player who wants to host their town opens the gate in-game; the other player walks through the train station.

---

## Repository Layout

```
AC-Netplay/
├── README.md
├── docs/
│   ├── RESEARCH.md       # Game internals research
│   ├── MEMORY_MAP.md     # Documented RAM addresses
│   ├── PROTOCOL.md       # Netplay wire protocol
│   └── SETUP.md          # Detailed setup guide
├── server/
│   ├── server.py         # Asyncio relay server
│   ├── room.py           # Room / session management
│   └── requirements.txt
├── client/
│   ├── client.py         # Main client entry point
│   ├── dolphin_memory.py # Dolphin process memory I/O
│   ├── state.py          # Game state data classes
│   └── requirements.txt
├── gecko_codes/
│   ├── ac_netplay.txt    # Human-readable Gecko codes
│   └── README.md         # Code documentation
├── patch/
│   ├── generate_patch.py # xdelta patch generator
│   ├── patcher.py        # ISO binary patcher
│   └── requirements.txt
└── tools/
    ├── memory_monitor.py # Live RAM viewer / debugger
    └── find_offsets.py   # Offset discovery helper
```

---

## Documentation

- [Research Notes](docs/RESEARCH.md)
- [Memory Map](docs/MEMORY_MAP.md)
- [Network Protocol](docs/PROTOCOL.md)
- [Setup Guide](docs/SETUP.md)

---

## License

MIT — see [LICENSE](LICENSE).  
This project does not distribute any copyrighted Nintendo content.
ROM/ISO files are **not** included and must be obtained legally.