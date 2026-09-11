# Changelog

## 0.4.2 — 2026-09-10

- Added a local vehicle-alarm state and publishes the firmware's native `VAPI_alarmStatus` as `Disarmed` by default. The previous invalid value blocked the normal Service Mode access-code flow.
- Confirmed the real MCU2 center display enters Service Mode after entering the normal code; no access-code, gateway or authentication check is patched.
- Made Service Mode a center-owned display channel. The instrument cluster receives enter/exit state and renders its native Service Mode overlay.
- Added a vehicle-alarm toggle to the Doors page for armed-state UI testing. It affects only this application's private display services and never sends a disarm request to vehicle hardware.
- Full diagnostic gateway services and Service Mode Plus remain unavailable in the local lab.

### 中文

- 增加本地车辆报警状态，默认向固件发布原生 `VAPI_alarmStatus=Disarmed`，修复无效状态阻止正常进入 Service Mode 的问题。
- 已在真实运行的 MCU2 中控验证正常输入代码后进入 Service Mode；没有修改访问码、网关或认证检查。
- Service Mode 状态由中控同步到仪表，仪表显示原生 Service Mode 画面；车门页可切换本地报警布防状态。
- 该状态只存在于应用私有显示服务，不会向真实车辆发送解除报警命令；完整诊断网关和 Service Mode Plus 仍不可用。

## 0.4.1 — 2026-09-10

- Fixed striped and scrambled native text by restoring OpenGL unpack alignment after each 3D texture upload, including failed uploads.
- Resolve center, cluster and firmware browser fonts from the selected image, with a private font cache and the supplied CJK selection rules. No firmware fonts are bundled or installed into the host.
- Added steering-wheel volume hold/repeat with release and focus-loss cancellation; corrected shared left/right/hazard indicator phases.
- Connected six door/trunk position flags to both displays and the native 3D view. Center lock/unlock and supported closure requests update the local model.
- Added Off, Parking, On and Auto light modes, a simulated dark environment, and consistent manual-light controls.
- Expanded Santa/theme/wheel preference synchronization and center-to-cluster playback metadata. Added native media process recovery, connection diagnostics and the scoped media-browser environment.
- Updated English and Mandarin setup instructions: users must supply their own compatible Firmware Dump. Firmware, extraction tools and dump/export tutorials are not provided.
- Still unresolved: native Spotify login/playback and complete media-service confinement. Service Mode manual entry remains unverified. This update does not add physical vehicle or cloud services.

### 中文

- 修复 3D 纹理上传后引起的文字花字，中控、仪表和固件浏览器从当前固件读取字体，字体缓存独立保存。
- 补齐方向盘音量长按、转向灯闪烁、六个车门／备箱位置、锁车请求和四种灯光模式的本地同步。
- 改进 Santa 与偏好同步、播放信息转发、媒体服务恢复及错误诊断。
- 明确需要用户自备 Firmware Dump；不提供固件、提取工具或导出教程。
- Spotify 原生登录／播放和完整服务隔离仍未修复，Service Mode 手动入口尚未验证。

## 0.4.0 — 2026-09-09

- Added native Browser, Card view and Theater controls with separate Chromium runtime profiles.
- Corrected embedded pointer coordinates, drag capture, wheel delivery and physical keyboard routing.
- Connected embedded dashcam driving data to the same clock as the camera video, with pause, seek, playback speed, looping and manual takeover. Reopening a session holds the preview in Park until Play.
- Added local climate, body, lights, energy, audio and navigation controls with per-field firmware readback. Both displays share driving data and reconcile supported preferences in either direction.
- Added bilingual control pages, replay and X11 integration tests, and a generator for a clearly labelled public demo recording.

## 0.3.0 — 2026-09-09

- Connected the existing RGB24/V4L2 pipeline to the firmware's native backup-camera view.
- Camera source controls for a steering-linked pattern, looping local video and an existing writer output.
- Measured producer and firmware frame consumption, stale-source handling and stop/recovery controls.
- Shared source preview and separate window; camera playback continues with the device when the control panel closes.
- Verified 24 fps pattern/video input, original writer compatibility, and Reverse opening the firmware camera.

## 0.2.1 — 2026-09-09

- Double-click Windows launcher for the native Linux GUI, included with the Linux bundle.
- Direct WSLg desktop and Start-menu shortcut installer, startup logs and visible launch errors.
- Reopening the application activates its existing control panel; smaller windows can scroll.
- Corrected desktop application identity and simplified compatibility wording in both READMEs.

## 0.2.0 — 2026-09-09

- Emulator-style device manager with searchable firmware entries and per-device launch preferences.
- Actual center and instrument display captures in a five-second overview.
- Native toolbar for display focus, restart, PNG capture, controls and camera.
- Preflight launch gating, guided setup, persistent errors and busy indicators.
- Scrollable layouts, keyboard shortcuts, matching English/Mandarin documentation and refreshed screenshots.

## 0.1.0 — 2026-09-09

- Native Qt workbench with English and Mandarin interfaces.
- Local firmware library with drag and drop, build checks and read-only mounts.
- Standalone MCU2 center/instrument session with AMD WSLg graphics and embedded Chromium.
- Private display simulator for gear, speed, pedals, steering and turn signals.
- Camera pattern/local video preview, process diagnostics and sanitized report export.
- Native Linux and optional Windows/WSL packaging.

Known gaps at 0.1.0: firmware camera integration, map routing/imagery, theater/card browser modes, embedded drag/clipboard behavior, and complete vehicle-service emulation. See the READMEs for the current scope.
