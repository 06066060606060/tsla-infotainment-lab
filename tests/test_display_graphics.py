import subprocess
from types import SimpleNamespace

import pytest

from infotainment_lab import display_graphics as graphics

SOFTWARE = 'direct rendering: Yes\nOpenGL renderer string: llvmpipe (LLVM)\n'
GPU = 'direct rendering: Yes\nOpenGL renderer string: virgl (D3D12 (AMD Radeon))\n'


def test_virtualgl_uses_actual_renderer_when_mesa_query_extension_is_absent(monkeypatch):
    monkeypatch.setattr(graphics, 'VGL_LIBRARIES', (__file__,))
    calls = []
    def run(args, **kwargs):
        calls.append(kwargs['env'])
        return SimpleNamespace(stdout=GPU if len(calls) == 2 else SOFTWARE)
    env = {'DISPLAY': ':1.0', 'LD_PRELOAD': '/existing/input.so'}
    info, _ = graphics.probe_display(env, render_display=':0.0', run=run)
    assert info['accelerated'] and info['transport'] == 'virtualgl'
    assert calls[1]['DISPLAY'] == ':1.0' and calls[1]['VGL_DISPLAY'] == ':0.0'
    assert calls[1]['LD_PRELOAD'].endswith(':/existing/input.so')
    assert 'VGL_DISPLAY' not in env
    app = graphics.application_environment({'display_graphics': {'cluster': info}}, 'cluster', env)
    assert app == calls[1]


@pytest.mark.parametrize('failure', ['missing', 'timeout', 'software'])
def test_unusable_offload_preserves_working_software_display(monkeypatch, failure):
    monkeypatch.setattr(graphics, 'VGL_LIBRARIES', ('/missing-virtualgl.so',) if failure == 'missing' else (__file__,))
    calls = []
    def run(args, **kwargs):
        calls.append(kwargs['env'])
        if len(calls) > 1 and failure == 'timeout':
            raise subprocess.TimeoutExpired(args, 12)
        return SimpleNamespace(stdout=SOFTWARE)
    info, _ = graphics.probe_display({'DISPLAY': ':1.0'}, render_display=':0.0', run=run)
    assert info['transport'] == 'direct' and not info['accelerated']
    assert info['offload_detail']


def test_direct_hardware_never_adds_virtualgl():
    info, _ = graphics.probe_display({}, render_display=':0.0', run=lambda *a, **kw: SimpleNamespace(stdout=GPU))
    assert info['transport'] == 'direct' and info['accelerated']
    with pytest.raises(ValueError, match='local X11'):
        graphics.offload_environment({}, 'another-host:0')
