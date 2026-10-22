import ctypes
import time
from ctypes import wintypes

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

FLAGS = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool


def exclude_from_capture(w, on=True):
    """WDA_EXCLUDEFROMCAPTURE: window stays visible to you but is invisible to screen capture."""
    try:
        ctypes.windll.user32.SetWindowDisplayAffinity(wintypes.HWND(int(w.winId())), 0x11 if on else 0)
    except Exception:
        pass


class _Frame(QWidget):
    def __init__(self, r):
        super().__init__(None, FLAGS | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setGeometry(r.adjusted(-4, -4, 4, 4))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setPen(QPen(QColor("#ff3b30"), 2))
        p.drawRect(self.rect().adjusted(1, 1, -2, -2))


class RecordHUD(QWidget):
    """Region outline + small control bar (timer and Stop button)."""

    def __init__(self, scr, rect, exclude, on_stop):
        super().__init__(None, FLAGS)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet("QWidget{background:#202124;color:white;font-size:13px}"
                           "QPushButton{background:#d93025;border:0;padding:4px 14px;border-radius:4px}")
        self.lbl = QLabel("● 00:00")
        self.btn = QPushButton("Stop")
        self.btn.clicked.connect(lambda _=False: on_stop())
        lay = QHBoxLayout(self)
        lay.addWidget(self.lbl)
        lay.addWidget(self.btn)
        self.adjustSize()
        g = scr.geometry()
        w, h = self.sizeHint().width(), self.sizeHint().height()
        self.frame = None
        if rect is not None:
            gr = rect.translated(g.topLeft())
            self.frame = _Frame(gr)
            x, y = gr.center().x() - w // 2, gr.bottom() + 10
            if y + h > g.bottom():
                y = gr.top() - h - 10
            if y < g.top():
                y = gr.bottom() - h - 10
        else:
            x, y = g.center().x() - w // 2, g.top() + 10
        self.move(x, y)
        self.exclude = exclude
        self.t0 = time.monotonic()
        self.timer = QTimer(self, interval=500)
        self.timer.timeout.connect(self._tick)

    def present(self):
        if self.frame:
            self.frame.show()
            exclude_from_capture(self.frame)
        self.show()
        exclude_from_capture(self, self.exclude)
        self.t0 = time.monotonic()
        self.timer.start()

    def _tick(self):
        s = int(time.monotonic() - self.t0)
        self.lbl.setText(f"● {s // 60:02d}:{s % 60:02d}")

    def saving(self):
        self.timer.stop()
        self.lbl.setText("Saving…")
        self.btn.setEnabled(False)

    def close_all(self):
        self.timer.stop()
        if self.frame:
            self.frame.close()
        self.close()
