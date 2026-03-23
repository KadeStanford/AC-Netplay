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
| In-game town browser (train station) | ✅ Implemented |
| Visitor name injection | ✅ Gecko code provided |
| Visitor spawn (no memory card needed) | ✅ Gecko code provided |
| xdelta patch generation | ✅ Tool provided |
| Self-hosted relay server | ✅ Implemented |

---

## Quick Start

### Requirements

- [Dolphin 5.0+](https://dolphin-emu.org/) (Windows / macOS / Linux)
- Python 3.10+
- An **unmodified** Animal Crossing (US, GAFE01) ISO or GCM

### 1 — Install dependencies

```bash
# Relay server (run once on the hosting machine)
cd server && pip install -r requirements.txt && cd ..

# Client (run on every player's machine)
cd client && pip install -r requirements.txt && cd ..
```

### 2 — Apply Gecko codes (required for visitor spawning)

1. In Dolphin, right-click **Animal Crossing** → **Properties** → **Gecko Codes** tab.
2. Click **Add New Code** and paste each block from [`gecko_codes/ac_netplay.txt`](gecko_codes/ac_netplay.txt) one at a time.
3. Check the checkbox next to **every** AC-Netplay code to enable it.

> See [`gecko_codes/README.md`](gecko_codes/README.md) for what each code does.

### 3 — (Optional) Generate an xdelta patch instead of Gecko codes

```bash
cd patch
pip install -r requirements.txt
python generate_patch.py --iso path/to/GAFE01.iso
xdelta3 -d -s GAFE01_original.iso ac_netplay.xdelta GAFE01_patched.iso
```

Use `GAFE01_patched.iso` in Dolphin — no Gecko codes needed.

### 4 — Start the relay server (the host runs this once)

```bash
cd server
python server.py --port 9000
```

Open **port 9000 TCP** in your firewall/router and share your public IP with friends.

### 5 — Host: start the client and load your town

Load your save in Dolphin (get past the title screen), then:

```bash
cd client
python client.py --server ws://<YOUR_IP>:9000 --room MyTown --name YourName
```

Your town is now open. Visitors will appear automatically when they join.

### 6 — Visitor: join a town in-game (browse mode)

Load your save in Dolphin, then start the client **without** `--room`:

```bash
cd client
python client.py --server ws://<HOST_IP>:9000 --name YourName
```

Walk your character **north to the train station** (where Porter lives). An overlay will appear listing available towns — use the **D-pad** to select one and press **A** to join. Your character will arrive at the train station of the host's town, just like a real visit.

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