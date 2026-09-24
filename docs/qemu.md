
The [virtual desktop](virtual-desktop.md) uses a replacement Linux kernel with
VirtIO drivers and read-only firmware applications. MCU2's real UI and embedded
browser now run in native QEMU windows; both displays use AMD-backed VirGL.
The original-kernel diagnostics below remain separate. Full equivalent firmware
functionality is still in development.

## Vendor boot checks

The device manager's **QEMU boot check** runs an independent, bounded test of the selected firmware. It does not replace the native compatibility session. It is not a complete Tesla hardware emulator and does not promise the same GUI, GPU, audio, camera or vehicle functionality.

## Requirements

- Linux with `qemu-system-x86_64`, `unsquashfs`, and user access to `/dev/kvm`.
- A locally supplied SquashFS containing `deploy/iasImage-bank_a` with one complete x86 Linux boot image.
- No firmware, extracted kernel or VM disk is distributed in this repository.

The test uses Q35/KVM, four virtual CPUs, 2 GiB RAM, an SDHCI controller and a serial console. It has no network adapter, host directory sharing, host disk passthrough or vehicle hardware. The firmware boot check runs for 60 seconds and QEMU is then stopped and reaped by the worker. This timeout is a diagnostic limit, not proof that the guest booted.

The worker locates and validates the x86 boot header before extracting the declared kernel extent. It leaves the embedded vendor init intact. This directly boots the kernel; it does **not** validate or reproduce the original bootloader chain.

## Results

Logs and machine-readable results are stored under the Linux user's application data directory:

```text
~/.local/share/tsla-infotainment-lab/qemu/<firmware-id>/serial.log
~/.local/share/tsla-infotainment-lab/qemu/<firmware-id>/result.json
```

On September 16, 2026, the 2026.26.6.1 MCU2 kernel (`5.4.302-PLK`) reached vendor `/init` under QEMU/KVM. `verity-init` then reported that one or more parent devices never appeared, followed by an init panic. `desktop_verified` remains false. The same result is reproduced by the integrated worker.

The integrated check also tested 2026.26.6.5 ICE on the same date: kernel and vendor init started, then stopped at the same missing-parent-device error.

Full boot needs the expected block-device topology, partition contents and integrity metadata, followed by compatible graphics, peripherals and service dependencies. These have not been implemented or validated. A standalone SquashFS on a VirtIO disk does not supply that environment. Do not describe kernel startup as a complete firmware desktop.

## Storage progress after the initial test

The firmware supplies `sbin/mmcblk0.sfdisk` and a 1024 MiB per-bank expansion reservation in `sbin/check-lvm-parts`. The new storage builder uses that GPT layout in a 64 GiB sparse guest file. It copies the image verbatim into both legacy root-bank partitions, placing any overflow in the corresponding reserved tail of partition 4. It rejects images exceeding those extents and refuses to overwrite an existing disk. It never opens a host block device.

On the same date, MCU2 boot with SDHCI and the vendor GPT successfully created the dm-verity root device, matched the initramfs commit, switched root, and ran the firmware's `/sbin/init`. This supersedes the initial missing-parent-device blocker for that tested MCU2 image. The firmware logs still report missing HECI support; no claim of original hardware identity or bootloader-chain verification is made.

A separate maintenance VM prepares the boot ext2 filesystem and `ivg` volume group before vendor boot. It uses Debian's `6.12.107+deb13-amd64` kernel, downloaded as a package from the configured Debian security repository and extracted into application data without installing a host kernel. Its initramfs contains local BusyBox, LVM and filesystem tools. Preparation completed and powered off successfully; a subsequent original-kernel boot began creating `var` and `log` volumes. The maintenance kernel is not substituted for the vendor kernel in the firmware boot.

The source SquashFS remains unchanged. Bounded tests discard subsequent writes through QEMU's temporary snapshot. An ongoing development run uses a persistent qcow2 overlay over the prepared raw guest disk so first-boot provisioning can finish across a longer observation window. This development run is not yet a supported GUI launch mode.

Remaining completion gates: reproducible setup on a clean machine; completed vendor service startup; working guest graphics and native input; equivalent browser/window, Internet, audio, camera/replay and simulator control paths; persistence and clean shutdown/restart; native/VM selection and diagnostics in the application. None of these gates is established by a kernel boot log or unit-test pass alone.

## Persistent manager under development

The backend now exposes `qemu-start --id <firmware-id>`, `qemu-status --id <firmware-id>` and `qemu-stop --id <firmware-id>`. Start requires an already prepared guest disk and kernel. It uses a persistent qcow2 overlay, an original-kernel boot, a standard swtpm 2.0 device and a native GTK QEMU window. `--headless` omits that window; `--internet` opts into a QEMU user-mode igb adapter. No port forwards or host folders are configured.

The manager verifies both Linux PID start time and QMP UUID before controlling a VM. Stop requests ACPI shutdown and reports the live process until it actually exits; it does not turn a request or observation timeout into proof of shutdown. It refuses to compete with an active development VM or virtual TPM. Backend status reports an independently verified development VM separately from managed sessions.

Validation so far: a real paused QEMU test passed QMP identity, status and shutdown-request checks; a separate Q35/KVM test exposed the swtpm-backed `tpm-tis` device through `query-tpm`. These prove the control mechanisms and standard device attachment, not vendor service compatibility. The original-kernel development run has progressed through home and map volume setup to gamesusr formatting, with ongoing disk writes. No firmware desktop has been verified.

## Original-kernel graphics constraint

All seven supplied MCU2/ICE images were inspected through their embedded kernel configuration, including gzip- and LZ4-compressed kernels. Their configurations enable Intel i915 as a module, disable VirtIO PCI and the QXL/Bochs/VMware/VirtualBox graphics drivers, and require signed kernel modules. The per-image findings are recorded in `qemu-driver-inventory.json` without distributing firmware or kernel payloads.

The current host has AMD integrated graphics and an NVIDIA RTX 5090; Debian WSL sees Hyper-V display devices. The installed QEMU does not expose an emulated Intel i915 GPU. Firmware's X service explicitly loads i915 and requires `/sys/class/drm/card0`. These observations identify a real remaining graphics compatibility gap; a QEMU VGA window does not satisfy it. No module-signature or firmware integrity checks have been disabled.

A separate original-kernel run with a standard virtual TPM successfully enumerated TPM 2.0, selected the firmware's `tpm2` storage implementation and began creating its encrypted volumes. The original development guest remains separate. The new run's graphical desktop is still unverified.

Networking now models the firmware's isolated `192.168.90.0/24` eth0 segment using igb. Optional upstream networking is a second adapter because the firmware's ConnMan startup ignores eth0. Guest route, DNS and application connectivity remain to be verified after service startup.

A separate original-kernel MCU2 guest using the experimental QEMU SD erase patch reached `/etc/runit/2` at approximately 196 seconds after boot. This verifies that first-boot storage initialization can progress into the service supervisor. Its serial log still contains missing GPIO, HECI, eMMC boot-region and gateway configuration errors. The guest also marked TSC unstable and subsequently reported RCU stalls in `read_hpet`; timing compatibility needs further investigation. Service supervisor entry is not evidence that the dependent applications work.

The SD patch and its local erase/readback measurements are described in [patches/README.md](../patches/README.md). It preserves erased bytes as `0xff`. The local experimental build does not yet include all audio backends and is not the application's default emulator.

## Timing comparison and disk ownership

A second, independent guest used QEMU's `hpet=off` machine option. Its original
kernel selected `acpi_pm` and entered the service supervisor. No RCU stalls
appeared in the first 265 seconds, but three had appeared by 403 seconds. The
HPET guest had 14 at 889 seconds; the observation windows differ, so these are
not a controlled rate comparison. Disabling HPET is not a verified fix and is
not selected by default. Recurring minijail general-protection faults resolve
to libc's `abort()`/`hlt` path, rather than evidence of a missing CPU instruction.

Boot checks and persistent starts now share the same lifecycle lock and live
process/control-socket checks before extracting a kernel or provisioning a
base disk. A real active-guest check confirmed preparation is refused without
touching its files. A stale development socket is reusable only when its
recorded process is gone; transient control failures continue to block writes.

## Delivery audit

The requested full firmware mode with equivalent functionality is **not complete**.
The user has selected preservation of the original kernel and requested AMD
support. Host AMD rendering is now verified and selected for this application;
the remaining guest driver/device requirements are recorded in
[AMD graphics](amd-graphics.md). A generic-kernel VM port is not the selected route.

| Requirement | Current evidence |
| --- | --- |
| Original firmware kernel and root boot | MCU2 serial logs show vendor init, verified root transition and service supervisor entry. |
| Complete desktop and graphics | Not achieved. Firmware X requires i915/card0; this host and QEMU configuration cannot provide it. |
| Stable service startup | Not achieved. Missing peripheral/configuration dependencies and recurring service failures remain. |
| Internet, Chromium, theater and multiple windows in the VM | Not verified. A NIC or QEMU window alone does not establish these functions. |
| VM audio, camera/replay and vehicle controls | Not integrated or verified against the existing native session's functionality. |
| Dual-screen synchronization | Not verified in the VM. |
| Persistence and lifecycle | Separate qcow2/TPM state and identity-checked QMP control tested; firmware clean shutdown/restart remains unverified. |
| Drop-and-play GUI and clean-machine setup | Material Qt shell, VM selection and guest preparation are implemented; clean-machine setup and full feature parity remain unverified. |

Both timing-comparison guests were explicitly ended after their experiments;
fresh process checks confirmed exit. Their virtual disks and logs remain for
inspection. These test endings are not evidence of firmware-managed shutdown.

