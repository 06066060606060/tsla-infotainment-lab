import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from infotainment_lab.hold_button import HoldButton


@pytest.fixture
def button():
    app = QApplication.instance() or QApplication([])
    widget = HoldButton('Volume', repeat=True)
    widget.resize(200, 60)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()


def test_mouse_hold_repeats_and_release_cancels_without_an_extra_click(button):
    calls = []
    button.triggered.connect(lambda: calls.append(True))
    QTest.mousePress(button, Qt.LeftButton)
    assert len(calls) == 1
    QTest.qWait(680)
    assert len(calls) >= 3
    QTest.mouseRelease(button, Qt.LeftButton)
    count = len(calls)
    QTest.qWait(250)
    assert len(calls) == count and not button.holding


@pytest.mark.parametrize('event', [QEvent.Type.Leave, QEvent.Type.FocusOut, QEvent.Type.WindowDeactivate, QEvent.Type.Hide])
def test_losing_interaction_cancels_held_input(button, event):
    QTest.mousePress(button, Qt.LeftButton)
    QApplication.sendEvent(button, QEvent(event))
    assert not button.holding and not button.hold_timer.isActive()


def test_keyboard_hold_and_disabled_session_cancel(button):
    calls = []
    button.triggered.connect(lambda: calls.append(True))
    QTest.keyPress(button, Qt.Key_Space)
    assert button.holding and calls == [True]
    button.setEnabled(False)
    assert not button.holding and not button.hold_timer.isActive()
    QTest.keyRelease(button, Qt.Key_Space)
    assert calls == [True]


def test_mute_style_buttons_fire_once_when_held(button):
    button.repeat = False
    calls = []
    button.triggered.connect(lambda: calls.append(True))
    QTest.mousePress(button, Qt.LeftButton)
    QTest.qWait(550)
    QTest.mouseRelease(button, Qt.LeftButton)
    assert calls == [True]
