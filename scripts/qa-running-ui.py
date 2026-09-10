"""Opt-in smoke test and genuine screenshots against an already running lab.

Run with the GUI Python environment. This changes local simulator inputs,
captures the app, and returns the simulator to Park. It never starts a vehicle.
"""
import argparse
import json
from pathlib import Path
import sys
import time
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog
from PySide6.QtGui import QImage
from infotainment_lab.application import MainWindow, STYLE

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('destination', type=Path)
parser.add_argument('--cycle', action='store_true', help='Also exercise Stop and Start through the native buttons')
parser.add_argument('--tools', action='store_true', help='Exercise screen focus, screenshot export and session restart')
parser.add_argument('--video', type=Path, help='Optional local test clip to verify firmware camera input')
args = parser.parse_args()
args.destination.mkdir(parents=True, exist_ok=True)
app = QApplication([])
app.setStyle('Fusion')
app.setStyleSheet(STYLE)
window = MainWindow()
window.zh = False
window.rebuild()
window.show()

def wait_until(predicate, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QTest.qWait(100)
        if predicate():
            return
    raise AssertionError('Timed out waiting for the real session response')

try:
    wait_until(lambda: window.session.get('phase') == 'running')
    if args.tools:
        replies = []
        window.bridge.finished.connect(lambda action, result: replies.append((action, result)))
        for name in ('center', 'cluster'):
            replies.clear()
            QTest.mouseClick(window.tool_buttons[name], Qt.LeftButton)
            wait_until(lambda: any(action == 'focus' for action, _ in replies))
            assert next(result for action, result in replies if action == 'focus')['ok']
        export_dir = args.destination / 'toolbar-captures'
        export_dir.mkdir(exist_ok=True)
        original_dialog = QFileDialog.getExistingDirectory
        QFileDialog.getExistingDirectory = lambda *a, **kw: str(export_dir)
        try:
            QTest.mouseClick(window.tool_buttons['capture'], Qt.LeftButton)
            wait_until(lambda: len(list(export_dir.glob('*.png'))) >= 2)
            sizes = {(QImage(str(path)).width(), QImage(str(path)).height()) for path in export_dir.glob('*.png')}
            assert sizes == {(720, 1152), (1280, 480)}
        finally:
            QFileDialog.getExistingDirectory = original_dialog
        QTest.mouseClick(window.tool_buttons['restart'], Qt.LeftButton)
        wait_until(lambda: not window.busy and window.session.get('phase') == 'running', seconds=60)
    if args.cycle:
        QTest.mouseClick(window.stop_button, Qt.LeftButton)
        wait_until(lambda: window.session.get('phase') == 'stopped' and not window.busy)
        QTest.mouseClick(window.start_button, Qt.LeftButton)
        wait_until(lambda: window.session.get('phase') == 'running' and not window.busy, seconds=60)
    window.refresh_preview()
    wait_until(lambda: not window.overview.center.isNull())
    window.grab().save(str(args.destination / 'workspace-en.png'))
    window.resize(1080, 780)
    QTest.qWait(300)
    window.grab().save(str(args.destination / 'workspace-compact.png'))
    window.resize(1360, 920)
    window.change_language(1)
    window.refresh_preview()
    wait_until(lambda: not window.overview.center.isNull())
    window.grab().save(str(args.destination / 'workspace-zh.png'))
    window.change_language(0)
    QTest.mouseClick(window.nav_group.button(1), Qt.LeftButton)
    QTest.mouseClick(window.gears.buttons()[3], Qt.LeftButton)
    window.sliders['speed_kph'].setValue(42)
    window.sliders['throttle_pct'].setValue(20)
    window.sliders['brake_pct'].setValue(15)
    window.sliders['steering_deg'].setValue(90)
    window.indicator.setCurrentIndex(1)
    wait_until(lambda: window.session.get('controls', {}).get('requested', {}).get('speed_kph') == 42)
    firmware = window.session['controls']['firmware']
    assert len(firmware) == 2 and all(v == 'accepted' for fields in firmware.values() for v in fields.values())
    window.grab().save(str(args.destination / 'simulator-en.png'))
    (args.destination / 'simulation-proof.json').write_text(json.dumps({'requested': window.session['controls']['requested'], 'firmware': firmware}, indent=2))
    subprocess.run([sys.executable, str(Path(__file__).with_name('capture-displays.py')), str(args.destination / 'simulation'), '--only', 'cluster'], check=True)
    QTest.mouseClick(window.nav_group.button(2), Qt.LeftButton)
    window.show_pattern()
    wait_until(lambda: not window.camera_preview.frame.isNull())
    window.grab().save(str(args.destination / 'camera-en.png'))
    window.float_camera()
    QTest.qWait(300)
    assert window.camera_window.isVisible()
    if args.video:
        window.bridge.call('camera', '--source', 'video', '--path', str(args.video.resolve()))
        wait_until(lambda: window.session.get('camera', {}).get('mode') == 'video' and window.session['camera'].get('source_ready'))
        window.float_camera()
        wait_until(lambda: not window.camera_window.frame.isNull())
        assert window.camera_window.isVisible()
        print('Local video decoded and available to firmware camera input and native preview windows.')
    print('Native UI: display previews, language switch, controls, both display acknowledgements, camera window passed. Lifecycle cycle:', args.cycle, 'Display tools:', args.tools)
finally:
    window.show_pattern()
    window.reset_simulator()
    QTest.qWait(1500)
    window.close()
