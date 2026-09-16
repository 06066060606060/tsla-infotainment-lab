"""Build guest-only storage from the firmware's declared GPT layout.

The signed root images are copied verbatim. No host block devices are opened.
Data-volume provisioning is separate from this root-bank assembly step.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

SECTOR = 512


def parse_layout(text: str) -> list[dict]:
    if 'label: gpt' not in text or 'unit: sectors' not in text:
        raise ValueError('Expected the vendor GPT layout in sector units.')
    partitions = []
    for line in text.splitlines():
        match = re.fullmatch(r'/dev/mmcblk0p([1-4])\s*:\s*(.+)', line.strip())
        if not match:
            continue
        fields = dict(re.findall(r'(start|size|type|name)\s*=\s*("[^"]*"|[\w-]+)', match[2]))
        if not {'start', 'type', 'name'} <= fields.keys():
            raise ValueError('Incomplete vendor partition entry.')
        partitions.append({'number': int(match[1]), 'start': int(fields['start']),
                           'size': int(fields['size']) if 'size' in fields else None,
                           'type': fields['type'], 'name': fields['name'].strip('"')})
    if [p['number'] for p in partitions] != [1, 2, 3, 4]:
        raise ValueError('Expected four ordered vendor partitions.')
    if [p['name'] for p in partitions] != ['boot', 'rootfs-a-legacy', 'rootfs-b-legacy', 'lvm']:
        raise ValueError('Unknown root-bank storage layout.')
    end = 34
    for part in partitions:
        if part['start'] < end or (part['size'] is not None and part['size'] <= 0):
            raise ValueError('Overlapping or invalid partitions.')
        if part['number'] != 4 and part['size'] is None:
            raise ValueError('A legacy partition must declare its size.')
        end = part['start'] + (part['size'] or 0)
    return partitions


def bank_extents(partitions: list[dict], disk_bytes: int, expansion_bytes: int) -> list[list[tuple[int, int]]]:
    """Each bank joins its legacy partition to a reserved tail of partition 4."""
    if disk_bytes % SECTOR or expansion_bytes <= 0 or expansion_bytes % 4096:
        raise ValueError('Storage sizes must be aligned.')
    last = partitions[3]
    # GPT backup occupies the last 33 sectors; the vendor rounds p4 to 4 KiB.
    count = last['size'] or (disk_bytes // SECTOR - 33 - last['start'])
    if last['start'] + count > disk_bytes // SECTOR - 33:
        raise ValueError('Partition 4 exceeds the disk.')
    aligned = count // 8 * 8 * SECTOR
    if aligned <= expansion_bytes * 2:
        raise ValueError('Disk is too small for data and expanded root banks.')
    tail = last['start'] * SECTOR + aligned - expansion_bytes * 2
    return [[(partitions[i]['start'] * SECTOR, partitions[i]['size'] * SECTOR),
             (tail + (i - 1) * expansion_bytes, expansion_bytes)] for i in (1, 2)]


def build_storage(image: Path, destination: Path, layout: str, *, expansion_bytes: int,
                  disk_bytes: int = 64 * 1024**3) -> dict:
    image = image.resolve(strict=True)
    if destination.exists():
        raise FileExistsError('Refusing to overwrite an existing guest disk.')
    parts = parse_layout(layout)
    extents = bank_extents(parts, disk_bytes, expansion_bytes)
    before = image.stat()
    if any(before.st_size > sum(length for _, length in bank) for bank in extents):
        raise ValueError('Firmware exceeds the capacity of the declared root banks.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix='guest-disk-', suffix='.raw', dir=destination.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.truncate(disk_bytes)
    try:
        spec = 'label: gpt\nunit: sectors\nfirst-lba: 512\n\n'
        for part in parts:
            spec += f"start={part['start']}, "
            if part['size'] is not None:
                spec += f"size={part['size']}, "
            spec += f"type={part['type']}, name=\"{part['name']}\"\n"
        subprocess.run(['sfdisk', '--no-reread', '--no-tell-kernel', str(temporary)],
                       input=spec, text=True, capture_output=True, check=True, timeout=30)
        actual = json.loads(subprocess.run(['sfdisk', '--json', str(temporary)],
                                          capture_output=True, text=True, check=True, timeout=10).stdout)['partitiontable']['partitions']
        if len(actual) != 4 or any(a['start'] != p['start'] or (p['size'] is not None and a['size'] != p['size'])
                                   for a, p in zip(actual, parts)):
            raise ValueError('Written GPT does not match the declared layout.')
        hashes = []
        with temporary.open('r+b') as target:
            for bank in extents:
                digest = hashlib.sha256()
                with image.open('rb') as source:
                    for offset, length in bank:
                        target.seek(offset)
                        remaining = length
                        while remaining:
                            chunk = source.read(min(4 * 1024**2, remaining))
                            if not chunk:
                                break
                            target.write(chunk)
                            digest.update(chunk)
                            remaining -= len(chunk)
                hashes.append(digest.hexdigest())
        after = image.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or len(set(hashes)) != 1:
            raise ValueError('The source image changed while building guest storage.')
        # Atomic publication without replacing an existing disk.
        os.link(temporary, destination)
        return {'disk_bytes': disk_bytes, 'image_bytes': before.st_size, 'image_sha256': hashes[0],
                'root_banks': extents, 'data_volumes_provisioned': False, 'boot_filesystem_provisioned': False}
    finally:
        temporary.unlink(missing_ok=True)
