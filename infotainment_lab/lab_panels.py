"""Desktop controls for browser views, recorded drives and local vehicle state."""
import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QTabWidget, QVBoxLayout, QWidget)

from .vehicle_services import FIELD_SPECS, VehicleServices


class Panel(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.tr2 = window.tr2
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 14, 0, 0)
        self.layout.setSpacing(12)

    def text(self, en, zh, style='muted'):
        item = QLabel(self.tr2(en, zh))
        item.setObjectName(style)
        item.setWordWrap(True)
        self.layout.addWidget(item)
        return item

    def send(self, backend_action, **payload):
        return self.window.bridge.call(backend_action, '--payload', json.dumps(payload))


class BrowserPanel(Panel):
    def __init__(self, window):
        super().__init__(window)
        self.text('Open an address in Browser or Card view. Theater opens the firmware’s app catalog.',
                  '使用浏览器或卡片模式打开网址。影院按钮打开固件内的应用目录。')
        self.url = QLineEdit()
        self.url.setPlaceholderText(self.tr2('https://…   Leave blank for the local browser check', 'https://…   留空打开本地浏览器测试页'))
        self.url.setAccessibleName(self.tr2('Website address', '网页地址'))
        self.layout.addWidget(self.url)
        row = QHBoxLayout()
        self.buttons = []
        for mode, en, zh in (('browser', 'Browser', '浏览器'), ('card', 'Card view', '卡片模式'), ('theater', 'Theater', '影院')):
            button = window.button(en, zh, lambda checked=False, m=mode: self.open(m))
            row.addWidget(button)
            self.buttons.append(button)
        self.layout.addLayout(row)
        self.health = self.text('', '', 'notice')
        self.text('In the browser check page, drag the slider, select text and move the tile. Use a parked simulation for video playback.',
                  '在浏览器测试页内可拖动滑块、选择文字和移动方块。播放影院视频时请使用驻车模拟状态。')
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
        modes = [('chromium', 'Browser', '浏览器'), ('chromium-card', 'Card', '卡片'), ('chromium-theater', 'Theater', '影院')]
        self.health.setText('  ·  '.join(self.tr2(en, zh) + (' ●' if live and components.get(key) == 'running' else ' ○') for key, en, zh in modes))


class ReplayPanel(Panel):
    def __init__(self, window):
        super().__init__(window)
        self.duration = 0
        self.phase = 'idle'
        self.text('Recorded drive', '行车记录回放', 'subtitle')
        self.text('Replay the video and its embedded driving data together. Moving a vehicle control takes over from the recording.',
                  '同步回放视频与内嵌行驶数据。操作车辆控制后，将切换为手动输入。')
        row = QHBoxLayout()
        row.addWidget(window.button('Open dashcam MP4…', '打开行车记录 MP4…', self.open))
        self.play = window.button('Play', '播放', self.toggle_play)
        row.addWidget(self.play)
        self.take_over = window.button('Take over', '手动接管', lambda: self.send('replay', action='manual'))
        row.addWidget(self.take_over)
        self.rate = QComboBox()
        for speed in (.25, .5, 1, 1.5, 2): self.rate.addItem(f'{speed:g}×', speed)
        self.rate.setCurrentIndex(2)
        self.rate.setAccessibleName(self.tr2('Playback speed', '播放倍速'))
        self.rate.currentIndexChanged.connect(lambda _: self.send('replay', action='rate', rate=self.rate.currentData()))
        row.addWidget(self.rate)
        self.loop = QCheckBox(self.tr2('Loop', '循环'))
        self.loop.setChecked(True)
        self.loop.toggled.connect(lambda value: self.send('replay', action='loop', loop=value))
        row.addWidget(self.loop)
        self.layout.addLayout(row)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.setAccessibleName(self.tr2('Replay position', '回放位置'))
        self.seek.sliderReleased.connect(self.send_seek)
        self.seek.actionTriggered.connect(lambda _: self.send_seek() if not self.seek.isSliderDown() else None)
        self.layout.addWidget(self.seek)
        self.feedback = self.text('Choose a dashcam recording with embedded telemetry.', '选择包含内嵌行驶数据的行车记录视频。', 'notice')

    def open(self):
        path, _ = QFileDialog.getOpenFileName(self, self.tr2('Open a recorded drive', '打开行车记录'), '', 'Dashcam (*.mp4)')
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
        self.play.setText(self.tr2('Pause', '暂停') if self.phase in ('playing', 'seeking-playing') else self.tr2('Play', '播放'))
        if not self.seek.isSliderDown(): self.seek.setValue(round(position / self.duration * 1000) if self.duration else 0)
        for widget, value in ((self.rate, replay.get('rate', 1)), (self.loop, replay.get('loop', True))):
            widget.blockSignals(True)
            if widget is self.rate: widget.setCurrentIndex(max(0, widget.findData(value)))
            else: widget.setChecked(value)
            widget.blockSignals(False)
        phases = {'playing': ('Playing', '播放中'), 'paused': ('Paused', '已暂停'), 'manual': ('Manual controls', '手动控制'), 'ready': ('Ready · press Play', '已就绪 · 点击播放'),
                  'ended': ('Finished', '已结束'), 'error': ('Unable to replay', '无法回放'), 'seeking-playing': ('Seeking', '定位中')}
        if live:
            text = self.tr2(*phases.get(self.phase, ('Loading', '正在读取'))) + f'  ·  {position:.1f} / {self.duration:.1f} s'
            controls = replay.get('telemetry_sample', {})
            if controls:
                text += f"  ·  {controls.get('gear', '')}  {controls.get('speed_kph', 0):.1f} km/h"
                text += self.tr2('  ·  Steering ', '  ·  转向 ') + f"{controls.get('steering_deg', 0):.1f}°"
                text += self.tr2('  ·  Accelerator ', '  ·  加速踏板 ') + f"{controls.get('throttle_pct', 0):.1f}%"
            if replay.get('error'): text += '  ·  ' + replay['error']
            self.feedback.setText(text)
        else:
            self.feedback.setText(self.tr2('Choose a dashcam recording with embedded telemetry.', '选择包含内嵌行驶数据的行车记录视频。'))


class ServicesPanel(Panel):
    def __init__(self, window):
        super().__init__(window)
        self.dirty = set()
        self.pending = None
        self.awaiting = {}
        self.live = False
        self.widgets, self.results = {}, {}
        self.text('Set the local vehicle state, then apply your changes. Each field shows the firmware response.',
                  '设置本地车辆状态后应用更改，每一项都会显示固件的响应。')
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)
        defaults = VehicleServices().as_dict()
        for group, en, zh in (('climate', 'Climate', '空调'), ('closures', 'Doors', '车门'), ('lights', 'Lights', '灯光'),
                               ('energy', 'Energy', '电量'), ('audio', 'Audio', '声音'), ('navigation', 'Navigation', '导航'), ('tires', 'Tires', '轮胎')):
            page = QWidget()
            form = QFormLayout(page)
            form.setContentsMargins(20, 24, 20, 24)
            form.setSpacing(14)
            for name, spec in FIELD_SPECS.items():
                if spec['group'] != group: continue
                value = defaults[name]
                if spec['type'] == 'bool':
                    widget = QCheckBox()
                    widget.setChecked(value)
                    widget.toggled.connect(lambda _, n=name: self.dirty.add(n))
                elif spec['type'] == 'str' or spec.get('nullable'):
                    widget = QLineEdit('' if value is None else str(value))
                    widget.setPlaceholderText(self.tr2('Unset', '未设置'))
                    widget.textEdited.connect(lambda _, n=name: self.dirty.add(n))
                else:
                    widget = QDoubleSpinBox()
                    widget.setRange(spec['min'], spec['max'])
                    widget.setDecimals(0 if spec['type'] == 'int' else 1)
                    widget.setValue(value)
                    widget.valueChanged.connect(lambda _, n=name: self.dirty.add(n))
                widget.setAccessibleName(spec['label_zh'] if window.zh else spec['label'])
                self.widgets[name] = widget
                row = QHBoxLayout()
                row.addWidget(widget, 1)
                result = QLabel('—')
                result.setObjectName('muted')
                row.addWidget(result)
                self.results[name] = result
                form.addRow(spec['label_zh'] if window.zh else spec['label'], row)
            self.tabs.addTab(page, self.tr2(en, zh))
        row = QHBoxLayout()
        self.apply_button = window.button('Apply changes', '应用更改', self.apply, True)
        row.addWidget(self.apply_button)
        row.addStretch()
        self.layout.addLayout(row)
        self.feedback = self.text('', '', 'notice')
        self.text('The local model covers climate, body indicators, energy, audio and trip data. Tire pressure remains a local value. Connected accounts, physical vehicle hardware and live traffic require their own services.',
                  '本地模型包含空调、车身提示、电量、声音和行程数据。胎压目前保存在本地。账号、真实车辆硬件与实时路况需要对应服务。')
        self.layout.addStretch()

    def apply(self):
        if self.pending is not None:
            return
        payload = {}
        try:
            for name in self.dirty:
                payload[name] = self.field_value(name)
            if payload and self.send('vehicle-services', **payload):
                self.pending = payload
                self.apply_button.setEnabled(False)
        except ValueError:
            self.window.show_message(self.tr2('Enter a valid number for location and heading.', '请为位置与航向输入有效数字。'), True)

    def field_value(self, name):
        widget, spec = self.widgets[name], FIELD_SPECS[name]
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
        self.apply_button.setEnabled(self.live)

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
            elif isinstance(widget, QCheckBox): widget.setChecked(value)
            else: widget.setValue(value)
            widget.blockSignals(False)
        self.dirty = set(draft.get('dirty', ())) & self.widgets.keys()
        self.pending = draft.get('pending')
        self.awaiting = dict(draft.get('awaiting', {}))
        self.tabs.setCurrentIndex(draft.get('tab', 0))
        self.apply_button.setEnabled(self.live and self.pending is None)

    def update_status(self, session):
        live = self.live = session.get('phase') in ('running', 'degraded')
        self.apply_button.setEnabled(live and self.pending is None)
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
                elif isinstance(widget, QLineEdit): widget.setText('' if value is None else str(value))
                else: widget.setValue(value)
                widget.blockSignals(False)
            result = center.get(name, 'pending')
            if isinstance(result, dict): result = result.get('status', 'pending')
            states = {'accepted': ('Applied', '已应用'), 'partial': ('Partial', '部分应用'), 'unsupported': ('Local only', '仅本地'), 'local-model': ('Local only', '仅本地'), 'mismatch': ('Not applied', '未应用'), 'rejected': ('Not accepted', '未接收')}
            self.results[name].setText(self.tr2(*states.get(result, ('—', '—'))) if live else '—')
        link = session.get('display_link', {})
        connected = link.get('connected', {})
        synced = live and connected.get('center') and connected.get('cluster')
        if synced:
            self.feedback.setText(self.tr2('Center ↔ Instruments', '中控 ↔ 仪表') + '  ·  ' + str(link.get('synchronized_count', 0)) + self.tr2(' shared preferences synchronized', ' 项偏好已同步'))
        else:
            self.feedback.setText(self.tr2('Waiting for both displays to synchronize.', '等待两块屏幕完成同步。') if live else self.tr2('Start a device to use vehicle services.', '启动设备后即可使用车辆服务。'))
