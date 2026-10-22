import ctypes
from ctypes import wintypes

import mss
from PySide6.QtCore import QObject, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

user32 = ctypes.windll.user32
dwm = ctypes.windll.dwmapi


def monitors():
    with mss.mss() as m:
        return [dict(x) for x in m.monitors[1:]]


def to_physical(screen, r=None):
    """QScreen (+ optional QRect in that screen's local logical coords) -> mss region in physical px."""
    mons = monitors()
    dpr = screen.devicePixelRatio()
    g = screen.geometry()
    w, h = round(g.width() * dpr), round(g.height() * dpr)
    cands = [m for m in mons if (m["width"], m["height"]) == (w, h)] or mons
    m = min(cands, key=lambda m: abs(m["left"] - g.x() * dpr) + abs(m["top"] - g.y() * dpr))
    if r is None:
        return dict(m)
    return {"left": m["left"] + round(r.x() * dpr), "top": m["top"] + round(r.y() * dpr),
            "width": round(r.width() * dpr), "height": round(r.height() * dpr)}


def grab(mon):
    with mss.mss() as s:
        sh = s.grab(mon)
        return QImage(sh.bgra, sh.width, sh.height, sh.width * 4, QImage.Format_RGB32).copy()


def screen_under_cursor():
    return QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()


def active_window_rect():
    user32.GetForegroundWindow.restype = wintypes.HWND
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    r = wintypes.RECT()
    if dwm.DwmGetWindowAttribute(wintypes.HWND(hwnd), 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r))
    mons = monitors()
    L, T = min(m["left"] for m in mons), min(m["top"] for m in mons)
    R, B = max(m["left"] + m["width"] for m in mons), max(m["top"] + m["height"] for m in mons)
    l, t, rr, b = max(r.left, L), max(r.top, T), min(r.right, R), min(r.bottom, B)
    if rr - l < 2 or b - t < 2:
        return None
    return {"left": l, "top": t, "width": rr - l, "height": b - t}


class _Overlay(QWidget):
    done = Signal(object, object, object)  # screen, local logical QRect | None, pixmap

    def __init__(self, screen, pix):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.scr, self.pix = screen, pix
        self.a = self.b = None
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)

    def _sel(self):
        return QRect(self.a, self.b).normalized() if self.a and self.b else None

    def paintEvent(self, _):
        p = QPainter(self)
        p.drawPixmap(self.rect(), self.pix)
        p.fillRect(self.rect(), QColor(0, 0, 0, 120))
        r = self._sel()
        if r:
            p.save()
            p.setClipRect(r)
            p.drawPixmap(self.rect(), self.pix)
            p.restore()
            p.setPen(QPen(QColor("#3d8bfd"), 2))
            p.drawRect(r)
            d = self.scr.devicePixelRatio()
            p.setPen(Qt.white)
            p.drawText(r.x(), max(14, r.y() - 6), f"{round(r.width() * d)} × {round(r.height() * d)}")

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.done.emit(self.scr, None, self.pix)
        else:
            self.a = self.b = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if self.a:
            self.b = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        r = self._sel()
        if r and r.width() > 3 and r.height() > 3:
            self.done.emit(self.scr, r, self.pix)
        else:
            self.a = self.b = None
            self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.done.emit(self.scr, None, self.pix)


class RegionPicker(QObject):
    picked = Signal(object, object, object)
    cancelled = Signal()

    def __init__(self):
        super().__init__()
        self._ov = []
        # Esc is polled globally while the overlay is up: Windows often refuses to give a window opened from
        # a global hotkey keyboard focus, which would make a normal key handler miss the key press.
        self._esc_timer = QTimer(self)
        self._esc_timer.setInterval(15)
        self._esc_timer.timeout.connect(self._poll_esc)
        self._esc_was_down = False

    def _poll_esc(self):
        down = bool(user32.GetAsyncKeyState(0x1B) & 0x8000)
        if down and not self._esc_was_down:
            self.cancel()
        self._esc_was_down = down

    def cancel(self):
        if self._ov:
            o = self._ov[0]
            self._done(o.scr, None, o.pix)

    @property
    def active(self):
        return bool(self._ov)

    def start(self):
        if self._ov:
            return
        self._esc_was_down = bool(user32.GetAsyncKeyState(0x1B) & 0x8000)  # only react to a fresh press
        self._esc_timer.start()
        for s in QGuiApplication.screens():
            o = _Overlay(s, s.grabWindow(0))
            o.done.connect(self._done)
            self._ov.append(o)
            o.show()
        cur = screen_under_cursor()
        for o in self._ov:
            if o.scr == cur:
                o.raise_()
                o.activateWindow()
                o.setFocus()

    def _done(self, screen, rect, pix):
        self._esc_timer.stop()
        for o in self._ov:
            o.close()
            o.deleteLater()
        self._ov = []
        if rect is None:
            self.cancelled.emit()
        else:
            self.picked.emit(screen, rect, pix)
