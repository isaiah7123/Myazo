from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# Myazo logo: a navy diamond with a white monoline "M"
LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect x="12" y="12" width="40" height="40" rx="9" transform="rotate(45 32 32)" fill="#26345C"/>'
    '<path d="M23 41V25L32 34 41 25V41" fill="none" stroke="#FFFFFF" stroke-width="4" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>')


def make_pixmap(size=256):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    QSvgRenderer(QByteArray(LOGO_SVG.encode())).render(p)
    p.end()
    return pm


_icon = None


def make_icon():
    """The app icon, rendered at several sizes so it stays crisp in the tray, title bars and taskbar."""
    global _icon
    if _icon is None:
        _icon = QIcon()
        for s in (16, 24, 32, 48, 64, 128, 256):
            _icon.addPixmap(make_pixmap(s))
    return _icon


if __name__ == "__main__":  # build step: python icon.py -> app.ico (multi-size, so small icons stay sharp)
    import os
    import tempfile
    _app = QGuiApplication([])
    tmp = os.path.join(tempfile.gettempdir(), "myazo_logo.png")
    make_pixmap(256).save(tmp)
    try:
        from PIL import Image
        Image.open(tmp).save("app.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    except Exception:
        make_pixmap(256).save("app.ico")
