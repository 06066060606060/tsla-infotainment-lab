"""Momentary wheel buttons with bounded, cancellable hold repetition."""
from PySide6.QtCore import QEvent, QTimer, Signal
from PySide6.QtWidgets import QPushButton


class HoldButton(QPushButton):
    triggered = Signal()

    def __init__(self, text, repeat=False, parent=None):
        super().__init__(text, parent)
        self.repeat = repeat
        self.holding = False
        self.hold_timer = QTimer(self)
        self.hold_timer.setSingleShot(True)
        self.hold_timer.timeout.connect(self.repeat_press)
        self.pressed.connect(self.begin_hold)
        self.released.connect(self.cancel_hold)

    def begin_hold(self):
        if self.holding:
            return
        self.holding = True
        self.triggered.emit()
        if self.repeat and self.holding and self.isEnabled():
            self.hold_timer.start(450)

    def repeat_press(self):
        if not self.holding or not self.isEnabled() or not self.isDown():
            self.cancel_hold()
            return
        self.triggered.emit()
        if self.holding:
            self.hold_timer.start(180)

    def cancel_hold(self):
        self.holding = False
        self.hold_timer.stop()

    def event(self, event):
        if hasattr(self, 'hold_timer') and event.type() in (
                QEvent.Type.WindowDeactivate, QEvent.Type.FocusOut,
                QEvent.Type.Hide, QEvent.Type.Leave):
            self.cancel_hold()
        return super().event(event)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled():
            self.cancel_hold()
        super().changeEvent(event)

    def keyPressEvent(self, event):
        if event.isAutoRepeat():
            event.ignore()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.isAutoRepeat():
            event.ignore()
            return
        super().keyReleaseEvent(event)
