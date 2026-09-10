# Dashcam replay / 行车记录回放

Select a local Tesla dashcam MP4 with embedded driving data in the Replay panel.
The camera pipeline decodes the selected view and sends RGB24 frames to the
firmware camera input. Driving data follows the same decoded video frame:
gear, speed, accelerator position, brake, steering angle and turn signals.

在回放面板选择带有内嵌行驶数据的本地 Tesla 行车记录 MP4。摄像头管线解码
所选视角，将 RGB24 画面送入固件摄像头输入；挡位、车速、油门、刹车、方向盘
角度和转向灯按照同一视频时钟回放。

Use Play, Pause and the timeline to move through the recording. Playback speed
ranges from 0.25× to 2×, and Loop restarts the clip at the end. Pause holds both
the image and driving data. Seeking decodes a new frame before changing the
vehicle inputs. If decoding falls behind, data slows with the video.

Reopening a device restores a still preview of the previous recording and keeps
the simulator parked. Press Play to resume driving-data input; seeking or
adjusting playback options alone does not take control.

播放、暂停和时间轴控制画面与数据；支持 0.25×–2× 倍速和循环。暂停时保留
当前画面与行驶数据。跳转后先解码目标画面，再更新车机输入；解码变慢时，
数据也会随画面减速，避免提前播放。

重新启动设备时保留上一段录像的静态预览，模拟器仍保持 P 挡。按下播放后才会
恢复行驶数据输入；仅跳转时间或调整回放选项不会接管车辆输入。

Manual takeover releases the recording's control of the simulator immediately.
Changing a manual vehicle control also takes over. A separate ordinary camera
video continues playing when manual controls are used. Press Play in Replay to
resume the recording's inputs.

手动接管会立即停止录制数据控制模拟器；调整任一手动车辆输入也会接管。
普通摄像头视频不会因此停止。在回放面板重新播放即可恢复录制数据输入。

The original GPS position, heading, acceleration and recorded assistance-state
code remain available as recording metadata. A recorded assistance state does
not activate driving assistance. Display acceptance and readback are reported
separately from decoding. The firmware camera page must be visible to see the
video; a drive recording does not automatically change the recorded gear to R.

原始 GPS、航向、加速度及录制时的辅助驾驶状态码保留为录制元数据。辅助驾驶
状态码不会启动辅助驾驶功能。数据解码与双屏接收、回读结果分别显示。观看视频
时需要打开固件摄像头页面；回放不会为了显示摄像头而把录制的 D 挡改成 R 挡。

## Supported recordings

- Local H.264 MP4 clips containing the project's Tesla SEI telemetry fields.
- Up to 8 GiB, two hours and 300,000 video packets per clip.
- Source timestamps come from the MP4 packet index, including variable frame
  intervals; frame sequence numbers are retained as metadata.
- One selected camera view at a time. Select front, back or a repeater recording
  from the same event as needed.
- The six simulator values retain the same range limits as manual controls.
  The brake field records a pressed/released flag rather than brake pressure.

支持带有本项目识别的 Tesla SEI 数据字段的本地 H.264 MP4；单段上限为
8 GiB、两小时、300,000 个视频包。时间来自 MP4 实际时间戳，兼容可变帧间隔。
每次播放一个视角；可选择同一事件的前、后或侧摄像头录像。六项模拟输入采用
与手动控制相同的范围限制，刹车数据为踩下/松开标记。

## Local integration

`replay_source(path, rate=1.0, loop=True, autoplay=True)` creates the camera-source
configuration. Session restoration sets `autoplay=False`: the worker decodes a
preview, enters `ready`, and waits for an explicit Play command before writing
driving controls. `controls_active` in status reports ownership independently of
the available preview; `replay_id` identifies the selection and
`decoded_frame_index` identifies its current decoder segment frame.
`replay_request(action, **values)` validates playback commands and assigns an ID.
Commands carry an `issued_at` timestamp so a manual input received after selecting
a recording is honored even while its decoder is still starting. Older commands
do not restart playback when a device is reopened.
The Linux camera worker reads `camera-source.json` and `replay-request.json`,
writes `camera/back.rgb`, then publishes the corresponding `controls.json`.
`replay-status.json` includes the video position, sample count, current controls,
recorded metadata and command acknowledgement. A false `frame_ready` value means
the decoder has not produced the requested frame yet.

`manual_takeover(state, controls=None)` shares an advisory lock with the replay
writer. It prevents an in-flight frame from overwriting a later manual command.
The API only writes local session files; the display bridge uses the session's
private D-Bus. It contains no connection to a real vehicle.

Recordings and their GPS metadata stay in the local session and are excluded
from the public diagnostic report. Do not include personal recordings or live
metadata in repository screenshots or releases.

## Verification

Parser and control tests cover the SEI field mapping, variable frame timestamps,
bounded reads, seek/pause/rate transitions and manual ownership. Local playback
was also checked against all four supplied camera clips from one event. The
rear clip contains 2,117 telemetry samples across 60.1085 seconds. Actual FFmpeg
tests exercised RGB output, pause, seek, rate changes, loop, end-of-file, manual
takeover and returning to an ordinary camera video.
