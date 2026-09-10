"""Preview of the RGB source sent to the firmware camera."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget


class CameraPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame = QPixmap()
        self.setMinimumSize(420, 250)

    def set_frame(self, frame):
        self.frame = frame
        self.update()

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#101d27'))
        if not self.frame.isNull():
            scaled = self.frame.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.drawPixmap((self.width() - scaled.width()) // 2, (self.height() - scaled.height()) // 2, scaled)
