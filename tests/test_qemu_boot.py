import struct

import pytest

from infotainment_lab.qemu_boot import kernel_payload, classify_boot


def boot_image():
    image = bytearray(5 * 512 + 1024)
    image[0x1f1] = 4
    struct.pack_into('<I', image, 0x1f4, 64)
    image[510:512] = b'\x55\xaa'
    image[0x202:0x206] = b'HdrS'
    struct.pack_into('<H', image, 0x206, 0x20d)
    return bytes(image)


def test_kernel_extraction_excludes_wrapper_and_trailer():
    kernel = boot_image()
    assert kernel_payload(b'wrapper' + kernel + b'trailer') == kernel


@pytest.mark.parametrize('value', [b'HdrS', boot_image()[:-1], boot_image() * 2])
def test_invalid_or_ambiguous_payload_is_rejected(value):
    with pytest.raises(ValueError):
        kernel_payload(value)


def test_init_failure_is_not_reported_as_successful_desktop():
    result = classify_boot('Linux version 5.4.302-PLK\nverity-init booting\none or more parent devices never appeared\nKernel panic')
    assert result['kernel_started'] and result['vendor_init_started']
    assert result['phase'] == 'blocked'
    assert result['desktop_verified'] is False


def test_timeout_without_success_evidence_is_unverified():
    assert classify_boot('Linux version 5.4.302-PLK')['phase'] == 'unverified'


def test_live_observation_does_not_claim_the_check_ended():
    result = classify_boot('Linux version 5.4.302-PLK', observing=True)
    assert result['phase'] == 'unverified'
    assert result['desktop_verified'] is False
    assert 'ended' not in result['detail']
    assert classify_boot('Kernel panic', observing=True)['phase'] == 'blocked'


def test_vendor_userspace_progress_does_not_imply_desktop_parity():
    result = classify_boot('Linux version 5.4\nverity-init booting\nswitching root and executing /sbin/init\nVolume group "ivg" not found')
    assert result['vendor_root_entered'] is True
    assert result['desktop_verified'] is False
    assert result['phase'] == 'blocked'
