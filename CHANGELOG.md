# Changelog

## 0.5.0 — 2026-09-16 · Material desktop and QEMU

- Removed the upper-left wordmark from both expanded and compact control-panel navigation.

- Added an experimental replacement-kernel QEMU desktop with a Debian guest builder, read-only firmware attachment, native dual windows, AMD-backed VirGL on both displays and VirtualGL GPU sharing for the independent instrument window. Added managed start, shutdown, guest simulation controls, per-display graphics reporting and stale-heartbeat rejection.
- Connected the Qt panel to QEMU: saved engine/directory selection, dual previews, display focus, browser cards, vehicle inputs, selected media import, live RGB relay and embedded-telemetry replay. Guest requests are serialized and stale responses from a previous mode are ignored. Full feature parity remains unfinished.
- Added buffered, on-demand WSLg audio with VM-owned cleanup, bounded queues and output diagnostics. Verified two 30-second plays and one 120-second play, firmware Chromium sound, idle/resume and Qt stop/start; long-session streaming remains unverified. Native Linux retains its existing desktop sound server.
- Publish the firmware's speed-unit signal together with converted speed, fixing MPH values incorrectly labeled km/h on the instruments.
- Corrected symbolic direction-enum readback so accepted gear inputs no longer report a false partial failure. Paused and ended recordings retain their last camera frame while the producer heartbeat remains healthy.

- Restyled all seven native Qt pages with Material 3 inspired tonal cards, a shared color system, filled actions, switches, tabs and keyboard focus indicators.
- Added saved system/light/dark appearance and Iris, Blue and Leaf accents. Switching appearance preserves the current page, driving controls and unapplied form edits.
- Replaced the duplicate right navigation strip with contextual display actions in the app bar. Narrow windows use an icon rail with an appearance/language menu.
- The display overview fits actual capture proportions and supports the single-screen ICE profile. Device descriptions wrap, camera actions fit a compact grid, and empty previews explain their next step.
- Closing the panel cancels delayed environment checks and polling, preventing work from starting after its window is gone.
- Added text contrast checks and theme interaction tests. Windows Qt and Debian WSLg native rendering were reviewed in English and Simplified Chinese. QEMU desktop parity remains under development.
- Added verified, application-scoped AMD/NVIDIA/Intel selection for WSLg. A failed hardware-rendering check preserves the previous setting; host acceleration is reported separately from firmware-VM graphics.

### 中文

- 移除控制面板左上角标识，宽屏和紧凑导航均不再显示。

- 新增实验性替代内核 QEMU 桌面：Debian 客体构建器、固件只读挂载、原生双窗口、双屏 AMD VirGL 加速及仪表独立窗口的 VirtualGL GPU 共享；加入启动、正常关机、本地模拟控制、分屏渲染器报告和过期状态检测。
- Qt 面板接入 QEMU 模式：保存模式和目录、双屏预览、窗口聚焦、浏览器卡片、车辆输入、视频导入、实时 RGB 管线及内嵌行驶数据回放；客体请求串行处理，忽略旧模式的延迟响应。完整功能等效仍待完成。
- WSLg 音频新增缓冲和按需输出，随虚拟机清理进程，并记录队列丢弃数据；已验证两次 30 秒和一次 120 秒播放、车机内 Chromium 声音、静音后恢复及 Qt 停止／启动。长时间流媒体播放尚未验证；原生 Linux 沿用现有音频服务。
- 同步发送车速单位信号与转换后的数值，修复仪表将 MPH 数值标成 km/h 的问题。
- 修复方向枚举回读导致挡位误报部分失败的问题；回放暂停或结束后，在生产进程心跳正常时保留最后摄像头帧。

- 七个原生 Qt 页面统一采用 Material 3 风格，包含分层卡片、语义配色、主操作按钮、开关、标签页和键盘焦点提示。
- 新增跟随系统、浅色、深色外观，以及鸢尾紫、晴空蓝、叶绿强调色；设置自动保存，切换主题保留当前页面、驾驶控制与未提交表单。
- 显示窗口快捷操作移至顶部，窄窗口使用图标导航栏，并可从菜单调整外观与语言。
- 屏幕预览按真实截图比例显示，适配 ICE 单屏；设备说明自动换行，摄像头操作重新分组，空画面提供明确提示。
- 增加文字对比度与主题交互测试，并检查 Windows Qt / Debian WSLg 下的中英文原生渲染。QEMU 的桌面效果一致性仍在开发中。
- 新增 WSLg 的 AMD/NVIDIA/Intel 渲染器选择，实测硬件加速成功后才保存；失败时保留旧设置，并明确区分主机加速与固件虚拟机图形支持。

## 0.4.4 — 2026-09-10

- Fixed the native media card remaining at `Audio Initializing` by publishing `GUI_audioReady=true`, a valid `Base` audio type and a cleared Service Mode audio-reset state to both displays.
- Starts QtCar, QtCarCluster, SpotifyServer and ChromiumAdapter with the AppArmor peer names required by the firmware.
- Added persistent Debian/WSL AppArmor policy installation to Runtime Setup and verified successful SpotifyServer and ChromiumAdapter peer matches after restart.
- Native media health now reaches `services-running`; WSLg volume and mute routing remain connected to both displays.
- Added the GStreamer playback runtime and firmware ALSA aliases used by Toybox and chime fallbacks, including `fart`, so enabling audio readiness no longer exposes a missing playback executable or device.
- Connected replay motion to native ApViz with signed speed, playback gear, road-wheel angle and calculated yaw rate; Model X steering and forward/reverse animation now follow the committed camera frame, with the firmware road-wheel convention applied to reverse-camera guide lines.

### 中文

- 修复原生媒体卡片停留在 `Audio Initializing`：向中控和仪表发布 `GUI_audioReady=true`、有效的 `Base` 音响类型，并清除 Service Mode 音频重置状态。
- QtCar、QtCarCluster、SpotifyServer 和 ChromiumAdapter 现在以固件要求的 AppArmor peer 名称启动。
- 将持久化 Debian/WSL AppArmor profile 安装接入“运行环境安装”，重启后已验证 SpotifyServer 和 ChromiumAdapter 安全标签匹配成功。
- 原生媒体健康状态现为 `services-running`，WSLg 音量与静音仍与中控、仪表同步。
- 补齐 Toybox 和提示音回退路径所需的 GStreamer 运行环境及 `fart` 等固件 ALSA 设备别名，避免音频就绪后调用缺失的播放器或设备。
- 将回放运动数据接入原生 ApViz：发布带方向车速、回放挡位、路轮角和计算后的横摆角速度，使 Model X 转向及前进/倒车动画跟随已提交的摄像头帧，并按固件路轮角约定修正倒车轨迹线方向。

## 0.4.3 — 2026-09-10

- Added a persistent Model X MCU2 vehicle profile and applies it to both display services whenever they start.
- Selected the newest meaningful values exposed by the 2026.26.6.1 services: P100D trim, Tesla adaptive suspension, TeslaAP3 driver assistance, permanent-magnet front drive unit, SEMCO backup camera, Valeo5 park assist, Model X radar placement, fold-flat restraints and 21-inch Twin Turbine wheels.
- Added per-signal application results to runtime feedback, so unsupported or rejected profile values are visible instead of silently ignored.
- Connected exterior color, interior trim and dual-motor state to the native 3D ego model; the model now receives the same profile as both displays.
- Verified all 32 profile signals on both center and instrument displays after a clean runtime restart.

### 中文

- 新增持久化 Model X MCU2 车辆配置，中控和仪表服务每次启动时都会自动应用。
- 按 2026.26.6.1 服务提供的有效枚举选择较新配置，包括 P100D、TeslaAdaptive 悬架、TeslaAP3、永磁前电机、SEMCO 倒车摄像头、Valeo5 泊车辅助、Model X 雷达位置、可折叠后排约束系统和 21 英寸 Twin Turbine 轮毂。
- 补齐车漆、内饰和双电机状态到原生 3D 车模的联动；运行状态记录每项接受结果，干净重启后验证中控和仪表两端各 32 项全部接受。

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
