from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QLinearGradient, QPainter, QPen, QPixmap


def make_pixmap(size=256):
    pm = QPixmap(256, 256)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, 256, 256)
    g.setColorAt(0, QColor("#4f9dff"))
    g.setColorAt(1, QColor("#1b4fd8"))
    p.setBrush(g)
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(16, 16, 224, 224, 48, 48)
    p.setPen(QPen(Qt.white, 20, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    for x, y, dx, dy in ((70, 70, 1, 1), (186, 70, -1, 1), (70, 186, 1, -1), (186, 186, -1, -1)):
        p.drawLine(x, y, x + 46 * dx, y)
        p.drawLine(x, y, x, y + 46 * dy)
    p.setBrush(Qt.white)
    p.setPen(Qt.NoPen)
    p.drawEllipse(QPoint(128, 128), 16, 16)
    p.end()
    return pm


def make_icon():
    return QIcon(make_pixmap())


if __name__ == "__main__":  # build step: python icon.py -> app.ico
    _app = QGuiApplication([])
    make_pixmap().save("app.ico")
