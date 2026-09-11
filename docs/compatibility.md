# Compatibility · 兼容性

This matrix describes version **0.4.2** and the local configuration used for
validation. An imported image's build profile determines whether it can launch.
The library can inspect images beyond the currently supported launch profile.

此表描述 **0.4.2** 及本地验证环境。设备库可检查更多镜像，但能否启动取决于
是否存在匹配的构建适配。

## Host and firmware

| Component | Status |
| --- | --- |
| Windows 11 + WSL2 + Debian 13 + WSLg | Tested native Linux GUI and device runtime. |
| Physical x86_64 Linux | Launch path implemented; not validated on a separate physical host. Requires X11/XWayland, systemd user services and FUSE. |
| Optional native Windows control panel | Uses the same Debian WSL backend; this is not a Windows firmware runtime. |
| AMD Radeon / Mesa D3D12 | Observed accelerated renderer on the tested WSLg host. Other GPU configurations remain unverified. |
| Native fonts | Both Qt displays load Universal Sans from the selected firmware; Fontconfig uses an image-specific font directory and private cache. CJK selection uses the supplied image's rules. |
| `2026.26.6.1` Model S/X MCU2 (`modelsx_info2`) | Supported exact launch profile, with center display and instrument cluster. |
| Other firmware builds | Image inspection available; no compatibility claim or automatic fallback to the tested profile. |
| Maps | A supplied NA image can be inspected/mounted. A street base map rendered after valid replay GPS, in a session without an offline map mounted. Offline NA imagery and routing remain unverified. |
| Locally built Debian 13 executable | Built and tested with glibc 2.41; older glibc versions remain unverified. Source launch is available; CI is configured for Ubuntu 22.04. |

The launch profile is recorded in the application's `profiles.json`:

| Binary | Accepted build ID |
| --- | --- |
| Center display | `6e5be629ea4c0546bc157c9ac6c5bd323b888ba7` |
| Instrument display | `b568abe1e320808c6131ae95bcffed7736762aae` |

The MCU2 visualization uses the supplied Godot application. Renderer information
comes from the actual host graphics stack. No frame-rate or input-latency guarantee
is made for other systems.

## Browser and desktop integration

| Feature | Verified scope | Limit |
| --- | --- | --- |
| Browser | HTTP/HTTPS pages inside the firmware center UI; pointer, keyboard, scrolling, WebGL and audio path | Web application behavior varies; not all sites are tested. |
| Card view | Native compact view, resizing and browser interaction; shares the visible Browser app/profile | Does not imply every firmware card application is implemented. |
| Theater | Firmware catalog and YouTube home page | Commercial streaming, DRM playback, account-dependent flows and all catalog apps remain unverified. |
| Dragging | Embedded page receives motion and a release; draggable tile and range slider exercised at native scale | No universal claim for every website gesture. |
| Audio | Firmware stream routing and volume/mute control on the host | Physical DSP, microphone/telephony and subjective playback quality are not modeled. |
| Native music card | Dedicated media web app, ChromiumApp, adapter and Spotify processes run; Spotify SDK reports connectivity | Native service security-context rejection still prevents Spotify login/playback. |
| Multiple windows | Center, instruments, panel and optional camera preview | Each firmware view remains a separate desktop window; the device overview is view-only. |

Clipboard integration is not included in this release.

## Camera and recorded driving data

| Feature | Verified scope | Limit |
| --- | --- | --- |
| Camera source | Pattern, local H.264 video and existing 1280×720 RGB24 output through the native camera input | Only the native backup-camera view is validated. |
| Feed health | Independent fresh-source and actual V4L2-consumption measurements | An open producer alone does not mean the firmware is consuming frames. |
| Dashcam parser | Local H.264 MP4 with the project's embedded SEI telemetry fields and MP4 presentation timestamps | Maximum 8 GiB, two hours and 300,000 video packets per selected clip. |
| Playback | Pause, seek, rate, loop/end and manual ownership | One selected camera view at a time. |
| Shared driving data | Gear, speed, accelerator, brake, steering and signals follow the committed video frame | Brake is a pressed/released flag. Speed and pedals do not form a vehicle physics model. |
| Location | Valid recorded GPS/heading delivered to both local display services | Accuracy is the recording's; no real GPS hardware or live route engine is connected. |
| Recorded assistance state | Retained for inspection | Does not activate a driving-assistance controller. |

Generate a public sample from source with `python3 scripts/make-replay-demo.py`.
The resulting `build/replay-demo.mp4` contains 12 seconds and 288 embedded samples,
with synthetic graphics and no GPS location. It requires FFmpeg with libx264 and
drawtext. See [replay documentation](replay.md).

## Vehicle services and synchronization

| Domain | Local behavior | Limit |
| --- | --- | --- |
| Climate | Native requests, shared temperatures, fan, A/C and defrost request | Supplied state; no thermal or compressor physics. |
| Closures | Six independent door/trunk positions in both displays and the native 3D view; center lock/unlock and supported closure requests update the local model | No physical actuators; unsupported native request types are not executed. |
| Lights | Off, Parking, On and Auto with simulated ambient darkness; shared headlight/high-beam/parking indicators | No physical lamps. |
| Energy | Battery, charge limit, charging state and power | No battery model or charging equipment. |
| Audio | Shared volume/mute and host audio-stream control | Only the mounted firmware's streams are adjusted. |
| Navigation | Supplied GPS, heading, destination label and remaining trip metadata; street base map observed after valid replay GPS | Offline NA imagery, route computation and live traffic remain unverified. |
| Tires | Four editable local pressure values | Native TPMS units remain unverified; pressure is not injected. |
| Driving state | Same local inputs sent to both displays, with readback | Does not recreate the complete vehicle IPC graph. |
| Preferences | Santa, supported theme/wheel and unit/audio preferences; center-owned playback metadata forwarded to instruments | The current default session reports 23 shared values; unsupported fields remain in diagnostics. |
| Service Mode | Native center entry through the normal access-code flow; enter/exit state forwarded to the instrument cluster | Complete diagnostic gateway services and Service Mode Plus are not implemented. |
| Vehicle/cloud-only services | Capability report lists unavailable domains | Physical ECU/CAN, powertrain, cellular provisioning, accounts, phone keys, payments and remote services are not connected. |

“Applied” means the display read back the intended value. Unsupported, rejected,
partial and mismatched values remain distinct. See [service details](vehicle-services.md)
and the [validation record](VALIDATION.md).

## 中文范围说明

已验证的是 Windows 11／WSL2 Debian 13／WSLg、AMD Radeon D3D12，以及
`2026.26.6.1` MCU2 双屏适配。独立 Linux、其他显卡和其他固件构建尚未做同等验证。

浏览器与卡片交互、影院目录和 YouTube 首页已通过固件内验证；商业视频、DRM、
账号和全部目录应用没有因此被视为可用。本版本不包含剪贴板集成。回放使用选中视频
的真实时间戳，每次一个视角；公开演示片可自行生成，不含道路录像或 GPS。

车辆服务提供本地显示数据和部分请求反馈，逐项报告固件是否回读成功。它不等同于
完整实车 IPC、真实硬件或云服务。已看到有效回放 GPS 对应的街道底图，但离线
NA 图包的使用和路线服务仍未验证。实体 TPMS、账号和支付等未连接能力保留明确状态。
