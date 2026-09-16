# AMD graphics

The replacement-kernel [virtual desktop](virtual-desktop.md) now renders the MCU2
center display through `virgl (D3D12 (AMD Radeon(TM) Graphics))`. Its independent
instrument window and vehicle visualization now share that GPU through VirtualGL. Host and guest renderer status are
reported separately.

替代内核模式已验证双屏 AMD VirGL 加速，仪表通过 VirtualGL 共用 GPU。构建与启动见
[虚拟桌面说明](virtual-desktop.md)。以下保留原厂内核路线的排查结果。

## Original-kernel diagnostic findings

| Layer | Verified on September 16, 2026 |
| --- | --- |
| Windows | AMD Radeon driver installed and reported healthy. |
| Debian WSLg | Mesa D3D12 driver and `/dev/dxg` available. Default shell rendering used llvmpipe; explicit D3D12/AMD selection used the Radeon GPU. |
| Actual host rendering | `glxinfo` reported acceleration and OpenGL 4.6. A short `glxgears` run rendered 594 frames in 5 seconds using `D3D12 (AMD Radeon(TM) Graphics)`. This simple test is not a firmware performance benchmark. |
| MCU2 guest kernel | `5.4.302-PLK` has i915 as a module, no AMDGPU configuration, and enforced module signatures. Its extracted kernel hash still matches the original firmware payload. |
| Firmware modules | i915 is present; no matching AMDGPU kernel module was found in the inspected image or project files. The existing `libdrm_amdgpu.so` is a userspace library. |
| Original-kernel VM graphics | The vendor-kernel diagnostic has VGA, not a usable Radeon GPU or the WSLg `/dev/dxg` interface. Its firmware graphics remain unavailable. |

## Application-scoped AMD selection

From the repository directory inside Debian WSL:

```sh
python3 -m infotainment_lab.host_graphics AMD
```

The command first checks the actual accelerated renderer. Only a successful
match saves `graphics.json` in the Linux user's application data directory.
A software renderer or a different adapter leaves the previous selection intact.
Future native sessions, WSL Qt launches and QEMU host windows use the saved
selection. This does not change Windows drivers, global shell configuration,
guest kernel parameters or firmware files. The vendor-kernel check's VGA configuration
does not gain guest 3D acceleration from the host selection.

Microsoft documents WSLg's D3D12 adapter selection in its
[GPU selection guide](https://github.com/microsoft/wslg/wiki/GPU-selection-in-WSLg).

## Remaining requirements

Loading AMD support into the unchanged guest kernel requires a module built
for its ABI and dependencies, with a signature accepted by that kernel, plus a
compatible GPU device exposed to the guest. The kernel's signature enforcement
accepts only modules signed by a trusted key; adding a generic Debian driver
package does not satisfy that requirement. See the official
[kernel module signing documentation](https://www.kernel.org/doc/html/v5.15/admin-guide/module-signing.html).

The current firmware X startup also explicitly loads i915 and waits for DRM
card0. Host AMD rendering alone cannot complete that startup or establish
equivalent browser, audio, camera and dual-display functionality in the VM.

### Device and upstream-source checks

The installed QEMU exposes `ati-vga`, but its source identifies the emulated
models as Rage 128 Pro and RV100, initially targeting 2D. This is not a modern
AMDGPU device. The inspected firmware disables the legacy Radeon driver as
well. Choosing that device does not fill the guest's AMDGPU/3D gap.

This Debian WSL instance has no IOMMU groups or numbered VFIO device nodes.
Its two PCI display devices have Microsoft vendor ID `1414` and use `dxgkrnl`.
No host AMD PCI device is currently available there for VFIO passthrough.
These are observations of this machine, not a claim about every Linux host.

Tesla's official Linux repository does contain an `amd-5.4` branch. The checked
head was `a3b2ab966b1c8dc105c49d3fb41950c023c0c844`; its
[Makefile](https://github.com/teslamotors/linux/blob/a3b2ab966b1c8dc105c49d3fb41950c023c0c844/Makefile)
declares version **5.4.265**, while the current MCU2 kernel is **5.4.302-PLK**.
Its [INFOZ configuration](https://github.com/teslamotors/linux/blob/a3b2ab966b1c8dc105c49d3fb41950c023c0c844/arch/x86/configs/infoz_defconfig)
enables AMDGPU modules and enforced signatures. This is useful official source
material, but it is not a verified compatible, trusted binary module for the
current guest. That original-kernel audit did not replace its kernel. A separately authorized virtual-hardware VM now uses a Debian kernel.

## 中文

最新要求已允许更换内核；原厂内核诊断模式单独保留。主机端 AMD 驱动已经具备，问题在于默认 Mesa 环境使用 CPU 软件渲染；项目现已加入验证后保存 AMD 选择的流程，并通过真实 OpenGL 渲染验证。设置仅作用于本应用，后续启动生效。

原厂内核诊断客体仍未获得 AMD 加速：该内核未启用 AMDGPU、强制验证模块签名，镜像中也没有匹配的 AMDGPU 内核模块；该模式的虚拟设备不提供可用的 Radeon GPU。工作目录中的 `libdrm_amdgpu.so` 是用户态库，不能替代内核模块。

## Virtual-hardware kernel experiment / 虚拟硬件内核实验

The replacement-kernel QEMU
VM boots Debian `7.1.8+deb13-amd64` with matching modules, VirtIO graphics,
network and storage, and HDA audio. This is a packaged kernel, not a locally
compiled Tesla kernel. The firmware is attached read-only.

Guest `glxinfo -B` reports **Accelerated: yes** and
`virgl (D3D12 (AMD Radeon(TM) Graphics))`, OpenGL 4.2. Guest HTTPS returned 200;
PulseAudio enumerated the HDA output. SDL on X11 provides two native windows
showing the actual firmware UI. Guest browser and host QEMU audio streams were
observed during a browser tone test. The managed WSLg audio route now passes
two 30-second plays, a 120-second play and browser idle/resume checks with no
output-queue drops; extended streaming sessions remain unverified.

Nested Xephyr fell back to llvmpipe. Direct, independent Xorg servers now provide
the center and instrument displays. Kernel 7.1 also supplies the Unix socket
AppArmor peer labeling used by the existing local service profiles. Actual
service peer matches and the firmware browser card have been observed. The
instrument window now uses VirtualGL to share the accelerated center GPU. The
actual firmware visualization log also reports the AMD-backed VirGL renderer;
complete feature parity remains under validation.

客体已验证 AMD 经 VirGL 提供 OpenGL 4.2 加速、HTTPS 联网及 HDA 设备枚举。
原生 QEMU 双窗口已显示车机与浏览器卡片。双屏加速已验证；长时间流媒体播放和
摄像头等完整功能等效仍需验证。
