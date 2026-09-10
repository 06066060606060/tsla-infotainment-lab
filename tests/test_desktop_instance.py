"""Exercise the real local socket used when a user opens the app twice."""
import os
import subprocess
import sys
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from infotainment_lab.desktop_instance import DesktopInstance


def test_second_launch_hands_files_to_the_existing_control_panel(tmp_path):
    app = QApplication.instance() or QApplication([])
    primary = DesktopInstance(directory=tmp_path)
    assert primary.acquire({'files': []})
    received = []
    primary.attach(received.append)
    code = '''
import sys
from PySide6.QtCore import QCoreApplication
from infotainment_lab.desktop_instance import DesktopInstance
app = QCoreApplication([])
instance = DesktopInstance(directory=sys.argv[1])
assert instance.acquire({'files': ['example firmware.mcu2']}) is False
'''
    child = subprocess.Popen([sys.executable, '-c', code, str(tmp_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while child.poll() is None and time.monotonic() < deadline:
            QTest.qWait(25)
        assert child.poll() == 0, child.stderr.read().decode() if child.poll() is not None else 'Second launch timed out'
        assert received == [['example firmware.mcu2']]
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=5)
        primary.server.close()
        primary.lock.unlock()
