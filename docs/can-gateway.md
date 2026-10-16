# OS gateway observation and frame injection

## Observe the running OS

The panel opens on **OS traffic observation**. This view does not start the
emulated gateway or its periodic LAB transmitter. Select **Network sends** to
see successful firmware UDP sends to the session gateway on loopback, or
**Gateway API requests** to inspect requests before transport delivery is known.
These observation points can describe the same message; select **Both** only
when comparing them. Timestamps are milliseconds since observer startup.

Vehicle bus filters are **Party**, **Chassis** and **Body / VH**. The current
Model 3 firmware's exported catalogue describes an **ETH** channel. Its message
number does not establish the physical bus the vehicle gateway would forward
onto. Those records therefore appear under **Gateway / Ethernet**; empty CAN
bus filters remain empty. CAN extended/RTR flags are left unknown for Ethernet
records, rather than invented. A successful UDP send does not prove CAN delivery.

For single-display native sessions, `native_vehicle.py` starts the firmware's
`QtCarVehicle`, which assembles the gateway messages. It reads the display's
real published requests while keeping its own output publishers in a private
mount namespace and its shared memory in a private IPC namespace. User namespaces
and `mount` must be available. Its default vehicle data does not replace the
lab display model. The supervisor owns and stops the process tree.

`native-traffic.c` copies gateway API calls and successful `send`/`sendto` calls
to a private nonblocking Unix datagram collector. It preserves the original
calls, results and errno. `native_traffic.py` keeps a bounded 256-record memory
window; the panel displays up to 128 matching records. This is a best-effort
live view, not a lossless recorder. Slow viewers do not block the OS. Detailed
snapshots and signal decoding are published while a viewer is polling; the
closed panel retains only small status snapshots on disk.

**Choose DBC** selects a local definition file without changing it. The source
and selected path stay outside the repository. `native_catalog.py` reads the
selected firmware's exported message/signal tables without executing the ELF;
the recognized x86-64 layout is checked through symbol sizes and back pointers.
It supplies names, units and enumerations, but these tables do not contain the
bit positions needed for decoding. `native_dbc.py` applies the selected bit
layouts, signedness, scaling and supported multiplex conditions. It refuses
length mismatches and omits overlapping fields lacking multiplex definitions.
An older DBC is not automatically merged with current definitions.

Select a raw record to see **Signal / Value / Unit**. **Copy raw CSV** and
**Copy decoded CSV** retain the supplied log formats' leading columns, with
bus/direction/transport information appended so that the source stays visible.
No recorded CSV is imported or replayed by this view. Captures, derived metadata
and selected DBC paths remain local and outside public diagnostic exports.

## FRAME INJECTION

The desktop's former Lab gateway tools section is replaced by **FRAME INJECTION**.
Select a decoded record under **Network sends**, choose **Use selected frame**,
name the rule and check the signals to override. Editing a value checks its
Override box. Values accept physical DBC units or exact enumeration labels.
**Save rule (disabled)** stores the draft; **Enable selected rule** starts it.
**Edit selected rule** loads an existing rule; saving edits disables it again.

Each newly observed, successful OS UDP send for the selected message triggers
one selective echo to **127.0.0.102:4321**. The echo contains the original
message number and payload length. Its payload starts from that new frame,
with only the selected signal bits replaced. The worker does not replay the
sample used to create a rule or send periodically when no new frame arrives.
Gateway API copies do not trigger a second echo. The worker is not preloaded
with the capture adapter, so its own sends do not feed the observer again.
The original OS send is preserved; this is an additional datagram.

The local gateway endpoint is the only destination. No physical CAN interface,
bus assignment, gateway receive service or OS input mapping is added by these
rules. A successful UDP write is counted as an echo, not proof of receipt by
another process, an OS state change or physical CAN delivery.

The editor freezes its draft while observations keep updating. Inactive mux
signals, ambiguous layouts, length/name mismatches, unknown labels and values
outside raw range/resolution are refused. An inactive mux page on a later
source frame is skipped and counted. Unselected counters and checksums follow
the original frame; checksums are **not** automatically recalculated. The rule
list shows errors, echo/skip counts and the last output; hover for source/output
bytes. Up to 16 rules can be stored. **Disable selected rule**, **Delete selected
rule** and **Stop all echoes** operate independently of the display pause.

`native_injection.py` runs inside the observer. Configuration updates are
serialized and acknowledged through its applied status, rather than reporting
queue acceptance as success. Rules live in the private session directory,
remain outside public diagnostic exports, and are disabled on every worker or
device restart. Changing or losing the selected DBC stops active rules;
explicit activation is required to resume. Closing the control panel keeps
explicitly enabled rules running with the OS session.

## Emulated lab gateway (CLI)

This subsystem adds two things to the lab: a local CAN transport with several
named channels, and an emulated gateway that decides what may cross between
those channels and the infotainment (Ethernet) side.

## Scope and honesty about it

- The gateway is a **behavioural model**, not a reimplementation of any vendor
  gateway. It models the properties that matter when testing an infotainment
  session: separate channels, an identifier allowlist per direction, writes
  refused by default, a rate limit, and diagnostic traffic kept on its own
  channel.
- The emulated gateway contains **no vendor protocol, key, certificate or authentication scheme**.
  Its unlock step is a local HMAC handshake over a secret the
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

Lab channel keys remain `veh` (displayed as BODY / VH), `ch` (CHASSIS),
and `party` (PARTY). Their LAB frame roles are an emulation convention, not a
description of those physical vehicle buses. With SocketCAN they map
to `vcan0`, `vcan1` and `vcan2`.

## Routing

Read paths are open, and anything that ends on a vehicle channel is gated:

| Route | Identifiers | Unlock required |
| --- | --- | --- |
| `veh` → Ethernet | `0x102`, `0x118`, `0x129`, `0x2E5`, `0x3D8`, `0x3F5` | no |
| `ch` → Ethernet | `0x352` | no |
| `party` → Ethernet | `0x651` | no |
| Ethernet → `veh` | `0x2E5`, `0x3F5` | **yes** |
| Ethernet → `party` | `0x641` | **yes** |
| `veh` → `ch` mirror | `0x3F5` | no |

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
projection of that state. The paths back are the accepted inbound frames. `LAB_climate` and
`LAB_lighting` are written to the vehicle services file; `LAB_driveState`,
`LAB_steering` and the indicator field of `LAB_lighting` are written to the
controls file and release replay ownership, the same as moving a control by
hand. So an injected drive frame moves gear, speed and steering on both
screens. A frame carries physical quantities rather than UI intent, so a brake
flag only clears or leaves the pedal; it cannot restore a pedal percentage. A
request whose content is not a possible vehicle state — 40 km/h while in park —
is counted as blocked and not applied.

## Frame origin

Every frame reaching a listener carries where it came from: `periodic` for the
frames this service transmits from session state, `send` for a local write that
crossed the gateway, `inject` for one presented as another ECU, and `recv` for
one read from a SocketCAN interface. Only the last three can change local
state; reading back our own periodic traffic would fight the session and would
take ownership away from replay on every tick.

A raw CAN socket does not read back what it writes, so locally sent and
injected frames are traced and dispatched in software rather than by enabling
`CAN_RAW_RECV_OWN_MSGS`. The trace and the state feedback therefore behave
identically on both transports.

The service reports a revision, and starting it after an update replaces a
process still running older code instead of silently reusing it. After pulling a
change, restart both the desktop session and the CAN service:
the service is a long-lived process and keeps running the code it started with.

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
  --payload '{"action": "trace", "channel": "veh", "limit": 20}'
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

## Ethernet bridge

UDP on `127.0.0.1:20200`. Binary messages carry one frame:

```
byte 0    channel index (veh, ch, party)
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
