# CAN channels and the emulated vehicle gateway

This subsystem adds two things to the lab: a local CAN transport with several
named channels, and an emulated gateway that decides what may cross between
those channels and the infotainment (Ethernet) side.

## Scope and honesty about it

- The gateway is a **behavioural model**, not a reimplementation of any vendor
  gateway. It models the properties that matter when testing an infotainment
  session: separate channels, an identifier allowlist per direction, writes
  refused by default, a rate limit, and diagnostic traffic kept on its own
  channel.
- There is **no vendor protocol, key, certificate or authentication scheme** in
  this repository. The unlock step is a local HMAC handshake over a secret the
  operator chooses (`LAB_GATEWAY_SECRET`, default `infotainment-lab`), so the
  "locked by default" path can be exercised end to end.
- The frame definitions in `can_database.py` are **lab definitions**, authored
  for this project. Names begin with `LAB_`. A value decoded from them proves
  what this lab encoded and nothing about a real vehicle. Load your own `.dbc`
  when you have one you are entitled to use.
- Nothing here reaches a vehicle. `vcan` is a virtual kernel interface, the
  software hub stays inside the process tree, and the Ethernet bridge binds the
  loopback only.

## Parts

| Module | Responsibility |
| --- | --- |
| `can_frames.py` | Frame model, DBC-style signal packing, rolling counter, CRC-8 |
| `can_bus.py` | Transport: SocketCAN over `vcan`, or an in-process software hub |
| `can_database.py` | The `LAB_*` frame table and a minimal `.dbc` reader |
| `gateway.py` | Routes, filters, the unlock gate, and the loopback Ethernet bridge |
| `vehicle_can.py` | Projects `Simulation` and `VehicleServices` onto periodic frames |
| `can_service.py` | The loop: transport, gateway, periodic transmitter, control socket |

Channels: `veh` (body), `pt` (powertrain), `ch` (charging), `party` (isolated
diagnostic). With SocketCAN they map to `vcan0`…`vcan3`.

## Routing

Read paths are open, and anything that ends on a vehicle channel is gated:

| Route | Identifiers | Unlock required |
| --- | --- | --- |
| `pt` → Ethernet | `0x118`, `0x129` | no |
| `veh` → Ethernet | `0x102`, `0x2E5`, `0x3D8`, `0x3F5` | no |
| `ch` → Ethernet | `0x352` | no |
| Ethernet → `veh` | `0x2E5`, `0x3F5` | **yes** |
| Ethernet → `party` | `0x641` | **yes** |
| `party` → Ethernet | `0x651` | no |
| `veh` → `pt` | `0x3F5` | no |

A frame outside a route's filter is dropped and counted. A checksummed frame
with a bad CRC is refused even when unlocked. More than 400 inbound frames per
second are rate limited.

An accepted inbound `LAB_climate` or `LAB_lighting` frame is turned back into a
`VehicleServices` patch, so a write that crosses the gateway shows up in the
desktop session exactly as a UI change would.

## Where the state comes from

The desktop session owns the state the displays receive: `session/controls.json`
for driving inputs and `session/vehicle-services.json` for everything else. The
service follows both files, so a trace matches what is on screen, including
while a recorded drive is playing. Turn that off with
`{"action": "state", "follow_session": false}` to drive the frames from the
panel alone.

The displays themselves are never driven by CAN. They read the session's own
value interfaces, exactly as before this subsystem existed; the frames are a
projection of that state. The one path back is an accepted inbound
`LAB_climate` or `LAB_lighting` request, which is written to the vehicle
services file and therefore reaches both screens.

## Running it

One privileged step, only if you want real SocketCAN interfaces:

```bash
sudo python3 infotainment_lab/backend.py can-setup      # creates vcan0..vcan3
```

Without it, the service falls back to the software hub and everything still
works. Start the service and inspect it:

```bash
python3 infotainment_lab/backend.py can-start --can-backend auto
python3 infotainment_lab/backend.py can-status
```

Read frames, with signals decoded where a definition matches:

```bash
python3 infotainment_lab/backend.py can \
  --payload '{"action": "trace", "channel": "pt", "limit": 20}'
```

Send a frame. `origin: ethernet` goes through the gateway and is subject to the
gate; `origin: bus` presents the frame as if another ECU had produced it:

```bash
python3 infotainment_lab/backend.py can \
  --payload '{"action": "send", "origin": "ethernet",
              "frame": {"channel": "veh", "id": "0x3F5", "data": "01 00"}}'
```

Unlock, using the lab secret:

```bash
python3 - <<'PY'
import hashlib, hmac, json, subprocess
run = lambda p: json.loads(subprocess.run(
    ['python3', 'infotainment_lab/backend.py', 'can', '--payload', json.dumps(p)],
    capture_output=True, text=True).stdout.splitlines()[-1])
challenge = bytes.fromhex(run({'action': 'challenge'})['data']['challenge'])
response = hmac.new(b'infotainment-lab', challenge, hashlib.sha256).hexdigest()[:32]
print(run({'action': 'unlock', 'response': response}))
PY
```

Load your own database:

```bash
python3 infotainment_lab/backend.py can \
  --payload '{"action": "load-dbc", "path": "~/mine.dbc", "channel": "veh", "period_ms": 100}'
```

With SocketCAN selected, ordinary tools see the same traffic:

```bash
candump vcan0 vcan1 vcan2 vcan3
cansend vcan0 3F5#0100
```

## Desktop panel

**CAN & gateway** in the sidebar starts the service, shows the transport,
lock state and per-channel counters, performs the unlock handshake, sends a
frame either through the gateway or straight onto a channel, and lists recent
frames with decoded signals.

## Ethernet bridge

UDP on `127.0.0.1:20200`. Binary messages carry one frame:

```
byte 0    channel index (veh, pt, ch, party)
byte 1    flags (bit 0: extended identifier)
bytes 2-5 identifier, big endian
byte 6    payload length (0-8)
bytes 7+  payload
```

A datagram beginning with `{` is a JSON control request: `challenge`, `unlock`,
`lock` or `status`. Frames leaving the gateway are published to every peer that
has sent at least one datagram. A refusal is answered with
`{"ok": false, "error": …}`.

## Control socket

`$XDG_DATA_HOME/tsla-infotainment-lab/session/can-gateway.sock`, one JSON
request per connection, replies as `{"ok": …, "data": …}` like the rest of the
project. Actions: `status`, `send`, `trace`, `challenge`, `unlock`, `lock`,
`state`, `snapshot`, `load-dbc`, `stop`.

## Tests

```bash
python3 -m pytest tests/test_can_frames.py tests/test_gateway.py tests/test_can_service.py
```

They run on the software hub: no kernel module, no privileges, no hardware.
