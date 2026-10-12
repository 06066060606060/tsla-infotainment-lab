# Firmware replacements and Debug

## Replace a mounted firmware file

1. Stop the firmware session.
2. Open **Diagnostics** and find **Firmware replacements**.
3. Select an imported firmware image.
4. Enter the existing file's path inside the SquashFS, for example
   `/usr/tesla/UI/path/to/file.qml`.
5. Click **Choose replacement…** and select your local replacement file.
6. Start the device. The runtime and Console see the replacement at that path.

The original image is never rewritten. Replacements are copied into private
storage per image, retain the original file's permission bits without setuid or
setgid, and persist across restarts. Choose an entry and click **Restore selected
original** to remove its replacement; the next launch uses the original.
**Full reset** removes all replacements along with the session cache.

Only existing regular files are supported. Symbolic-link targets and paths with
parent traversal are refused. For a link, enter the actual path of the file
inside the image. Changes are blocked while that firmware session runs.

The native engine needs `fuse-overlayfs`; **Prepare computer** installs it with
the other runtime dependencies. It combines the replacements and original
SquashFS as read-only layers. See the
[upstream mount options](https://github.com/containers/fuse-overlayfs/blob/main/fuse-overlayfs.1.md).
No writable layer is exposed to firmware processes.

QEMU guests must be rebuilt with the updated `scripts/build-virtual-guest.py`
to use replacements. The launcher refuses an older guest when replacements are
configured. Each launch copies only the chosen replacement files into a private
read-only input share. The guest keeps its original SquashFS at `/firmware-base`
and exposes the combined view at `/firmware`, including to the SSH Console.
The prepared guest disk and original firmware disk remain separate.

The compatibility profile checks the original image. A modified executable or
asset can change behavior or fail; adding a replacement does not establish that
the modified firmware is compatible.

## Inspect the running OS

Open **Debug**, immediately below **Diagnostics** in the sidebar. Logs refresh
every two seconds while this page is visible and **Auto refresh** is enabled.
**Refresh now** takes a snapshot even when auto refresh is paused.

Use the source selector to inspect a single log or all sources. The filter keeps
lines containing the supplied text, ignoring case. The viewer follows new output
when already scrolled to the bottom; scrolling up preserves your position.

- **Native:** firmware process logs, the owned session's user-service journal,
  and the host's current-boot kernel journal. This engine runs compatible firmware
  applications on the host OS; it does not boot the original firmware OS.
- **QEMU:** the guest's serial console and VM launch log are available even before
  the guest agent is ready. Updated guests also expose firmware process logs,
  the desktop service journal, the guest kernel and the guest OS journal.

Missing logs or journal permissions produce a visible notice. Large files show
their latest 32,000 bytes; journal queries show at most 200 entries. These are
local debug snapshots, not a complete persistent capture. Existing guests need
a rebuild for the new guest-journal operation. Public diagnostic reports continue
to exclude raw logs and replacement file contents.
