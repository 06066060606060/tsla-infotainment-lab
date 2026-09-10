"""Native Qt desktop application for Linux, WSLg, and an optional Windows client."""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
from pathlib import Path
import sys
import time

from PySide6.QtCore import Qt, QSettings, QTimer, Signal, QSize
from PySide6.QtGui import QPixmap, QShortcut, QKeySequence
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QScrollArea, QSlider, QStackedWidget, QTextEdit, QVBoxLayout, QWidget, QToolButton, QProgressBar, QLineEdit)

from .bridge import Bridge
from . import __version__
from .camera import CameraPreview
from .core import size_label, profile_for
from .presentation import icon, readiness
from .workspace import build_workspace
from .simulation import Simulation
from .desktop_instance import DesktopInstance
from .lab_panels import BrowserPanel, ReplayPanel, ServicesPanel

STYLE = """
QWidget { background: #0d141c; color: #e6edf3; font-family: 'Noto Sans CJK SC', 'Segoe UI', sans-serif; font-size: 14px; }
QLabel { background: transparent; }
QFrame#sidebar { background: #111c27; border-right: 1px solid #233240; }
QFrame#card { background: #14212d; border: 1px solid #283a49; border-radius: 13px; }
QFrame#card QLabel, QFrame#card QWidget { background: transparent; }
QLabel#muted { color: #91a6b8; } QLabel#eyebrow { color: #69d8b8; font-size: 11px; letter-spacing: 2px; }
QLabel#title { font-size: 30px; font-weight: 650; } QLabel#subtitle { font-size: 19px; font-weight: 600; }
QLabel#metric { font-size: 29px; font-weight: 600; } QLabel#brand { font-size: 22px; font-weight: 650; }
QLabel#notice { padding: 12px; background: #1b2d36; border-radius: 8px; color: #a7dfd1; }
QPushButton { background: #1c2b3a; border: 1px solid #35495a; border-radius: 7px; padding: 11px 18px; font-weight: 550; }
QPushButton:hover { background: #293f50; border-color: #6b879c; }
QPushButton:checked { background: #254a4b; color: #abf2da; border-color: #68d8b7; }
QPushButton:disabled { color: #586b7c; background: #17222d; border-color: #223140; }
QPushButton#primary { background: #68d8b7; color: #102a25; border: 0; }
QPushButton#primary:hover { background: #91e8cd; }
QPushButton#primary:disabled { background: #243e3b; color: #78948d; }
QPushButton#danger { color: #ffb0a8; border-color: #714547; }
QPushButton#danger:disabled { color: #586b7c; border-color: #223140; }
QPushButton#nav { text-align: left; border: 0; background: transparent; color: #9bafbf; padding: 13px 16px; }
QPushButton#nav:checked { background: #263b47; color: #89e5ca; }
QComboBox { border: 1px solid #35495a; padding: 8px; border-radius: 6px; background: #172633; }
QComboBox QAbstractItemView { background: #192936; selection-background-color: #2b4b57; }
QDoubleSpinBox { border: 1px solid #35495a; border-radius: 6px; padding: 8px; background: #172633; }
QTabWidget::pane { border: 1px solid #283a49; border-radius: 9px; background: #14212d; }
QTabBar::tab { padding: 10px 13px; background: #172633; color: #91a6b8; }
QTabBar::tab:selected { background: #254a4b; color: #abf2da; }
QLineEdit { background: #101a24; border: 1px solid #2b4050; border-radius: 7px; padding: 9px; }
QLineEdit:focus { border-color: #68d8b7; }
QGroupBox { border: 1px solid #2b4050; border-radius: 8px; margin-top: 12px; padding: 15px 10px 8px; color: #a2b7c5; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QToolButton { background: transparent; border: 0; border-radius: 8px; padding: 8px; color: #a6bbc8; font-size: 11px; }
QToolButton:hover { background: #263d47; color: #b2efdd; }
QToolButton:disabled { color: #526774; }
QFrame#tools { background: #111c27; border-left: 1px solid #233240; }
QLabel#badge { color: #93e4cb; background: #203e39; border-radius: 11px; padding: 5px 12px; font-size: 12px; }
QProgressBar { border: 0; background: #182c36; max-height: 3px; }
QProgressBar::chunk { background: #68d8b7; }
QListWidget { background: #111d27; border: 1px solid #2b4050; border-radius: 8px; padding: 5px; }
QListWidget::item { padding: 13px; border-radius: 5px; }
QListWidget::item:selected { background: #254a4b; color: #abf2da; }
QTextEdit { background: #0a1118; border: 1px solid #293b49; border-radius: 8px; padding: 12px; font-family: 'Cascadia Code', monospace; font-size: 12px; }
QSlider::groove:horizontal { height: 5px; background: #2b4051; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #65cfb2; border-radius: 2px; }
QSlider::handle:horizontal { background: #b4efdc; width: 17px; margin: -6px 0; border-radius: 8px; }
QCheckBox { spacing: 9px; } QCheckBox::indicator { width: 17px; height: 17px; }
QScrollArea { border: 0; } QToolTip { color: #edf5f7; background: #253847; border: 1px solid #496373; }
QScrollBar:vertical { background: #101b25; width: 9px; margin: 0; border-radius: 4px; }
QScrollBar::handle:vertical { background: #3c5668; min-height: 28px; border-radius: 4px; }
QScrollBar:horizontal { background: #101b25; height: 9px; margin: 0; border-radius: 4px; }
QScrollBar::handle:horizontal { background: #3c5668; min-width: 28px; border-radius: 4px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""


def label(text, style=None, wrap=False):
    result = QLabel(text)
    if style: result.setObjectName(style)
    result.setWordWrap(wrap)
    return result


def card():
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(24, 22, 24, 22)
    layout.setSpacing(14)
    return frame, layout


class DropArea(QFrame):
    files = Signal(list)
    clicked = Signal()

    def __init__(self, title, hint):
        super().__init__()
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("DropArea { border: 1px dashed #548c85; border-radius: 12px; background: #12262a; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.addWidget(label(title, "subtitle"))
        layout.addWidget(label(hint, "muted", True))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and all(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.files.emit([url.toLocalFile() for url in event.mimeData().urls()])
        event.acceptProposedAction()

    def mouseReleaseEvent(self, _):
        self.clicked.emit()


class MainWindow(QMainWindow):
    def __init__(self, initial_files=None, settings=None):
        super().__init__()
        self.settings = settings if settings is not None else QSettings("InfotainmentLab", "Desktop")
        self.zh = self.settings.value("language", "en") == "zh"
        self.bridge = Bridge(str(self.settings.value("distro", "Debian")), self)
        self.bridge.finished.connect(self.received)
        self.environment, self.session = {}, {}
        self.library = []
        self.import_queue = list(initial_files or [])
        self.busy = False
        self.active_action = None
        self.notification = None
        self.loading_options = False
        self.loaded_device_id = None
        self.current_page = 0
        self.sim = Simulation()
        self.manual_override = False
        self.camera_window = None
        self.setWindowTitle("Infotainment Lab · tsla-infotainment-lab")
        self.resize(1360, 920)
        self.setMinimumSize(1080, 680)
        self.rebuild()
        self.poll = QTimer(self)
        self.poll.timeout.connect(lambda: self.bridge.call("status") if not self.busy else None)
        self.poll.start(1000)
        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self.refresh_preview)
        self.preview_timer.start(5000)
        self.camera_timer = QTimer(self)
        self.camera_timer.timeout.connect(self.refresh_camera)
        self.camera_timer.start(1000)
        self.control_timer = QTimer(self)
        self.control_timer.setSingleShot(True)
        self.control_timer.timeout.connect(self.send_controls)
        QTimer.singleShot(200, lambda: self.bridge.call("probe"))
        for sequence, callback in (('Ctrl+O', self.choose_files), ('Ctrl+1', lambda: self.show_page(0)),
                                   ('Ctrl+2', lambda: self.show_page(1)), ('Ctrl+3', lambda: self.show_page(2))):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)

    def tr2(self, en, zh):
        return zh if self.zh else en

    def button(self, en, zh, callback, primary=False):
        button = QPushButton(self.tr2(en, zh).replace('&', '&&'))
        if primary: button.setObjectName("primary")
        button.clicked.connect(callback)
        return button

    def rebuild(self):
        browser_draft = self.browser_panel.export_draft() if hasattr(self, 'browser_panel') else None
        services_draft = self.services_panel.export_draft() if hasattr(self, 'services_panel') else None
        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(218)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(22, 30, 18, 23)
        side.setSpacing(9)
        side.addWidget(label("il /", "eyebrow"))
        side.addWidget(label("Infotainment\nLab", "brand"))
        side.addWidget(label(f"DESKTOP  /  {__version__}", "muted"))
        side.addSpacing(28)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for index, en, zh, symbol in ((0, 'Devices', '设备', 'devices'), (1, 'Controls', '车辆控制', 'controls'),
                                       (2, 'Camera & replay', '摄像头与回放', 'camera'), (5, 'Browsers', '浏览器', 'screen'),
                                       (6, 'Vehicle services', '车辆服务', 'settings'), (3, 'Diagnostics', '诊断', 'settings'), (4, 'About', '关于项目', 'help')):
            nav = self.button(en, zh, lambda checked=False, i=index: self.show_page(i))
            nav.setObjectName("nav")
            nav.setIcon(icon(symbol))
            nav.setCheckable(True)
            self.nav_group.addButton(nav, index)
            side.addWidget(nav)
        side.addStretch()
        side.addWidget(label(self.tr2("LOCAL SESSION", "本地会话"), "eyebrow"))
        side.addWidget(label(self.tr2("Closing this panel keeps your device running.", "关闭面板后，设备仍会继续运行。"), "muted", True))
        side.addSpacing(16)
        self.language = QComboBox()
        self.language.addItems(["English", "简体中文"])
        self.language.setCurrentIndex(1 if self.zh else 0)
        self.language.currentIndexChanged.connect(self.change_language)
        side.addWidget(self.language)
        outer.addWidget(sidebar)
        main = QWidget()
        layout = QVBoxLayout(main)
        layout.setContentsMargins(24, 25, 24, 20)
        self.page_title = label("", "title")
        layout.addWidget(self.page_title)
        self.banner = label(self.tr2("Checking your Linux environment…", "正在检查 Linux 环境…"), "notice", True)
        banner_row = QHBoxLayout()
        banner_row.addWidget(self.banner, 1)
        self.dismiss_button = QToolButton()
        self.dismiss_button.setText('×')
        self.dismiss_button.setToolTip(self.tr2('Dismiss message', '关闭提示'))
        self.dismiss_button.clicked.connect(self.dismiss_notice)
        banner_row.addWidget(self.dismiss_button)
        layout.addLayout(banner_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.pages = QStackedWidget()
        self.browser_panel = BrowserPanel(self)
        self.services_panel = ServicesPanel(self)
        if browser_draft: self.browser_panel.restore_draft(browser_draft)
        if services_draft: self.services_panel.restore_draft(services_draft)
        for page in (self.workspace_page(), self.simulator_page(), self.camera_page(), self.diagnostics_page(), self.about_page(), self.browser_panel, self.services_panel):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self.pages.addWidget(scroll)
        layout.addWidget(self.pages, 1)
        self.footer = label(self.tr2("Native Qt interface · User-provided firmware · Local simulation", "原生 Qt 界面 · 用户自备固件 · 本地模拟"), "muted")
        layout.addWidget(self.footer)
        outer.addWidget(main, 1)
        tools = QFrame()
        tools.setObjectName('tools')
        tools.setFixedWidth(76)
        rail = QVBoxLayout(tools)
        rail.setContentsMargins(6, 28, 6, 20)
        rail.setSpacing(12)
        self.tool_buttons = {}
        for name, symbol, en, zh, callback in (
            ('center', 'screen', 'Center', '中控', lambda: self.bridge.call('focus', '--display', 'center')),
            ('cluster', 'cluster', 'Cluster', '仪表', lambda: self.bridge.call('focus', '--display', 'cluster')),
            ('restart', 'restart', 'Restart', '重启', lambda: self.operation('restart')),
            ('capture', 'camera', 'Capture', '截图', lambda: self.bridge.call('capture')),
            ('controls', 'controls', 'Controls', '控制', lambda: self.show_page(1)),
            ('camera', 'camera', 'Camera', '摄像头', lambda: self.show_page(2))):
            button = QToolButton()
            button.setIcon(icon(symbol))
            button.setIconSize(QSize(24, 24))
            button.setText(self.tr2(en, zh))
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setToolTip(self.tr2(en, zh))
            button.setMinimumHeight(58)
            button.clicked.connect(callback)
            rail.addWidget(button)
            self.tool_buttons[name] = button
        rail.addStretch()
        outer.addWidget(tools)
        self.setCentralWidget(root)
        self.show_page(self.current_page)
        self.loaded_device_id = None
        self.refresh_library()
        self.update_status()

    def workspace_page(self):
        return build_workspace(self, label, card, DropArea)

    def filter_library(self, text):
        for row in range(self.items.count()):
            item = self.items.item(row)
            item.setHidden(text.casefold() not in item.text().casefold())

    def device_selected(self, *_):
        entry = self.selected_item()
        if entry and self.loaded_device_id != entry['id']:
            self.loading_options = True
            self.loaded_device_id = entry['id']
            self.settings.setValue('selected_device', entry['id'])
            prefix = 'devices/' + entry['id'] + '/'
            self.cluster_box.setChecked(self.settings.value(prefix + 'cluster', True, type=bool))
            self.browser_box.setChecked(self.settings.value(prefix + 'browser', True, type=bool))
            target = self.settings.value(prefix + 'map', '')
            index = self.maps_box.findData(target)
            self.maps_box.setCurrentIndex(max(0, index))
            self.loading_options = False
        self.update_status()

    def save_options(self, *_):
        if self.loading_options:
            return
        entry = self.selected_item()
        if not entry:
            return
        prefix = 'devices/' + entry['id'] + '/'
        self.settings.setValue(prefix + 'cluster', self.cluster_box.isChecked())
        self.settings.setValue(prefix + 'browser', self.browser_box.isChecked())
        self.settings.setValue(prefix + 'map', self.maps_box.currentData() or '')

    def refresh_preview(self):
        if self.current_page == 0 and not self.busy and self.session.get('phase') in ('running', 'degraded'):
            self.bridge.call('preview')

    def dismiss_notice(self):
        self.notification = None
        self.update_status()

    def setup_text(self):
        messages = {
            'checking': ('Checking this computer…', '正在检查电脑…'),
            'ready': ('Ready for your devices', '可以启动设备'),
            'dependencies': ('Install the display and runtime components to get started.', '安装显示及运行组件后即可使用。'),
            'display': ('A Linux desktop display is required. Check WSLg or your X11 session.', '需要 Linux 桌面显示，请检查 WSLg 或 X11 会话。'),
            'services': ('Enable the Linux user service manager before starting.', '启动前请启用 Linux 用户服务管理器。'),
            'mounts': ('The Linux user needs access to FUSE for read-only images.', 'Linux 用户需要 FUSE 权限才能只读挂载镜像。'),
            'user': ('Open this app as your normal Linux user.', '请使用普通 Linux 用户打开应用。'),
            'architecture': ('This device requires an x86_64 Linux computer.', '此设备需要 x86_64 Linux 电脑。'),
        }
        return self.tr2(*messages[readiness(self.environment)])

    def simulator_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 14, 0, 0)
        panel, inner = card()
        inner.addWidget(label(self.tr2("Drive the local demo", "控制本地演示"), "subtitle"))
        inner.addWidget(label(self.tr2("These are simulated inputs. They do not connect to a vehicle. Firmware acceptance appears below.",
                                      "这些输入只用于本地模拟，不连接真实车辆。下方显示固件的接收结果。"), "muted", True))
        gear_row = QHBoxLayout()
        self.gears = QButtonGroup(self)
        for gear in ("P", "R", "N", "D"):
            button = QPushButton(gear)
            button.setCheckable(True)
            button.setChecked(gear == self.sim.gear)
            button.clicked.connect(lambda checked=False, g=gear: self.set_gear(g))
            self.gears.addButton(button)
            gear_row.addWidget(button)
        inner.addLayout(gear_row)
        self.sliders, self.slider_values = {}, {}
        for key, en, zh, low, high, suffix in (
            ("speed_kph", "Dummy speed", "模拟车速", 0, 200, "km/h"),
            ("throttle_pct", "Accelerator", "加速踏板", 0, 100, "%"),
            ("brake_pct", "Brake", "制动踏板", 0, 100, "%"),
            ("steering_deg", "Steering wheel", "方向盘角度", -540, 540, "°")):
            row = QHBoxLayout()
            row.addWidget(label(self.tr2(en, zh)))
            row.addStretch()
            value = label(f"{int(getattr(self.sim, key))} {suffix}", "eyebrow")
            row.addWidget(value)
            inner.addLayout(row)
            slider = QSlider(Qt.Horizontal)
            slider.setRange(low, high)
            slider.setValue(int(getattr(self.sim, key)))
            slider.valueChanged.connect(lambda v, k=key, s=suffix: self.set_control(k, v, s))
            self.sliders[key], self.slider_values[key] = slider, value
            inner.addWidget(slider)
        self.radius_label = label("", "muted")
        inner.addWidget(self.radius_label)
        row = QHBoxLayout()
        row.addWidget(label(self.tr2("Turn signals", "转向灯")))
        self.indicator = QComboBox()
        for key, en, zh in (("off", "Off", "关闭"), ("left", "Left", "左转"), ("right", "Right", "右转"), ("hazard", "Hazards", "双闪")):
            self.indicator.addItem(self.tr2(en, zh), key)
        self.indicator.setCurrentIndex(('off', 'left', 'right', 'hazard').index(self.sim.indicator))
        self.indicator.currentIndexChanged.connect(lambda _: self.set_indicator())
        row.addWidget(self.indicator, 1)
        row.addWidget(self.button("Reset to Park", "恢复驻车", self.reset_simulator))
        inner.addLayout(row)
        layout.addWidget(panel)
        self.control_feedback = label(self.tr2("Start a session to send inputs. Speed is an explicit test value; the pedals do not run a physics model.",
                                                "启动会话后可发送输入。车速是手动测试值；踏板不驱动物理模型。"), "notice", True)
        layout.addWidget(self.control_feedback)
        layout.addStretch()
        self.update_radius()
        return page

    def camera_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.addWidget(label(self.tr2("Camera feed", "摄像头输入"), "subtitle"))
        layout.addWidget(label(self.tr2("Choose a source, then open Camera on the center display or select Reverse. The firmware receives this feed through its camera input.",
                                      "选择画面来源，然后打开中控的摄像头页面或切换倒挡。画面会通过摄像头输入进入固件。"), "muted", True))
        self.camera_status = label('', 'notice', True)
        layout.addWidget(self.camera_status)
        self.replay_panel = ReplayPanel(self)
        layout.addWidget(self.replay_panel)
        self.camera_preview = CameraPreview()
        layout.addWidget(self.camera_preview, 1)
        layout.addWidget(label(self.tr2('Source preview · 1 fps here; full frame rate in the firmware window', '输入预览 · 此处每秒刷新一次，固件窗口以完整帧率播放'), 'muted', True))
        actions = QHBoxLayout()
        actions.addWidget(self.button("Test pattern", "测试画面", self.show_pattern))
        actions.addWidget(self.button("Open video…", "打开视频…", self.open_video))
        actions.addWidget(self.button("Center display", "打开中控", lambda: self.bridge.call('focus', '--display', 'center')))
        actions.addWidget(self.button("Separate preview", "独立预览窗口", self.float_camera))
        actions.addWidget(self.button("Stop feed", "停止输入", lambda: self.bridge.call('camera', '--source', 'off')))
        layout.addLayout(actions)
        pipeline = QHBoxLayout()
        self.camera_path = QLineEdit(str(self.settings.value('camera_raw_path', '/tmp/tesla-sim/v4l2-back.rgb')))
        self.camera_path.setPlaceholderText(self.tr2('Linux path to your RGB24 output', 'RGB24 输出的 Linux 路径'))
        self.camera_path.setAccessibleName(self.tr2('Existing camera pipeline path', '现有摄像头管线路径'))
        pipeline.addWidget(self.camera_path, 1)
        pipeline.addWidget(self.button('Connect pipeline', '接入现有管线', self.connect_camera_pipeline))
        layout.addLayout(pipeline)
        layout.addWidget(label(self.tr2('Existing pipeline: 1280 × 720 RGB24. Start your writer, then connect its output file.', '现有管线格式：1280 × 720 RGB24。启动原有 writer 后，接入它的输出文件。'), 'muted', True))
        return page

    def diagnostics_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.addWidget(label(self.tr2("See what is happening", "查看运行情况"), "subtitle"))
        layout.addWidget(label(self.tr2("Health checks are separate from raw logs. Export creates a small report without firmware, browser profiles, raw logs or personal paths.",
                                      "健康检查与原始日志分开显示。导出报告不包含固件、浏览器配置、原始日志或个人路径。"), "muted", True))
        row = QHBoxLayout()
        row.addWidget(self.button("Check environment", "检查环境", lambda: self.bridge.call("probe")))
        row.addWidget(self.button("View local logs", "查看本地日志", lambda: self.bridge.call("logs")))
        row.addWidget(self.button("Export report…", "导出报告…", lambda: self.bridge.call("report")))
        layout.addLayout(row)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view, 1)
        return page

    def about_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 14, 0, 0)
        panel, inner = card()
        inner.addWidget(label("tsla-infotainment-lab", "subtitle"))
        inner.addWidget(label(self.tr2(
            "A desktop workbench built from hands-on infotainment compatibility research. Import your own firmware, inspect the environment, and launch its real interface in separate desktop windows.",
            "一个从实际车机兼容性研究中整理出的桌面工作台。导入自备固件，检查环境，并在独立桌面窗口中运行真实车机界面。"), None, True))
        inner.addWidget(label(self.tr2(
            f"Version {__version__} supports the tested 2026.26.6.1 Model S/X MCU2 build. Other images can be identified but require a matching profile. This is user-space compatibility, not complete hardware emulation.",
            f"{__version__} 版本支持已验证的 2026.26.6.1 Model S/X MCU2 构建。其他镜像可以识别，但需要对应适配配置。这是用户态兼容运行，不是完整硬件仿真。"), "muted", True))
        inner.addWidget(label(self.tr2(
            "Bring your own firmware and recordings. The desktop provides local vehicle inputs, camera replay and browser integration. Vehicle services show their actual firmware response. Steering radius illustrates a 2.96 m wheelbase and 15:1 steering ratio.",
            "请自备固件与录像。桌面提供本地车辆输入、摄像头回放和浏览器集成，车辆服务会显示固件的实际响应。示意转弯半径采用 2.96 米轴距与 15:1 转向比。"), "muted", True))
        inner.addWidget(label(self.tr2("Independent research project. Not affiliated with or endorsed by Tesla.", "独立研究项目，与 Tesla 无隶属或背书关系。"), "muted", True))
        layout.addWidget(panel)
        layout.addStretch()
        return page

    def show_page(self, index):
        self.current_page = index
        self.pages.setCurrentIndex(index)
        titles = (("Device manager", "设备管理"), ("Vehicle controls", "车辆控制"), ("Camera & replay", "摄像头与回放"),
                  ("Diagnostics", "诊断"), ("About this lab", "关于项目"), ('Browser workspace', '浏览器工作区'), ('Vehicle services', '车辆服务'))
        self.page_title.setText(self.tr2(*titles[index]))
        self.nav_group.button(index).setChecked(True)

    def change_language(self, index):
        self.zh = index == 1
        self.settings.setValue("language", "zh" if self.zh else "en")
        self.rebuild()

    def change_distro(self, value):
        self.bridge.distro = value.strip() or "Debian"
        self.settings.setValue("distro", self.bridge.distro)

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, self.tr2("Import firmware or maps", "导入固件或地图"), "",
                                               "Firmware and maps (*.mcu2 *.ice *.map *.squashfs);;All files (*)")
        self.queue_imports(paths)

    def queue_imports(self, paths):
        self.import_queue.extend(paths)
        if not self.busy: self.next_import()

    def next_import(self):
        if self.import_queue:
            self.operation("import", "--path", self.import_queue.pop(0))

    def refresh_library(self):
        selected = self.selected_item()
        preferred = selected['id'] if selected else self.settings.value('selected_device', '')
        self.loading_options = True
        self.items.blockSignals(True)
        self.items.clear()
        self.maps_box.clear()
        self.maps_box.addItem(self.tr2('No map image', '不挂载地图'), None)
        selected_row = 0
        for entry in self.library:
            if entry['kind'] == 'map':
                self.maps_box.addItem(entry['version'], entry['id'])
                continue
            profile = profile_for(entry['version'], entry['variant'])
            title = profile['name'] if profile else entry['variant']
            support = self.tr2('Ready', '可启动') if entry['supported'] else self.tr2('Needs a profile', '需要适配')
            item = QListWidgetItem(f"{title}\n{entry['version']}\n{support} · {size_label(entry['bytes'])}")
            item.setData(Qt.UserRole, entry)
            self.items.addItem(item)
            if preferred == entry['id']:
                selected_row = self.items.count() - 1
        self.items.setCurrentRow(selected_row)
        self.items.blockSignals(False)
        self.loading_options = False
        self.loaded_device_id = None
        self.device_selected()
        self.filter_library(self.search.text())

    def selected_item(self):
        if not hasattr(self, "items"): return None
        item = self.items.currentItem()
        return item.data(Qt.UserRole) if item else None

    def operation(self, action, *args):
        if self.busy:
            return
        self.notification = None
        self.busy, self.active_action = True, action
        if not self.bridge.call(action, *args):
            self.busy, self.active_action = False, None
            self.show_message(self.tr2('An operation is already in progress.', '已有操作正在执行。'), True)
        self.update_status()

    def start_session(self):
        entry = self.selected_item()
        if not entry: return
        args = ["--id", entry["id"]]
        if self.maps_box.currentData(): args += ["--map-id", self.maps_box.currentData()]
        if not self.browser_box.isChecked(): args += ["--no-browser"]
        if not self.cluster_box.isChecked(): args += ["--no-cluster"]
        self.operation("start", *args)

    def setup_dependencies(self):
        if readiness(self.environment) != 'dependencies':
            if readiness(self.environment) != 'ready':
                self.show_page(3)
            self.bridge.call('probe')
            return
        text = self.tr2("Install the Linux display, audio, compiler and read-only mount packages using your distribution's package manager? This changes the selected Linux environment.",
                        "是否通过发行版的软件包管理器安装显示、音频、编译器和只读挂载依赖？此操作会修改所选 Linux 环境。")
        if QMessageBox.question(self, self.tr2("Runtime setup", "运行环境安装"), text) == QMessageBox.Yes:
            self.operation("setup")

    def received(self, action, result):
        if action == 'vehicle-services': self.services_panel.acknowledge(bool(result.get('ok')))
        if action in ('start', 'stop', 'restart', 'import', 'setup'):
            self.busy, self.active_action = False, None
        if not result.get('ok'):
            if action == 'camera-preview': return
            if action == 'preview':
                self.preview_caption.setText(self.tr2('Preview unavailable · Open a display directly', '预览暂不可用 · 可直接打开显示窗口'))
                return
            self.show_message(result.get('error', 'Unknown error'), True)
            self.update_status()
            return
        data = result.get('data', {})
        if action == 'probe':
            self.environment, self.library = data, data.get('library', [])
            self.session = data.get('status', {})
            self.refresh_library()
            self.log_view.setPlainText(json.dumps(data, indent=2, ensure_ascii=False))
            self.next_import()
            self.refresh_preview()
        elif action in ('status', 'start', 'stop', 'restart'):
            self.session = data
            if action in ('start', 'restart'):
                self.sync_control_widgets(Simulation().as_dict())
                self.manual_override = False
        elif action == 'camera':
            if data.get('mode') == 'replay': self.manual_override = False
            self.show_message(self.tr2('Camera source selected.', '已选择摄像头来源。'))
            self.bridge.call('status')
        elif action in ('replay', 'vehicle-services', 'browser'):
            if action == 'replay' and data.get('action') == 'play': self.manual_override = False
            self.bridge.call('status')
        elif action == 'camera-preview':
            frame = QPixmap()
            if data.get('image'): frame.loadFromData(base64.b64decode(data['image']))
            self.camera_preview.set_frame(frame)
            if self.camera_window: self.camera_window.set_frame(frame)
        elif action == 'import':
            self.library = [entry for entry in self.library if entry['id'] != data['id']] + [data]
            self.settings.setValue('selected_device', data['id'])
            self.refresh_library()
            for row in range(self.items.count()):
                if self.items.item(row).data(Qt.UserRole)['id'] == data['id']:
                    self.items.setCurrentRow(row)
            self.show_message(self.tr2('Added to your library. Your original file stays in place.', '已添加至固件库，原文件保留在原位置。'))
            self.next_import()
        elif action == 'setup':
            self.bridge.call('probe')
        elif action == 'logs':
            self.log_view.setPlainText('\n\n'.join(f'--- {name} ---\n{text}' for name, text in data.get('logs', {}).items()))
        elif action == 'report':
            path, _ = QFileDialog.getSaveFileName(self, self.tr2('Export diagnostics', '导出诊断报告'), 'infotainment-lab-report.json', 'JSON (*.json)')
            if path:
                try:
                    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
                    self.show_message(self.tr2('Report saved.', '报告已保存。'))
                except OSError as exc:
                    self.show_message(str(exc), True)
        elif action == 'preview':
            frames = {}
            for name, encoded in data.get('images', {}).items():
                pixmap = QPixmap()
                pixmap.loadFromData(base64.b64decode(encoded))
                frames[name] = pixmap
            self.overview.set_frames(frames.get('center', QPixmap()), frames.get('cluster', QPixmap()))
            stamp = time.strftime('%H:%M:%S', time.localtime(data['captured_at']))
            self.preview_caption.setText(self.tr2('Live overview · ', '实时预览 · ') + stamp + self.tr2(' · Open a display to interact', ' · 打开显示窗口进行操作'))
        elif action == 'capture':
            folder = QFileDialog.getExistingDirectory(self, self.tr2('Save display screenshots', '保存显示屏截图'))
            if folder:
                try:
                    stamp = time.strftime('%Y%m%d-%H%M%S') + '-' + str(time.time_ns() % 1000000)
                    for name, encoded in data['images'].items():
                        with (Path(folder) / f'infotainment-{name}-{stamp}.png').open('xb') as stream:
                            stream.write(base64.b64decode(encoded))
                    self.show_message(self.tr2('Screenshots saved to your chosen folder.', '截图已保存至所选文件夹。'))
                except OSError as exc:
                    self.show_message(str(exc), True)
        self.update_status()

    def show_message(self, text, error=False):
        self.notification = (text, error, None if error else time.monotonic() + 8)
        if hasattr(self, 'banner'):
            self.banner.setText(text)
            self.banner.setStyleSheet('color:#ffb7ae; background:#39282e; padding:12px; border-radius:8px;' if error else '')

    def update_status(self):
        if not hasattr(self, 'start_button') or not hasattr(self, 'tool_buttons'):
            return
        phase = self.session.get('phase', 'stopped')
        live = phase in ('starting', 'running', 'degraded')
        usable = phase in ('running', 'degraded')
        self.browser_panel.update_status(self.session)
        self.replay_panel.update_status(self.session)
        self.services_panel.update_status(self.session)
        if hasattr(self, 'control_timer') and not self.manual_override and not self.control_timer.isActive() and 'controls' not in self.bridge.pending:
            actual = self.session.get('replay', {}).get('telemetry_sample', {})
            if self.session.get('camera', {}).get('mode') == 'replay' and self.session.get('replay', {}).get('phase') in ('playing', 'paused', 'seeking-playing', 'ended') and actual:
                self.sync_control_widgets(actual)
        camera = self.session.get('camera', {})
        sources = {'pattern': ('Test pattern', '测试画面'), 'video': ('Local video', '本地视频'), 'replay': ('Recorded drive', '行车记录回放'), 'raw': ('Existing pipeline', '现有管线'), 'off': ('Off', '已停止')}
        camera_text = self.tr2(*sources.get(camera.get('mode'), ('Camera', '摄像头')))
        if camera.get('source_name'): camera_text += ' · ' + camera['source_name']
        if camera.get('firmware_receiving'):
            camera_text += self.tr2(' · Firmware receiving', ' · 固件正在接收') + f" · {camera.get('fps', 0):.1f} fps · 1280 × 720"
        elif camera.get('source_ready'):
            camera_text += self.tr2(' · Source ready. Open Camera on the center display.', ' · 画面已就绪，请打开中控摄像头页面。')
        elif not live:
            camera_text = self.tr2('Start a device to connect the camera feed.', '启动设备后即可接入摄像头画面。')
            self.camera_preview.set_frame(QPixmap())
            if self.camera_window: self.camera_window.set_frame(QPixmap())
        elif camera.get('phase') == 'off':
            camera_text += self.tr2(' · Feed stopped', ' · 输入已停止')
        else:
            camera_text += self.tr2(' · Waiting for frames. Check the source file and writer.', ' · 等待画面，请检查源文件与 writer 是否运行。')
        self.camera_status.setText(camera_text)
        self.camera_status.setToolTip(camera.get('detail', ''))
        selected = self.selected_item()
        ready = readiness(self.environment) == 'ready'
        self.start_button.setEnabled(bool(selected and selected.get('supported')) and ready and not self.busy and not live)
        self.stop_button.setEnabled(live and not self.busy)
        self.setup_button.setEnabled(not self.busy and not live and readiness(self.environment) != 'checking')
        self.setup_button.setText(self.tr2('Check again', '重新检查') if ready else self.tr2('Prepare computer', '准备运行环境'))
        self.setup_hint.setText(self.setup_text())
        for control in (self.cluster_box, self.browser_box, self.maps_box, self.distro_box):
            control.setEnabled(not live and not self.busy)
        self.items.setEnabled(not live and not self.busy)
        for name, button in self.tool_buttons.items():
            button.setEnabled((usable and not self.busy) if name in ('center', 'cluster', 'restart', 'capture') else True)
        self.tool_buttons['cluster'].setEnabled(usable and self.session.get('components', {}).get('instruments') == 'running' and not self.busy)
        self.tool_buttons['restart'].setToolTip(self.tr2('Restart this device and return controls to Park', '重启当前设备，并将模拟控制恢复为驻车'))
        title = self.tr2('Add your first device', '添加第一台设备')
        subtitle = self.tr2('Bring your firmware. We will check compatibility before launch.', '导入自备固件，启动前会检查兼容性。')
        if selected:
            profile = profile_for(selected['version'], selected['variant'])
            title = profile['name'] if profile else selected['variant']
            subtitle = selected['version'] + ' · ' + self.tr2('Local firmware', '本地固件')
            if not selected.get('supported'):
                subtitle += ' · ' + self.tr2('Launch profile unavailable', '尚无启动适配')
            self.item_detail.setText(self.tr2('SHA-256 recorded · ', '已记录 SHA-256 · ') + selected['sha256'][:12] + '…')
        else:
            self.item_detail.setText(self.tr2('Add a firmware image to create a device.', '添加固件镜像即可创建设备。'))
        self.device_title.setText(title)
        self.device_subtitle.setText(subtitle)
        phases = {'stopped': ('Offline', '已停止'), 'starting': ('Starting', '启动中'), 'running': ('Running', '运行中'),
                  'degraded': ('Needs attention', '需要检查'), 'failed': ('Needs attention', '需要检查')}
        self.phase_badge.setText(self.tr2(*phases.get(phase, ('Unknown', '未知'))))
        self.steps.setText(self.tr2('1  Prepare computer', '1  准备环境') + ('  ✓' if ready else '  ○') + '     /     ' +
                           self.tr2('2  Add firmware', '2  添加固件') + ('  ✓' if selected else '  ○') + '     /     ' +
                           self.tr2('3  Start your device', '3  启动设备') + ('  ✓' if usable else '  ○'))
        labels = {'center': ('Center', '中控'), 'instruments': ('Instruments', '仪表'), 'chromium': ('Chromium', '浏览器')}
        for key, metric in self.metrics.items():
            running = self.session.get('components', {}).get(key) == 'running' and live
            metric.setText(('●  ' if running else '○  ') + self.tr2(*labels[key]))
            metric.setStyleSheet('color:#87e0c5' if running else 'color:#718493')
        host = self.session.get('host', {})
        renderer = self.session.get('renderer', self.tr2('Graphics checked at launch', '启动时检查图形加速'))
        if host.get('total_bytes'):
            renderer += '  ·  ' + size_label(host.get('free_bytes', 0)) + self.tr2(' free of ', ' 可用 / ') + size_label(host['total_bytes'])
        self.renderer_label.setText(renderer)
        self.progress.setVisible(self.busy or phase == 'starting')
        if not live:
            self.overview.set_frames(QPixmap(), QPixmap())
        if self.notification and self.notification[2] and time.monotonic() > self.notification[2]:
            self.notification = None
        self.dismiss_button.setVisible(self.notification is not None)
        error = False
        if self.notification:
            text, error, _ = self.notification
        elif self.busy:
            messages = {'start': ('Starting your device…', '正在启动设备…'), 'stop': ('Stopping your device…', '正在停止设备…'),
                        'restart': ('Restarting your device…', '正在重启设备…'), 'import': ('Inspecting firmware and recording its checksum…', '正在检查固件并记录校验值…'),
                        'setup': ('Preparing your computer. This may take a few minutes…', '正在准备电脑环境，可能需要几分钟…')}
            text = self.tr2(*messages.get(self.active_action, ('Working…', '正在处理…')))
        elif phase == 'failed':
            text, error = self.session.get('error', 'Session failed'), True
        elif phase == 'starting':
            text = self.tr2('Starting displays and loading firmware resources…', '正在启动显示窗口并加载固件资源…')
        elif usable:
            battery = self.session.get('vehicle_services', {}).get('state', {}).get('battery_percent', 50)
            text = self.tr2('Device running', '设备运行中') + '  ·  ' + self.tr2('Internet connected' if host.get('online') else 'Internet unavailable', '已联网' if host.get('online') else '互联网不可用') + '  ·  ' + self.tr2(f'Battery {battery:g}% · simulated', f'电量 {battery:g}% · 模拟')
            if phase == 'degraded':
                text += '  ·  ' + self.tr2('A component needs attention. Open Diagnostics.', '部分组件需要检查，请查看诊断。')
        elif not ready:
            text = self.setup_text()
        elif selected and not selected.get('supported'):
            text = self.tr2('This firmware needs a tested launch profile before it can run.', '此固件需要经过验证的启动适配后才能运行。')
        else:
            text = self.tr2('Ready. Choose a device or drop in firmware to get started.', '准备就绪，选择设备或拖入固件即可开始。')
        self.banner.setText(text)
        self.banner.setStyleSheet('color:#ffb7ae; background:#39282e; padding:12px; border-radius:8px;' if error else '')
        feedback = self.session.get('controls', {}).get('firmware', {}).get('com.tesla.CenterDisplay', {})
        if feedback and live:
            names = {'gear': ('Gear', '挡位'), 'speed_kph': ('Speed', '车速'), 'throttle_pct': ('Accelerator', '加速踏板'),
                     'brake_pct': ('Brake', '制动踏板'), 'steering_deg': ('Steering', '转向'), 'indicator': ('Signals', '转向灯')}
            states = {'accepted': ('accepted', '已接收'), 'unsupported': ('unavailable', '不可用'), 'rejected': ('rejected', '未接收')}
            self.control_feedback.setText(self.tr2('Firmware feedback: ', '固件反馈：') + '  ·  '.join(
                f'{self.tr2(*names[name])}: {self.tr2(*states.get(value, (value, value)))}' for name, value in feedback.items() if name in names))
        elif not live:
            self.control_feedback.setText(self.tr2('Start a device to use the local simulator.', '启动设备后即可使用本地模拟控制。'))

    def set_gear(self, gear):
        self.manual_override = True
        self.sim.gear = gear
        if gear == "P":
            self.sliders["speed_kph"].setValue(0)
            self.sliders["throttle_pct"].setValue(0)
        self.control_timer.start(180)

    def sync_control_widgets(self, values):
        self.sim = Simulation.parse(values)
        for button in self.gears.buttons(): button.setChecked(button.text() == self.sim.gear)
        for key, slider in self.sliders.items():
            slider.blockSignals(True)
            slider.setValue(round(getattr(self.sim, key)))
            slider.blockSignals(False)
            suffix = 'km/h' if key == 'speed_kph' else '°' if key == 'steering_deg' else '%'
            self.slider_values[key].setText(f'{getattr(self.sim, key):g} {suffix}')
        self.indicator.blockSignals(True)
        self.indicator.setCurrentIndex(self.indicator.findData(self.sim.indicator))
        self.indicator.blockSignals(False)
        self.update_radius()

    def set_control(self, key, value, suffix):
        self.manual_override = True
        if self.sim.gear == 'P' and key in ('speed_kph', 'throttle_pct') and value:
            self.sliders[key].setValue(0)
            return
        setattr(self.sim, key, value)
        self.slider_values[key].setText(f"{value} {suffix}")
        if key == "steering_deg":
            self.update_radius()
        self.control_timer.start(180)

    def update_radius(self):
        radius = self.sim.turning_radius_m()
        self.radius_label.setText(self.tr2("Illustrative turn radius: ", "示意转弯半径：") + (f"{radius:.1f} m" if radius else self.tr2("straight", "直行")))

    def set_indicator(self):
        self.manual_override = True
        self.sim.indicator = self.indicator.currentData()
        self.control_timer.start(180)

    def send_controls(self):
        self.sim = Simulation.parse(self.sim.as_dict())
        if not self.bridge.call("controls", "--payload", json.dumps(self.sim.as_dict())):
            self.control_timer.start(180)

    def reset_simulator(self):
        self.sim = Simulation()
        self.gears.buttons()[0].setChecked(True)
        for slider in self.sliders.values(): slider.setValue(0)
        self.indicator.setCurrentIndex(0)
        self.control_timer.start(180)

    def show_pattern(self):
        self.bridge.call('camera', '--source', 'pattern')

    def open_video(self):
        path, _ = QFileDialog.getOpenFileName(self, self.tr2("Open a local camera clip", "打开本地摄像头视频"), "", "Video (*.mp4 *.mkv *.webm *.mov *.avi);;All files (*)")
        if path:
            self.bridge.call('camera', '--source', 'video', '--path', path)

    def connect_camera_pipeline(self):
        path = self.camera_path.text().strip()
        self.settings.setValue('camera_raw_path', path)
        self.bridge.call('camera', '--source', 'raw', '--path', path)

    def refresh_camera(self):
        if (self.current_page == 2 or (self.camera_window and self.camera_window.isVisible())) and self.session.get('phase') in ('running', 'degraded'):
            self.bridge.call('camera-preview')

    def float_camera(self):
        if self.camera_window is None:
            self.camera_window = CameraPreview()
            self.camera_window.setWindowTitle("Infotainment Lab · Camera feed")
            self.camera_window.resize(800, 450)
        self.camera_window.set_frame(self.camera_preview.frame)
        self.camera_window.show()
        self.camera_window.raise_()

    def closeEvent(self, event):
        if self.busy:
            QMessageBox.information(self, "Infotainment Lab", self.tr2("Wait for the current operation to finish before closing.", "请等待当前操作完成后再关闭。"))
            event.ignore()
            return
        if self.camera_window: self.camera_window.close()
        # The service owns the session. Closing this control panel does not
        # discard the user's running displays or terminate unrelated apps.
        event.accept()


def main():
    parser = argparse.ArgumentParser(description="Infotainment Lab native desktop application")
    parser.add_argument("files", nargs="*")
    parser.add_argument("--language", choices=("en", "zh"))
    parser.add_argument("--page", type=int, choices=range(7), default=0)
    parser.add_argument("--screenshot", help="Save this application's rendered window for documentation")
    parser.add_argument("--quit-after", type=int, default=0, help="Exit after N seconds for packaging smoke tests")
    args = parser.parse_args()
    if os.environ.get('WSL_DISTRO_NAME'):
        # Use WSLg's XWayland path for consistent native widget rendering.
        os.environ.setdefault('QT_QPA_PLATFORM', 'xcb')
        os.environ.setdefault('QT_X11_NO_MITSHM', '1')
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Infotainment Lab")
    app.setDesktopFileName('infotainment-lab')
    app.setApplicationVersion(__version__)
    app.setWindowIcon(icon('devices', '#68d8b7'))
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    instance = None
    if not args.screenshot and not args.quit_after:
        instance = DesktopInstance(app)
        try:
            if not instance.acquire({'files': args.files}):
                return 0
        except RuntimeError as exc:
            QMessageBox.critical(None, 'Infotainment Lab', str(exc))
            return 1
    if args.language: QSettings("InfotainmentLab", "Desktop").setValue("language", args.language)
    window = MainWindow(args.files)
    window.show_page(args.page)
    window.show()
    window.raise_()
    window.activateWindow()
    if instance:
        def reopen(files):
            if window.isMinimized():
                window.showNormal()
            window.show()
            window.raise_()
            window.activateWindow()
            QApplication.alert(window)
            if files:
                window.queue_imports(files)
        instance.attach(reopen)
    if args.screenshot:
        QTimer.singleShot(7000, lambda: window.grab().save(args.screenshot))
    if args.quit_after: QTimer.singleShot(args.quit_after * 1000, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
