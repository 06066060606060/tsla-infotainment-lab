# Infotainment Lab

[Download](https://github.com/derrickyau9/tsla-infotainment-lab/releases/latest) · [Changelog](CHANGELOG.md)

Run infotainment software on your own computer, with the center display and instrument cluster in separate desktop windows. A native Qt app handles your firmware library, driving controls, browser windows, cameras, and recorded drives.

Infotainment Lab runs on Linux and Windows with Debian WSL2. The Material 3 control panel supports native and QEMU desktop sessions. The latest release, **0.5.1**, fixes native startup and QEMU idle-display stalls; the [changelog](CHANGELOG.md) lists what has landed since, including the Console, Vehicle config, Alerts, the Service Mode panel and firmware network isolation.

![Device manager with the light theme](docs/screenshots/material-devices-en.png)

## Bring your own firmware

**You need your own compatible Firmware Dump.** Firmware and maps are not included in this repository or its downloads. Obtain a dump you have permission to use; this project does not provide extraction tools or export tutorials.

The app reads fonts and vehicle assets from your selected image. Model S/X MCU2 images use a center display and instrument cluster; ICE images use a landscape center display. The built-in MCU2 profile is for **2026.26.6.1**. Other Model S/X MCU2 and ICE builds launch on an **experimental** generic profile for their platform, marked as such in Devices; they have no validation record (see [compatibility](docs/compatibility.md)).

## Get started

You need an x86_64 computer and a Linux graphical desktop. On Windows, install **Debian under WSL2** with [WSLg support](https://learn.microsoft.com/en-us/windows/wsl/tutorials/gui-apps).

1. Download and fully extract a release archive. Keep the `_internal` folder beside the executable.
2. For the Linux app, run `bash Launch-Linux.sh`, or double-click **Launch-WSL.cmd** on Windows. The Windows control-panel package starts with **InfotainmentLab.exe**.
3. Select **Prepare computer** to install the Linux runtime components.
4. Drop your firmware image into **Devices**, select it, then choose **Start device**.
5. Use **Center** and **Cluster** in the toolbar to bring a display forward. **Capture** saves both screens as PNGs.

Run the app as your normal desktop user. Setup asks for administrator access when it needs to install packages. Linux binary downloads require glibc 2.41 or newer.

Closing the control panel leaves the session running. **Stop** ends it; **Restart** starts again in Park. Device settings and your selected map package are remembered.

**Full reset**, next to **QEMU boot check** on the Device page, stops the session and deletes the lab's cached session, engine copy, mount points, library index and saved device settings, as on a first import. Your firmware, map and QEMU guest files are never touched. Stop and Full reset unmount the image themselves, lazily if a Console shell or a leftover process still holds it, and a start after the mount helper died clears the dead mount and mounts the image again.

### From source

Install Python 3.11+ and `python3-venv`, then:

```bash
git clone https://github.com/derrickyau9/tsla-infotainment-lab.git
cd tsla-infotainment-lab
bash Launch-Linux.sh
```

The launcher creates a Python environment and installs Qt on first use. On Windows, use **Launch-WSL.cmd** from the checkout. To select another distribution, run `Launch-WSL.ps1 -Distribution <name>` in PowerShell.

For a Start-menu shortcut, run `scripts/install-wsl-shortcut.ps1`. If the window does not open, launch from a terminal and check `~/.local/state/tsla-infotainment-lab/launcher.log`.

#### Display scaling on Windows

Under WSLg the lab reads your Windows display scale and draws everything at that size: the panel through Qt, and the center and instrument displays by starting the firmware at a larger window scale on a matching larger screen. Nothing is stretched, so text stays sharp and touches stay aligned. The displays shrink as needed to fit your desktop, in steps that keep whole pixels. A new scale applies from the next session start. Set `INFOTAINMENT_LAB_SCALE` (for example `1.25`, or `1` to turn scaling off) to choose another size. `python3 -m infotainment_lab.display_scale` prints the detected values.

QEMU mode needs a guest image built with this version of `scripts/build-virtual-guest.py`; older images keep the default size.

WSLg's own fractional scaling (`WESTON_RDP_FRACTIONAL_HI_DPI_SCALING` in `%USERPROFILE%\.wslgconfig`) stretches every window as a bitmap, which blurs text and enlarges the cursor. The lab takes it into account, but it isn't needed. If an earlier version added it, `python3 -m infotainment_lab.display_scale --disable-wslg-scaling` removes the line; then run `wsl --shutdown`.

### QEMU mode

Choose **QEMU** in Devices to run the desktop inside a Debian guest. The panel manages startup, shutdown, dual-screen previews, browser cards, driving inputs, and camera replay. MCU2 uses VirGL for graphics, with VirtualGL sharing the GPU with the instrument window.

QEMU uses a replacement Linux kernel and your read-only firmware image. Prepare the guest disk locally using the [QEMU desktop guide](docs/virtual-desktop.md).

## Make it yours

Choose System, Light, or Dark appearance and an Iris, Blue, or Leaf accent. Smaller windows switch to compact navigation.

## Driving and instruments

Select P, R, N, or D and adjust speed, accelerator, brake, steering, and turn signals in **Controls**. Both displays receive the same local inputs. Park resets speed and accelerator to zero. Drive, Wheel buttons and the vehicle-service groups share one tab bar.

The Drive tab's power meter spans **-100 kW** (regen) to **+400 kW** (drive) in 1 kW steps and writes that value to `VAPI_powerLevel`. The kW unit is inferred from the firmware, not yet confirmed on a running display.

**Car off** is separate from Park. It shifts to Park, zeroes speed and accelerator, and turns off the power values the firmware watches: the rails, driver present, accessory power and the display keep-alive and backlight. The firmware then sees an off car and can sleep its screens. Selecting a gear turns the car back on, and the Drive feedback line shows the firmware's answer as **Power**.

The steering-wheel buttons control volume, mute, playback, and tracks. Hold Volume + or − for continuous adjustment. The right-hand buttons open instrument panels. Santa mode and supported display preferences carry across both screens, along with music titles and playback information.

![Santa mode and the instrument volume popup](docs/screenshots/cluster-santa.png)

**Vehicle services** brings together climate, doors, lights, energy, and audio. Open a door, change the battery level, or switch the headlights; the panel shows the firmware's response. Changes made through the native climate and audio controls feed back into the panel. See the [vehicle services guide](docs/vehicle-services.md).

These controls operate the local desktop session. They do not connect to a physical vehicle.

## Service Mode

Enter Service Mode on the center display with the normal access code (Controls → Software, hold MODEL), or use the Developer, Service and Factory switches on the **Modes** tab. The lab starts the firmware's own Service panel: its `service-ui` backend in a private network namespace and its `chromium-odin` window, with the firmware's data-value server supplying vehicle values. A stand-in for the diagnostic engine lists the image's own task catalogue (691 tasks on a 2026.8.3 MCU2 image).

This is **experimental**. Tasks never run: each ends with an error saying no vehicle is attached. Gateway-config values are placeholders, VIN, odometer and firmware fields stay empty, the CAN Viewer stays locked, and Service Mode Plus is not available. No token, identity or access-code check is changed. See [Service Mode](docs/vehicle-services.md#service-mode).

## Vehicle configuration

**Vehicle config** imports a `Name,Value` CSV, such as a dump from your own car. Search it, show changed values only, edit or add keys, and **Apply** to write them to the running displays; each row shows the firmware's answer. **Defaults** returns to the lab's vehicle profile and **Export CSV** saves your edits.

Imports keep personal data out: logins, passwords, PINs, keys, device and network identifiers, and locations are never imported, stored or written. Live readings such as display power are listed but never written. A Model 3 configuration is refused on an image that has only the Model S/X interface.

Some car-config values make the firmware restart its UI. The lab handles that as a configuration restart, drops conflicting language settings after three restarts, and records each restart. See the [vehicle configuration guide](docs/vehicle-config.md).

## Alerts

Refused or unknown configuration keys and firmware restarts are listed under **Diagnostics › Alerts**, with a count on the Diagnostics sidebar entry, instead of popups. Each restart alert names the display and the values it restarted for.

## Console

**Console** opens a terminal inside the running CID's read-only firmware root, with Tab completion, history and Ctrl+C. The native engine enters it directly through a user namespace. The QEMU engine connects over SSH to `127.0.0.1:2222` with a key the lab creates and authorizes on first **Connect**, then enters the image the guest mounts at `/firmware`. Guest images built before the SSH server was added need a rebuild.

## Firmware network isolation

Firmware processes and browsers the lab starts cannot reach Tesla's servers. Names under `tesla.com`, `teslamotors.com`, `tesla.services` and `tesla.cn` do not resolve, and each process log records `netguard: blocked lookup of …`. The two local media names still map to loopback, and other traffic such as map tiles is unchanged. Connections to literal IP addresses are not intercepted.

## Browser workspace

Open **Browsers**, enter an address, and choose **Browser** or **Card view**. **Theater** opens the firmware's app catalog. Browser and Card share a profile, with keyboard input, scrolling, text selection, and dragging inside the embedded view.

Leave the address empty to open a local page with audio, text input, dragging, and WebGL examples. Music apps open from the center display and use their own account sign-in.

<img src="docs/screenshots/embedded-browser.png" width="350" alt="Chromium inside the center display" /> <img src="docs/screenshots/theater.png" width="350" alt="The native Theater catalog" />

## Cameras and recorded drives

In **Camera & replay**, choose a test pattern, open a video, or connect an existing RGB pipeline. Open the camera on the center display, or select R for the backup-camera view.

Choose **Open dashcam MP4…** to play a recording with embedded driving data. Gear, speed, pedals, steering, and indicators follow the video. Pause, seek, playback speed, and looping apply to both. **Take over** returns control to you; Play resumes the recording.

![Camera and replay controls](docs/screenshots/replay-en.png)

To try a sample recording, run `python3 scripts/make-replay-demo.py` and open `build/replay-demo.mp4`.

An existing camera pipeline can publish **1280 × 720 RGB24** frames through an atomically replaced file, such as `/tmp/tesla-sim/v4l2-back.rgb`. Enter that path in the panel. See [camera and replay formats](docs/replay.md) for the details.

## CAN channels and the emulated gateway

Open **CAN & gateway** to start the local CAN service. It offers the channels the vehicle names — VEH, CHASSIS and PARTY — over SocketCAN `vcan` interfaces when the kernel provides them, and over a software hub when it does not.

An emulated gateway sits between those channels and the infotainment side. Reads are published freely; a write arriving from the infotainment side needs a route, an allowlisted identifier, a valid checksum and an unlocked session, and is rate limited. Accepted climate and lighting requests feed back into the vehicle services panel, so a frame that crosses the gateway changes the session exactly as the UI would.

The panel sends a frame either through the gateway or straight onto a channel, and lists recent traffic with decoded signals. `candump` and `cansend` see the same frames when SocketCAN is selected.

The gateway is a behavioural model: separate channels, per-direction filters, locked by default. It contains no vendor protocol, key or authentication scheme, and the frame definitions are this project's own `LAB_*` layouts — load your own `.dbc` for anything else. See the [CAN and gateway guide](docs/can-gateway.md).

## Development

This is an independent compatibility and cybersecurity engineering project. It brings together native graphics, input routing, process management, and local simulation while keeping the supplied firmware unchanged.

See the [architecture](docs/ARCHITECTURE.md), [compatibility notes](docs/compatibility.md), and [contribution guide](CONTRIBUTING.md).

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
python scripts/build.py
```

On Windows, activate with `.venv\Scripts\Activate.ps1`. Build on the target operating system; output goes to `dist/`.

Firmware, maps, recordings, browser profiles, logs, and credentials stay out of the repository. Public replay screenshots use generated footage.

Not affiliated with or endorsed by Tesla. Project code is MIT-licensed; firmware, trademarks, screenshots of third-party interfaces, and dependencies retain their respective rights. See [third-party notices](THIRD_PARTY_NOTICES.md).
