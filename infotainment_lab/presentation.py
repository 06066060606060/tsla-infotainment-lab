"""Small native desktop components, independent of the firmware runtime."""
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QIcon
from PySide6.QtWidgets import QWidget


def icon(name, color='#a7bbc5'):
    """Draw the app's own simple line icons at device-independent resolution."""
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
        self.setMinimumHeight(225)
        self.setAccessibleName('Display overview')

    def set_frames(self, center, cluster):
        self.center, self.cluster = center, cluster
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#101a23'))
        p.drawRoundedRect(QRectF(0, 0, w, h), 12, 12)
        for x in range(18, w, 22):
            for y in range(18, h, 22):
                p.setPen(QColor('#22313d'))
                p.drawPoint(x, y)
        empty = self.center.isNull() and self.cluster.isNull()
        display_height = h - 34 if empty else h
        ch = display_height - 30
        cw = ch * 720 / 1152
        left_w = min(w * .53, (display_height - 50) * 2.66)
        gap = 22
        start = max(12., (w - cw - left_w - gap) / 2)
        panels = [(QRectF(start, (display_height - left_w / 2.66) / 2, left_w, left_w / 2.66), self.cluster),
                  (QRectF(start + left_w + gap, 15, cw, ch), self.center)]
        for rect, frame in panels:
            p.setPen(QPen(QColor('#415568'), 2))
            p.setBrush(QColor('#060b10'))
            p.drawRoundedRect(rect, 9, 9)
            content = rect.adjusted(5, 5, -5, -5)
            if not frame.isNull():
                scaled = frame.scaled(content.size().toSize(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                p.drawPixmap(int(content.center().x() - scaled.width()/2), int(content.center().y() - scaled.height()/2), scaled)
            else:
                p.setPen(QPen(QColor('#2b414f'), 2))
                p.drawLine(content.center().toPoint(), (content.center() + QPointF(0, -12)).toPoint())
        if empty:
            p.setPen(QColor('#a7bdc8'))
            p.drawText(QRectF(10, h-29, w-20, 24), Qt.AlignCenter, self.message)
        p.end()


def readiness(environment):
    """Return an actionable setup state. Missing data is not a successful check."""
    if not environment:
        return 'checking'
    if environment.get('root_user'):
        return 'user'
    if environment.get('architecture') != 'x86_64':
        return 'architecture'
    if environment.get('missing') or not environment.get('runtime_ready'):
        return 'dependencies'
    if not environment.get('display_available'):
        return 'display'
    if not environment.get('systemd_available'):
        return 'services'
    if not environment.get('fuse_available'):
        return 'mounts'
    return 'ready'
