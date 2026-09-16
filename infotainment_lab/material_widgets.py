"""Native accessible widgets using the application's Material color roles."""
from PySide6.QtCore import Qt, QSize, QRectF
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import QCheckBox
from .theme import current_colors


class MaterialSwitch(QCheckBox):
    """Keep Qt checkbox signals, keyboard interaction and accessibility intact."""
    def sizeHint(self):
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        return QSize(52 + (12 + text_width if self.text() else 0), 40)

    def minimumSizeHint(self):
        return self.sizeHint()

    def hitButton(self, point):
        return self.rect().contains(point)

    def paintEvent(self, event):
        c = current_colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        y = (self.height() - 28) / 2
        fill = c['primary'] if self.isChecked() else c['high']
        if not self.isEnabled(): fill = c['outline_variant']
        p.setPen(QPen(QColor(fill if self.isChecked() else c['outline']), 2))
        p.setBrush(QColor(fill))
        p.drawRoundedRect(QRectF(2, y, 46, 28), 14, 14)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c['on_primary'] if self.isChecked() else c['outline']))
        p.drawEllipse(QRectF(24 if self.isChecked() else 8, y + 5, 18, 18))
        p.setPen(QColor(c['on_surface'] if self.isEnabled() else c['disabled']))
        p.drawText(self.rect().adjusted(62, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, self.text())
        if self.hasFocus():
            p.setPen(QPen(QColor(c['primary']), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 12, 12)
        p.end()
