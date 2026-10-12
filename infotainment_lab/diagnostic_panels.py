"""Firmware replacement controls and a live local debug log viewer."""
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
                              QLineEdit, QPushButton, QFileDialog, QListWidget, QListWidgetItem, QTextEdit)
from .material_widgets import MaterialSwitch
from .core import size_label


class FirmwareFilesPanel(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.pending_id = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        heading = QLabel('Firmware replacements')
        heading.setObjectName('subtitle')
        layout.addWidget(heading)
        hint = QLabel('Select firmware, enter an existing path inside its SquashFS, then choose a replacement. '
                      'Stop that session before changing files. Replacements persist per image and apply on the next launch. '
                      'Removing an entry restores the original file. QEMU guests need a rebuild for this feature.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        self.firmware = QComboBox()
        self.firmware.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.firmware.setMinimumContentsLength(12)
        self.firmware.setAccessibleName('Firmware for file replacements')
        self.firmware.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.firmware, 1)
        refresh = QPushButton('Refresh list')
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)
        layout.addLayout(row)
        self.target = QLineEdit()
        self.target.setPlaceholderText('/usr/tesla/UI/path/to/file')
        self.target.setAccessibleName('File path inside SquashFS')
        layout.addWidget(self.target)
        row = QHBoxLayout()
        self.replace = QPushButton('Choose replacement…')
        self.replace.clicked.connect(self.choose)
        row.addWidget(self.replace)
        self.remove = QPushButton('Restore selected original')
        self.remove.clicked.connect(self.restore)
        row.addWidget(self.remove)
        row.addStretch()
        layout.addLayout(row)
        self.files = QListWidget()
        self.files.setMinimumHeight(130)
        self.files.setAccessibleName('Configured firmware replacements')
        self.files.currentItemChanged.connect(self.selection_changed)
        layout.addWidget(self.files)
        self.message = QLabel('Select an imported firmware image.')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.update_status({})

    def update_library(self, library):
        previous = self.firmware.currentData()
        self.firmware.blockSignals(True)
        self.firmware.clear()
        for item in library:
            if item.get('kind') == 'firmware':
                self.firmware.addItem(f"{item['version']} · {item.get('filename', item['id'])}", item['id'])
        self.firmware.setCurrentIndex(max(0, self.firmware.findData(previous)))
        self.firmware.blockSignals(False)
        self.files.clear()
        if self.window.current_page == 3:
            self.refresh()

    def refresh(self, *_):
        identifier = self.firmware.currentData()
        if identifier and self.window.bridge.call('firmware-files', '--id', identifier):
            self.pending_id = identifier
            self.message.setText('Loading replacement list…')

    def request(self, operation, target, filename=None):
        identifier = self.firmware.currentData()
        if not identifier:
            return
        arguments = ['--id', identifier, '--replacement-operation', operation, '--target', target]
        if filename:
            arguments += ['--path', filename]
        if self.window.bridge.call('firmware-files', *arguments):
            self.pending_id = identifier
            self.message.setText('Saving replacement changes…')
            self.update_status(self.window.session)

    def choose(self):
        if not self.target.text().strip():
            self.message.setText('Enter the existing file path inside the firmware first.')
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Choose replacement file')
        if path:
            self.request('put', self.target.text().strip(), path)

    def restore(self):
        item = self.files.currentItem()
        if item:
            self.request('remove', item.data(Qt.UserRole))

    def selection_changed(self, item, *_):
        if item:
            self.target.setText(item.data(Qt.UserRole))
        self.update_status(self.window.session)

    def received(self, result):
        requested, self.pending_id = self.pending_id, None
        if requested != self.firmware.currentData():
            self.refresh()
            return
        if not result.get('ok'):
            self.message.setText(result.get('error', 'Replacement operation failed.'))
        else:
            data = result.get('data', {})
            self.files.clear()
            for entry in data.get('files', []):
                item = QListWidgetItem(entry['target'] + ' · ' + size_label(entry['bytes']))
                item.setData(Qt.UserRole, entry['target'])
                self.files.addItem(item)
            count = self.files.count()
            self.message.setText(f'{count} replacement(s) saved. Applied on the next launch.' if count else 'No replacements. The original firmware files will be used.')
        self.update_status(self.window.session)

    def update_status(self, session):
        live = session.get('phase') in ('starting', 'booting', 'running', 'degraded', 'stopping')
        available = bool(self.firmware.currentData()) and not live and not self.window.busy and 'firmware-files' not in self.window.bridge.pending
        self.replace.setEnabled(available)
        self.remove.setEnabled(available and self.files.currentItem() is not None)


class DebugPanel(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.logs = {}
        self.context = ''
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 14, 0, 0)
        hint = QLabel('Live local debug output. Each source shows its latest output; large logs are truncated. '
                      'Native mode runs on the host OS. QEMU exposes the guest serial console and available guest journals.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        self.sources = QComboBox()
        self.sources.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.sources.setMinimumContentsLength(12)
        self.sources.addItem('All sources', '')
        self.sources.setAccessibleName('Debug log source')
        self.sources.currentIndexChanged.connect(self.render)
        row.addWidget(self.sources, 1)
        self.auto = MaterialSwitch('Auto refresh')
        self.auto.setChecked(True)
        self.auto.toggled.connect(lambda enabled: self.refresh() if enabled else None)
        row.addWidget(self.auto)
        refresh = QPushButton('Refresh now')
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)
        layout.addLayout(row)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText('Filter log lines…')
        self.filter.setClearButtonEnabled(True)
        self.filter.setAccessibleName('Debug log line filter')
        self.filter.textChanged.connect(self.render)
        layout.addWidget(self.filter)
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setAcceptRichText(False)
        self.view.setMinimumHeight(360)
        self.view.setPlaceholderText('Debug logs will appear here when available.')
        self.view.setStyleSheet('font-family: monospace;')
        layout.addWidget(self.view, 1)
        self.caption = QLabel('Waiting for log output.')
        self.caption.setWordWrap(True)
        layout.addWidget(self.caption)

    def refresh(self):
        if not self.window.busy:
            self.window.bridge.call('debug')

    def received(self, result):
        if not result.get('ok'):
            self.caption.setText(result.get('error', 'Debug logs unavailable.'))
            return
        data = result.get('data', {})
        self.logs = data.get('logs', {})
        selected = self.sources.currentData()
        self.sources.blockSignals(True)
        self.sources.clear()
        self.sources.addItem('All sources', '')
        for name in self.logs:
            self.sources.addItem(name, name)
        self.sources.setCurrentIndex(max(0, self.sources.findData(selected)))
        self.sources.blockSignals(False)
        self.context = data.get('context', '')
        stamp = time.strftime('%H:%M:%S', time.localtime(data.get('captured_at', time.time())))
        self.caption.setText(self.context + ' · ' + stamp + (' · ' + data['notice'] if data.get('notice') else ''))
        self.render()

    def render(self, *_):
        source = self.sources.currentData()
        needle = self.filter.text().casefold()
        parts = []
        for name, text in self.logs.items():
            if source and name != source:
                continue
            if needle:
                text = '\n'.join(line for line in text.splitlines() if needle in line.casefold())
            parts.append(f'--- {name} ---\n{text}')
        content = '\n\n'.join(parts)
        if content == self.view.toPlainText():
            return
        scrollbar = self.view.verticalScrollBar()
        position = scrollbar.value()
        follow = position >= scrollbar.maximum() - 2
        self.view.setPlainText(content)
        scrollbar.setValue(scrollbar.maximum() if follow else position)

    def reset(self):
        self.logs = {}
        self.view.clear()
        self.caption.setText('Waiting for log output.')
