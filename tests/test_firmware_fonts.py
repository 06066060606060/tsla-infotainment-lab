import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

from infotainment_lab.firmware_fonts import font_environment


def test_font_configuration_escapes_paths_and_keeps_cache_outside_firmware(tmp_path):
    firmware = tmp_path / 'Firmware & fonts'
    (firmware / 'usr/share/fonts').mkdir(parents=True)
    state = tmp_path / 'session'
    env = font_environment(firmware, state)
    root = ET.parse(env['FONTCONFIG_FILE']).getroot()
    assert root.findtext('dir') == str((firmware / 'usr/share/fonts').resolve())
    assert Path(root.findtext('cachedir')).is_relative_to(state)
    assert not root.findall('include')
    assert list((firmware / 'usr/share/fonts').iterdir()) == []


def test_missing_firmware_fonts_reports_a_clear_error(tmp_path):
    with pytest.raises(RuntimeError, match='usr/share/fonts'):
        font_environment(tmp_path, tmp_path / 'session')


@pytest.mark.skipif(os.name == 'nt' or not shutil.which('fc-match'), reason='Linux Fontconfig')
def test_fontconfig_selects_only_the_supplied_image(tmp_path):
    host_font = subprocess.check_output(['fc-match', '-f', '%{file}', 'sans-serif'], text=True)
    firmware = tmp_path / 'image & spaces'
    fonts = firmware / 'usr/share/fonts'
    fonts.mkdir(parents=True)
    supplied_font = fonts / Path(host_font).name
    shutil.copyfile(host_font, supplied_font)
    env = dict(os.environ, **font_environment(firmware, tmp_path / 'state'))
    selected = subprocess.check_output(['fc-match', '-f', '%{file}', 'sans-serif'], env=env, text=True)
    assert Path(selected) == supplied_font


@pytest.mark.skipif(os.name == 'nt' or not shutil.which('gcc'), reason='Linux native compositor')
def test_compositor_preserves_glyph_alignment_even_when_upload_fails(tmp_path):
    source = Path(__file__).resolve().parents[1] / 'infotainment_lab/runtime/native-compositor.c'
    harness = tmp_path / 'alignment.c'
    harness.write_text('#include "' + source.as_posix() + '"\n' + r'''
#include <assert.h>
static int alignment;
static unsigned int upload_error;
static int uploads;
static void get_value(unsigned int name, int *value) {
    assert(name == GL_UNPACK_ALIGNMENT); *value = alignment;
}
static void set_value(unsigned int name, int value) {
    assert(name == GL_UNPACK_ALIGNMENT); alignment = value;
}
static void texture(unsigned int target, int level, int format, int width,
                    int height, int border, unsigned int external,
                    unsigned int type, const void *pixels) {
    assert(alignment == 1); assert(width == 3 && height == 2); uploads++;
}
static unsigned int error_value(void) { return upload_error; }
int main(void) {
    cpu.glGetIntegerv = get_value; cpu.glPixelStorei = set_value;
    cpu.glTexImage2D = texture; cpu.glGetError = error_value;
    for (int original = 1; original <= 8; original *= 2) {
        for (int failed = 0; failed < 2; failed++) {
            alignment = original; upload_error = failed ? 0x0502 : GL_NO_ERROR;
            assert(upload_rgba_texture(GL_TEXTURE_2D, 3, 2, NULL) == upload_error);
            assert(alignment == original);
        }
    }
    assert(uploads == 8);
}
''')
    binary = tmp_path / 'alignment'
    subprocess.run(['gcc', '-O0', str(harness), '-ldl', '-o', str(binary)], check=True, capture_output=True)
    subprocess.run([str(binary)], check=True, capture_output=True)
