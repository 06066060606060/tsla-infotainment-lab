# QEMU development modes / QEMU 开发模式

The [virtual desktop](virtual-desktop.md) uses a replacement Linux kernel with
VirtIO drivers and read-only firmware applications. MCU2's real UI and embedded
browser now run in native QEMU windows; both displays use AMD-backed VirGL.
The original-kernel diagnostics below remain separate. Full equivalent firmware
functionality is still in development.

使用替代内核的[虚拟桌面模式](virtual-desktop.md)已启动 MCU2 真实 UI 与内嵌浏览器，
双屏使用 AMD 支持的 VirGL 加速。原厂内核诊断独立保留，完整等效功能仍在验证中。

## Vendor boot checks / 原厂内核启动检查

The device manager's **QEMU boot check** runs an independent, bounded test of the selected firmware. It does not replace the native compatibility session. It is not a complete Tesla hardware emulator and does not promise the same GUI, GPU, audio, camera or vehicle functionality.

设备管理器中的 **QEMU 启动检查** 对选中固件运行独立、限时测试，不替换正在运行的原生兼容会话。当前没有实现完整 Tesla 硬件模拟，也没有达到与现有界面、GPU、音频、摄像头和车辆控制相同的效果。

## Requirements / 环境要求

- Linux with `qemu-system-x86_64`, `unsquashfs`, and user access to `/dev/kvm`.
- A locally supplied SquashFS containing `deploy/iasImage-bank_a` with one complete x86 Linux boot image.
- No firmware, extracted kernel or VM disk is distributed in this repository.

The test uses Q35/KVM, four virtual CPUs, 2 GiB RAM, an SDHCI controller and a serial console. It has no network adapter, host directory sharing, host disk passthrough or vehicle hardware. The firmware boot check runs for 60 seconds and QEMU is then stopped and reaped by the worker. This timeout is a diagnostic limit, not proof that the guest booted.

测试使用 Q35/KVM、四个虚拟 CPU、2 GiB 内存、SDHCI 控制器和串口控制台；没有网卡、主机目录共享、主机物理磁盘直通或车辆硬件。固件检查运行 60 秒后结束并回收进程，超时不代表启动成功。

The worker locates and validates the x86 boot header before extracting the declared kernel extent. It leaves the embedded vendor init intact. This directly boots the kernel; it does **not** validate or reproduce the original bootloader chain.

## Results / 结果

Logs and machine-readable results are stored under the Linux user's application data directory:

```text
~/.local/share/tsla-infotainment-lab/qemu/<firmware-id>/serial.log
~/.local/share/tsla-infotainment-lab/qemu/<firmware-id>/result.json
```

On September 16, 2026, the 2026.26.6.1 MCU2 kernel (`5.4.302-PLK`) reached vendor `/init` under QEMU/KVM. `verity-init` then reported that one or more parent devices never appeared, followed by an init panic. `desktop_verified` remains false. The same result is reproduced by the integrated worker.

2026 年 9 月 16 日，2026.26.6.1 MCU2 的 `5.4.302-PLK` 内核已在 QEMU/KVM 下进入原厂 `/init`。随后 `verity-init` 报告预期的父设备没有出现，并触发 init panic。项目内复测得到相同结果，`desktop_verified` 保持 false。

The integrated check also tested 2026.26.6.5 ICE on the same date: kernel and vendor init started, then stopped at the same missing-parent-device error. / 同日用项目内流程测试 2026.26.6.5 ICE：内核和原厂 init 均已启动，随后同样停在父设备缺失错误处。

Full boot needs the expected block-device topology, partition contents and integrity metadata, followed by compatible graphics, peripherals and service dependencies. These have not been implemented or validated. A standalone SquashFS on a VirtIO disk does not supply that environment. Do not describe kernel startup as a complete firmware desktop.

完整启动仍需预期的块设备拓扑、分区内容及完整性元数据，之后还需兼容图形设备、外设和服务依赖；这些尚未实现或验证。单独将 SquashFS 作为 VirtIO 磁盘无法提供该环境，不能把内核启动称为完整车机桌面。

## Storage progress after the initial test / 初次测试后的存储进展

The firmware supplies `sbin/mmcblk0.sfdisk` and a 1024 MiB per-bank expansion reservation in `sbin/check-lvm-parts`. The new storage builder uses that GPT layout in a 64 GiB sparse guest file. It copies the image verbatim into both legacy root-bank partitions, placing any overflow in the corresponding reserved tail of partition 4. It rejects images exceeding those extents and refuses to overwrite an existing disk. It never opens a host block device.

固件自带 `sbin/mmcblk0.sfdisk` 分区表；`sbin/check-lvm-parts` 声明每个根分区预留 1024 MiB 扩展空间。新构建器按该布局创建 64 GiB 稀疏虚拟盘，将固件原始字节写入 A/B 根分区，并把超出旧分区容量的部分放入第四分区对应的尾部预留区。超出容量时拒绝构建，也不会覆盖已有磁盘或打开主机块设备。

On the same date, MCU2 boot with SDHCI and the vendor GPT successfully created the dm-verity root device, matched the initramfs commit, switched root, and ran the firmware's `/sbin/init`. This supersedes the initial missing-parent-device blocker for that tested MCU2 image. The firmware logs still report missing HECI support; no claim of original hardware identity or bootloader-chain verification is made.

同日，MCU2 在 SDHCI 和原厂 GPT 布局下，已创建 dm-verity 根设备、匹配 initramfs 版本、切换根文件系统并执行固件的 `/sbin/init`。这解决了该 MCU2 镜像最初的父设备缺失问题。日志仍报告 HECI 缺失，未验证原厂硬件身份或完整引导链。

A separate maintenance VM prepares the boot ext2 filesystem and `ivg` volume group before vendor boot. It uses Debian's `6.12.107+deb13-amd64` kernel, downloaded as a package from the configured Debian security repository and extracted into application data without installing a host kernel. Its initramfs contains local BusyBox, LVM and filesystem tools. Preparation completed and powered off successfully; a subsequent original-kernel boot began creating `var` and `log` volumes. The maintenance kernel is not substituted for the vendor kernel in the firmware boot.

独立维护虚拟机负责预先创建 boot 的 ext2 文件系统和 `ivg` 卷组。它使用 Debian 安全仓库的 `6.12.107+deb13-amd64` 内核包，下载后仅解包到应用数据目录，不安装主机内核；维护 initramfs 包含本机 BusyBox、LVM 和文件系统工具。实测初始化完成后正常关机，后续原厂内核启动已开始创建 `var`、`log` 数据卷。维护内核不替代正式固件启动使用的原厂内核。

The source SquashFS remains unchanged. Bounded tests discard subsequent writes through QEMU's temporary snapshot. An ongoing development run uses a persistent qcow2 overlay over the prepared raw guest disk so first-boot provisioning can finish across a longer observation window. This development run is not yet a supported GUI launch mode.

原始 SquashFS 保持不变。限时测试通过 QEMU 临时快照丢弃后续写入；开发中的长时运行使用已初始化虚拟盘上的持久化 qcow2 写入层，以便继续完成首次启动。这个长时开发运行尚未成为受支持的 GUI 启动模式。

Remaining completion gates: reproducible setup on a clean machine; completed vendor service startup; working guest graphics and native input; equivalent browser/window, Internet, audio, camera/replay and simulator control paths; persistence and clean shutdown/restart; native/VM selection and diagnostics in the application. None of these gates is established by a kernel boot log or unit-test pass alone.

仍需验证：新机器可复现的环境准备、原厂服务启动完成、虚拟机图形与原生输入、浏览器/窗口/联网/音频/摄像头回放/模拟控制等效、持久化及正常关机重启，以及应用内模式选择和诊断。内核日志或单元测试通过都不能单独证明这些要求完成。


## Persistent manager under development

The backend now exposes `qemu-start --id <firmware-id>`, `qemu-status --id <firmware-id>` and `qemu-stop --id <firmware-id>`. Start requires an already prepared guest disk and kernel. It uses a persistent qcow2 overlay, an original-kernel boot, a standard swtpm 2.0 device and a native GTK QEMU window. `--headless` omits that window; `--internet` opts into a QEMU user-mode igb adapter. No port forwards or host folders are configured.

The manager verifies both Linux PID start time and QMP UUID before controlling a VM. Stop requests ACPI shutdown and reports the live process until it actually exits; it does not turn a request or observation timeout into proof of shutdown. It refuses to compete with an active development VM or virtual TPM. Backend status reports an independently verified development VM separately from managed sessions.

Validation so far: a real paused QEMU test passed QMP identity, status and shutdown-request checks; a separate Q35/KVM test exposed the swtpm-backed `tpm-tis` device through `query-tpm`. These prove the control mechanisms and standard device attachment, not vendor service compatibility. The original-kernel development run has progressed through home and map volume setup to gamesusr formatting, with ongoing disk writes. No firmware desktop has been verified.

后端已加入持久化启动、状态查询与正常关机请求；控制前同时核对 PID 启动时间和 QMP UUID。新的启动路径使用持久化写入层、原厂内核、标准虚拟 TPM 与原生 GTK 窗口，可显式启用用户态网络。当前开发虚拟机仍在首次格式化，新启动会拒绝重复占盘。真实 QEMU 控制协议与 TPM 挂接已验证；这不代表固件服务或桌面效果已验证，也尚未接通 GUI 中的模式切换及功能通道。


## Original-kernel graphics constraint

All seven supplied MCU2/ICE images were inspected through their embedded kernel configuration, including gzip- and LZ4-compressed kernels. Their configurations enable Intel i915 as a module, disable VirtIO PCI and the QXL/Bochs/VMware/VirtualBox graphics drivers, and require signed kernel modules. The per-image findings are recorded in `qemu-driver-inventory.json` without distributing firmware or kernel payloads.

The current host has AMD integrated graphics and an NVIDIA RTX 5090; Debian WSL sees Hyper-V display devices. The installed QEMU does not expose an emulated Intel i915 GPU. Firmware's X service explicitly loads i915 and requires `/sys/class/drm/card0`. These observations identify a real remaining graphics compatibility gap; a QEMU VGA window does not satisfy it. No module-signature or firmware integrity checks have been disabled.

A separate original-kernel run with a standard virtual TPM successfully enumerated TPM 2.0, selected the firmware's `tpm2` storage implementation and began creating its encrypted volumes. The original development guest remains separate. The new run's graphical desktop is still unverified.

Networking now models the firmware's isolated `192.168.90.0/24` eth0 segment using igb. Optional upstream networking is a second adapter because the firmware's ConnMan startup ignores eth0. Guest route, DNS and application connectivity remain to be verified after service startup.

七个镜像均已核对内核配置：i915 为模块，VirtIO PCI 与常用 QEMU 图形驱动未启用，并强制验证模块签名。本机没有对应 Intel GPU，固件 X 服务又要求 DRM card0，因此原厂内核的图形兼容仍是明确缺口。标准 TPM 已在独立原厂内核启动中被识别，并被数据卷初始化采用；桌面、路由、DNS 与应用联网仍未验证。

## Service startup after the SD erase fix / SD 擦除优化后的服务启动

A separate original-kernel MCU2 guest using the experimental QEMU SD erase patch reached `/etc/runit/2` at approximately 196 seconds after boot. This verifies that first-boot storage initialization can progress into the service supervisor. Its serial log still contains missing GPIO, HECI, eMMC boot-region and gateway configuration errors. The guest also marked TSC unstable and subsequently reported RCU stalls in `read_hpet`; timing compatibility needs further investigation. Service supervisor entry is not evidence that the dependent applications work.

The SD patch and its local erase/readback measurements are described in [patches/README.md](../patches/README.md). It preserves erased bytes as `0xff`. The local experimental build does not yet include all audio backends and is not the application's default emulator.

独立 MCU2 原厂内核实例使用 SD 擦除优化后，约 196 秒进入 `/etc/runit/2` 服务管理阶段。日志仍存在 GPIO、HECI、eMMC boot 区域和网关配置缺失，并出现 TSC 不稳定及 `read_hpet` 中的 RCU 停顿。首次初始化已取得进展，但服务功能、图形和音频仍未达到完整固件模式的交付要求。

## Timing comparison and disk ownership / 时钟对照与磁盘占用

A second, independent guest used QEMU's `hpet=off` machine option. Its original
kernel selected `acpi_pm` and entered the service supervisor. No RCU stalls
appeared in the first 265 seconds, but three had appeared by 403 seconds. The
HPET guest had 14 at 889 seconds; the observation windows differ, so these are
not a controlled rate comparison. Disabling HPET is not a verified fix and is
not selected by default. Recurring minijail general-protection faults resolve
to libc's `abort()`/`hlt` path, rather than evidence of a missing CPU instruction.

关闭 HPET 的对照实例成功切换到 ACPI 时钟，但延长观察后仍发生 RCU 停顿，因此没有采用为默认修复。两组观察时长不同，不能据此宣称改善比例。当前仍需解决图形设备和服务运行环境的缺口。

Boot checks and persistent starts now share the same lifecycle lock and live
process/control-socket checks before extracting a kernel or provisioning a
base disk. A real active-guest check confirmed preparation is refused without
touching its files. A stale development socket is reusable only when its
recorded process is gone; transient control failures continue to block writes.

## Delivery audit / 交付核对

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

完整 QEMU 固件模式及功能等效尚未交付。用户已选择保留原厂内核并补齐 AMD 支持；主机端 AMD 渲染已验证，固件客体仍缺少对应驱动和 GPU 设备。通用内核移植不是当前选择的路线。两组时钟对照测试已明确结束并核实进程退出，磁盘和日志保留；不能把测试进程结束当作原厂系统正常关机已验证。
