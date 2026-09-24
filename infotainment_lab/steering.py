"""Steering-wheel shortcuts through the local displays' exported interfaces."""
from __future__ import annotations

ACTIONS = {
    'volume_up': ('Volume +', 'left'),
    'volume_down': ('Volume −', 'left'),
    'play': ('Play', 'left'),
    'pause': ('Pause', 'left'),
    'previous': ('Previous', 'left'),
    'next': ('Next', 'left'),
    'mute': ('Mute / unmute', 'left'),
    'volume_popup': ('Volume card', 'right'),
    'wiper_popup': ('Wiper card', 'right'),
    'voice_popup': ('Voice panel', 'right'),
}


def execute(action, center, cluster, read_services, write_services):
    """Issue one semantic button action; never infer success of cloud playback."""
    if action not in ACTIONS:
        raise ValueError('Unknown steering-wheel button.')
    if action in ('volume_up', 'volume_down', 'mute'):
        current = read_services()
        patch = ({'muted': not current['muted']} if action == 'mute' else
                 {'volume_pct': max(0, min(100, current['volume_pct'] + (5 if action == 'volume_up' else -5)))})
        write_services(patch)
        result = {'action': action, 'status': 'requested', 'values': patch}
        if cluster is not None:
            try:
                cluster.ShowVolumePopup(timeout=1)
            except Exception:
                result['warning'] = 'Volume updated; the instrument volume card is unavailable.'
        return result
    if action in ('previous', 'next', 'play', 'pause'):
        method = {'play': 'playMedia', 'pause': 'pauseMedia',
                  'previous': 'skipBackwardMedia', 'next': 'skipForwardMedia'}[action]
        getattr(center, method)(timeout=2)
        return {'action': action, 'status': 'requested'}
    if cluster is None:
        raise RuntimeError('Start the instrument display to use this button.')
    method = {'volume_popup': 'ShowVolumePopup', 'wiper_popup': 'ShowWiperPopup',
              'voice_popup': 'ShowVoiceUI'}[action]
    getattr(cluster, method)(timeout=2)
    return {'action': action, 'status': 'requested'}
