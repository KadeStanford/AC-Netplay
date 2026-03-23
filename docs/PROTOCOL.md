# AC-Netplay Wire Protocol

Version: **1.0**

All communication between the **client** and **relay server** uses WebSockets  
(`ws://` or `wss://` for TLS). Messages are UTF-8 encoded JSON unless otherwise noted.

---

## Message Format

Every message is a JSON object with at least a `type` field:

```json
{
  "type": "MESSAGE_TYPE",
  "seq":  12345,
  ...payload fields...
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | string | yes | Message type identifier |
| `seq` | uint | no | Sequence number (client → server, echoed back) |

---

## Connection Lifecycle

```
Client                    Server
  │                          │
  │──── HELLO ──────────────►│
  │◄─── WELCOME / ERROR ─────│
  │                          │
  │──── JOIN_ROOM ──────────►│
  │◄─── ROOM_STATE ──────────│  (current players in room)
  │◄─── PLAYER_JOINED ───────│  (broadcast to others)
  │                          │
  │     [gameplay loop]       │
  │──── PLAYER_STATE ───────►│  (repeated ~30 Hz)
  │◄─── PLAYER_STATE ────────│  (from other players)
  │──── GAME_EVENT ─────────►│
  │◄─── GAME_EVENT ──────────│
  │──── CHAT ───────────────►│
  │◄─── CHAT ────────────────│
  │                          │
  │──── LEAVE_ROOM ─────────►│
  │◄─── PLAYER_LEFT ─────────│  (broadcast to others)
  │                          │
  │──── BYE ────────────────►│
  │  [WebSocket close]        │
```

---

## Message Types

### Client → Server

#### `HELLO`

Sent immediately after WebSocket connection is established.

```json
{
  "type": "HELLO",
  "version": "1.0",
  "player_name": "Alice",
  "town_name": "Timberland",
  "platform": "dolphin"
}
```

| Field | Type | Description |
|---|---|---|
| `version` | string | Protocol version (`"1.0"`) |
| `player_name` | string | Player name (max 8 chars, AC encoding) |
| `town_name` | string | Town name (max 6 chars) |
| `platform` | string | Always `"dolphin"` for now |

#### `JOIN_ROOM`

```json
{
  "type": "JOIN_ROOM",
  "room": "MyTown",
  "password": ""
}
```

| Field | Type | Description |
|---|---|---|
| `room` | string | Room name (max 32 chars, alphanumeric + `-_`) |
| `password` | string | Optional password (empty string = no password) |

#### `PLAYER_STATE`

Sent ~30 times per second. Contains the local player's current runtime state.

```json
{
  "type": "PLAYER_STATE",
  "seq": 1001,
  "ts": 1711152000.123,
  "pos": [45.2, 0.0, 32.7],
  "angle": 1.5708,
  "anim": 3,
  "anim_frame": 12,
  "move_state": 1,
  "held_item": 8201,
  "emote": 0
}
```

| Field | Type | Description |
|---|---|---|
| `ts` | float | Unix timestamp (seconds) of sample |
| `pos` | [f32, f32, f32] | World X, Y, Z position |
| `angle` | f32 | Facing angle in radians |
| `anim` | u16 | Current animation ID |
| `anim_frame` | u8 | Frame within animation |
| `move_state` | u8 | 0=idle 1=walk 2=run 3=using tool |
| `held_item` | u16 | Item code of held item (0 = nothing) |
| `emote` | u8 | Emote ID (0 = none) |

#### `APPEARANCE`

Sent once on connect and whenever appearance changes (clothing, tan, etc.).

```json
{
  "type": "APPEARANCE",
  "face": 2,
  "hair": 5,
  "hair_color": 1,
  "gender": 0,
  "tan": 0,
  "shirt": 4096,
  "hat": 0,
  "glasses": 0
}
```

#### `GAME_EVENT`

Discrete game events (item pickup/drop, entering building, etc.).

```json
{
  "type": "GAME_EVENT",
  "event": "ITEM_PICKUP",
  "tile_x": 45,
  "tile_z": 32,
  "item_code": 8201
}
```

```json
{
  "type": "GAME_EVENT",
  "event": "ITEM_DROP",
  "tile_x": 46,
  "tile_z": 32,
  "item_code": 8201
}
```

```json
{
  "type": "GAME_EVENT",
  "event": "ENTER_BUILDING",
  "building_id": 2
}
```

```json
{
  "type": "GAME_EVENT",
  "event": "EXIT_BUILDING",
  "building_id": 2
}
```

```json
{
  "type": "GAME_EVENT",
  "event": "GATE_OPEN"
}
```

```json
{
  "type": "GAME_EVENT",
  "event": "GATE_CLOSE"
}
```

| `event` value | Description |
|---|---|
| `ITEM_PICKUP` | Player picked up item at tile |
| `ITEM_DROP` | Player dropped item at tile |
| `ITEM_BURY` | Player buried item at tile |
| `ITEM_DIG` | Player dug up buried item |
| `ENTER_BUILDING` | Player entered a building |
| `EXIT_BUILDING` | Player exited a building |
| `GATE_OPEN` | Host opened the gate |
| `GATE_CLOSE` | Host closed the gate |
| `TIME_SYNC` | Host broadcasts current in-game time |

#### `CHAT`

```json
{
  "type": "CHAT",
  "text": "Hello!"
}
```

`text` is limited to 255 UTF-8 bytes. The client truncates longer messages.

#### `LEAVE_ROOM`

```json
{ "type": "LEAVE_ROOM" }
```

#### `BYE`

```json
{ "type": "BYE" }
```

---

### Server → Client

#### `WELCOME`

```json
{
  "type": "WELCOME",
  "player_id": "a3f9c2b1",
  "server_version": "1.0",
  "motd": "Welcome to AC-Netplay!"
}
```

#### `ERROR`

```json
{
  "type": "ERROR",
  "code": "ROOM_FULL",
  "message": "The room already has 4 players."
}
```

Error codes:

| Code | Meaning |
|---|---|
| `BAD_VERSION` | Protocol version mismatch |
| `ROOM_FULL` | Room at capacity (4 players) |
| `WRONG_PASSWORD` | Incorrect room password |
| `NAME_TAKEN` | Player name already in room |
| `RATE_LIMITED` | Too many messages per second |
| `INTERNAL` | Server-side error |

#### `ROOM_STATE`

Sent once after a successful `JOIN_ROOM`. Lists all current players.

```json
{
  "type": "ROOM_STATE",
  "room": "MyTown",
  "host": "a3f9c2b1",
  "players": [
    {
      "player_id": "a3f9c2b1",
      "player_name": "Alice",
      "town_name": "Timberland",
      "appearance": { "face": 2, "hair": 5, "hair_color": 1, "gender": 0, "tan": 0, "shirt": 4096, "hat": 0, "glasses": 0 }
    }
  ]
}
```

#### `PLAYER_JOINED`

Broadcast when a new player joins the room.

```json
{
  "type": "PLAYER_JOINED",
  "player_id": "b1c2d3e4",
  "player_name": "Bob",
  "town_name": "Leafton",
  "appearance": { ... }
}
```

#### `PLAYER_LEFT`

```json
{
  "type": "PLAYER_LEFT",
  "player_id": "b1c2d3e4",
  "reason": "disconnected"
}
```

#### `PLAYER_STATE` (relayed)

Same structure as the client sends, but with an added `player_id` field:

```json
{
  "type": "PLAYER_STATE",
  "player_id": "b1c2d3e4",
  "seq": 1001,
  "ts": 1711152000.123,
  "pos": [45.2, 0.0, 32.7],
  "angle": 1.5708,
  "anim": 3,
  "anim_frame": 12,
  "move_state": 1,
  "held_item": 8201,
  "emote": 0
}
```

#### `APPEARANCE` (relayed)

Same structure as client sends with added `player_id`.

#### `GAME_EVENT` (relayed)

Same structure as client sends with added `player_id`.

#### `CHAT` (relayed)

```json
{
  "type": "CHAT",
  "player_id": "b1c2d3e4",
  "player_name": "Bob",
  "text": "Hello!"
}
```

---

## Rate Limits

| Message type | Max rate |
|---|---|
| `PLAYER_STATE` | 60 / second |
| `GAME_EVENT` | 10 / second |
| `CHAT` | 2 / second |
| All others | 5 / second |

Exceeding limits returns an `ERROR` with code `RATE_LIMITED`.

---

## Latency & Interpolation

Clients should implement **linear interpolation** (lerp) for remote player positions using the `ts` (timestamp) field. Recommended parameters:

- **Interpolation buffer**: 100 ms (3 frames at 30 Hz)
- **Maximum extrapolation**: 200 ms
- **Snap threshold**: If predicted vs. received delta exceeds 5.0 world units, snap immediately.
