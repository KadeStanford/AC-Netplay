# AC-Netplay Setup Guide

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10 or newer | `python --version` to check |
| Dolphin 5.0 or newer | [dolphin-emu.org](https://dolphin-emu.org/) |
| Animal Crossing ISO/GCM | GAFE01 (North America), legally obtained |
| xdelta3 (optional) | Only needed if applying binary patch |

---

## Part 1 — Dolphin Configuration

### Enable "Enable Cheats" (for Gecko codes)

1. Open Dolphin → **Config** → **General** tab.
2. Check **Enable Cheats**.

### Memory access (required for client)

The AC-Netplay client reads/writes Dolphin's emulated RAM directly via the OS process memory API. No special Dolphin settings are needed, but you must:

- **Linux**: Ensure `/proc/sys/kernel/yama/ptrace_scope` is `0` or `1`.
  ```bash
  echo 0 | sudo tee /proc/sys/kernel/yama/ptrace_scope
  ```
- **Windows**: Run Dolphin and the client from the same user account (no elevation mismatch).
- **macOS**: Grant the client terminal app access to Dolphin in **System Preferences → Security & Privacy → Privacy → Developer Tools** (macOS 13+).

### Recommended Dolphin settings for online play

- **Backend**: Vulkan or OpenGL (Direct3D also works)
- **Dual Core**: OFF — keeps emulation more deterministic
- **Idle Skipping**: OFF — prevents timing drift
- **Speed Limit**: 100% — never run faster than real-time

---

## Part 2 — Applying Gecko Codes

Gecko codes add deeper integration (automatic gate opening, visitor name display, etc.). They are **recommended but optional** — the client works without them using pure memory R/W.

1. In Dolphin, right-click **Animal Crossing** in the game list → **Properties**.
2. Go to the **Gecko Codes** tab.
3. Click **Add New Code** and paste the content of [`gecko_codes/ac_netplay.txt`](../gecko_codes/ac_netplay.txt) one code at a time (see the file for individual code blocks and descriptions).
4. Make sure all AC-Netplay codes are **checked** (enabled).

---

## Part 3 — (Optional) xdelta Patch

If you prefer a patched ISO over Gecko codes, generate and apply the binary patch.

### Generate

```bash
cd patch
pip install -r requirements.txt
python generate_patch.py --iso /path/to/GAFE01.iso --out ac_netplay.xdelta
```

This injects the same hooks as the Gecko codes directly into the ISO's `main.dol` executable.

### Apply

Install [xdelta3](https://github.com/jmacd/xdelta-gpl/releases):

```bash
# Linux / macOS
xdelta3 -d -s GAFE01_original.iso ac_netplay.xdelta GAFE01_patched.iso

# Windows (xdelta3.exe in PATH)
xdelta3.exe -d -s GAFE01_original.iso ac_netplay.xdelta GAFE01_patched.iso
```

Use `GAFE01_patched.iso` in Dolphin. You do **not** need Gecko codes when using the patched ISO.

---

## Part 4 — Running the Relay Server

Anyone can host a relay server. The server needs to be reachable on a public IP (or via port forwarding).

### Install

```bash
cd server
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Start

```bash
python server.py --port 9000
```

Options:

| Flag | Default | Description |
|---|---|---|
| `--port` | `9000` | TCP port to listen on |
| `--host` | `0.0.0.0` | Bind address |
| `--max-rooms` | `100` | Maximum concurrent rooms |
| `--max-players` | `4` | Maximum players per room |
| `--log-level` | `INFO` | Logging level (DEBUG / INFO / WARNING) |

### TLS (recommended for public servers)

Put a reverse proxy (nginx, Caddy) in front of the server with a TLS certificate and proxy WebSocket connections:

```nginx
location /netplay {
    proxy_pass http://127.0.0.1:9000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

Then clients connect to `wss://yourdomain.com/netplay`.

---

## Part 5 — Running the Client

### Install

It is recommended to use a Python virtual environment to avoid polluting your
system Python installation:

```bash
cd client
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Start Dolphin and load the game first

The client needs to attach to a running Dolphin process with Animal Crossing active and a save loaded (past the title screen).

### Start client

```bash
python client.py \
  --server ws://HOST_IP:9000 \
  --room MyTown \
  --name YourName
```

Options:

| Flag | Default | Description |
|---|---|---|
| `--server` | `ws://localhost:9000` | Relay server URL |
| `--room` | required | Room name to join |
| `--name` | required | Your player name |
| `--password` | `""` | Room password (if set) |
| `--player-slot` | `0` | Which player slot you are (0–3) |
| `--tick-rate` | `30` | State updates per second |
| `--interp-ms` | `100` | Interpolation buffer in milliseconds |
| `--log-level` | `INFO` | Logging level |

### What you will see

```
[INFO] Attaching to Dolphin (PID 12345)...
[INFO] Verified game ID: GAFE01
[INFO] Connected to relay server ws://1.2.3.4:9000
[INFO] Joined room 'MyTown' (1 player)
[INFO] Sending state at 30 Hz
```

---

## Part 6 — Gameplay Instructions

### How co-presence works

Both players end up **in the host's town at the same time**:

- The **host** stays in their own town throughout.  Their character moves normally.
- The **visitor's** Dolphin instance automatically receives the host's town data
  the moment they connect.  The visitor's game renders the host's town (terrain,
  placed items, furniture), and the visitor's character is placed near the gate
  so they "arrive" without needing to walk through the train station.
- On the **host's screen**, the visitor's character appears as a visitor NPC
  moving in real time.
- On the **visitor's screen**, the host's character appears as a visitor NPC,
  and the town layout is the host's town.

### Hosting a town visit

1. Load your Animal Crossing save.
2. Start the relay server (or use a public one) and share the address.
3. Start the client:
   ```bash
   python client.py --server ws://HOST_IP:9000 --room YourRoomName --name YourName
   ```
4. Walk to the **gate** (south of town) and talk to Copper — or let the
   Gecko code open it automatically.
5. Tell your friend your server address and room name.  Once they connect,
   their character will appear in your town automatically.

### Visiting a town

1. Load your Animal Crossing save.
2. Start the client pointing to the **same** server and room as the host:
   ```bash
   python client.py --server ws://HOST_IP:9000 --room HostsRoomName --name YourName
   ```
3. The client will automatically:
   - Receive the host's town grid and write it to your Dolphin RAM.
   - Teleport your character to the gate-entrance area of the host's town.
4. You are now in the host's town.  Walk around, pick up items, and interact
   with the environment just as you would in your own game.

> **Tip**: Keep both players in the same time zone / season for the best
> experience. The host's in-game clock is authoritative.

---

## Troubleshooting

### "Could not find Dolphin process"

- Make sure Dolphin is running and the game is loaded (not just the launcher).
- On Linux, check ptrace scope (see above).
- Specify the PID manually: `--dolphin-pid 12345`.

### "Wrong game ID"

- The client only supports GAFE01. If you have a different region, update `GAME_ID` in `client/dolphin_memory.py`.

### "Connection refused"

- Ensure the relay server is running on the host machine.
- Check firewall rules — port 9000 (or your chosen port) must be open for inbound TCP.

### Visitor character not appearing in-game

- Make sure Gecko codes are active **and** the gate is open.
- Try talking to Copper and opening the gate manually.
- Increase `--interp-ms` if your connection is laggy.

### Items desyncing

- Item events are best-effort. If an item desync occurs, the host's town grid is authoritative.
- Use the `GAME_EVENT / TIME_SYNC` packet to re-sync: run `tools/memory_monitor.py --sync-items`.
