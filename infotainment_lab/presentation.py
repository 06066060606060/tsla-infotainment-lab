"""Small native desktop components, independent of the firmware runtime."""
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QIcon
from PySide6.QtWidgets import QWidget
from .theme import current_colors


def icon(name, color=None):
    """Draw the app's own simple line icons at device-independent resolution."""
    color = color or current_colors()['muted']
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(2, 2)
    painter.setPen(QPen(QColor(color), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    if name in ('screen', 'devices'):
        painter.drawRoundedRect(QRectF(3, 4, 18, 13), 2, 2)
        painter.drawLine(12, 17, 12, 21)
        painter.drawLine(8, 21, 16, 21)
    elif name == 'cluster':
        painter.drawRoundedRect(QRectF(2, 7, 20, 10), 3, 3)
        painter.drawArc(QRectF(7, 9, 10, 9), 0, 180 * 16)
        painter.drawLine(12, 14, 15, 11)
    elif name == 'camera':
        painter.drawRoundedRect(QRectF(3, 6, 18, 14), 2, 2)
        painter.drawEllipse(QRectF(8, 9, 8, 8))
        painter.drawLine(8, 3, 16, 3)
    elif name == 'restart':
        painter.drawArc(QRectF(4, 4, 16, 16), 40 * 16, 290 * 16)
        painter.drawLine(20, 4, 20, 10)
        painter.drawLine(14, 10, 20, 10)
    elif name == 'controls':
        painter.drawEllipse(QRectF(3, 3, 18, 18))
        painter.drawEllipse(QRectF(9, 9, 6, 6))
        painter.drawLine(3, 11, 9, 11)
        painter.drawLine(15, 11, 21, 11)
        painter.drawLine(12, 15, 12, 21)
    elif name == 'help':
        painter.drawEllipse(QRectF(3, 3, 18, 18))
        painter.drawLine(12, 10, 12, 17)
        painter.drawPoint(12, 7)
    elif name == 'add':
        painter.drawLine(12, 5, 12, 19)
        painter.drawLine(5, 12, 19, 12)
    elif name == 'play':
        painter.drawLine(8, 4, 20, 12)
        painter.drawLine(20, 12, 8, 20)
        painter.drawLine(8, 20, 8, 4)
    else:
        for y, x in ((6, 8), (12, 16), (18, 10)):
            painter.drawLine(3, y, 21, y)
            painter.drawEllipse(QRectF(x - 2, y - 2, 4, 4))
    painter.end()
    return QIcon(pixmap)


class DisplayOverview(QWidget):
    """A view-only overview of actual display captures, never synthetic telemetry."""
    def __init__(self):
        super().__init__()
        self.center = QPixmap()
        self.cluster = QPixmap()
        self.message = 'Your displays will appear here'
        self.single_display = False
        self.setMinimumHeight(225)
        self.setAccessibleName('Display overview')

    def set_frames(self, center, cluster):
        self.center, self.cluster = center, cluster
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = current_colors()
        w, h = self.width(), self.height()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c['preview']))
        p.drawRoundedRect(QRectF(0, 0, w, h), 20, 20)
        empty = self.center.isNull() and self.cluster.isNull()
        area = QRectF(18, 18, max(1, w - 36), max(1, h - (64 if empty else 36)))
        frames = [self.center] if self.single_display else [self.cluster, self.center]
        ratios = [(frame.width() / frame.height() if not frame.isNull() else
                   (1.6 if self.single_display else 2.66 if index == 0 else .625))
                  for index, frame in enumerate(frames)]
        # Fit real frame proportions into equal slots; landscape ICE is never
        # squeezed into a portrait MCU2 placeholder.
        gap = 18
        slot_width = (area.width() - gap * (len(frames) - 1)) / len(frames)
        for index, (frame, ratio) in enumerate(zip(frames, ratios)):
            height = min(area.height(), slot_width / ratio)
            width = height * ratio
            x = area.x() + index * (slot_width + gap) + (slot_width - width) / 2
            rect = QRectF(x, area.center().y() - height / 2, width, height)
            p.setPen(QPen(QColor(c['outline']), 1.5))
            p.setBrush(QColor(c['surface']))
            p.drawRoundedRect(rect, 12, 12)
            content = rect.adjusted(5, 5, -5, -5)
            if not frame.isNull():
                scaled = frame.scaled(content.size().toSize(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                p.drawPixmap(int(content.center().x() - scaled.width()/2), int(content.center().y() - scaled.height()/2), scaled)
            else:
                p.setPen(QPen(QColor(c['outline_variant']), 2))
                p.drawEllipse(content.center(), 6, 6)
        if empty:
            p.setPen(QColor(c['muted']))
            p.drawText(QRectF(12, h - 34, w - 24, 24), Qt.AlignCenter, self.message)
        p.end()


def readiness(environment):
    """Return an actionable setup state. Missing data is not a successful check."""
    if not environment:
        return 'checking'
    if environment.get('root_user'):
        return 'user'
    if environment.get('architecture') != 'x86_64':
        return 'architecture'
    if environment.get('engine') == 'qemu':
        if environment.get('missing'):
            return 'dependencies'
        if not environment.get('kvm_available'):
            return 'kvm'
        if not environment.get('display_available'):
            return 'display'
        return 'ready' if environment.get('runtime_ready') else 'virtual-image'
    if environment.get('missing') or not environment.get('runtime_ready'):
        return 'dependencies'
    if not environment.get('display_available'):
        return 'display'
    if not environment.get('systemd_available'):
        return 'services'
    if not environment.get('fuse_available'):
        return 'mounts'
    return 'ready'
