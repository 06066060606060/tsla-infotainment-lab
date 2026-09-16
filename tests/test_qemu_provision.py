import pytest

from infotainment_lab.qemu_provision import newc


def test_maintenance_archive_contains_exact_files_and_aligned_records():
    files = {'init': b'#!/bin/sh\necho ready\n', 'usr/bin/tool': b'ELF-example'}
    archive = newc(files)
    offset, unpacked = 0, {}
    while True:
        assert offset % 4 == 0
        assert archive[offset:offset + 6] == b'070701'
        fields = [int(archive[offset + 6 + i * 8:offset + 14 + i * 8], 16) for i in range(13)]
        name = archive[offset + 110:offset + 110 + fields[11] - 1].decode()
        data_start = (offset + 110 + fields[11] + 3) & ~3
        unpacked[name] = archive[data_start:data_start + fields[6]]
        offset = (data_start + fields[6] + 3) & ~3
        if name == 'TRAILER!!!':
            break
    assert unpacked['init'] == files['init']
    assert unpacked['usr/bin/tool'] == files['usr/bin/tool']
    assert 'usr' in unpacked and 'usr/bin' in unpacked


@pytest.mark.parametrize('path', ['/init', '../init', 'usr/../../init'])
def test_maintenance_archive_rejects_paths_outside_root(path):
    with pytest.raises(ValueError):
        newc({path: b''})
