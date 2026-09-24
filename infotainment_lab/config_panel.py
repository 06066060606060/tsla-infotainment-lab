"""Desktop panel for importing, searching and editing Name,Value configuration CSVs."""
import json
import re

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem)

from . import config_csv
from .lab_panels import Panel

DISPLAYS = {'center': 'The center display', 'instruments': 'The instrument cluster', 'host-state': 'The host-state service'}
STATUS = {'accepted': '✓ Applied', 'unsupported': 'Not supported', 'rejected': 'Rejected', 'mismatch': 'Mismatch'}


class ConfigPanel(Panel):
    """Import a Name,Value configuration CSV, then search, filter and set values.

    Apply writes the changed values to the running displays as named DataValues,
    the same way Vehicle services does, and each row shows the firmware's answer.
    """

    def __init__(self, window):
        super().__init__(window)
        self.rows = []
        self.results = {}
        self.pending = None
        self.removed = set()
        self.restart_after = []
        self.reported = set()
        self.restarts_seen = 0
        self.learned = []
        self.imported = 0
        self.live = False
        self.was_live = False
        self.text('Import a Name,Value CSV (@invalid entries are skipped), edit values, then Apply to write them to the running displays. Defaults are the app’s vehicle-profile values; some car-config values make the firmware restart its UI.')
        bar = QHBoxLayout()
        bar.addWidget(window.button('Import CSV', self.open_file))
        self.export_button = window.button('Export CSV', self.save_file)
        self.apply_button = window.button('Apply', self.apply, True)
        self.reset_button = window.button('Defaults', self.revert)
        bar.addWidget(self.export_button)
        bar.addWidget(self.reset_button)
        bar.addStretch()
        bar.addWidget(self.apply_button)
        self.layout.addLayout(bar)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search name or value')
        self.search.setClearButtonEnabled(True)
        self.changed_only = window.button('Changed only', lambda: None)
        self.changed_only.setCheckable(True)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.changed_only)
        self.layout.addLayout(bar)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(('Name', 'Value', 'Default', 'Firmware'))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column, width in ((1, 150), (2, 130), (3, 110)):  # fixed: measuring thousands of rows would stall the UI
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.Interactive)
            self.table.setColumnWidth(column, width)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().hide()
        self.table.setStyleSheet('QHeaderView::section { background: transparent; border: 0; padding: 8px; font-weight: 600; }')
        self.table.setMinimumHeight(160)
        self.layout.addWidget(self.table, 1)
        bar = QHBoxLayout()
        for en, value in (('Set true', 'true'), ('Set false', 'false'), ('Default (selected)', None)):
            bar.addWidget(window.button(en, lambda _=False, v=value: self.set_selected(v)))
        bar.addStretch()
        bar.addWidget(window.button('Remove selected', self.remove_selected))
        self.summary = QLabel()
        self.summary.setObjectName('notice')
        bar.addWidget(self.summary)
        self.layout.addLayout(bar)
        bar = QHBoxLayout()
        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText('New key, for example VAPI_myFlag')
        self.new_value = QLineEdit()
        self.new_value.setPlaceholderText('Value')
        self.new_name.returnPressed.connect(self.add_key)
        self.new_value.returnPressed.connect(self.add_key)
        bar.addWidget(self.new_name, 2)
        bar.addWidget(self.new_value, 1)
        bar.addWidget(window.button('Add key', self.add_key))
        self.layout.addLayout(bar)
        self.search.textChanged.connect(self.refresh)
        self.changed_only.toggled.connect(self.refresh)
        self.table.itemChanged.connect(self.edited)
        try:
            saved = json.loads(window.settings.value('config_rows_v2', '[]'))
            if isinstance(saved, list):
                self.rows = [row for row in saved if isinstance(row, dict) and {'name', 'value', 'original', 'applied'} <= row.keys()
                             and row['original'] != config_csv.INVALID]
        except (TypeError, ValueError):
            pass
        self.rows = self.with_defaults(self.rows)
        self.refresh()

    @staticmethod
    def with_defaults(rows):
        """The default file's keys are always listed, ahead of any imported or added ones."""
        rest = {row['name']: row for row in rows}
        first = [rest.pop(row['name'], row) for row in config_csv.default_rows(config_csv.profile_defaults())]
        return first + list(rest.values())

    def apply(self):
        if self.pending is not None: return
        changed = {row['name']: row['value'] for row in self.rows if row['value'] != row['applied']}
        removed = set(self.removed)
        if not changed and not removed: return
        if not self.live:
            self.commit(changed, removed)
            self.window.show_message('Saved. These values are written when the device starts.')
        elif not self.confirm_restart(changed):
            return
        elif self.send('config-values', values={name: config_csv.coerce(value) for name, value in changed.items()},
                       explicit=self.explicit_names(changed), remove=sorted(removed)):
            self.pending = (changed, removed)
            self.apply_button.setEnabled(False)

    def confirm_restart(self, changed):
        """Car-config values (the default file's keys) cannot be written live: the firmware restarts its UI
        for each one. They are saved and the device is restarted once instead."""
        car = sorted(name for name in changed if name in config_csv.car_config(self.learned))
        if not car: return True
        answer = QMessageBox.question(self, 'Restart needed', f'{len(car)} car-config value(s) changed ({", ".join(car[:6])}{"…" if len(car) > 6 else ""}). '
            'They take effect when the device starts, so it will restart once now and the controls return to Park. Apply and restart?')
        self.restart_after = car if answer == QMessageBox.Yes else []
        return bool(self.restart_after)

    def explicit_names(self, names):
        """Names the user set deliberately (edited or added): they override the app's own model."""
        return sorted(row['name'] for row in self.rows if row['name'] in names and row.get('explicit'))

    def commit(self, values, removed=()):
        for row in self.rows:
            if row['name'] in values: row['applied'] = values[row['name']]
        self.removed -= set(removed)
        self.window.settings.setValue('config_rows_v2', json.dumps(self.rows))
        self.refresh()

    def acknowledge(self, success, data=None):
        pending, self.pending = self.pending, None
        restart, self.restart_after = self.restart_after, []
        rejected = [name for name in (data or {}).get('rejected', []) if isinstance(name, str)]
        if pending is not None and success:
            changed, removed = pending
            self.commit({name: value for name, value in changed.items() if name not in rejected}, removed)
            if restart:
                self.window.raise_alert(f'Restarting the device: {len(restart)} car-config value(s) only take effect at start.', restart)
                self.window.operation('restart')
        else: self.refresh()
        if rejected: self.discard_rejected(rejected)

    def discard_rejected(self, names):
        """Entries the backend refused (a bad name, or a value too large) go back to what they were."""
        positions = set()
        for position, row in enumerate(self.rows):
            if row['name'] not in names: continue
            if row['applied'] is None: positions.add(position)
            else: row['value'] = row['applied']
        if positions: self.drop_rows(positions)
        self.removed -= set(names)
        self.refresh()
        self.window.raise_alert(f'{len(names)} config value(s) refused (personal data, invalid name or too large) and reverted.', names)

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Import configuration CSV', '', 'CSV (*.csv);;All files (*)')
        if not path: return
        try:
            with open(path, encoding='utf-8-sig', newline='') as handle:
                text = handle.read()
        except (OSError, UnicodeDecodeError) as error:
            self.window.show_message(str(error), True)
            return
        rows = config_csv.parse(text, {}, [])[0]
        refused = config_csv.unsupported_car({row['name']: row['value'] for row in rows}, self.window.overview.single_display)
        if refused:
            self.window.show_message(refused, True)
            return
        invalid, duplicates = self.load(text)
        self.show_report(invalid, duplicates)

    def show_report(self, invalid, duplicates):
        defaults = config_csv.profile_defaults()
        differ = sum(row['name'] in defaults and row['value'] != row['original'] for row in self.rows)
        new = sum(row['applied'] is None for row in self.rows)
        unsent = sum((config_csv.prefix(row['name']) not in config_csv.SETTING_PREFIXES or config_csv.live(row['name'])) and row['name'] not in defaults for row in self.rows if row['applied'] == row['value'])
        summary = f'Imported {self.imported} entries: {differ} differ from the app defaults, {new} are new keys. Press Apply to write them; {unsent} hardware/telemetry values are listed but not sent. Skipped {len(invalid)} @invalid, withheld {len(self.withheld)} personal values and removed {len(duplicates)} duplicates.'
        self.window.show_message(summary)
        if not (invalid or duplicates or self.withheld): return
        lines = [f'Not imported: @invalid ({len(invalid)})', *('  ' + name for name in invalid), '',
                 f'Not imported: personal data ({len(self.withheld)})', *('  ' + name for name in self.withheld), '',
                 f'Removed duplicates ({len(duplicates)}): the last value is kept',
                 *(f'  {name}: {old} → {new}' if old != new else f'  {name}: {old}' for name, old, new in duplicates)]
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle('Import report')
        box.setText(summary)
        box.setDetailedText('\n'.join(lines))
        box.exec()

    def load(self, text):
        """A full import replaces the config: it starts from the defaults, so nothing from the previous one carries over.

        Keys the previous config set that this file lacks are removed, default keys it lacks go back to their
        default, and each queued row keeps what the firmware holds now as `applied`, so Apply writes the difference.
        """
        self.withheld = []
        defaults = config_csv.profile_defaults()
        imported, invalid, duplicates = config_csv.parse(text, defaults, self.withheld)
        self.imported = len(imported)
        previous = {row['name']: row for row in self.rows}
        self.rows = self.with_defaults(imported)
        names = {row['name'] for row in self.rows}
        sent = {name for name, row in previous.items() if row['applied'] is not None and (row.get('added') or (
            config_csv.prefix(name) in config_csv.SETTING_PREFIXES and not config_csv.live(name)))}
        self.removed = (self.removed | sent) - names
        for row in self.rows:
            old = previous.get(row['name'])
            if old is not None and (row['name'] in defaults or row['applied'] is None):  # listed-only rows are never sent
                row['applied'] = old['applied']
        self.results = {}
        self.refresh()
        return invalid, duplicates

    def save_file(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Export configuration CSV', 'export.csv', 'CSV (*.csv)')
        if not path: return
        try:
            with open(path, 'w', encoding='utf-8', newline='') as handle:
                handle.write(config_csv.export(self.rows))
        except OSError as error:
            self.window.show_message(str(error), True)

    def visible(self):
        return [(position, row) for position, row in enumerate(self.rows) if config_csv.matches(
            row, self.search.text(), self.changed_only.isChecked())]

    def status_text(self, name):
        status = self.results.get(name)
        return STATUS.get(status, '')

    def refresh(self, *_):
        shown = self.visible()
        defaults = config_csv.profile_defaults()
        self.table.blockSignals(True)
        self.table.setRowCount(len(shown))
        for index, (position, row) in enumerate(shown):
            name = QTableWidgetItem(row['name'])
            name.setFlags(name.flags() & ~Qt.ItemIsEditable)
            name.setData(Qt.UserRole, position)
            value = QTableWidgetItem(row['value'])
            self.style_value(value, row)
            default = QTableWidgetItem(row['original'] if row['name'] in defaults else '')
            default.setFlags(default.flags() & ~Qt.ItemIsEditable)
            status = QTableWidgetItem(self.status_text(row['name']))
            status.setFlags(status.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(index, 0, name)
            self.table.setItem(index, 1, value)
            self.table.setItem(index, 2, default)
            self.table.setItem(index, 3, status)
        self.table.blockSignals(False)
        self.refresh_footer(len(shown))

    def style_value(self, item, row):
        changed = row['value'] != row['original']
        item.setToolTip('App default: ' + row['original'] if changed else '')
        font = item.font()
        font.setBold(changed)
        item.setFont(font)

    def refresh_footer(self, shown=None):
        shown = self.table.rowCount() if shown is None else shown
        changed = sum(config_csv.is_changed(row) for row in self.rows)
        self.summary.setText(f'{shown} of {len(self.rows)} shown  ·  {changed} changed')
        for button in (self.export_button, self.reset_button): button.setEnabled(bool(self.rows))
        waiting = config_csv.pending(self.rows) + len(self.removed)
        self.apply_button.setEnabled(waiting > 0 and self.pending is None)
        self.apply_button.setText(f'Apply ({waiting})' if waiting else 'Apply')

    def edited(self, item):
        if item.column() != 1: return
        row = self.rows[self.table.item(item.row(), 0).data(Qt.UserRole)]
        row['value'] = item.text()
        row['explicit'] = True
        # Never rebuild the table from inside its own itemChanged signal: that
        # replaces the item being edited. Restyle it in place instead.
        self.table.blockSignals(True)
        self.style_value(item, row)
        self.table.blockSignals(False)
        self.refresh_footer()
        if self.changed_only.isChecked(): QTimer.singleShot(0, self.refresh)

    def set_selected(self, value):
        defaults = config_csv.profile_defaults() if value is None else {}
        drop = set()
        for row in {index.row() for index in self.table.selectedIndexes()}:
            position = self.table.item(row, 0).data(Qt.UserRole)
            data = self.rows[position]
            if value is None and data['name'] not in defaults: drop.add(position)
            else:
                data['value'] = data['original'] if value is None else value
                data['explicit'] = value is not None
        if drop: self.drop_rows(drop)
        self.refresh()

    def drop_rows(self, positions):
        defaults = config_csv.profile_defaults()
        for position in positions:  # default keys stay listed; removing one resets it
            if self.rows[position]['name'] in defaults: self.rows[position]['value'] = self.rows[position]['original']
        positions = {position for position in positions if self.rows[position]['name'] not in defaults}
        self.removed |= {self.rows[position]['name'] for position in positions}
        self.rows = [row for position, row in enumerate(self.rows) if position not in positions]

    def revert(self):
        """Back to the app's default file: its keys at their defaults, every other key removed."""
        defaults = config_csv.default_rows(config_csv.profile_defaults())
        names = {row['name'] for row in defaults}
        by_name = {row['name']: row for row in self.rows}
        self.removed |= {row['name'] for row in self.rows if row['name'] not in names}
        for row in defaults:
            if row['name'] in by_name: row['applied'] = by_name[row['name']]['applied']
        self.rows = defaults
        self.refresh()

    def add_key(self):
        name, value = self.new_name.text().strip(), self.new_value.text()
        if not re.fullmatch(config_csv.NAME, name):
            self.window.show_message('Use letters, digits and underscores, starting with a letter.', True)
            return
        if config_csv.private(name):
            self.window.raise_alert(f'{name} holds personal data (a password, PIN, key, identifier or place); it is never stored or written.')
            return
        row = next((row for row in self.rows if row['name'] == name), None)
        if row: row.update(value=value, explicit=True)
        else: self.rows.append({'name': name, 'value': value, 'original': value, 'applied': None, 'added': True, 'explicit': True})
        self.removed.discard(name)
        self.new_name.clear()
        self.new_value.clear()
        self.search.setText(name)
        self.refresh()

    def remove_selected(self):
        self.drop_rows({self.table.item(row, 0).data(Qt.UserRole) for row in {index.row() for index in self.table.selectedIndexes()}})
        self.refresh()

    def update_status(self, session):
        self.live = session.get('phase') in ('running', 'degraded')
        if self.live and not self.was_live:
            # A new session starts without earlier overrides; write the applied ones again.
            resend = {row['name']: config_csv.coerce(row['applied']) for row in self.rows if row['applied'] is not None and (row['applied'] != row['original'] or row.get('added'))}
            if resend and self.send('config-values', values=resend, explicit=self.explicit_names(resend)): self.was_live = True
            elif not resend: self.was_live = True
        elif not self.live:
            self.was_live = False
        self.learned = session.get('config_values', {}).get('car_config', [])
        self.report_restarts(session.get('config_values', {}).get('restarts', []))
        self.report_conflicts(session.get('config_values', {}).get('conflicts', []))
        seen = {}
        for statuses in session.get('config_values', {}).get('firmware', {}).values():
            for name, status in statuses.items():
                seen.setdefault(name, []).append(status)
        results = {name: next((st for st in stats if st != 'accepted'), 'accepted') for name, stats in seen.items()}
        self.drop_rejected([name for name, stats in seen.items() if set(stats) == {'unsupported'}])
        if results != self.results:
            self.results = results
            self.table.blockSignals(True)
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 3)
                if item: item.setText(self.status_text(self.table.item(row, 0).text()))
            self.table.blockSignals(False)

    def drop_rejected(self, names):
        """Keys no display knows are removed (also from the saved overrides) and listed in a popup."""
        defaults = config_csv.profile_defaults()
        dead = [name for name in names if name not in defaults and any(row['name'] == name and row['applied'] is not None for row in self.rows)]
        if not dead: return
        positions = {position for position, row in enumerate(self.rows) if row['name'] in dead}
        self.drop_rows(positions)
        self.results = {name: status for name, status in self.results.items() if name not in dead}
        self.refresh()
        if self.live: self.send('config-values', values={}, remove=sorted(dead))
        self.removed -= set(dead)
        self.window.settings.setValue('config_rows_v2', json.dumps(self.rows))
        self.window.raise_alert(f'The firmware does not know {len(dead)} config key(s); they were removed from the list.', dead)

    def report_conflicts(self, names):
        """Values the firmware kept restarting on were dropped from the overrides: put them back to their default."""
        if not names: self.reported.clear()
        fresh = [name for name in names if name not in self.reported]
        if not fresh: return
        self.reported.update(fresh)
        for row in self.rows:
            if row['name'] in fresh: row['value'] = row['applied'] = row['original']
        self.refresh()
        self.window.raise_alert(f'The firmware kept restarting because of {len(fresh)} value(s); they were reset to their defaults.', fresh)

    def report_restarts(self, history):
        """Each restart the supervisor recorded becomes an alert naming the values the firmware restarted for."""
        for entry in history:
            if not isinstance(entry, dict) or not isinstance(entry.get('at'), (int, float)) or entry['at'] <= self.restarts_seen: continue
            self.restarts_seen = entry['at']
            names = [name for name in entry.get('names', []) if isinstance(name, str)]
            who = DISPLAYS.get(entry.get('display'), 'The firmware')
            self.window.raise_alert(f'{who} restarted its UI because {len(names)} car-config value(s) changed.' if names else
                                    f'{who} restarted its UI to apply settings; the firmware did not name the values.', names)

    def export_draft(self):
        return {'rows': self.rows, 'search': self.search.text(), 'results': self.results}

    def restore_draft(self, draft):
        self.rows = draft.get('rows', [])
        self.results = draft.get('results', {})
        self.search.setText(draft.get('search', ''))
        self.refresh()
