import json
from types import SimpleNamespace

import pytest

from infotainment_lab.qemu_storage import parse_layout, bank_extents, build_storage


LAYOUT = '''label: gpt
unit: sectors
/dev/mmcblk0p1 : start=512, size=512, type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, name="boot"
/dev/mmcblk0p2 : start=1024, size=512, type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, name="rootfs-a-legacy"
/dev/mmcblk0p3 : start=1536, size=512, type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, name="rootfs-b-legacy"
/dev/mmcblk0p4 : start=2048, type=E6D6D379-F507-44C2-A23C-238F2A3DF928, name="lvm"
'''


def test_banks_use_distinct_expansion_tails_outside_legacy_partitions():
    banks = bank_extents(parse_layout(LAYOUT), 16 * 1024**2, 1024**2)
    assert banks[0][0] == (1024 * 512, 512 * 512)
    assert banks[1][0] == (1536 * 512, 512 * 512)
    assert banks[0][1][0] + banks[0][1][1] == banks[1][1][0]
    assert banks[1][1][0] + banks[1][1][1] <= 16 * 1024**2 - 33 * 512


def test_rejects_overlapping_layout():
    with pytest.raises(ValueError, match='Overlapping'):
        parse_layout(LAYOUT.replace('start=1536', 'start=1100'))


def test_signed_image_is_split_verbatim_across_both_banks(tmp_path, monkeypatch):
    image = tmp_path / 'firmware'
    original = bytes(range(256)) * 1500
    image.write_bytes(original)
    parts = parse_layout(LAYOUT)
    def run(*args, **kwargs):
        return SimpleNamespace(stdout=json.dumps({'partitiontable': {'partitions': [
            dict(start=p['start'], size=p['size'] or 1000) for p in parts]}}))
    monkeypatch.setattr('infotainment_lab.qemu_storage.subprocess.run', run)
    dest = tmp_path / 'guest.raw'
    result = build_storage(image, dest, LAYOUT, disk_bytes=16 * 1024**2, expansion_bytes=1024**2)
    with dest.open('rb') as stream:
        for bank in result['root_banks']:
            contents = b''
            for start, size in bank:
                stream.seek(start)
                contents += stream.read(size)
            assert contents[:len(original)] == original
    assert image.read_bytes() == original
    with pytest.raises(FileExistsError):
        build_storage(image, dest, LAYOUT, disk_bytes=16 * 1024**2, expansion_bytes=1024**2)
