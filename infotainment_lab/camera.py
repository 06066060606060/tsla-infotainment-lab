"""Preview of the RGB source sent to the firmware camera."""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget
from .theme import current_colors


class CameraPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame = QPixmap()
        self.message = 'No camera frame'
        self.setAccessibleName('Camera source preview')
        self.setMinimumSize(420, 250)

    def set_frame(self, frame):
        self.frame = frame
        self.update()

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(current_colors()['preview']))
        painter.drawRoundedRect(QRectF(self.rect()), 20, 20)
        if not self.frame.isNull():
            scaled = self.frame.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.drawPixmap((self.width() - scaled.width()) // 2, (self.height() - scaled.height()) // 2, scaled)
        else:
            painter.setPen(QColor(current_colors()['muted']))
            painter.drawText(self.rect(), Qt.AlignCenter, self.message)
        painter.end()
