from types import SimpleNamespace

import pytest
from infotainment_lab import display_scale as scale


def registry(dpi):
    def run(argv, **kwargs):
        if argv[0].endswith('reg.exe'):
            out = f'\r\nHKEY_CURRENT_USER\\Control Panel\\Desktop\\WindowMetrics\r\n    AppliedDPI    REG_DWORD    {dpi:#x}\r\n'
            return SimpleNamespace(returncode=0, stdout=out)
        raise OSError('not available')
    return run


@pytest.mark.parametrize('dpi,expected', [(96, 1.0), (120, 1.25), (144, 1.5), (168, 1.75), (192, 2.0)])
def test_windows_scale_reads_the_applied_dpi(dpi, expected):
    assert scale.windows_scale(registry(dpi)) == expected


def test_windows_scale_is_unknown_without_interop():
    def run(argv, **kwargs):
        raise FileNotFoundError(argv[0])
    assert scale.windows_scale(run) is None


@pytest.mark.parametrize('settings,expected', [
    ({}, 1.0),
    ({'WESTON_RDP_FRACTIONAL_HI_DPI_SCALING': 'true'}, 1.5),
    ({'WESTON_RDP_FRACTIONAL_HI_DPI_SCALING_ROUNDUP': 'true'}, 2.0),
    ({'WESTON_RDP_DEBUG_DESKTOP_SCALING_FACTOR': '125'}, 1.25),
    ({'WESTON_RDP_HI_DPI_SCALING': 'false', 'WESTON_RDP_FRACTIONAL_HI_DPI_SCALING': 'true'}, 1.0)])
def test_compositor_scale_follows_wslg_defaults_at_150_percent(settings, expected):
    assert scale.compositor_scale(1.5, settings) == expected


def test_compositor_scales_whole_steps_by_default():
    assert scale.compositor_scale(2.0, {}) == 2.0
    assert scale.compositor_scale(2.5, {}) == 2.0


def test_panel_makes_up_only_what_wslg_does_not_scale(monkeypatch, tmp_path):
    config = tmp_path / '.wslgconfig'
    monkeypatch.setattr(scale, 'wslg_config_path', lambda run: config)
    env = {'WSL_DISTRO_NAME': 'Debian'}
    assert scale.scale_factor(env, run=registry(144)) == 1.5
    assert scale.qt_environment(env, run=registry(144)) == {'QT_SCALE_FACTOR': '1.5'}
    assert scale.scale_factor(env, run=registry(240)) == 1.25  # 250% over WSLg's 2x
    config.write_text('[system-distro-env]\nWESTON_RDP_FRACTIONAL_HI_DPI_SCALING=true\n')
    assert scale.qt_environment(env, run=registry(144)) == {}


def test_override_and_explicit_qt_settings_win(monkeypatch):
    monkeypatch.setattr(scale, 'wslg_config_path', lambda run: None)
    wsl = {'WSL_DISTRO_NAME': 'Debian'}
    assert scale.qt_environment(dict(wsl, INFOTAINMENT_LAB_SCALE='2'), run=registry(96)) == {'QT_SCALE_FACTOR': '2'}
    assert scale.qt_environment(dict(wsl, INFOTAINMENT_LAB_SCALE='1'), run=registry(144)) == {}
    assert scale.qt_environment(dict(wsl, QT_SCALE_FACTOR='1.2'), run=registry(144)) == {}
    assert scale.qt_environment(dict(wsl, INFOTAINMENT_LAB_SCALE='junk'), run=registry(144)) == {'QT_SCALE_FACTOR': '1.5'}


def test_linux_hosts_are_not_scaled(monkeypatch):
    monkeypatch.setattr(scale.platform, 'release', lambda: '6.8.0-generic')
    def run(argv, **kwargs):
        raise AssertionError('Windows interop must not be queried outside WSL')
    assert scale.scale_factor({}, run=run) == 1.0


def test_wslg_settings_read_only_the_distro_environment_section():
    text = '[system-distro-env]\nWESTON_RDP_HI_DPI_SCALING = false\n# comment=1\n[other]\nWESTON_RDP_FRACTIONAL_HI_DPI_SCALING=true\n'
    assert scale.wslg_settings(text) == {'WESTON_RDP_HI_DPI_SCALING': 'false'}


def test_disabling_wslg_scaling_removes_only_its_line():
    text = '[system-distro-env]\nWESTON_RDP_DEBUG_LEVEL=1\nWESTON_RDP_FRACTIONAL_HI_DPI_SCALING=true\n[user]\nname=x\n'
    updated = scale.disable_fractional(text)
    assert updated == '[system-distro-env]\nWESTON_RDP_DEBUG_LEVEL=1\n[user]\nname=x\n'
    assert scale.disable_fractional(updated) == updated
    assert scale.disable_fractional('WESTON_RDP_FRACTIONAL_HI_DPI_SCALING=true\n') == ''


@pytest.mark.parametrize('wanted,screen,expected', [
    (1.5, (3840, 2160), 1.5),
    (1.5, (2560, 1440), 1.125),   # 1152 x 1.125 = 1296 fits under 1344
    (1.25, (1920, 1080), 1.0),    # never shrinks below the default
    (1.5, None, 1.5)])
def test_firmware_scale_fits_the_center_display_on_screen(wanted, screen, expected):
    assert scale.fit_scale(wanted, screen, [(720, 1152), (1280, 480)]) == expected


@pytest.mark.parametrize('factor', [n / 16 for n in range(16, 65)])
def test_firmware_scale_steps_give_whole_pixels_for_every_display(factor):
    step = scale.fit_scale(factor, None, [])
    for size in ((720, 1152), (1280, 480), (1920, 1200), (1200, 1920)):
        assert all(float(value * step).is_integer() for value in size)
    assert abs(float('%g' % (.6 * step)) * 1200 - 720 * step) < 1e-6  # QtCar's --window argument


def test_firmware_scale_uses_the_windows_scale_and_the_desktop_size(monkeypatch):
    monkeypatch.setattr(scale, 'wslg_config_path', lambda run: None)
    def run(argv, **kwargs):
        if argv[0] == 'xdotool':
            return SimpleNamespace(returncode=0, stdout='3840 2160\n')
        return registry(144)(argv, **kwargs)
    env = {'WSL_DISTRO_NAME': 'Debian'}
    assert scale.firmware_scale(False, env, run=run) == 1.5
    assert scale.firmware_scale(False, dict(env, INFOTAINMENT_LAB_SCALE='1'), run=run) == 1.0
