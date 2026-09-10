#!/usr/bin/env python3
"""Create a clearly labelled synthetic dashcam clip for public screenshots.

Requires FFmpeg with libx264 and drawtext. Generates its own video and driving
samples, adds standard H.264 unregistered SEI messages, then remuxes into MP4.
No firmware, road recording, location, account or network access is used.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FPS, SECONDS = 24, 12
UUID = b'\x42' * 15 + b'\x69'  # existing project's Tesla SEI payload identifier


def varint(value):
    output = bytearray()
    while value > 127:
        output.append((value & 127) | 128)
        value >>= 7
    output.append(value)
    return bytes(output)


def integer_field(number, value):
    return varint(number << 3) + varint(value)


def float_field(number, value):
    return varint((number << 3) | 5) + struct.pack('<f', value)


def telemetry(frame):
    """A short parked -> drive -> parked sequence in display units."""
    seconds = frame / FPS
    driving = .75 <= seconds < 10
    if seconds < .75 or seconds >= 10:
        speed = 0
    elif seconds < 3:
        speed = 35 * (seconds - .75) / 2.25
    elif seconds < 7:
        speed = 35
    else:
        speed = 35 * (10 - seconds) / 3
    steering = 40 * math.sin((seconds - .75) * 1.1) if driving else 0
    return b''.join((
        integer_field(1, 1), integer_field(2, 1 if driving else 0),
        integer_field(3, frame), float_field(4, speed / 3.6),
        float_field(5, 22 if .75 <= seconds < 3 else 12 if seconds < 7 and driving else 0),
        float_field(6, steering), integer_field(7, 2 <= seconds < 4),
        integer_field(8, 6 <= seconds < 8), integer_field(9, 7 <= seconds < 10),
        integer_field(10, 0), float_field(13, 90),
        float_field(14, (35 / 3.6 / 2.25) if .75 <= seconds < 3 else
                    (-35 / 3.6 / 3) if 7 <= seconds < 10 else 0),
        float_field(15, 0), float_field(16, 0),
    ))


def sei_message(payload):
    body = UUID + payload
    assert len(body) < 255
    rbsp = bytes((5, len(body))) + body + b'\x80'
    escaped, zeros = bytearray(), 0
    for byte in rbsp:
        if zeros >= 2 and byte <= 3:
            escaped.append(3)
            zeros = 0
        escaped.append(byte)
        zeros = zeros + 1 if byte == 0 else 0
    return b'\x06' + escaped


def add_telemetry(source, destination):
    """Insert one user-data SEI before each access unit's first video slice."""
    video = source.read_bytes()
    markers = list(re.finditer(rb'\x00\x00(?:\x00)?\x01', video))
    frame, inserted, waiting = -1, 0, False
    with destination.open('wb') as output:
        for index, marker in enumerate(markers):
            end = markers[index + 1].start() if index + 1 < len(markers) else len(video)
            nal = video[marker.end():end]
            if not nal:
                continue
            kind = nal[0] & 31
            if kind == 9:
                frame += 1
                waiting = True
            if kind in (1, 5) and waiting:
                assert 0 <= frame < FPS * SECONDS
                output.write(b'\x00\x00\x00\x01' + sei_message(telemetry(frame)))
                inserted += 1
                waiting = False
            output.write(b'\x00\x00\x00\x01' + nal)
    if inserted != FPS * SECONDS:
        raise RuntimeError(f'Expected {FPS * SECONDS} video frames; received {inserted}.')


def generate(output):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise SystemExit('Install FFmpeg to generate the replay demo.')
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    filters = ','.join((
        'drawgrid=width=160:height=90:thickness=1:color=0x385261@0.45',
        'drawbox=x=0:y=0:w=1280:h=205:color=0x11202a:t=fill',
        'drawbox=x=0:y=630:w=1280:h=90:color=0x11202a:t=fill',
        'drawbox=x=215:y=255:w=850:h=310:color=0x203847:t=fill',
        'drawbox=x=215:y=255:w=850:h=310:color=0x578995:t=3',
        "drawtext=text='LOCAL REPLAY DEMO':fontcolor=0xdcecf3:fontsize=48:x=80:y=50",
        "drawtext=text='SYNTHETIC VIDEO + EMBEDDED DRIVING DATA':fontcolor=0x81a4b8:fontsize=25:x=82:y=125",
        "drawtext=text='SPEED   STEERING   BRAKE   SIGNALS':fontcolor=0xa5c6d4:fontsize=28:x=325:y=280",
        "drawtext=text='●':fontcolor=0x70dfba:fontsize=110:x='585+140*sin(t*1.1)':y=365",
        "drawtext=text='DEMO FRAME %{n}':fontcolor=0x8eb0c2:fontsize=24:x=80:y=661",
        "drawtext=text='NO ROAD FOOTAGE  /  NO GPS LOCATION':fontcolor=0x8eb0c2:fontsize=24:x=655:y=661",
    ))
    with tempfile.TemporaryDirectory(prefix='infotainment-demo-') as folder:
        directory = Path(folder)
        original, enriched = directory / 'video.h264', directory / 'telemetry.h264'
        subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
            '-f', 'lavfi', '-i', f'color=c=0x172b36:s=1280x720:r={FPS}',
            '-vf', filters, '-t', str(SECONDS), '-an', '-c:v', 'libx264',
            '-preset', 'veryfast', '-crf', '22', '-pix_fmt', 'yuv420p',
            '-bf', '0', '-g', str(FPS), '-x264-params', 'aud=1:repeat-headers=1',
            '-f', 'h264', str(original)], check=True)
        add_telemetry(original, enriched)
        subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
            '-r', str(FPS), '-i', str(enriched), '-c:v', 'copy',
            '-movflags', '+faststart', str(output)], check=True)

    sys.path.insert(0, str(ROOT))
    from infotainment_lab.replay import load_recording, sample_controls
    recording = load_recording(output)
    assert len(recording.samples) == FPS * SECONDS
    assert sample_controls(recording.samples[0])['gear'] == 'P'
    assert sample_controls(recording.sample_at(5))['speed_kph'] > 34
    assert sample_controls(recording.samples[-1])['gear'] == 'P'
    assert all('latitude_deg' not in sample.fields and 'longitude_deg' not in sample.fields
               for sample in recording.samples)
    print(f'Created {output.name}: {recording.duration_seconds:.1f}s, '
          f'{len(recording.samples)} embedded samples, synthetic video, no GPS.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/replay-demo.mp4')
    generate(parser.parse_args().output)
