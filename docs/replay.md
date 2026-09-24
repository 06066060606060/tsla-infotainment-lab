# Dashcam replay

Select a local Tesla dashcam MP4 with embedded driving data in the Replay panel.
The camera pipeline decodes the selected view and sends RGB24 frames to the
firmware camera input. Driving data follows the same decoded video frame:
gear, speed, accelerator position, brake, steering angle and turn signals.
The display bridge also derives signed speed, road-wheel angle and yaw rate for
the native ApViz ego model, so forward/reverse motion and steering use the same
committed recording frame. Road-wheel angle is converted to the firmware camera
sign convention so projected reverse guide lines follow the recorded turn.
The 14.8:1 steering ratio matches the repository's TeslaCam 3D presentation
pipeline.

Use Play, Pause and the timeline to move through the recording. Playback speed
ranges from 0.25× to 2×, and Loop restarts the clip at the end. Pause holds both
the image and driving data. Seeking decodes a new frame before changing the
vehicle inputs. If decoding falls behind, data slows with the video.

Reopening a device restores a still preview of the previous recording and keeps
the simulator parked. Press Play to resume driving-data input; seeking or
adjusting playback options alone does not take control.

Manual takeover releases the recording's control of the simulator immediately.
Changing a manual vehicle control also takes over. A separate ordinary camera
video continues playing when manual controls are used. Press Play in Replay to
resume the recording's inputs.

The original GPS position, heading, acceleration and recorded assistance-state
code remain available as recording metadata. A recorded assistance state does
not activate driving assistance. Display acceptance and readback are reported
separately from decoding. The firmware camera page must be visible to see the
video; a drive recording does not automatically change the recorded gear to R.

## Supported recordings

- Local H.264 MP4 clips containing the project's Tesla SEI telemetry fields.
- Up to 8 GiB, two hours and 300,000 video packets per clip.
- Source timestamps come from the MP4 packet index, including variable frame
  intervals; frame sequence numbers are retained as metadata.
- One selected camera view at a time. Select front, back or a repeater recording
  from the same event as needed.
- The six simulator values retain the same range limits as manual controls.
  The brake field records a pressed/released flag rather than brake pressure.

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
