"""Desktop controls for browser views, recorded drives and local vehicle state."""
import json
import csv
import io
import re
import shlex
import os
from PySide6.QtCore import Qt, QProcess, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QApplication, QPushButton, QSlider, QListWidget, QStackedWidget, QVBoxLayout, QWidget, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView)

from .material_widgets import MaterialSwitch as QCheckBox
from .vehicle_services import FIELD_SPECS, VehicleServices
from .places import PLACES
from . import vehicle_options


class SideTabs(QWidget):
    """A category list beside the pages: QTabWidget's tab API, for more tabs than a row can hold."""

    def __init__(self):
        super().__init__()
        self.names, self.pages = QListWidget(), QStackedWidget()
        self.names.setFixedWidth(190)
        self.names.setAccessibleName('Categories')
        self.names.currentRowChanged.connect(self.pages.setCurrentIndex)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.names)
        row.addWidget(self.pages, 1)

    def insertTab(self, index, page, text):
        self.pages.insertWidget(index, page)
        self.names.insertItem(index, text)
        if self.names.currentRow() < 0: self.names.setCurrentRow(0)

    def addTab(self, page, text):
        self.insertTab(self.names.count(), page, text)

    def count(self): return self.names.count()
    def tabText(self, index): return self.names.item(index).text()
    def currentIndex(self): return self.names.currentRow()
    def setCurrentIndex(self, index): self.names.setCurrentRow(index)


class Panel(QFrame):
    def __init__(self, window):
        super().__init__()
        self.setObjectName('panel')
        self.window = window
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(24, 24, 24, 24)
        self.layout.setSpacing(12)

    def text(self, en, style='muted'):
        item = QLabel(en)
        item.setObjectName(style)
        item.setWordWrap(True)
        self.layout.addWidget(item)
        return item

    def send(self, backend_action, **payload):
        if backend_action == 'config-values':
            payload['single_display'] = self.window.overview.single_display
        return self.window.bridge.call(backend_action, '--payload', json.dumps(payload))


class BrowserPanel(Panel):
    def __init__(self, window):
        super().__init__(window)
        self.text('Open an address in Browser or Card view. Theater opens the firmware’s app catalog.')
        self.url = QLineEdit()
        self.url.setPlaceholderText('https://…   Leave blank for the local browser check')
        self.url.setAccessibleName('Website address')
        self.layout.addWidget(self.url)
        row = QHBoxLayout()
        self.buttons = []
        for mode, en in (('browser', 'Browser'), ('card', 'Card view'), ('theater', 'Theater')):
            button = window.button(en, lambda checked=False, m=mode: self.open(m))
            row.addWidget(button)
            self.buttons.append(button)
        self.layout.addLayout(row)
        self.health = self.text('', 'notice')
        self.media_health = self.text('', 'notice')
        self.audio_health = self.text('', 'notice')
        self.text('In the browser check page, drag the slider, select text and move the tile. Use a parked simulation for video playback.')
        self.layout.addStretch()

    def open(self, mode):
        args = ['--mode', mode]
        if self.url.text().strip(): args += ['--url', self.url.text().strip()]
        self.window.bridge.call('browser', *args)

    def export_draft(self):
        return {'url': self.url.text()}

    def restore_draft(self, draft):
        self.url.setText(draft.get('url', ''))

    def update_status(self, session):
        live = session.get('phase') in ('running', 'degraded')
        components = session.get('components', {})
        for button in self.buttons: button.setEnabled(live and components.get('chromium') == 'running')
        modes = [('chromium', 'Browser'), ('chromium-card', 'Card'), ('chromium-theater', 'Theater')]
        self.health.setText('  ·  '.join(en + (' ●' if live and components.get(key) == 'running' else ' ○') for key, en in modes))
        media = session.get('media', {}).get('state')
        audio = session.get('audio_transport', {})
        self.audio_health.setVisible(live and audio.get('phase') in ('degraded', 'failed', 'unavailable'))
        self.audio_health.setText('Audio output is unavailable. Check your desktop sound output.')
        self.audio_health.setToolTip(audio.get('detail', ''))
        self.media_health.setVisible(live and media not in (None, 'disabled'))
        if media == 'peer-profile-rejected':
            self.media_health.setText('Spotify is unavailable: the firmware rejected the media process security profile. This environment needs a compatible native service sandbox.')
        elif media == 'waiting-services':
            self.media_health.setText('Starting native music services…')
        else:
            self.media_health.setText('Music services are running. Sources that sign in directly with their provider, such as Amazon Music, can log in. Spotify and Apple Music sign in through Tesla\'s servers, which the lab does not reach.')


class ReplayPanel(Panel):
    def __init__(self, window):
        super().__init__(window)
        self.duration = 0
        self.phase = 'idle'
        self.text('Recorded drive', 'subtitle')
        self.text('Replay the video and its embedded driving data together. Moving a vehicle control takes over from the recording.')
        row = QHBoxLayout()
        row.addWidget(window.button('Open dashcam MP4…', self.open))
        self.play = window.button('Play', self.toggle_play)
        row.addWidget(self.play)
        self.take_over = window.button('Take over', lambda: self.send('replay', action='manual'))
        row.addWidget(self.take_over)
        self.rate = QComboBox()
        for speed in (.25, .5, 1, 1.5, 2): self.rate.addItem(f'{speed:g}×', speed)
        self.rate.setCurrentIndex(2)
        self.rate.setAccessibleName('Playback speed')
        self.rate.currentIndexChanged.connect(lambda _: self.send('replay', action='rate', rate=self.rate.currentData()))
        row.addWidget(self.rate)
        self.loop = QCheckBox('Loop')
        self.loop.setChecked(True)
        self.loop.toggled.connect(lambda value: self.send('replay', action='loop', loop=value))
        row.addWidget(self.loop)
        self.layout.addLayout(row)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.setAccessibleName('Replay position')
        self.seek.sliderReleased.connect(self.send_seek)
        self.seek.actionTriggered.connect(lambda _: self.send_seek() if not self.seek.isSliderDown() else None)
        self.layout.addWidget(self.seek)
        self.feedback = self.text('Choose a dashcam recording with embedded telemetry.', 'notice')

    def open(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Open a recorded drive', '', 'Dashcam (*.mp4)')
        if path: self.window.bridge.call('camera', '--source', 'replay', '--path', path)

    def toggle_play(self):
        self.send('replay', action='pause' if self.phase in ('playing', 'seeking-playing') else 'play')

    def send_seek(self):
        if self.duration > 0:
            self.send('replay', action='seek', position_seconds=self.seek.sliderPosition() / 1000 * self.duration)

    def update_status(self, session):
        replay = session.get('replay', {})
        self.phase = replay.get('phase', 'idle')
        live = session.get('phase') in ('running', 'degraded') and session.get('camera', {}).get('mode') == 'replay'
        self.duration = replay.get('duration_seconds', 0)
        position = replay.get('position_seconds', 0)
        for widget in (self.play, self.seek, self.rate, self.loop): widget.setEnabled(live and self.phase != 'error')
        self.take_over.setEnabled(live)
        self.play.setText('Pause' if self.phase in ('playing', 'seeking-playing') else 'Play')
        if not self.seek.isSliderDown(): self.seek.setValue(round(position / self.duration * 1000) if self.duration else 0)
        for widget, value in ((self.rate, replay.get('rate', 1)), (self.loop, replay.get('loop', True))):
            widget.blockSignals(True)
            if widget is self.rate: widget.setCurrentIndex(max(0, widget.findData(value)))
            else: widget.setChecked(value)
            widget.blockSignals(False)
        phases = {'playing': ('Playing'), 'paused': ('Paused'), 'manual': ('Manual controls'), 'ready': ('Ready · press Play'),
                  'ended': ('Finished'), 'error': ('Unable to replay'), 'seeking-playing': ('Seeking')}
        if live:
            text = phases.get(self.phase, 'Loading') + f'  ·  {position:.1f} / {self.duration:.1f} s'
            controls = replay.get('telemetry_sample', {})
            if controls:
                text += f"  ·  {controls.get('gear', '')}  {controls.get('speed_kph', 0):.1f} km/h"
                text += '  ·  Steering ' + f"{controls.get('steering_deg', 0):.1f}°"
                text += '  ·  Accelerator ' + f"{controls.get('throttle_pct', 0):.1f}%"
            if replay.get('error'): text += '  ·  ' + replay['error']
            self.feedback.setText(text)
        else:
            self.feedback.setText('Choose a dashcam recording with embedded telemetry.')


class ServicesPanel(Panel):
    def __init__(self, window):
        super().__init__(window)
        self.dirty = set()
        self.pending = None
        self.awaiting = {}
        self.live = False
        self.widgets, self.results = {}, {}
        self.text('Changes apply as you make them. Each field shows the firmware response.')
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.apply)
        self.tabs = SideTabs()
        self.layout.addWidget(self.tabs)
        defaults = VehicleServices().as_dict()
        for group, en in (('climate', 'Climate'), ('closures', 'Doors'), ('lights', 'Lights'),
                               ('energy', 'Energy'), ('audio', 'Audio'), ('navigation', 'Navigation'), ('tires', 'Tires'),
                               ('parking', 'Park Assist'), ('driver_assistance', 'Self-Driving simulation'),
                               ('modes', 'Modes')):
            page = QWidget()
            form = QFormLayout(page)
            form.setContentsMargins(20, 24, 20, 24)
            form.setSpacing(14)
            if group == 'navigation':
                self.place_box = QComboBox()
                self.place_box.setAccessibleName('Jump to')
                self.place_box.setToolTip('Moves the simulated GPS to a big city. Navigation needs a map image that covers it (EU, or TeslaMaps for the US).')
                self.place_box.activated.connect(self.jump_to_place)
                form.addRow('Jump to', self.place_box)
            if group == 'parking':
                notice = QLabel('Local simulation: adjustable ultrasonic distances only. No camera detection or automatic steering. '
                                'In Vehicle config, enable FEATURE_parkAssistEnabled, select Valeo or Tesla for '
                                'VAPI_parkAssist, and disable GUI_useVisionParkAssist.')
                notice.setWordWrap(True)
                notice.setObjectName('notice')
                form.addRow(notice)
            if group == 'driver_assistance':
                notice = QLabel('Model 3 lab interface simulation. The native Start/Stop button changes the displayed '
                                'FSD state only; speed, gear and steering remain under your control. '
                                'Requires the FSD menus and Start from Park preferences to be enabled, then a device restart. '
                                'Once that layout is ready, this switch applies immediately. Each restart begins disengaged.')
                notice.setWordWrap(True)
                notice.setObjectName('notice')
                form.addRow(notice)
            for name, spec in FIELD_SPECS.items():
                if spec['group'] != group: continue
                value = defaults[name]
                if spec.get('choices'):
                    widget = QComboBox()
                    for index, choice in enumerate(spec['choices']):
                        widget.addItem(choice, choice)
                    widget.setCurrentIndex(widget.findData(value))
                    widget.currentIndexChanged.connect(lambda _, n=name: self.field_changed(n))
                elif spec['type'] == 'bool':
                    widget = QCheckBox()
                    widget.setChecked(value)
                    widget.toggled.connect(lambda _, n=name: self.field_changed(n))
                elif spec['type'] == 'str' or spec.get('nullable'):
                    widget = QLineEdit('' if value is None else str(value))
                    widget.setPlaceholderText('Unset')
                    widget.textEdited.connect(lambda _, n=name: self.touch(n))
                else:
                    widget = QDoubleSpinBox()
                    widget.setRange(spec['min'], spec['max'])
                    widget.setDecimals(0 if spec['type'] == 'int' else 1)
                    widget.setValue(value)
                    widget.valueChanged.connect(lambda _, n=name: self.touch(n))
                widget.setAccessibleName(spec['label'])
                self.widgets[name] = widget
                row = QHBoxLayout()
                row.addWidget(widget, 1)
                result = QLabel('—')
                result.setObjectName('muted')
                row.addWidget(result)
                self.results[name] = result
                form.addRow(spec['label'], row)
            self.tabs.addTab(page, en)
        self.tabs.insertTab(0, self.vehicle_page(window), 'Vehicle')
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(20, 24, 20, 24)
        box.setSpacing(14)
        self.alert_name = QLineEdit()
        self.alert_name.setPlaceholderText('Alert name, for example BMS_w001_HW_Over_Current')
        self.alert_name.setAccessibleName('Alert name')
        self.alert_name.returnPressed.connect(lambda: self.change_alert('set'))
        row = QHBoxLayout()
        row.addWidget(self.alert_name, 1)
        row.addWidget(window.button('Raise', lambda: self.change_alert('set')))
        row.addWidget(window.button('Clear', lambda: self.change_alert('clear')))
        row.addWidget(window.button('Clear all', lambda: self.send('vehicle-alerts', clear_all=True)))
        box.addLayout(row)
        self.alert_list = QLabel('No active alerts.')
        self.alert_list.setWordWrap(True)
        box.addWidget(self.alert_list)
        note = QLabel('Raised alerts are served as the vehicle alert daemon would and appear in the firmware Service Mode panel. Nothing is sent to a vehicle.')
        note.setObjectName('muted')
        note.setWordWrap(True)
        box.addWidget(note)
        box.addStretch()
        self.tabs.addTab(page, 'Alerts')
        spin = self.widgets['power_level']
        spin.setSingleStep(1)
        self.power_slider = QSlider(Qt.Horizontal)
        self.power_slider.setRange(int(FIELD_SPECS['power_level']['min']), int(FIELD_SPECS['power_level']['max']))
        self.power_slider.setAccessibleName(FIELD_SPECS['power_level']['label'])
        self.power_slider.valueChanged.connect(spin.setValue)
        self.feedback = self.text('', 'notice')
        self.text('The local model covers climate, body indicators, energy, audio, trip data and simulated tire pressure. Native tire pressure follows the selected display units. Connected accounts, physical vehicle hardware and live traffic require their own services.')
        self.layout.addStretch()

    def change_alert(self, action):
        name = self.alert_name.text().strip()
        if name and self.send('vehicle-alerts', **{action: [name]}):
            self.alert_name.clear()

    def sync_power(self):
        """Mirror the power_level field onto the Drive tab slider without re-sending it."""
        self.power_slider.blockSignals(True)
        self.power_slider.setValue(round(self.widgets['power_level'].value()))
        self.power_slider.blockSignals(False)

    def touch(self, name):
        self.dirty.add(name)
        self.timer.start()

    def apply(self):
        if self.pending is not None or not self.live:
            return
        payload = {}
        try:
            for name in self.dirty:
                payload[name] = self.field_value(name)
            if payload and self.send('vehicle-services', **payload):
                self.pending = payload
                if payload.keys() & {'latitude_deg', 'longitude_deg'} and not self.window.maps_box.currentData():
                    self.window.show_message('No map image is loaded, so navigation may not work at this location.', True)
        except ValueError:
            self.window.show_message('Enter a valid number for location and heading.', True)

    def show_places(self, eu):
        """The Jump to list follows the market switch: EU cities with EU market on, US cities otherwise."""
        self.place_box.clear()
        self.place_box.addItem('Choose a city…', None)
        for region, name, lat, lon in PLACES:
            if region == ('EU' if eu else 'US'):
                self.place_box.addItem(name, (lat, lon))

    def jump_to_first_place(self):
        """A market switch moves the car to the new market's first city, so the map does not loop between regions."""
        if self.place_box.count() > 1:
            self.place_box.setCurrentIndex(1)
            self.jump_to_place(None)
            self.apply()

    def jump_to_place(self, _):
        place = self.place_box.currentData()
        if place:
            for name, value in zip(('latitude_deg', 'longitude_deg'), place):
                self.widgets[name].setText(str(value))
                self.touch(name)

    def field_changed(self, name):
        self.touch(name)
        if name not in ('headlights', 'exterior_light_mode', 'ambient_dark'):
            return
        mode = self.widgets['exterior_light_mode']
        headlight = self.widgets['headlights']
        if name == 'headlights':
            mode.blockSignals(True)
            mode.setCurrentIndex(mode.findData('On' if headlight.isChecked() else 'Off'))
            mode.blockSignals(False)
            self.touch('exterior_light_mode')
        else:
            enabled = mode.currentData() == 'On' or (mode.currentData() == 'Auto' and self.widgets['ambient_dark'].isChecked())
            headlight.blockSignals(True)
            headlight.setChecked(enabled)
            headlight.blockSignals(False)
            self.dirty.discard('headlights')

    def field_value(self, name):
        widget, spec = self.widgets[name], FIELD_SPECS[name]
        if isinstance(widget, QComboBox): return widget.currentData()
        if spec['type'] == 'bool': return widget.isChecked()
        if spec['type'] == 'str': return widget.text()
        if spec.get('nullable'): return float(widget.text()) if widget.text().strip() else None
        return widget.value()

    def acknowledge(self, success):
        # Queue acceptance is not a backend acknowledgement. Keep the edits
        # until the worker reports the accepted values in its next snapshot.
        if self.pending is not None and success:
            self.awaiting.update(self.pending)
        self.pending = None
        if self.dirty - self.awaiting.keys(): self.timer.start()

    def export_draft(self):
        values = {name: widget.text() if isinstance(widget, QLineEdit) else self.field_value(name)
                  for name, widget in self.widgets.items()}
        return {'values': values, 'dirty': sorted(self.dirty), 'pending': self.pending,
                'awaiting': dict(self.awaiting), 'tab': self.tabs.currentIndex()}

    def restore_draft(self, draft):
        for name, value in draft.get('values', {}).items():
            if name not in self.widgets: continue
            widget = self.widgets[name]
            widget.blockSignals(True)
            if isinstance(widget, QLineEdit): widget.setText(value)
            elif isinstance(widget, QComboBox): widget.setCurrentIndex(widget.findData(value))
            elif isinstance(widget, QCheckBox): widget.setChecked(value)
            else: widget.setValue(value)
            widget.blockSignals(False)
        self.dirty = set(draft.get('dirty', ())) & self.widgets.keys()
        self.pending = draft.get('pending')
        self.awaiting = dict(draft.get('awaiting', {}))
        self.tabs.setCurrentIndex(draft.get('tab', 0))
        self.sync_power()

    def update_status(self, session):
        live = self.live = session.get('phase') in ('running', 'degraded')
        if live and self.pending is None and self.dirty - self.awaiting.keys() and not self.timer.isActive(): self.timer.start()
        service = session.get('vehicle_services', {})
        state = service.get('state', {})
        firmware = service.get('firmware', {})
        center = firmware.get('com.tesla.CenterDisplay', {})
        for name, widget in self.widgets.items():
            if name in self.awaiting and name in state and state[name] == self.awaiting[name]:
                try:
                    if self.field_value(name) == self.awaiting[name]: self.dirty.discard(name)
                except ValueError:
                    pass
                del self.awaiting[name]
            if name in state and name not in self.dirty and not widget.hasFocus():
                value = state[name]
                widget.blockSignals(True)
                if isinstance(widget, QCheckBox): widget.setChecked(value)
                elif isinstance(widget, QComboBox): widget.setCurrentIndex(widget.findData(value))
                elif isinstance(widget, QLineEdit): widget.setText('' if value is None else str(value))
                else: widget.setValue(value)
                widget.blockSignals(False)
            result = center.get(name, 'pending')
            if isinstance(result, dict): result = result.get('status', 'pending')
            states = {'accepted': ('Applied'), 'partial': ('Partial'), 'unsupported': ('Local only'), 'local-model': ('Local only'), 'mismatch': ('Not applied'), 'rejected': ('Not accepted')}
            self.results[name].setText(states.get(result, '—') if live else '—')
        self.sync_power()
        alerts = session.get('alerts', [])
        self.alert_list.setText('Active: ' + ', '.join(alerts) if alerts else 'No active alerts.')
        link = session.get('display_link', {})
        connected = link.get('connected', {})
        synced = live and connected.get('center') and connected.get('cluster')
        if synced:
            self.feedback.setText('Center ↔ Instruments' + '  ·  ' + str(link.get('synchronized_count', 0)) + ' shared fields synchronized')
        else:
            self.feedback.setText('Waiting for both displays to synchronize.' if live else 'Start a device to use vehicle services.')

    def vehicle_page(self, window):
        """Model, paint, wheels, Autopilot hardware and market: car config, so Apply confirms and restarts the device."""
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(20, 24, 20, 24)
        form.setSpacing(14)
        self.vehicle_boxes = {}
        for key, label, items in (('model', 'Model', list(vehicle_options.MODELS)),
                                  ('paint', 'Paint', list(vehicle_options.PAINT)),
                                  ('wheel', 'Wheels', list(vehicle_options.WHEELS)),
                                  ('autopilot', 'Autopilot hardware', list(vehicle_options.AUTOPILOT))):
            box = QComboBox()
            for item in items:
                box.addItem(vehicle_options.AUTOPILOT.get(item, item) + (f' ({item})' if key == 'autopilot' else ''), item)
            box.setAccessibleName(label)
            self.vehicle_boxes[key] = box
            form.addRow(label, box)
        # A model change picks that model's stock wheel.
        self.vehicle_boxes['model'].currentIndexChanged.connect(lambda _: self.vehicle_boxes['wheel'].setCurrentIndex(
            self.vehicle_boxes['wheel'].findData(vehicle_options.DEFAULT_WHEEL[self.vehicle_boxes['model'].currentData()])))
        self.vehicle_boxes['wheel'].setCurrentIndex(self.vehicle_boxes['wheel'].findData('Pinwheel18'))
        self.vehicle_boxes['paint'].setCurrentIndex(self.vehicle_boxes['paint'].findData('UltraRed'))
        self.vehicle_boxes['autopilot'].setCurrentIndex(self.vehicle_boxes['autopilot'].findData('TeslaAP3'))
        self.market_box = QCheckBox('EU market')
        self.market_box.setToolTip('EU car settings (ES, km, °C, bar, R79, English GB) or North American (US, miles, °F, psi, English US). Takes effect on Apply and restarts the device.')
        self.market_box.toggled.connect(window.market_edited)
        window.market_box = self.market_box
        self.market_box.toggled.connect(self.show_places)
        self.show_places(self.market_box.isChecked())
        form.addRow(self.market_box)
        form.addRow(window.button('Apply', lambda: window.vehicle_changed(
            {**{key: box.currentData() for key, box in self.vehicle_boxes.items()}, 'market': self.market_box.isChecked()})))
        note = QLabel('Model 3 and Model Y only on the single-display image. Autopilot hardware sets the driver-assist profile; '
                      'Service Mode\'s own hardware readout needs a value the firmware does not supply here.')
        note.setObjectName('muted')
        note.setWordWrap(True)
        form.addRow(note)
        return page

    def update_vehicle(self, current):
        for box, value in zip(self.vehicle_boxes.values(), current):
            if value is not None and box.findData(value) >= 0 and not box.hasFocus():
                box.blockSignals(True)
                box.setCurrentIndex(box.findData(value))
                box.blockSignals(False)


class GatewayPanel(Panel):
    """Read and write frames through the emulated gateway.

    The gateway starts locked: write requests from this panel are refused until
    the lab unlock handshake succeeds. The secret below is this lab's own shared
    value, not a vehicle credential.
    """

    CHANNELS = (('veh', 'VEH · vehicle'), ('ch', 'CHASSIS'),
                ('party', 'PARTY · diagnostic'))
    PROFILES = (('lab', 'Lab frames'),
                ('model3', 'Model 3 · opendbc'),
                ('models', 'Model S/X · opendbc + tesla_can_signals'))

    def __init__(self, window):
        super().__init__(window)
        self.since = 0
        self.text('CAN bus and gateway', 'subtitle')
        self.text('An emulated gateway routes frames between the local channels and the infotainment Ethernet side. '
                  'Definitions and identifiers are this lab’s own; a decoded value is not evidence about a vehicle. '
                  'Diagnostic requests, including Service Mode tasks, pass only while unlocked and in Service Mode.')
        row = QHBoxLayout()
        self.backend_box = QComboBox()
        for key, en in (('auto', 'Automatic transport'),
                            ('socketcan', 'SocketCAN (vcan)'),
                            ('software', 'Software hub')):
            self.backend_box.addItem(en, key)
        self.backend_box.setAccessibleName('CAN transport')
        row.addWidget(self.backend_box)
        self.profile_box = QComboBox()
        for key, en in self.PROFILES:
            self.profile_box.addItem(en, key)
        self.profile_box.setAccessibleName('Bus profile')
        self.profile_box.setToolTip('Public signal databases are downloaded at a pinned commit on first start.')
        row.addWidget(self.profile_box)
        row.addWidget(window.button('Start service', self.start_service))
        row.addWidget(window.button('Refresh', self.refresh))
        self.layout.addLayout(row)

        unlock_row = QHBoxLayout()
        self.secret = QLineEdit('infotainment-lab')
        self.secret.setAccessibleName('Gateway lab secret')
        self.secret.setPlaceholderText('Gateway lab secret')
        unlock_row.addWidget(self.secret, 1)
        unlock_row.addWidget(window.button('Unlock gateway', self.unlock))
        unlock_row.addWidget(window.button('Lock', self.lock))
        self.layout.addLayout(unlock_row)
        self.state = self.text('Start the service to see the channels.', 'notice')

        send_row = QHBoxLayout()
        self.channel = QComboBox()
        for key, en in self.CHANNELS:
            self.channel.addItem(en, key)
        self.channel.setAccessibleName('Channel')
        send_row.addWidget(self.channel)
        self.identifier = QLineEdit()
        self.identifier.setPlaceholderText('Identifier, for example 0x2E5')
        self.identifier.setAccessibleName('Frame identifier')
        send_row.addWidget(self.identifier)
        self.payload = QLineEdit()
        self.payload.setPlaceholderText('Payload bytes, for example 21 04 00')
        self.payload.setAccessibleName('Frame payload')
        send_row.addWidget(self.payload, 1)
        self.origin = QComboBox()
        for key, en in (('ethernet', 'Through the gateway'), ('bus', 'Inject on the channel')):
            self.origin.addItem(en, key)
        self.origin.setAccessibleName('Write path')
        send_row.addWidget(self.origin)
        send_row.addWidget(window.button('Send frame', self.send_frame))
        self.layout.addLayout(send_row)
        self.result = self.text('', 'notice')

        self.trace = QLineEdit()
        self.trace.setReadOnly(True)
        self.trace.setAccessibleName('Last decoded frame')
        self.layout.addWidget(self.trace)
        self.frames = QLabel('')
        self.frames.setObjectName('muted')
        self.frames.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.frames.setWordWrap(False)
        self.layout.addWidget(self.frames)
        self.layout.addStretch()

    # -- requests ---------------------------------------------------------
    def request(self, payload):
        self.window.can_caller = self
        return self.window.bridge.call('can', '--payload', json.dumps(payload))

    def start_service(self):
        self.result.setText('Starting the CAN service…')
        self.window.bridge.call('can-start', '--can-backend', self.backend_box.currentData(),
                                '--can-profile', self.profile_box.currentData())

    def refresh(self):
        self.window.bridge.call('can-status')
        self.request({'action': 'trace', 'limit': 40, 'since': self.since})

    def unlock(self):
        # One request: the worker runs the challenge and response itself.
        self.request({'action': 'unlock', 'secret': self.secret.text()})

    def lock(self):
        self.request({'action': 'lock'})

    def send_frame(self):
        identifier = self.identifier.text().strip()
        if not identifier:
            self.result.setText('Enter an identifier first.')
            return
        self.request({'action': 'send', 'origin': self.origin.currentData(),
                      'frame': {'channel': self.channel.currentData(), 'id': identifier,
                                'data': self.payload.text().strip()}})

    # -- responses --------------------------------------------------------
    def received(self, action, result):
        if action not in ('can', 'can-start', 'can-status'):
            return
        if not result.get('ok'):
            self.result.setText(result.get('error', ''))
            return
        data = result.get('data', {})
        if 'frames' in data:
            self.render_frames(data['frames'])
            self.since = data.get('now', self.since)
            return
        if 'allowed' in data:
            reason = data.get('reason') or ''
            self.result.setText('Routed through ' + str(data.get('route'))
                                if data['allowed'] else 'Refused: ' + reason)
            return
        if 'unlocked' in data and 'gateway' not in data:
            self.result.setText(f"Gateway unlocked for {data.get('expires_in_s', 0) // 60} minutes."
                                if data['unlocked'] else 'Gateway locked.')
            self.window.bridge.call('can-status')  # The status line still shows the old state.
            return
        self.render_status(data)

    def render_status(self, data):
        if data.get('service') != 'running':
            self.state.setText('The CAN service is stopped.')
            return
        gateway = data.get('gateway', {})
        counters = gateway.get('counters', {})
        channels = data.get('channels') or [key for key, _ in self.CHANNELS]
        if channels != [self.channel.itemData(i) for i in range(self.channel.count())]:
            labels = dict(self.CHANNELS)
            self.channel.clear()
            for key in channels:
                self.channel.addItem(labels.get(key, key.upper()), key)
        channels = ', '.join(f"{item['channel']}:{item['received']}" for item in gateway.get('channels', []))
        if 'follow_session' not in data:
            source = 'older service running · restart it'
        elif data.get('follow_session'):
            source = 'following the session'
        else:
            source = 'panel state only'
        self.state.setText(' · '.join(filter(None, (
            'Transport: ' + str(gateway.get('backend')),
            'Profile: ' + str(data.get('profile', 'lab')),
            source,
            f"Unlocked · {gateway.get('unlock_expires_in_s', 0)} s left" if gateway.get('unlocked') else 'Locked',
            'Service Mode on' if gateway.get('service_mode') else 'Service Mode off',
            channels,
            'routed ' + str(counters.get('routed', 0)),
            'blocked ' + str(counters.get('blocked', 0) + counters.get('unknown', 0))))))

    def render_frames(self, frames):
        if not frames:
            return
        lines = []
        for item in frames[-16:]:
            signals = item.get('signals') or {}
            summary = ' '.join(f'{name}={value}' for name, value in list(signals.items())[:4])
            lines.append(f"{item['channel']:<5} {item['id_hex']:>4}  {item['data']:<24} "
                         f"{item.get('name', '')} {summary}")
        self.frames.setText('\n'.join(lines))
        self.trace.setText(lines[-1].strip())


class CanPanel(Panel):
    """Observe native OS traffic and configure explicit local frame echo rules."""

    def __init__(self, window):
        super().__init__(window)
        self.build_observer()
        from .frame_injection_panel import FrameInjectionPanel
        self.injection = FrameInjectionPanel(window, self.selected_frame)
        self.layout.addWidget(self.injection)
        self.layout.addStretch()

    def selected_frame(self):
        row = self.raw_observation.currentRow()
        return self.displayed_frames[row] if 0 <= row < len(self.displayed_frames) else None

    def build_observer(self):
        self.observed_frames = []
        self.displayed_frames = []
        self.updating_observation = False
        self.selected_observed_id = None
        self.pending_observation_dbc = None
        self.text('OS traffic observation', 'subtitle')
        self.text('Vehicle buses: Party, Chassis and Body (also called VH). '
                  'This view records requests made by the running OS. Gateway Ethernet messages '
                  'are labelled separately; their identifiers do not prove which CAN bus carries them.')
        row = QHBoxLayout()
        self.observation_bus = QComboBox()
        for key, name in (('', 'All observed traffic'), ('party', 'Party'), ('chassis', 'Chassis'),
                          ('body', 'Body / VH'), ('gateway', 'Gateway / Ethernet')):
            self.observation_bus.addItem(name, key)
        self.observation_bus.setAccessibleName('Observed bus')
        self.observation_bus.currentIndexChanged.connect(self.render_observation)
        row.addWidget(self.observation_bus)
        self.observation_direction = QComboBox()
        for key, name in (('TX', 'Network sends'), ('TX request', 'Gateway API requests'), ('', 'Both observation points')):
            self.observation_direction.addItem(name, key)
        self.observation_direction.setAccessibleName('OS observation point')
        self.observation_direction.currentIndexChanged.connect(self.render_observation)
        row.addWidget(self.observation_direction)
        self.observation_filter = QLineEdit()
        self.observation_filter.setPlaceholderText('Filter ID, message or signal')
        self.observation_filter.setMinimumWidth(180)
        self.observation_filter.setAccessibleName('Observed traffic filter')
        self.observation_filter.textChanged.connect(self.render_observation)
        row.addWidget(self.observation_filter, 1)
        self.pause_observation = QCheckBox('Pause display')
        row.addWidget(self.pause_observation)
        self.layout.addLayout(row)
        actions = QHBoxLayout()
        actions.addWidget(self.window.button('Refresh OS traffic', self.observe))
        actions.addWidget(self.window.button('Choose DBC', self.choose_observation_dbc))
        actions.addWidget(self.window.button('Frame injection ↓', self.focus_injection))
        actions.addWidget(self.window.button('Copy raw CSV', lambda: self.copy_observation(False)))
        actions.addWidget(self.window.button('Copy decoded CSV', lambda: self.copy_observation(True)))
        actions.addStretch()
        self.layout.addLayout(actions)
        self.observation_state = self.text('Start or restart the device to observe its OS traffic.', 'notice')
        self.observation_notice = self.text('No raw Party, Chassis or Body frames observed.')
        self.observation_dbc = self.text('DBC: none selected')
        self.raw_observation = QTableWidget(0, 9)
        self.raw_observation.setHorizontalHeaderLabels(('Timestamp ms', 'Bus', 'Direction', 'ID', 'EXT', 'RTR', 'Length', 'Data', 'Message'))
        self.raw_observation.setAccessibleName('Observed OS raw frames')
        self.raw_observation.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.raw_observation.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.raw_observation.setSelectionMode(QAbstractItemView.SingleSelection)
        self.raw_observation.setMinimumHeight(260)
        self.raw_observation.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.raw_observation.horizontalHeader().setSectionResizeMode(8, QHeaderView.Stretch)
        self.raw_observation.itemSelectionChanged.connect(self.render_selected_observation)
        self.layout.addWidget(self.raw_observation)
        self.decoded_caption = self.text('Select a frame to inspect its decoded signals.')
        self.decoded_observation = QTableWidget(0, 3)
        self.decoded_observation.setHorizontalHeaderLabels(('Signal', 'Value', 'Unit'))
        self.decoded_observation.setAccessibleName('Observed OS decoded signals')
        self.decoded_observation.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.decoded_observation.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.decoded_observation.setMinimumHeight(180)
        self.layout.addWidget(self.decoded_observation)
        self.observation_timer = QTimer(self)
        self.observation_timer.setInterval(1000)
        self.observation_timer.timeout.connect(self.observe)

    def focus_injection(self):
        self.window.pages.widget(6).verticalScrollBar().setValue(self.injection.y())

    def showEvent(self, event):
        super().showEvent(event)
        self.observation_timer.start()
        self.observe()

    def hideEvent(self, event):
        self.observation_timer.stop()
        super().hideEvent(event)

    def observe(self):
        if self.pending_observation_dbc:
            if self.window.bridge.call('can', '--payload', json.dumps({'action': 'os-dbc'}),
                                       '--path', self.pending_observation_dbc):
                self.pending_observation_dbc = None
            return
        self.injection.flush()
        self.request({'action': 'os-trace'})

    def choose_observation_dbc(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose observation DBC', '', 'CAN database (*.dbc)')
        if path:
            self.pending_observation_dbc = path
            self.observed_frames = []
            self.render_observation()
            self.observe()

    def receive_observation(self, data):
        if data.get('state') == 'stopped':
            self.injection.stopped()
        else:
            self.injection.render(data.get('injection', {}))
        if self.pause_observation.isChecked():
            return
        self.observed_frames = data.get('frames', [])
        self.observation_state.setText(' · '.join((
            'OS observer: ' + data.get('state', 'stopped'),
            'Vehicle emitter: ' + data.get('emitter', {}).get('state', 'unavailable'),
            str(data.get('records', 0)) + ' requests/records observed',
            str(data.get('catalog_messages', 0)) + ' native message definitions')))
        self.observation_notice.setText(data.get('notice', '') +
            '\nNo raw Party, Chassis or Body frames observed. Times are relative to observer startup.')
        self.observation_dbc.setText('DBC: ' + (data.get('dbc') or 'none selected') +
                                     (' · ' + data['dbc_error'] if data.get('dbc_error') else ''))
        self.render_observation()

    def render_observation(self, *_):
        if not hasattr(self, 'raw_observation'):
            return
        bus = self.observation_bus.currentData()
        direction = self.observation_direction.currentData()
        query = self.observation_filter.text().strip().lower()
        self.displayed_frames = [f for f in reversed(self.observed_frames)
            if (not bus or f.get('bus') == bus) and
               (not direction or f.get('direction') == direction) and
               (not query or query in (f.get('id_hex', '') + ' ' + f.get('message', '') + ' ' +
                                      ' '.join(s['signal'] for s in f.get('signals', []))).lower())][:128]
        self.updating_observation = True
        self.raw_observation.setRowCount(len(self.displayed_frames))
        chosen = None
        for row, frame in enumerate(self.displayed_frames):
            values = (frame.get('timestamp_ms'), frame.get('bus'), frame.get('direction'), frame.get('id_hex'),
                      frame.get('extended'), frame.get('rtr'), frame.get('length'), frame.get('data'), frame.get('message'))
            for col, value in enumerate(values):
                self.raw_observation.setItem(row, col, QTableWidgetItem('—' if value is None else str(value)))
            if frame.get('id') == self.selected_observed_id and chosen is None:
                chosen = row
        self.updating_observation = False
        if self.displayed_frames:
            self.raw_observation.selectRow(chosen if chosen is not None else 0)
        self.render_selected_observation()

    def render_selected_observation(self):
        if self.updating_observation:
            return
        row = self.raw_observation.currentRow()
        frame = self.displayed_frames[row] if 0 <= row < len(self.displayed_frames) else {}
        self.selected_observed_id = frame.get('id')
        signals = frame.get('signals', [])
        self.decoded_caption.setText(' · '.join(filter(None, (frame.get('message'),
            frame.get('decode_note'), '' if signals else 'No decoded signals available for this frame.'))))
        self.decoded_observation.setRowCount(len(signals))
        for row, field in enumerate(signals):
            for col, key in enumerate(('signal', 'value', 'unit')):
                value = field.get(key, '')
                if isinstance(value, float):
                    value = f'{value:.9g}'
                self.decoded_observation.setItem(row, col, QTableWidgetItem(str(value)))

    def copy_observation(self, decoded):
        output = io.StringIO()
        writer = csv.writer(output, delimiter=';', lineterminator='\n')
        if decoded:
            writer.writerow(('timestamp_ms', 'can_id', 'message', 'signal', 'value', 'unit', 'bus', 'direction'))
            for frame in reversed(self.displayed_frames):
                for signal in frame.get('signals', []):
                    writer.writerow((frame['timestamp_ms'], frame['id_hex'], frame['message'],
                        signal['signal'], signal['value'], signal['unit'], frame['bus'], frame['direction']))
        else:
            writer.writerow(('timestamp_ms', 'id', 'extended', 'rtr', 'dlc', 'data', 'bus', 'direction', 'transport'))
            for frame in reversed(self.displayed_frames):
                writer.writerow(tuple(frame.get(key, '') for key in
                    ('timestamp_ms', 'id_hex', 'extended', 'rtr', 'length', 'data', 'bus', 'direction', 'transport')))
        QApplication.clipboard().setText(output.getvalue())

    # -- requests ---------------------------------------------------------
    def request(self, payload):
        self.window.can_caller = self
        return self.window.bridge.call('can', '--payload', json.dumps(payload))

    def received(self, action, result):
        if action != 'can':
            return
        if self.injection.inflight:
            self.injection.received(result)
            return
        if not result.get('ok'):
            self.observation_state.setText(result.get('error', ''))
            return
        data = result.get('data', {})
        if data.get('observation'):
            self.receive_observation(data)
        elif data.get('os_dbc'):
            self.observation_dbc.setText('DBC: ' + data.get('dbc', ''))
            self.observe()


# The CID is the read-only firmware root the session runs from ($R). Enter it through a user
# namespace (no root needed); fall back to a shell in that directory if namespaces are blocked.
CID_ENTER = r'''
export PS1='[cid] \w # ' TERM=dumb
if unshare --user --map-root-user --mount true 2>/dev/null; then
  echo "Inside the CID firmware root (read-only)."
  exec unshare --user --map-root-user --mount sh -c 'R=$1; for d in dev proc sys tmp run; do mount --rbind "/$d" "$R/$d" 2>/dev/null; done; exec chroot "$R" /bin/bash -i' sh "$R"
fi
echo "User namespaces are unavailable; opening a shell in the CID firmware root instead of chrooting."
cd "$R" && exec bash -i
'''

# Native engine: the firmware root comes from the running session's config.
CID_SHELL = r'''
c="${XDG_DATA_HOME:-$HOME/.local/share}/tsla-infotainment-lab/session/config.json"
R=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['firmware'])" "$c" 2>/dev/null)
if [ -z "$R" ] || [ ! -d "$R/usr" ] || ! systemctl --user is-active --quiet tsla-infotainment-lab.service 2>/dev/null; then
  echo "The CID is not running. Start it from the Devices page, then connect again."; exit 1
fi
''' + CID_ENTER

# QEMU engine: run over SSH in the guest, where the image is mounted at /firmware. Without it the
# guest's own shell is the only useful place left, so open that instead of disconnecting.
GUEST_CID_SHELL = r'''
R=/firmware
if [ ! -d "$R/usr" ]; then
  echo "The firmware image is not mounted at /firmware in the guest; opening the guest shell instead."; exec bash -i
fi
''' + CID_ENTER


class TerminalView(QPlainTextEdit):
    """Read-only text view that forwards every keystroke, including Tab, to the shell."""

    typed = Signal(bytes)
    KEYS = {Qt.Key_Return: b'\r', Qt.Key_Enter: b'\r', Qt.Key_Backspace: b'\x7f', Qt.Key_Tab: b'\t',
            Qt.Key_Escape: b'\x1b', Qt.Key_Up: b'\x1b[A', Qt.Key_Down: b'\x1b[B', Qt.Key_Right: b'\x1b[C',
            Qt.Key_Left: b'\x1b[D', Qt.Key_Home: b'\x1b[H', Qt.Key_End: b'\x1b[F', Qt.Key_Delete: b'\x1b[3~'}

    def focusNextPrevChild(self, next):
        return False  # keep Tab for shell completion instead of moving focus

    def keyPressEvent(self, event):
        modifiers = event.modifiers()
        if modifiers & Qt.ControlModifier and modifiers & Qt.ShiftModifier:
            if event.key() == Qt.Key_C: self.copy()
            elif event.key() == Qt.Key_V: self.typed.emit(QApplication.clipboard().text().encode())
            return
        if modifiers & Qt.ControlModifier and Qt.Key_A <= event.key() <= Qt.Key_Z:
            self.typed.emit(bytes([event.key() - Qt.Key_A + 1]))
        elif event.key() in self.KEYS:
            self.typed.emit(self.KEYS[event.key()])
        elif event.text() and not modifiers & Qt.ControlModifier:
            self.typed.emit(event.text().encode())


# Runs the command on a pseudo-terminal so completion, prompts and Ctrl+C behave like a real shell.
PTY = 'import pty,sys;pty.spawn(sys.argv[1:])'


class ConsolePanel(Panel):
    """A shell in the CID: inside the firmware root on the native engine, over SSH on the QEMU engine."""

    def __init__(self, window):
        super().__init__(window)
        self.process = None
        self.rows, self.col = [''], 0
        self.escape = ''
        self.text('Console', 'subtitle')
        self.text('Both engines open a shell inside the running CID’s read-only firmware root. '
                  'QEMU virtual machine: reaches it over SSH on 127.0.0.1 with a key this lab creates for it '
                  '(set up on first Connect; an older guest image needs a rebuild to include the SSH server). '
                  'Native Linux / WSL: no SSH needed.')
        row = QHBoxLayout()
        self.connect_button = window.button('Connect', self.toggle, True)
        row.addWidget(self.connect_button)
        self.key_button = window.button('Set up SSH key', lambda: self.setup_key(False))
        row.addWidget(self.key_button)
        row.addStretch()
        self.key_ready = False
        self.connect_after_key = False
        self.layout.addLayout(row)
        self.output = TerminalView()
        self.output.setReadOnly(True)
        self.output.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)  # shows the caret
        self.output.setOverwriteMode(True)  # block caret, like a terminal
        self.output.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.output.setMinimumHeight(360)
        self.output.setAccessibleName('Console')
        self.output.typed.connect(self.send_bytes)
        self.layout.addWidget(self.output, 1)

    def show_text(self, text):
        self.rows, self.col, self.escape = text.split('\n'), 0, ''
        self.render()

    def render(self):
        del self.rows[:-2000]
        self.output.setPlainText('\n'.join(self.rows))
        cursor = self.output.textCursor()
        cursor.setPosition(self.output.document().lastBlock().position() + min(self.col, len(self.rows[-1])))
        self.output.setTextCursor(cursor)

    def feed(self, data):
        """Apply shell output to a simple screen: carriage return, backspace and line-erase are honoured."""
        for char in data:
            if self.escape:
                self.escape += char
                if self.escape[1:2] == ']':  # title sequence, ends at BEL
                    if char == '\x07': self.escape = ''
                elif self.escape[1:2] != '[' or char.isalpha() or char == '~':
                    if self.escape[1:2] == '[': self.csi(self.escape[2:-1], char)
                    self.escape = ''
                continue
            row = self.rows[-1]
            if char == '\x1b': self.escape = char
            elif char == '\n':
                self.rows.append('')
                self.col = 0
            elif char == '\r': self.col = 0
            elif char == '\b': self.col = max(0, self.col - 1)
            elif char >= ' ':
                self.rows[-1] = row[:self.col].ljust(self.col) + char + row[self.col + 1:]
                self.col += 1
        self.render()

    def csi(self, argument, final):
        count = int(re.sub(r'\D', '', argument) or 1)
        row = self.rows[-1]
        if final == 'K': self.rows[-1] = row[:self.col]
        elif final == 'C': self.col += count
        elif final == 'D': self.col = max(0, self.col - count)
        elif final == 'P': self.rows[-1] = row[:self.col] + row[self.col + count:]
        elif final == 'G': self.col = max(0, count - 1)

    def setup_key(self, then_connect):
        """Create this lab's own key if needed and authorize it in the running guest."""
        if self.window.bridge.engine != 'qemu':
            self.show_text('The native engine needs no SSH key; Connect opens the shell directly.')
            return
        self.connect_after_key = then_connect
        if not self.window.bridge.call('ssh-key'):
            return
        self.key_button.setEnabled(False)
        self.connect_button.setEnabled(False)
        self.show_text('Installing SSH key in the CID…')

    def key_result(self, result):
        self.key_button.setEnabled(True)
        self.connect_button.setEnabled(True)
        if not result.get('ok'):
            self.show_text(result.get('error', 'Unknown error'))
            return
        self.key_ready = True
        self.show_text('SSH key installed.')
        self.window.show_message('SSH key installed in the CID. Connect now opens a shell without a password.')
        if self.connect_after_key:
            self.toggle()

    def toggle(self):
        if self.process is not None:
            self.disconnect_now()
            return
        native = self.window.bridge.engine != 'qemu'
        if not native and not self.key_ready:
            self.setup_key(True)
            return
        from .qemu_virtual import SSH_PORT
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyRead.connect(self.read)
        self.process.finished.connect(self.closed)
        self.process.errorOccurred.connect(lambda error: error == QProcess.FailedToStart and self.closed())
        # Run ssh where the guest's forwarded port lives: inside WSL when this UI runs on Windows.
        script = ('export TERM=dumb; exec ssh -t -p %d -i "${XDG_DATA_HOME:-$HOME/.local/share}/tsla-infotainment-lab/ssh/id_ed25519" '
                  '-o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null '
                  '-o LogLevel=ERROR lab@127.0.0.1 %s' % (SSH_PORT, shlex.quote(GUEST_CID_SHELL)))
        argv = ['python3', '-c', PTY, 'sh', '-c', 'stty cols 120 rows 32 2>/dev/null; ' + (CID_SHELL if native else script)]
        if os.name == 'nt':
            argv = ['wsl.exe', '-d', self.window.bridge.distro, '--', *argv]
        self.show_text('')
        self.process.start(argv[0], argv[1:])
        self.connect_button.setText('Disconnect')
        self.output.setFocus()

    def send_bytes(self, data):
        if self.process is not None:
            self.process.write(data)

    def read(self):
        self.feed(bytes(self.process.readAll()).decode('utf-8', 'replace'))

    def disconnect_now(self):
        """Reset the UI at once. SIGKILL, not SIGTERM: an interactive shell ignores the latter."""
        process, self.process = self.process, None
        process.readyRead.disconnect()
        process.finished.disconnect()
        process.finished.connect(process.deleteLater)
        process.kill()
        self.closed()

    def closed(self, *_):
        if self.process is not None:
            self.process.deleteLater()
        self.process = None
        self.connect_button.setText('Connect')
        self.feed('\n' + '[disconnected]' + '\n')
