"""Controls for selective continuous echoes of observed OS gateway frames."""
import json

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QFormLayout, QHBoxLayout, QHeaderView,
                              QLabel, QLineEdit, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)


class FrameInjectionPanel(QWidget):
    def __init__(self, window, selected_frame):
        super().__init__()
        self.window, self.selected_frame = window, selected_frame
        self.rules, self.draft, self.editing_key = [], {}, None
        self.queue, self.inflight = [], False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        title = QLabel('FRAME INJECTION')
        title.setObjectName('subtitle')
        layout.addWidget(title)
        self.notice = QLabel('Select a decoded network frame, choose the values to override, save a rule, then enable it. '
            'Each new matching OS send triggers one echo.')
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        destination = QLabel('Destination: local Gateway 127.0.0.102:4321 · Original send preserved · '
                             'Checksums unchanged · Rules off at device restart')
        destination.setWordWrap(True)
        layout.addWidget(destination)
        row = QHBoxLayout()
        row.addWidget(window.button('Use selected frame', self.use_selected))
        row.addWidget(window.button('Edit selected rule', self.edit_selected))
        row.addStretch()
        layout.addLayout(row)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setMaxLength(80)
        self.name.setAccessibleName('Injection rule name')
        self.source = QLabel('No frame selected')
        form.addRow('Rule name', self.name)
        form.addRow('Source frame', self.source)
        layout.addLayout(form)
        self.values = QTableWidget(0, 4)
        self.values.setHorizontalHeaderLabels(('Override', 'Signal', 'Value', 'Unit'))
        self.values.setAccessibleName('Frame injection signal overrides')
        self.values.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.values.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.values.setMinimumHeight(180)
        self.values.itemChanged.connect(self.value_changed)
        layout.addWidget(self.values)
        layout.addWidget(window.button('Save rule (disabled)', self.save))
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(('Rule', 'Frame', 'State', 'Echoes', 'Skipped', 'Last result'))
        self.table.setAccessibleName('Continuous frame injection rules')
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setMinimumHeight(170)
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        for text, operation in (('Enable selected rule', 'enable'), ('Disable selected rule', 'disable'),
                                ('Delete selected rule', 'delete'), ('Stop all echoes', 'stop')):
            actions.addWidget(window.button(text, lambda checked=False, op=operation: self.operate(op)))
        layout.addLayout(actions)
        self.status = QLabel('No active injection rules.')
        self.status.setObjectName('notice')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.retry = QTimer(self)
        self.retry.setInterval(250)
        self.retry.timeout.connect(self.flush)

    def rule(self):
        row = self.table.currentRow()
        return self.rules[row] if 0 <= row < len(self.rules) else None

    def use_selected(self):
        frame = self.selected_frame()
        if not frame or frame.get('direction') != 'TX' or frame.get('bus') != 'gateway' or not frame.get('signals'):
            self.status.setText('Select a decoded Gateway network send first.')
            return
        self.editing_key = None
        self.fill(frame)
        self.name.setText(frame.get('message', 'Frame') + ' echo')

    def fill(self, frame, edits=None):
        self.draft = dict(frame)
        self.source.setText(f"{frame['id_hex']} · {frame['message']} · Gateway / Ethernet")
        self.values.blockSignals(True)
        fields = list(frame.get('signals', []))
        # Saved overrides remain visible even when a different mux page is selected.
        for name, value in (edits or {}).items():
            if not any(f['signal'] == name for f in fields):
                fields.append({'signal': name, 'value': value, 'unit': ''})
        self.values.setRowCount(len(fields))
        for row, field in enumerate(fields):
            checked = QTableWidgetItem()
            checked.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            checked.setCheckState(Qt.Checked if field['signal'] in (edits or {}) else Qt.Unchecked)
            self.values.setItem(row, 0, checked)
            for col, value in enumerate((field['signal'], (edits or {}).get(field['signal'], field['value']), field['unit']), 1):
                item = QTableWidgetItem(str(value))
                if col != 2:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.values.setItem(row, col, item)
        self.values.blockSignals(False)

    def value_changed(self, item):
        if item.column() == 2:
            self.values.item(item.row(), 0).setCheckState(Qt.Checked)

    def edit_selected(self):
        rule = self.rule()
        if not rule:
            self.status.setText('Select a rule first.')
            return
        frame = self.selected_frame()
        if not frame or frame.get('id') != rule['identifier']:
            frame = {'id': rule['identifier'], 'id_hex': f"0x{rule['identifier']:03X}",
                     'message': rule.get('message', ''), 'signals': []}
        self.fill(frame, rule['edits'])
        self.editing_key = rule['key']
        self.name.setText(rule['name'])

    def save(self):
        edits = {self.values.item(row, 1).text(): self.values.item(row, 2).text().strip()
                 for row in range(self.values.rowCount())
                 if self.values.item(row, 0).checkState() == Qt.Checked}
        if not self.draft or not edits or not self.name.text().strip():
            self.status.setText('Choose a frame, enter a rule name and check at least one override.')
            return
        self.submit({'operation': 'save', 'key': self.editing_key, 'name': self.name.text().strip(),
                     'identifier': self.draft['id'], 'edits': edits})

    def operate(self, operation):
        rule = self.rule()
        if operation != 'stop' and not rule:
            self.status.setText('Select a rule first.')
            return
        if operation == 'stop':
            self.queue.clear()
        self.submit({'operation': operation, 'key': rule['key'] if rule else None})

    def submit(self, payload):
        self.queue.append(dict(payload, action='os-injection'))
        self.status.setText('Waiting for observer acknowledgement…')
        self.retry.start()
        self.flush()

    def flush(self):
        if self.queue and not self.inflight:
            if self.window.bridge.call('can', '--payload', json.dumps(self.queue[0])):
                self.queue.pop(0)
                self.inflight = True
        if not self.queue and not self.inflight:
            self.retry.stop()

    def received(self, result):
        if not self.inflight:
            return
        self.inflight = False
        data = result.get('data', {})
        if result.get('ok') and data.get('injection'):
            self.render(data)
            self.status.setText(data.get('error') or 'Rule state acknowledged by the OS observer.')
        else:
            self.status.setText(result.get('error', 'The observer could not apply the rule change.'))
        self.flush()

    def render(self, data):
        selected = self.rule()
        key = selected['key'] if selected else None
        self.rules = data.get('rules', [])
        self.table.setRowCount(len(self.rules))
        for row, rule in enumerate(self.rules):
            result = rule.get('error') or ('UDP sent: ' + rule['last_data'] if rule.get('last_data') else 'Waiting for matching OS frame')
            values = (rule['name'], f"0x{rule['identifier']:03X}",
                      'Enabled' if rule.get('enabled') else 'Disabled', rule.get('echoes', 0), rule.get('skipped', 0), result)
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip('Source: ' + rule.get('last_source', '') + '\nEcho: ' + rule.get('last_data', '') + '\n' + result)
                self.table.setItem(row, col, item)
            if rule['key'] == key:
                self.table.selectRow(row)
        if self.rules and self.table.currentRow() < 0:
            self.table.selectRow(0)

    def stopped(self):
        for rule in self.rules:
            rule['enabled'] = False
        self.render({'rules': self.rules})
        self.status.setText('Device stopped; no echoes are running.')
