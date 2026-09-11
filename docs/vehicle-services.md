# Local vehicle services and display synchronization

The Services page supplies a shared local vehicle model to the center and
instrument displays. Both displays receive the same battery, climate and
driving state. Native climate and audio controls feed changes back into this
model, so changing temperature or volume inside the firmware updates the
desktop controls as well.

The model is a desktop simulation. It does not communicate with a vehicle.

| Domain | Local behavior | Practical limit |
| --- | --- | --- |
| Climate | Power, driver/passenger set points, cabin/outside temperature, fan, A/C and rear defrost request | Temperatures are supplied values; no thermal physics or compressor is running. |
| Closures | Individual positions for all four doors and both trunks, native Open/Lock/Unlock requests, and shared lock status | Native instrument 3D opening/closing is verified. Physical latches and powered-actuator timing are not modeled. |
| Lights | Off, Parking, On and Auto, headlight/high-beam and parking-light indicators | Auto uses the local Dark outside input. No physical lamps are controlled. |
| Energy | Battery percentage, charging state, power and charge limit | Charging does not increment the battery automatically. |
| Audio | Volume and mute synchronize across the two displays and firmware audio streams | Only audio streams whose executable belongs to the mounted firmware are changed. |
| Navigation | Supplied GPS, heading, destination label, remaining distance and time; street base map observed after valid replay GPS | Offline NA imagery, route computation and live traffic remain unverified. |
| Tire pressures | Four editable pressure values in the local model | Native TPMS units have not been verified, so these values are not injected into native TPMS fields. |
| Dashcam | Fresh GPS/heading follow the decoded video frame, alongside the six driving controls | Recorded driver-assistance and acceleration values remain metadata. |

Physical ECU/CAN services, drivetrain controllers, cellular provisioning, Tesla
accounts, phone keys, charging equipment, payments and cloud-only services are
not connected. Their status is listed as unavailable in the capability report.

## Delivery and acknowledgements

The backend validates changes with `VehicleServices.parse()` and atomically
writes `session/vehicle-services.json`. The runtime consumes new file versions,
applies existing fields on each private display, and reads the values back.
`session/vehicle-services-feedback.json` contains:

- `state` and `requested`: the current shared model, including accepted native
  climate/audio request changes.
- `firmware`: an acknowledgement for each field and display.
- `signals`: the individual native fields behind those acknowledgements.
- `source`: `desktop`, `native-ui` or initial `defaults`.
- `gps_source`, `capabilities`, `errors` and `updated_at`.
- `body_requests`: consumption and acknowledgement of native momentary requests.

The native display's door-position flags are supplied together, so changing one
door preserves the remaining doors. Its named readback is converted to the same
mask for verification. Momentary native requests are consumed once and reset
to None; a failed acknowledgement is retried without toggling a trunk again.
Pending commands from before connection are cleared without executing them.

Exterior-light mode synchronizes from the native selector and desktop panel.
The legacy Headlights checkbox is a manual override selecting On or Off. In
Auto, Dark outside determines whether the headlights and parking lights are on.

## Service Mode

The desktop Services page includes the normal touchscreen entry instructions
and a button to focus the center display. It does not force diagnostic access
or simulate successful vehicle service routines. Native Service Mode entry has
not yet been verified in this session. Use Controls → Software, hold MODEL for
two seconds and enter the public service code in the native prompt; exit through
the native Exit Service Mode control. This is the touchscreen procedure in
[Tesla's Model S service manual](https://service.tesla.com/docs/ModelS/ServiceManual/en-au/air/GUID-0DC534D7-A4B8-417F-8E42-DF1560E970C2.html).

During replay, the service model retains manually entered location values.
The active recording's GPS/heading are in `replay-status.json`, and `gps_source`
identifies which input is being delivered. Take over from replay before using
manual location changes to drive the display.

`accepted` means the native DataValue interface read back the requested value.
It does not prove a physical service or every animation is implemented.
`partial`, `unsupported`, `rejected` and `mismatch` retain the distinction between
stored simulator values and native display support. `local-model` identifies
values that are intentionally stored only in the desktop model.

The driving worker checks changed controls every 50 ms. Unchanged frames make
no control bus calls; periodic verification detects overwritten values and
display restarts. Host Internet and disk measurements run separately every
30 seconds. The control feedback records the target tick and measured apply
duration so a slow desktop can be diagnosed without assuming a fixed frame rate.

## Two-display preferences

Distance, temperature, charge and tire-pressure units, volume/mute, navigation
and response volume, timezone and available clock-format fields synchronize in
both directions. A change on either display updates its peer. If both displays
change the same field between polls, the center display wins; the report marks
the conflict. A restarted display receives its live peer's values.

The source update adds Santa mode (`GUI_HoHoHoMode`), its cheer setting,
supported day/theme options and steering-wheel preferences. Santa is mirrored
both when enabled and disabled. Playback title, artist, album, elapsed/duration,
source and status travel from center to instruments. The instruments cannot
overwrite the player's state; empty metadata clears the previous text. A failed
field is reported separately and does not stop the remaining channels.

The Controls page provides native media and instrument-panel button actions.
Consecutive volume presses use the latest pending request until the worker
acknowledges its file version, so rapid presses do not reuse stale feedback.
Volume buttons repeat after a 450 ms hold and then every 180 ms, subject to
backend completion. The UI does not queue repeats behind a pending request.
Release, pointer leave, focus loss, hiding or disabling the button cancels
repetition. Other actions fire once per press to avoid repeatedly toggling mute.
An accepted button command does not assert that a logged-out player started
playing or that a physical steering-wheel switch was connected.

Turn signals publish both intent booleans and the native `VAPI_turnSignalActive`
enum (`Off`, `Left`, `Right`, `Both`). The two `LIGHT_turnIndicator*` fields use
`On`/`Off` values with a shared monotonic clock: 400 ms on, 400 ms off. The active
direction remains selected throughout blinking. These fields are delivered to
both displays; individual D-Bus writes are not an atomic multi-display update.

`session/display-link.json` records each field's source, both observed values,
delivery/readback result, connected displays and routed audio streams. Unsupported
clock-format fields are listed explicitly instead of being counted as synchronized.

Driving speed is supplied in km/h through the desktop API. The native vehicle
speed remains metres per second; the displayed number follows each display's
Miles or Kilometers preference and is explicitly rounded to the native integer
display-speed field. Floating readback allows only half of the interface's
final rendered decimal digit.

## Validation

On the local `2026.26.6.1` MCU2 session, both native displays read back changed
driver/passenger temperature, fan speed, cabin temperature, battery percentage,
charging state/power and the headlight telltale. A native climate request updated
the shared model and the other display. Distance-unit changes propagated in both
directions. The check restored the original model and kept the simulator parked.

Eight preference fields have populated values in this session. The two timezone
fields are registered but initially unset; the two clock-format names are absent.
Absent fields are queried once per display process, then cached until that
display restarts. This avoids repeatedly adding unsupported-field messages to
the firmware logs.

## 中文说明

“车辆服务”页面向中控和仪表提供同一份本地模拟数据，包括空调、车门提示、
灯光、电量、充电、音量和导航元数据。在固件内调整空调温度或音量，也会更新
桌面控制面板。两屏的单位、音量、时区等可用偏好双向同步；同时发生冲突时，
以中控为准，并记录冲突。

源码更新增加 Santa 开关、相关主题与方向盘偏好同步。播放曲目、进度和状态由
中控单向传给仪表，清空内容也会同步。方向盘按钮调用原生媒体和仪表面板接口；
连续音量按键会保留尚未回报的最新输入。

“已接收”表示固件本地数据接口回读了写入值，不等于接通真实硬件服务。
车门目前提供打开提示和锁定状态，逐门 3D 锁扣动画仍未验证；胎压目前仅保存在
本地模型中。地图路线计算、实时路况、真实 ECU/CAN、账户、手机钥匙、蜂窝开通、
支付和云服务不在此本地模拟中运行。

行车记录仪回放按实际解码的视频帧同步位置、航向及驾驶控制数据。回放暂停、
跳转和手动接管会改变数据来源；录制的辅助驾驶状态只作为元数据显示，不启动
辅助驾驶控制器。
