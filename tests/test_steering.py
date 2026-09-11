import pytest
from infotainment_lab.steering import execute


class NativeInterface:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name not in {'playMedia', 'pauseMedia', 'skipForwardMedia', 'skipBackwardMedia',
                        'ShowVolumePopup', 'ShowWiperPopup', 'ShowVoiceUI'}:
            raise AttributeError(name)
        return lambda **kwargs: self.calls.append(name)


@pytest.mark.parametrize('action,method', [('play', 'playMedia'), ('pause', 'pauseMedia'),
                                         ('next', 'skipForwardMedia'), ('previous', 'skipBackwardMedia')])
def test_media_buttons_call_the_native_player_without_claiming_playback(action, method):
    center, cluster = NativeInterface(), NativeInterface()
    result = execute(action, center, cluster, lambda: {}, lambda _: pytest.fail('Unexpected model edit'))
    assert center.calls == [method]
    assert cluster.calls == []
    assert result['status'] == 'requested'


@pytest.mark.parametrize('action,start,expected', [('volume_up', 98, 100), ('volume_down', 2, 0),
                                                ('volume_up', 40, 45)])
def test_volume_is_bounded_and_opens_the_native_instrument_card(action, start, expected):
    center, cluster, patches = NativeInterface(), NativeInterface(), []
    execute(action, center, cluster, lambda: {'volume_pct': start, 'muted': False}, patches.append)
    assert patches == [{'volume_pct': expected}]
    assert cluster.calls == ['ShowVolumePopup']


def test_mute_and_no_cluster_mode():
    patches = []
    execute('mute', NativeInterface(), None, lambda: {'muted': True}, patches.append)
    assert patches == [{'muted': False}]
    with pytest.raises(RuntimeError):
        execute('wiper_popup', NativeInterface(), None, lambda: {}, patches.append)


def test_unknown_buttons_do_not_touch_the_model_or_native_interfaces():
    with pytest.raises(ValueError):
        execute('__getattribute__', None, None, lambda: pytest.fail('Read'), lambda _: pytest.fail('Write'))


def test_lost_instrument_popup_does_not_report_an_already_applied_volume_edit_as_failed():
    class Disconnected:
        def ShowVolumePopup(self, **kwargs):
            raise RuntimeError('Disconnected')
    patches = []
    result = execute('volume_up', None, Disconnected(), lambda: {'volume_pct': 20}, patches.append)
    assert patches == [{'volume_pct': 25}]
    assert result['values'] == patches[0] and result['warning']
