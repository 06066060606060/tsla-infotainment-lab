"""Keep independent display windows while sharing a VM's accelerated GPU."""
from pathlib import Path
import re
import subprocess

VGL_LIBRARIES = ('/usr/lib/libdlfaker.so', '/usr/lib/libvglfaker.so')


def renderer_info(output):
    fields = dict(line.strip().split(':', 1) for line in output.splitlines() if ':' in line)
    renderer = fields.get('OpenGL renderer string', '').strip()
    software = any(name in renderer.lower() for name in ('llvmpipe', 'softpipe', 'swrast', 'software'))
    # VirtualGL does not expose GLX_MESA_query_renderer on the presentation X
    # server. Its actual GL renderer and direct context still identify the GPU.
    accelerated = bool(renderer) and not software and (
        fields.get('Accelerated', '').strip() == 'yes' or
        fields.get('direct rendering', '').strip() == 'Yes')
    return {'renderer': renderer or 'Unknown', 'accelerated': accelerated}


def offload_environment(base, render_display):
    if not re.fullmatch(r':\d+\.\d+', render_display):
        raise ValueError('GPU rendering requires a local X11 screen.')
    env = dict(base, VGL_DISPLAY=render_display, VGL_COMPRESS='proxy', VGL_FPS='48')
    # Keep the existing input/compositor adapters after the GL interposers.
    env['LD_PRELOAD'] = ':'.join((*VGL_LIBRARIES, base.get('LD_PRELOAD', ''))).rstrip(':')
    return env


def probe_display(env, *, render_display=None, run=subprocess.run):
    def probe(candidate):
        return run(['glxinfo', '-B'], env=candidate, capture_output=True,
                   text=True, check=True, timeout=12).stdout

    output = probe(env)
    info = dict(renderer_info(output), transport='direct')
    if info['accelerated'] or not render_display:
        return info, output
    if not all(Path(path).is_file() for path in VGL_LIBRARIES):
        info['offload_detail'] = 'VirtualGL is not installed in this guest.'
        return info, output
    try:
        candidate = probe(offload_environment(env, render_display))
        rendered = renderer_info(candidate)
        if rendered['accelerated']:
            return dict(rendered, transport='virtualgl', render_display=render_display), candidate
        info['offload_detail'] = 'The shared GPU still reports software rendering.'
    except (OSError, subprocess.SubprocessError) as exc:
        info['offload_detail'] = f'Shared GPU probe failed: {type(exc).__name__}.'
    return info, output


def application_environment(config, name, env):
    info = config.get('display_graphics', {}).get(name, {})
    if info.get('transport') == 'virtualgl':
        return offload_environment(env, info['render_display'])
    return dict(env)
