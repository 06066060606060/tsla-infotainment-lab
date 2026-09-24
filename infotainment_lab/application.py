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
    QPushButton, QScrollArea, QSlider, QStackedWidget, QTextEdit, QVBoxLayout, QWidget, QToolButton, QProgressBar, QLineEdit, QSizePolicy, QMenu)

from .material_widgets import MaterialSwitch as QCheckBox
from .bridge import Bridge
from . import __version__
from .camera import CameraPreview
from .core import size_label, profile_for
from .presentation import icon, readiness
from .workspace import build_workspace
from .simulation import Simulation
from .desktop_instance import DesktopInstance
from .lab_panels import BrowserPanel, CanPanel, ConsolePanel, ReplayPanel, ServicesPanel
from .config_panel import ConfigPanel
from .steering import ACTIONS as STEERING_ACTIONS
from .hold_button import HoldButton

from .theme import apply_theme, current_colors, state, stylesheet, colors

# Compatibility for external launchers that import the default stylesheet.
STYLE = stylesheet(colors())

MAX_ALERTS = 100
ALERT_NAMES = 12  # names shown per alert; the full list is in its tooltip


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
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(title)
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

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Space):
            self.clicked.emit()
        else:
            super().keyPressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, initial_files=None, settings=None):
        super().__init__()
        self.settings = settings if settings is not None else QSettings("InfotainmentLab", "Desktop")
        self.bridge = Bridge(str(self.settings.value("distro", "Debian")), self)
        self.bridge.configure(str(self.settings.value('engine', 'native')),
                              str(self.settings.value('vm_directory', '')))
        self.bridge.finished.connect(self.received)
        self.environment, self.session = {}, {}
        self.library = []
        self.import_queue = list(initial_files or [])
        self.busy = False
        self.active_action = None
        self.notification = None
        self.alerts = []
        self.loading_options = False
        self.loaded_device_id = None
        self.current_page = 0
        self.sim = Simulation()
        self.manual_override = False
        self.camera_window = None
        self.setWindowTitle("Infotainment Lab · tsla-infotainment-lab")
        self.resize(1360, 920)
        self.setMinimumSize(960, 640)
        self.apply_appearance()
        self.rebuild()
        QApplication.instance().styleHints().colorSchemeChanged.connect(self.system_appearance_changed)
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
        self.probe_timer = QTimer(self)
        self.probe_timer.setSingleShot(True)
        self.probe_timer.timeout.connect(lambda: self.bridge.call('probe'))
        self.probe_timer.start(200)
        for sequence, callback in (('Ctrl+O', self.choose_files), ('Ctrl+1', lambda: self.show_page(0)),
                                   ('Ctrl+2', lambda: self.show_page(1)), ('Ctrl+3', lambda: self.show_page(2))):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)

    def button(self, en, callback, primary=False):
        button = QPushButton(en.replace('&', '&&'))
        if primary: button.setObjectName("primary")
        button.clicked.connect(callback)
        return button

    def rebuild(self):
        browser_draft = self.browser_panel.export_draft() if hasattr(self, 'browser_panel') else None
        services_draft = self.services_panel.export_draft() if hasattr(self, 'services_panel') else None
        config_draft = self.config_panel.export_draft() if hasattr(self, 'config_panel') else None
        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)
        sidebar = self.sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(232)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 24, 12, 18)
        side.setSpacing(9)
        self.version_label = label(f"DESKTOP  ·  {__version__}", "muted")
        self.version_label.setAlignment(Qt.AlignCenter)
        side.addWidget(self.version_label)
        side.addSpacing(20)
        if hasattr(self, 'nav_group'):
            self.nav_group.deleteLater()
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for index, en, symbol in ((0, 'Devices', 'devices'), (1, 'Controls', 'controls'),
                                  (2, 'Camera & replay', 'camera'), (5, 'Browsers', 'screen'),
                                  (6, 'CAN & gateway', 'controls'), (7, 'Console', 'settings'), (8, 'Vehicle config', 'settings'),
                                  (3, 'Diagnostics', 'settings'), (4, 'About', 'help')):
            nav = QToolButton()
            nav.setText(en.replace('&', '&&'))
            nav.setProperty('full_text', en)
            nav.setProperty('symbol', symbol)
            nav.setToolTip(en)
            nav.setAccessibleName(en)
            nav.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            nav.setIconSize(QSize(22, 22))
            nav.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            nav.clicked.connect(lambda checked=False, i=index: self.show_page(i))
            nav.setObjectName("nav")
            nav.setIcon(icon(symbol))
            nav.setCheckable(True)
            self.nav_group.addButton(nav, index)
            side.addWidget(nav)
        side.addStretch()
        self.session_hint = label("Closing this panel keeps your device running.", "muted", True)
        side.addWidget(self.session_hint)
        side.addSpacing(16)
        self.appearance = QComboBox()
        for key, en in (('system', 'System theme'), ('light', 'Light theme'), ('dark', 'Dark theme')):
            self.appearance.addItem(en, key)
        self.appearance.setCurrentIndex(max(0, self.appearance.findData(self.settings.value('appearance', 'system'))))
        self.appearance.setAccessibleName('Appearance')
        self.appearance.currentIndexChanged.connect(self.change_appearance)
        side.addWidget(self.appearance)
        self.accent = QComboBox()
        for key, en in (('violet', 'Iris'), ('blue', 'Blue'), ('green', 'Leaf')):
            self.accent.addItem(en, key)
        self.accent.setCurrentIndex(max(0, self.accent.findData(self.settings.value('accent', 'violet'))))
        self.accent.setAccessibleName('Accent color')
        self.accent.currentIndexChanged.connect(self.change_appearance)
        side.addWidget(self.accent)
        self.compact_settings = QToolButton()
        self.compact_settings.setIcon(icon('settings'))
        self.compact_settings.setAccessibleName('Appearance')
        self.compact_settings.setToolTip(self.compact_settings.accessibleName())
        self.compact_settings.setPopupMode(QToolButton.InstantPopup)
        preferences = QMenu(self.compact_settings)
        for combo, en in ((self.appearance, 'Appearance'), (self.accent, 'Accent color')):
            menu = preferences.addMenu(en)
            for index in range(combo.count()):
                action = menu.addAction(combo.itemText(index))
                action.triggered.connect(lambda checked=False, box=combo, i=index: box.setCurrentIndex(i))
        self.compact_settings.setMenu(preferences)
        side.addWidget(self.compact_settings)
        outer.addWidget(sidebar)
        main = QWidget()
        layout = QVBoxLayout(main)
        layout.setContentsMargins(24, 25, 24, 20)
        self.page_title = label("", "title")
        title_row = QHBoxLayout()
        title_row.addWidget(self.page_title, 1)
        layout.addLayout(title_row)
        self.banner = label("Checking your Linux environment…", "notice", True)
        banner_row = QHBoxLayout()
        banner_row.addWidget(self.banner, 1)
        self.dismiss_button = QToolButton()
        self.dismiss_button.setText('×')
        self.dismiss_button.setToolTip('Dismiss message')
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
        self.can_panel = CanPanel(self)
        self.console_panel = ConsolePanel(self)
        self.config_panel = ConfigPanel(self)
        if config_draft: self.config_panel.restore_draft(config_draft)
        if browser_draft: self.browser_panel.restore_draft(browser_draft)
        for page in (self.workspace_page(), self.simulator_page(), self.camera_page(), self.diagnostics_page(), self.about_page(), self.browser_panel, self.can_panel, self.console_panel, self.config_panel):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setWidget(page)
            self.pages.addWidget(scroll)
        if services_draft: self.services_panel.restore_draft(services_draft)
        layout.addWidget(self.pages, 1)
        self.footer = label("Native Qt interface · User-provided firmware · Local simulation", "muted")
        layout.addWidget(self.footer)
        outer.addWidget(main, 1)
        tools = QFrame()
        tools.setObjectName('tools')
        rail = QHBoxLayout(tools)
        rail.setContentsMargins(0, 0, 0, 0)
        rail.setSpacing(4)
        self.tool_buttons = {}
        for name, symbol, en, callback in (
            ('center', 'screen', 'Center', lambda: self.bridge.call('focus', '--display', 'center')),
            ('cluster', 'cluster', 'Cluster', lambda: self.bridge.call('focus', '--display', 'cluster')),
            ('restart', 'restart', 'Restart', lambda: self.operation('restart')),
            ('capture', 'camera', 'Capture', lambda: self.bridge.call('capture'))):
            button = QToolButton()
            button.setIcon(icon(symbol))
            button.setIconSize(QSize(24, 24))
            button.setText(en)
            button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            button.setProperty('symbol', symbol)
            button.setAccessibleName(en)
            button.setToolTip(en)
            button.setFixedSize(44, 44)
            button.clicked.connect(callback)
            rail.addWidget(button)
            self.tool_buttons[name] = button
        title_row.addWidget(tools)
        self.setCentralWidget(root)
        self.adapt_navigation()
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
            'checking': ('Checking this computer…'),
            'ready': ('Ready for your devices'),
            'dependencies': ('Install the display and runtime components to get started.'),
            'display': ('A Linux desktop display is required. Check WSLg or your X11 session.'),
            'services': ('Enable the Linux user service manager before starting.'),
            'mounts': ('The Linux user needs access to FUSE for read-only images.'),
            'user': ('Open this app as your normal Linux user.'),
            'architecture': ('This device requires an x86_64 Linux computer.'),
            'virtual-image': ('Prepare a QEMU guest, or choose an existing guest directory.'),
            'kvm': ('The Linux user needs access to /dev/kvm.'),
        }
        return messages[readiness(self.environment)]

    def simulator_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 14, 0, 0)
        panel, inner = card()
        inner.addWidget(label("Drive the local demo", "subtitle"))
        inner.addWidget(label("These are simulated inputs. They do not connect to a vehicle. Firmware acceptance appears below.", "muted", True))
        gear_row = QHBoxLayout()
        self.gears = QButtonGroup(self)
        for gear in ("P", "R", "N", "D"):
            button = QPushButton(gear)
            button.setCheckable(True)
            button.setChecked(gear == self.sim.gear)
            button.clicked.connect(lambda checked=False, g=gear: self.set_gear(g))
            self.gears.addButton(button)
            gear_row.addWidget(button)
        self.car_off_button = QPushButton("Car off")
        self.car_off_button.setCheckable(True)
        self.car_off_button.setChecked(self.sim.car_off)
        self.car_off_button.clicked.connect(self.set_car_off)
        gear_row.addWidget(self.car_off_button)
        inner.addLayout(gear_row)
        self.sliders, self.slider_values = {}, {}
        for key, en, low, high, suffix in (
            ("speed_kph", "Dummy speed", 0, 200, "km/h"),
            ("throttle_pct", "Accelerator", 0, 100, "%"),
            ("brake_pct", "Brake", 0, 100, "%"),
            ("steering_deg", "Steering wheel", -540, 540, "°")):
            row = QHBoxLayout()
            row.addWidget(label(en))
            row.addStretch()
            value = label(f"{int(getattr(self.sim, key))} {suffix}", "eyebrow")
            row.addWidget(value)
            inner.addLayout(row)
            slider = QSlider(Qt.Horizontal)
            slider.setAccessibleName(en)
            slider.setRange(low, high)
            slider.setValue(int(getattr(self.sim, key)))
            slider.valueChanged.connect(lambda v, k=key, s=suffix: self.set_control(k, v, s))
            self.sliders[key], self.slider_values[key] = slider, value
            inner.addWidget(slider)
        row = QHBoxLayout()
        row.addWidget(label("Power meter"))
        row.addStretch()
        self.power_value = label("", "eyebrow")
        row.addWidget(self.power_value)
        inner.addLayout(row)
        power = self.services_panel.power_slider
        power.valueChanged.connect(lambda v: self.power_value.setText(f"{v:+d} kW"))
        self.power_value.setText(f"{power.value():+d} kW")
        inner.addWidget(power)
        self.radius_label = label("", "muted")
        inner.addWidget(self.radius_label)
        row = QHBoxLayout()
        row.addWidget(label("Turn signals"))
        self.indicator = QComboBox()
        for key, en in (("off", "Off"), ("left", "Left"), ("right", "Right"), ("hazard", "Hazards")):
            self.indicator.addItem(en, key)
        self.indicator.setCurrentIndex(('off', 'left', 'right', 'hazard').index(self.sim.indicator))
        self.indicator.currentIndexChanged.connect(lambda _: self.set_indicator())
        row.addWidget(self.indicator, 1)
        row.addWidget(self.button("Reset to Park", self.reset_simulator))
        inner.addLayout(row)
        drive = QWidget()
        drive_layout = QVBoxLayout(drive)
        drive_layout.setContentsMargins(0, 0, 0, 0)
        drive_layout.addWidget(panel)
        self.control_feedback = label("Start a session to send inputs. Speed is an explicit test value; the pedals do not run a physics model.", "notice", True)
        drive_layout.addWidget(self.control_feedback)
        wheel, wheel_layout = card()
        wheel_layout.addWidget(label('Steering-wheel buttons', 'subtitle'))
        pods = QHBoxLayout()
        self.wheel_buttons = []
        for side, en in (('left', 'Left · Media'), ('right', 'Right · Instruments')):
            pod = QVBoxLayout()
            pod.addWidget(label(en, 'eyebrow'))
            grid = QGridLayout()
            actions = [(key, item) for key, item in STEERING_ACTIONS.items() if item[1] == side]
            for index, (key, (english, _)) in enumerate(actions):
                button = HoldButton(english, repeat=key in ('volume_up', 'volume_down'))
                button.triggered.connect(lambda action=key: self.send_steering(action))
                button.setObjectName('wheel_' + key)
                grid.addWidget(button, index // 2, index % 2)
                self.wheel_buttons.append(button)
            pod.addLayout(grid)
            pod.addStretch()
            pods.addLayout(pod, 1)
        wheel_layout.addLayout(pods)
        wheel_layout.addWidget(label('Hold Volume + or − to adjust continuously. Release or leave the button to stop.', 'muted', True))
        wheel_layout.addWidget(label('Media buttons use the active native player. Right buttons open instrument panels; voice recognition needs its own service.', 'muted', True))
        tabs = self.services_panel.tabs
        tabs.insertTab(0, drive, 'Drive')
        tabs.insertTab(1, wheel, 'Wheel buttons')
        tabs.setCurrentIndex(0)
        layout.addWidget(self.services_panel)
        layout.addStretch()
        self.update_radius()
        return page

    def camera_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.addWidget(label("Camera feed", "subtitle"))
        layout.addWidget(label("Choose a source, then open Camera on the center display or select Reverse. The firmware receives this feed through its camera input.", "muted", True))
        self.camera_status = label('', 'notice', True)
        layout.addWidget(self.camera_status)
        self.replay_panel = ReplayPanel(self)
        layout.addWidget(self.replay_panel)
        self.camera_preview = CameraPreview()
        self.camera_preview.message = 'Choose a source to preview camera frames'
        layout.addWidget(self.camera_preview, 1)
        layout.addWidget(label('Source preview · 1 fps here; full frame rate in the firmware window', 'muted', True))
        actions = QGridLayout()
        actions.addWidget(self.button("Test pattern", self.show_pattern), 0, 0)
        actions.addWidget(self.button("Open video…", self.open_video), 0, 1)
        actions.addWidget(self.button("Center display", lambda: self.bridge.call('focus', '--display', 'center')), 0, 2)
        actions.addWidget(self.button("Separate preview", self.float_camera), 1, 0)
        actions.addWidget(self.button("Stop feed", lambda: self.bridge.call('camera', '--source', 'off')), 1, 1)
        layout.addLayout(actions)
        pipeline = QHBoxLayout()
        self.camera_path = QLineEdit(str(self.settings.value('camera_raw_path', '/tmp/tesla-sim/v4l2-back.rgb')))
        self.camera_path.setPlaceholderText('Linux path to your RGB24 output')
        self.camera_path.setAccessibleName('Existing camera pipeline path')
        pipeline.addWidget(self.camera_path, 1)
        pipeline.addWidget(self.button('Connect pipeline', self.connect_camera_pipeline))
        layout.addLayout(pipeline)
        layout.addWidget(label('Existing pipeline: 1280 × 720 RGB24. Start your writer, then connect its output file.', 'muted', True))
        return page

    def diagnostics_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.addWidget(label("See what is happening", "subtitle"))
        layout.addWidget(label("Health checks are separate from raw logs. Export creates a small report without firmware, browser profiles, raw logs or personal paths.", "muted", True))
        row = QHBoxLayout()
        row.addWidget(self.button("Check environment", lambda: self.bridge.call("probe")))
        row.addWidget(self.button("View local logs", lambda: self.bridge.call("logs")))
        row.addWidget(self.button("Export report…", lambda: self.bridge.call("report")))
        layout.addLayout(row)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText('Choose View local logs to inspect the current session, or Check environment to refresh setup checks.')
        layout.addWidget(self.log_view, 1)
        self.log_view.setMinimumHeight(240)
        self.alert_box, alerts = card()
        header = QHBoxLayout()
        header.addWidget(label('Alerts', 'subtitle'), 1)
        self.clear_alerts_button = self.button('Clear all', self.clear_alerts)
        header.addWidget(self.clear_alerts_button)
        alerts.addLayout(header)
        self.alert_empty = label('No alerts. Refused config values and the reasons the firmware restarts are listed here.', 'muted', True)
        alerts.addWidget(self.alert_empty)
        self.alert_rows = QVBoxLayout()  # plain rows: the page scrolls, not a nested list
        self.alert_rows.setSpacing(10)
        alerts.addLayout(self.alert_rows)
        layout.insertWidget(2, self.alert_box)
        self.refresh_alerts()
        return page

    def raise_alert(self, text, details=()):
        """A lasting alert, like the car's: listed under Diagnostics and counted on its sidebar entry."""
        self.alerts = (self.alerts + [(time.strftime('%H:%M'), text, list(details))])[-MAX_ALERTS:]
        self.refresh_alerts()
        self.show_message(text + '  See Diagnostics › Alerts.', True)

    def clear_alerts(self):
        self.alerts.clear()
        self.refresh_alerts()

    def refresh_alerts(self):
        while self.alert_rows.count():
            row = self.alert_rows.takeAt(0).widget()
            row.hide()
            row.deleteLater()
        for stamp, text, details in reversed(self.alerts):
            row = QFrame()
            lines = QVBoxLayout(row)
            lines.setContentsMargins(0, 0, 0, 0)
            lines.setSpacing(2)
            heading = label(f'{stamp}  ·  {text}', None, True)
            heading.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lines.addWidget(heading)
            if details:
                shown = ', '.join(details[:ALERT_NAMES]) + (f' and {len(details) - ALERT_NAMES} more' if len(details) > ALERT_NAMES else '')
                names = label(shown, 'muted', True)
                names.setTextInteractionFlags(Qt.TextSelectableByMouse)
                names.setToolTip('\n'.join(details))
                lines.addWidget(names)
            self.alert_rows.addWidget(row)
        self.alert_empty.setVisible(not self.alerts)
        self.clear_alerts_button.setEnabled(bool(self.alerts))
        nav = self.nav_group.button(3)
        nav.setText(f'Diagnostics  ({len(self.alerts)})' if self.alerts else 'Diagnostics')
        nav.setIcon(icon('warning' if self.alerts else 'settings'))

    def about_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 14, 0, 0)
        panel, inner = card()
        inner.addWidget(label("tsla-infotainment-lab", "subtitle"))
        inner.addWidget(label("A desktop workbench built from hands-on infotainment compatibility research. Import your own firmware, inspect the environment, and launch its real interface in separate desktop windows.", None, True))
        inner.addWidget(label(f"Version {__version__} supports the tested 2026.26.6.1 Model S/X MCU2 build. Other images can be identified but require a matching profile. This is user-space compatibility, not complete hardware emulation.", "muted", True))
        inner.addWidget(label("Bring your own firmware and recordings. The desktop provides local vehicle inputs, camera replay and browser integration. Vehicle services show their actual firmware response. Steering radius illustrates a 2.96 m wheelbase and 14.8:1 steering ratio.", "muted", True))
        inner.addWidget(label("Independent research project. Not affiliated with or endorsed by Tesla.", "muted", True))
        layout.addWidget(panel)
        layout.addStretch()
        return page

    def show_page(self, index):
        self.current_page = index
        self.pages.setCurrentIndex(index)
        titles = ("Device manager", "Vehicle controls", "Camera & replay",
                  "Diagnostics", "About this lab", 'Browser workspace',
                  'CAN & gateway', 'Console', 'Vehicle configuration')
        self.page_title.setText(titles[index])
        self.nav_group.button(index).setChecked(True)
        self.refresh_icons()

    def refresh_icons(self):
        c = current_colors()
        for button in self.nav_group.buttons():
            button.setIcon(icon(button.property('symbol'), c['on_secondary_container'] if button.isChecked() else c['muted']))
        for button in self.tool_buttons.values():
            button.setIcon(icon(button.property('symbol'), c['muted']))
        self.start_button.setIcon(icon('play', c['on_primary']))
        self.compact_settings.setIcon(icon('settings', c['muted']))

    def apply_appearance(self):
        apply_theme(QApplication.instance(), str(self.settings.value('appearance', 'system')),
                    str(self.settings.value('accent', 'violet')))
        if hasattr(self, 'nav_group'):
            self.refresh_icons()

    def change_appearance(self, *_):
        self.settings.setValue('appearance', self.appearance.currentData())
        self.settings.setValue('accent', self.accent.currentData())
        self.apply_appearance()

    def system_appearance_changed(self, *_):
        if self.settings.value('appearance', 'system') == 'system':
            self.apply_appearance()

    def adapt_navigation(self):
        if not hasattr(self, 'sidebar'):
            return
        compact = self.width() < 1220
        self.compact_settings.setVisible(compact)
        self.sidebar.setFixedWidth(88 if compact else 232)
        for widget in (self.version_label, self.session_hint, self.appearance, self.accent):
            widget.setVisible(not compact)
        for button in self.nav_group.buttons():
            button.setToolButtonStyle(Qt.ToolButtonIconOnly if compact else Qt.ToolButtonTextBesideIcon)
        self.library_card.setFixedWidth(242 if compact else 266)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.adapt_navigation()

    def change_distro(self, value):
        self.bridge.distro = value.strip() or "Debian"
        self.settings.setValue("distro", self.bridge.distro)

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Import firmware or maps", "",
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
        self.maps_box.addItem('No map image', None)
        selected_row = 0
        for entry in self.library:
            if entry['kind'] == 'map':
                self.maps_box.addItem(entry['version'], entry['id'])
                continue
            profile = profile_for(entry['version'], entry['variant'])
            if profile:
                entry['supported'] = True
            title = profile['name'] if profile else entry['variant']
            support = 'Ready' if entry['supported'] else 'Needs a profile'
            if profile and profile.get('experimental'):
                support = 'Experimental · launch checks required'
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
            self.show_message('An operation is already in progress.', True)
        self.update_status()

    def start_session(self):
        entry = self.selected_item()
        if not entry: return
        args = ["--id", entry["id"]]
        if self.maps_box.currentData(): args += ["--map-id", self.maps_box.currentData()]
        if not self.browser_box.isChecked(): args += ["--no-browser"]
        if not self.cluster_box.isChecked(): args += ["--no-cluster"]
        self.operation("start", *args)

    def full_reset(self):
        text = ('Delete all cached data, saved settings and the library index, as if the app had just been installed? '
                'The session stops, the firmware image is unmounted and images must be imported again. '
                'Your original files are not touched.')
        if QMessageBox.warning(self, 'Full reset', text, QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) == QMessageBox.Yes:
            self.operation('factory-reset')

    def check_qemu(self):
        entry = self.selected_item()
        if entry:
            self.operation('qemu-check', '--id', entry['id'])

    def change_engine(self, *_):
        engine = self.engine_box.currentData()
        self.settings.setValue('engine', engine)
        self.bridge.configure(engine, self.vm_directory.text().strip())
        self.vm_options.setVisible(engine == 'qemu')
        self.environment, self.session = {}, {}
        self.bridge.call('probe')
        self.update_status()

    def change_vm_directory(self):
        directory = self.vm_directory.text().strip()
        if directory == self.bridge.vm_directory:
            return
        self.settings.setValue('vm_directory', directory)
        self.bridge.configure(self.bridge.engine, directory)
        self.environment, self.session = {}, {}
        self.bridge.call('probe')
        self.update_status()

    def choose_vm_directory(self):
        directory = QFileDialog.getExistingDirectory(self, 'Choose a QEMU guest',
                                                       self.vm_directory.text())
        if directory:
            self.vm_directory.setText(directory)
            self.change_vm_directory()

    def setup_dependencies(self):
        if readiness(self.environment) not in ('dependencies', 'virtual-image'):
            if readiness(self.environment) != 'ready':
                self.show_page(3)
            self.bridge.call('probe')
            return
        text = "Install the Linux display, audio, compiler and read-only mount packages using your distribution's package manager? This changes the selected Linux environment."
        if self.bridge.engine == 'qemu':
            text = 'Download the QEMU dependencies and build a new Debian guest disk? Existing VM directories are preserved. This may take several minutes.'
        if QMessageBox.question(self, "Runtime setup", text) == QMessageBox.Yes:
            self.operation("setup")

    def send_steering(self, action):
        # Drop a repeat while the previous command is in flight. Never queue
        # held input that could continue applying after the user releases it.
        self.bridge.call('steering', '--button', action)

    def received(self, action, result):
        if action == 'ssh-key':
            self.console_panel.key_result(result)
            return
        if action in ('can', 'can-start', 'can-status'):
            self.can_panel.received(action, result)
            return
        if action == 'vehicle-services': self.services_panel.acknowledge(bool(result.get('ok')))
        if action == 'config-values': self.config_panel.acknowledge(bool(result.get('ok')), result.get('data'))
        if action in ('start', 'stop', 'restart', 'import', 'setup', 'qemu-check', 'factory-reset'):
            self.busy, self.active_action = False, None
        if not result.get('ok'):
            if action == 'steering':
                for button in self.wheel_buttons:
                    button.cancel_hold()
            if action == 'camera-preview': return
            if action == 'preview':
                self.preview_caption.setText('Preview unavailable · Open a display directly')
                return
            self.show_message(result.get('error', 'Unknown error'), True)
            self.update_status()
            return
        data = result.get('data', {})
        if action == 'qemu-check':
            self.log_view.setPlainText(json.dumps(data, indent=2, ensure_ascii=False))
            self.show_message('QEMU check finished; full firmware desktop is not verified. See Diagnostics.', True)
            self.update_status()
            return
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
            self.show_message('Camera source selected.')
            self.bridge.call('status')
        elif action in ('replay', 'vehicle-services', 'config-values', 'browser', 'steering'):
            if action == 'replay' and data.get('action') == 'play': self.manual_override = False
            if action == 'steering':
                self.show_message(data.get('warning') or 'Steering-wheel command sent.')
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
            self.show_message('Added to your library. Your original file stays in place.')
            self.next_import()
        elif action == 'setup':
            self.bridge.call('probe')
        elif action == 'factory-reset':
            self.settings.remove('devices')
            self.settings.remove('selected_device')
            self.loaded_device_id = None
            self.session, self.library = data.get('status', {}), []
            self.refresh_library()
            self.config_panel.revert()
            self.show_message('Full reset done. Import a firmware image to start again.')
            self.update_status()
        elif action == 'logs':
            self.log_view.setPlainText('\n\n'.join(f'--- {name} ---\n{text}' for name, text in data.get('logs', {}).items()))
        elif action == 'report':
            path, _ = QFileDialog.getSaveFileName(self, 'Export diagnostics', 'infotainment-lab-report.json', 'JSON (*.json)')
            if path:
                try:
                    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
                    self.show_message('Report saved.')
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
            self.preview_caption.setText('Live overview · ' + stamp + ' · Open a display to interact')
        elif action == 'capture':
            folder = QFileDialog.getExistingDirectory(self, 'Save display screenshots')
            if folder:
                try:
                    stamp = time.strftime('%Y%m%d-%H%M%S') + '-' + str(time.time_ns() % 1000000)
                    for name, encoded in data['images'].items():
                        with (Path(folder) / f'infotainment-{name}-{stamp}.png').open('xb') as stream:
                            stream.write(base64.b64decode(encoded))
                    self.show_message('Screenshots saved to your chosen folder.')
                except OSError as exc:
                    self.show_message(str(exc), True)
        self.update_status()

    def show_message(self, text, error=False):
        self.notification = (text, error, None if error else time.monotonic() + 8)
        if hasattr(self, 'banner'):
            self.banner.setText(text)
            state(self.banner, 'error', error)

    def update_status(self):
        if not hasattr(self, 'start_button') or not hasattr(self, 'tool_buttons'):
            return
        phase = self.session.get('phase', 'stopped')
        live = phase in ('starting', 'booting', 'running', 'degraded', 'stopping')
        usable = phase in ('running', 'degraded')
        for button in getattr(self, 'wheel_buttons', []):
            button.setEnabled(usable)
        self.browser_panel.update_status(self.session)
        self.replay_panel.update_status(self.session)
        self.services_panel.update_status(self.session)
        self.config_panel.update_status(self.session)
        if hasattr(self, 'control_timer') and not self.manual_override and not self.control_timer.isActive() and 'controls' not in self.bridge.pending:
            actual = self.session.get('replay', {}).get('telemetry_sample', {})
            if self.session.get('camera', {}).get('mode') == 'replay' and self.session.get('replay', {}).get('phase') in ('playing', 'paused', 'seeking-playing', 'ended') and actual:
                self.sync_control_widgets(actual)
        camera = self.session.get('camera', {})
        sources = {'pattern': ('Test pattern'), 'video': ('Local video'), 'replay': ('Recorded drive'), 'raw': ('Existing pipeline'), 'off': ('Off')}
        camera_text = sources.get(camera.get('mode'), 'Camera')
        if camera.get('source_name'): camera_text += ' · ' + camera['source_name']
        if camera.get('frame_held'):
            camera_text += ' · Paused — holding frame' if camera.get('phase') == 'paused' else ' · Ended — holding last frame'
        elif camera.get('firmware_receiving'):
            camera_text += ' · Firmware receiving' + f" · {camera.get('fps', 0):.1f} fps · 1280 × 720"
        elif camera.get('source_ready'):
            camera_text += ' · Source ready. Open Camera on the center display.'
        elif not live:
            camera_text = 'Start a device to connect the camera feed.'
            self.camera_preview.set_frame(QPixmap())
            if self.camera_window: self.camera_window.set_frame(QPixmap())
        elif camera.get('phase') == 'off':
            camera_text += ' · Feed stopped'
        else:
            camera_text += ' · Waiting for frames. Check the source file and writer.'
        self.camera_status.setText(camera_text)
        self.camera_status.setToolTip(camera.get('detail', ''))
        selected = self.selected_item()
        ready = readiness(self.environment) == 'ready'
        self.qemu_button.setEnabled(bool(selected and selected.get('kind', 'firmware') == 'firmware') and not self.busy)
        self.start_button.setEnabled(bool(selected and selected.get('supported')) and ready and not self.busy and not live)
        self.stop_button.setEnabled(live and not self.busy)
        self.reset_button.setEnabled(not self.busy)
        self.engine_box.setEnabled(not live and not self.busy)
        self.vm_directory.setEnabled(not live and not self.busy)
        self.vm_browse.setEnabled(not live and not self.busy)
        self.setup_button.setEnabled(not self.busy and not live and readiness(self.environment) != 'checking')
        self.setup_button.setText('Check again' if ready else 'Prepare computer')
        self.setup_hint.setText(self.setup_text())
        for control in (self.cluster_box, self.browser_box, self.maps_box, self.distro_box):
            control.setEnabled(not live and not self.busy)
        self.items.setEnabled(not live and not self.busy)
        for name, button in self.tool_buttons.items():
            button.setEnabled((usable and not self.busy) if name in ('center', 'cluster', 'restart', 'capture') else True)
        self.tool_buttons['cluster'].setEnabled(usable and self.session.get('components', {}).get('instruments') == 'running' and not self.busy)
        self.tool_buttons['restart'].setToolTip('Restart this device and return controls to Park')
        title = 'Add your first device'
        subtitle = 'Bring your firmware. We will check compatibility before launch.'
        if selected:
            profile = profile_for(selected['version'], selected['variant'])
            title = profile['name'] if profile else selected['variant']
            subtitle = selected['version'] + ' · ' + 'Local firmware'
            if profile and profile.get('single_display'):
                self.cluster_box.setEnabled(False)
                subtitle += ' · ' + 'Single display'
            if not selected.get('supported'):
                subtitle += ' · ' + 'Launch profile unavailable'
            self.item_detail.setText('SHA-256 recorded · ' + selected['sha256'][:12] + '…')
        else:
            self.item_detail.setText('Add a firmware image to create a device.')
        profile = profile_for(selected['version'], selected['variant']) if selected else None
        self.overview.single_display = bool(profile and profile.get('single_display'))
        self.device_title.setText(title)
        self.device_subtitle.setText(subtitle)
        phases = {'stopped': ('Offline'), 'starting': ('Starting'), 'booting': ('Booting'),
                  'stopping': ('Stopping'), 'running': ('Running'),
                  'degraded': ('Needs attention'), 'failed': ('Needs attention')}
        self.phase_badge.setText(phases.get(phase, 'Unknown'))
        state(self.phase_badge, 'phase', phase)
        self.steps.setText('1  Prepare computer' + ('  ✓' if ready else '  ○') + '     /     ' +
                           '2  Add firmware' + ('  ✓' if selected else '  ○') + '     /     ' +
                           '3  Start your device' + ('  ✓' if usable else '  ○'))
        labels = {'center': ('Center'), 'instruments': ('Instruments'), 'chromium': ('Chromium')}
        for key, metric in self.metrics.items():
            running = self.session.get('components', {}).get(key) == 'running' and live
            metric.setText(('●  ' if running else '○  ') + labels[key])
            state(metric, 'active', running)
        host = self.session.get('host', {})
        renderer = self.session.get('renderer', 'Graphics checked at launch')
        cluster_graphics = self.session.get('display_graphics', {}).get('cluster')
        if cluster_graphics and not cluster_graphics.get('accelerated'):
            renderer += ' · Instruments: software rendering'
        if host.get('total_bytes'):
            renderer += '  ·  ' + size_label(host.get('free_bytes', 0)) + ' free of ' + size_label(host['total_bytes'])
        self.renderer_label.setText(renderer)
        self.progress.setVisible(self.busy or phase in ('starting', 'booting', 'stopping'))
        if not live:
            self.overview.set_frames(QPixmap(), QPixmap())
        if self.notification and self.notification[2] and time.monotonic() > self.notification[2]:
            self.notification = None
        self.dismiss_button.setVisible(self.notification is not None)
        error = False
        if self.notification:
            text, error, _ = self.notification
        elif self.busy:
            messages = {'start': ('Starting your device…'), 'stop': ('Stopping your device…'),
                        'restart': ('Restarting your device…'), 'import': ('Inspecting firmware and recording its checksum…'),
                        'setup': ('Preparing your computer. This may take a few minutes…')}
            text = messages.get(self.active_action, 'Working…')
        elif phase == 'failed':
            text, error = self.session.get('error', 'Session failed'), True
        elif phase == 'starting' and self.session.get('configuration_restart'):
            names = self.session.get('changed_dvs', [])
            text = ('Restarting: the firmware applies changed ' + ', '.join(names[:4]) + ('…' if len(names) > 4 else '') if names
                    else 'Restarting: the firmware applies its display settings…') + '  See Diagnostics › Alerts.'
        elif phase in ('starting', 'booting'):
            text = 'Starting displays and loading firmware resources…'
        elif phase == 'stopping':
            text = 'Waiting for the guest to shut down…'
        elif usable:
            battery = self.session.get('vehicle_services', {}).get('state', {}).get('battery_percent', 50)
            text = 'Device running' + '  ·  ' + ('Internet connected' if host.get('online') else 'Internet unavailable') + '  ·  ' + f'Battery {battery:g}% · simulated'
            if phase == 'degraded':
                text += '  ·  ' + 'A component needs attention. Open Diagnostics.'
        elif not ready:
            text = self.setup_text()
        elif selected and not selected.get('supported'):
            text = 'This firmware needs a tested launch profile before it can run.'
        else:
            text = 'Ready. Choose a device or drop in firmware to get started.'
        self.banner.setText(text)
        state(self.banner, 'error', error)
        feedback = self.session.get('controls', {}).get('firmware', {}).get('com.tesla.CenterDisplay', {})
        if feedback and live:
            names = {'gear': ('Gear'), 'speed_kph': ('Speed'), 'throttle_pct': ('Accelerator'),
                     'brake_pct': ('Brake'), 'steering_deg': ('Steering'), 'indicator': ('Signals'), 'rails': ('Power')}
            states = {'accepted': ('accepted'), 'unsupported': ('unavailable'), 'rejected': ('rejected')}
            self.control_feedback.setText('Firmware feedback: ' + '  ·  '.join(
                f'{names[name]}: {states.get(value, (value, value))}' for name, value in feedback.items() if name in names))
        elif not live:
            self.control_feedback.setText('Start a device to use the local simulator.')

    def set_car_off(self, off):
        self.manual_override = True
        self.sim.car_off = off
        if off:
            self.sim.gear = "P"
            for button in self.gears.buttons(): button.setChecked(button.text() == "P")
            self.sliders["speed_kph"].setValue(0)
            self.sliders["throttle_pct"].setValue(0)
        self.control_timer.start(180)

    def set_gear(self, gear):
        self.manual_override = True
        self.sim.gear = gear
        self.sim.car_off = False
        self.car_off_button.setChecked(False)
        if gear == "P":
            self.sliders["speed_kph"].setValue(0)
            self.sliders["throttle_pct"].setValue(0)
        self.control_timer.start(180)

    def sync_control_widgets(self, values):
        self.sim = Simulation.parse(values)
        for button in self.gears.buttons(): button.setChecked(button.text() == self.sim.gear)
        self.car_off_button.setChecked(self.sim.car_off)
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
        self.radius_label.setText("Illustrative turn radius: " + (f"{radius:.1f} m" if radius else "straight"))

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
        self.car_off_button.setChecked(False)
        for slider in self.sliders.values(): slider.setValue(0)
        self.indicator.setCurrentIndex(0)
        self.control_timer.start(180)

    def show_pattern(self):
        self.bridge.call('camera', '--source', 'pattern')

    def open_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open a local camera clip", "", "Video (*.mp4 *.mkv *.webm *.mov *.avi);;All files (*)")
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
            QMessageBox.information(self, "Infotainment Lab", "Wait for the current operation to finish before closing.")
            event.ignore()
            return
        if self.camera_window: self.camera_window.close()
        for timer in (self.probe_timer, self.poll, self.preview_timer, self.camera_timer, self.control_timer):
            timer.stop()
        for button in self.wheel_buttons:
            button.cancel_hold()
        # The service owns the session. Closing this control panel does not
        # discard the user's running displays or terminate unrelated apps.
        event.accept()


def main():
    parser = argparse.ArgumentParser(description="Infotainment Lab native desktop application")
    parser.add_argument("files", nargs="*")
    parser.add_argument("--page", type=int, choices=range(8), default=0)
    parser.add_argument("--screenshot", help="Save this application's rendered window for documentation")
    parser.add_argument("--quit-after", type=int, default=0, help="Exit after N seconds for packaging smoke tests")
    args = parser.parse_args()
    if os.environ.get('WSL_DISTRO_NAME'):
        # Use WSLg's XWayland path for consistent native widget rendering.
        os.environ.setdefault('QT_QPA_PLATFORM', 'xcb')
        os.environ.setdefault('QT_X11_NO_MITSHM', '1')
        from .host_graphics import environment as graphics_environment
        os.environ.update(graphics_environment(is_wsl=True))
        # WSLg does not pass the Windows display scale to X11 clients.
        from .display_scale import qt_environment
        os.environ.update(qt_environment())
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Infotainment Lab")
    app.setDesktopFileName('infotainment-lab')
    app.setApplicationVersion(__version__)
    app.setWindowIcon(icon('devices', colors()['primary']))
    app.setStyle("Fusion")
    apply_theme(app)
    instance = None
    if not args.screenshot and not args.quit_after:
        instance = DesktopInstance(app)
        try:
            if not instance.acquire({'files': args.files}):
                return 0
        except RuntimeError as exc:
            QMessageBox.critical(None, 'Infotainment Lab', str(exc))
            return 1
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
