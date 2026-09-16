import os
from pathlib import Path
import pytest

from infotainment_lab.camera_source import source_config, camera_health, FRAME_BYTES


def test_sources_require_local_regular_files(tmp_path):
    with pytest.raises(ValueError): source_config('video', 'https://example.com/camera')
    with pytest.raises(ValueError): source_config('video', str(tmp_path))
    with pytest.raises(ValueError): source_config('video', str(tmp_path / 'missing.mp4'))
    clip = tmp_path / 'camera clip.mp4'
    clip.write_bytes(b'local clip')
    assert source_config('video', str(clip))['path'] == str(clip)


def test_pipeline_can_wait_for_writer_but_rejects_wrong_format(tmp_path):
    frame = tmp_path / 'back.rgb'
    assert source_config('raw', str(frame))['mode'] == 'raw'
    frame.write_bytes(b'not a full frame')
    with pytest.raises(ValueError, match='RGB24'): source_config('raw', str(frame))
    frame.write_bytes(bytes(FRAME_BYTES))
    assert source_config('raw', str(frame))['path'] == str(frame)


def test_health_requires_live_source_and_recent_firmware_consumption():
    producer = {'phase': 'live', 'frame_at': 99}
    consumer = {'updated_at': 99, 'frames': 24, 'fps': 24}
    assert camera_health(producer, consumer, True, 100)['firmware_receiving']
    assert not camera_health(producer, {}, True, 100)['firmware_receiving']
    assert not camera_health(producer, consumer, False, 100)['source_ready']
    assert camera_health(producer, consumer, True, 105)['phase'] == 'waiting'
    assert not camera_health(producer | {'phase': 'off'}, consumer, True, 100)['firmware_receiving']


@pytest.mark.parametrize('phase', ['paused', 'ended'])
def test_recording_retains_frame_only_with_a_live_producer(phase):
    producer = {'mode': 'replay', 'phase': phase, 'frame_at': 10, 'updated_at': 99}
    consumer = {'updated_at': 99, 'frames': 240, 'fps': 24}
    state = camera_health(producer, consumer, True, 100)
    assert state['source_ready'] and state['frame_held'] and state['firmware_receiving']
    assert not camera_health(producer, consumer, True, 105)['source_ready']
    assert not camera_health(producer, consumer, False, 100)['frame_held']
    assert not camera_health(producer | {'frame_at': 0}, consumer, True, 100)['source_ready']


@pytest.mark.skipif(os.name == 'nt', reason='Linux V4L2 compatibility adapter')
def test_v4l2_adapter_streams_rgb_and_preserves_regular_files(tmp_path):
    import subprocess
    camera = Path(__file__).resolve().parents[1] / 'infotainment_lab/runtime/native-camera.c'
    library = tmp_path / 'camera.so'
    subprocess.run(['gcc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror', str(camera), '-o', str(library), '-ldl'], check=True)
    harness = tmp_path / 'capture.c'
    harness.write_text(r'''
#include <assert.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
int main(int argc, char **argv) {
    int ordinary = open(argv[1], O_RDONLY);
    char text[4] = {0};
    assert(read(ordinary, text, 3) == 3 && !memcmp(text, "rgb", 3));
    close(ordinary);
    int fd = open("/dev/video32", O_RDWR);
    assert(fd >= 0);
    struct v4l2_format fmt = {.type = V4L2_BUF_TYPE_VIDEO_CAPTURE};
    fmt.fmt.pix.width = 160; fmt.fmt.pix.height = 120;
    fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_RGB24;
    assert(ioctl(fd, VIDIOC_S_FMT, &fmt) == 0);
    struct v4l2_requestbuffers req = {.count=2, .type=V4L2_BUF_TYPE_VIDEO_CAPTURE, .memory=V4L2_MEMORY_MMAP};
    assert(ioctl(fd, VIDIOC_REQBUFS, &req) == 0);
    assert(ioctl(fd, VIDIOC_S_FMT, &fmt) == -1);
    struct v4l2_buffer buf = {.index=0, .type=V4L2_BUF_TYPE_VIDEO_CAPTURE, .memory=V4L2_MEMORY_MMAP};
    assert(ioctl(fd, VIDIOC_QUERYBUF, &buf) == 0);
    assert(mmap(0, 1, PROT_READ, MAP_SHARED, fd, buf.m.offset) == MAP_FAILED);
    unsigned char *frame = mmap(0, buf.length, PROT_READ, MAP_SHARED, fd, buf.m.offset);
    assert(frame != MAP_FAILED);
    assert(ioctl(fd, VIDIOC_QBUF, &buf) == 0);
    enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    assert(ioctl(fd, VIDIOC_STREAMON, &type) == 0);
    assert(ioctl(fd, VIDIOC_DQBUF, &buf) == 0);
    assert(buf.bytesused == 160*120*3);
    assert(frame[0] == 10 && frame[1] == 120 && frame[2] == 230);
    assert(ioctl(fd, VIDIOC_STREAMOFF, &type) == 0);
    assert(munmap(frame, buf.length) == 0);
    close(fd);
    return 0;
}
''')
    executable = tmp_path / 'capture'
    subprocess.run(['gcc', str(harness), '-o', str(executable)], check=True)
    raw = tmp_path / 'frame.rgb'
    raw.write_bytes(bytes((10, 120, 230)) * (160 * 120))
    regular = tmp_path / 'ordinary.txt'
    regular.write_text('rgb passthrough')
    env = dict(os.environ, LD_PRELOAD=str(library), TESLA_ADAS_CAMERA_SIM='0', TESLA_V4L2_FRAME_FILE=str(raw))
    subprocess.run([str(executable), str(regular)], env=env, check=True, timeout=10)
