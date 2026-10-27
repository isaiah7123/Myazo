import ctypes
import os
import subprocess
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QPointF, QRectF, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QGuiApplication, QIcon, QImage, QImageReader, QKeySequence,
                           QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QShortcut)
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListView,
                               QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton, QSizePolicy,
                               QSlider, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

import ocr
import theme
from config import APP, IMG, VID
from icon import make_icon
from lazy import lazy
from log import log
from theme import PAL

try:
    from send2trash import send2trash
except Exception:  # pragma: no cover
    send2trash = None

cv2 = lazy("cv2")  # only loaded when a video thumbnail or frame is actually needed
GAP, PAD, INFO_H, RATIO, MIN_CELL = 20, 10, 66, 0.65, 270  # card grid metrics (px)
THUMB = (420, 280)  # largest stored thumbnail


# ---------- shell helpers shared by the grid menu and the viewer ----------
def show_in_folder(p):
    subprocess.Popen(["explorer", "/select,", str(Path(p))])


def open_default(p):
    os.startfile(str(Path(p)))


class OPENASINFO(ctypes.Structure):
    _fields_ = [("pcszFile", wintypes.LPCWSTR), ("pcszClass", wintypes.LPCWSTR), ("oaifInFlags", wintypes.DWORD)]


def open_with(p, hwnd=None):
    """Windows' 'Open with' chooser, parented to our window so it appears in front."""
    info = OPENASINFO(str(Path(p)), None, 0x1 | 0x4)  # OAIF_ALLOW_REGISTRATION | OAIF_EXEC
    fn = ctypes.windll.shell32.SHOpenWithDialog
    fn.argtypes = [wintypes.HWND, ctypes.POINTER(OPENASINFO)]
    fn.restype = ctypes.c_long
    hr = fn(hwnd, ctypes.byref(info)) & 0xFFFFFFFF
    if hr in (0, 0x800704C7):  # OK, or the user cancelled
        return
    subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", str(Path(p))])


class ThumbWorker(QThread):
    ready = Signal(str, QImage, float)  # path, thumbnail, video length in seconds (0 for images)

    def __init__(self, paths, cache):
        super().__init__()
        self.paths, self.cache, self._stop = paths, cache, False

    def stop(self):
        self._stop = True

    def run(self):
        self.cache.mkdir(parents=True, exist_ok=True)
        try:  # hide the metadata folder, but only if it isn't hidden yet (re-setting it would touch the media folder)
            k32, d = ctypes.windll.kernel32, str(self.cache.parent)
            a = k32.GetFileAttributesW(d)
            if a != 0xFFFFFFFF and not a & 2:
                k32.SetFileAttributesW(d, a | 2)
        except Exception:
            pass
        for p in self.paths:
            if self._stop:
                return
            try:
                img, dur = self.make(Path(p))
            except Exception:
                img, dur = None, 0.0
            if img is not None and not img.isNull():
                self.ready.emit(p, img, dur)

    def make(self, p):
        vid, dur, cap = p.suffix.lower() in VID, 0.0, None
        if vid:
            cap = cv2.VideoCapture(str(p))
            fps, n = cap.get(cv2.CAP_PROP_FPS) or 0, cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            dur = n / fps if fps > 0 and n > 0 else 0.0
        c = self.cache / f"{p.name}_{int(p.stat().st_mtime)}_v2.jpg"
        if c.exists():
            if cap:
                cap.release()
            return QImage(str(c)), dur
        if vid:
            cap.set(cv2.CAP_PROP_POS_MSEC, 500)
            ok, f = cap.read()
            if not ok:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, f = cap.read()
            cap.release()
            if not ok:
                return None, dur
            f = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
            h, w = f.shape[:2]
            img = QImage(f.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        else:
            r = QImageReader(str(p))
            r.setAutoTransform(True)
            sz = r.size()
            if sz.isValid():
                r.setScaledSize(sz.scaled(*THUMB, Qt.KeepAspectRatio))
            img = r.read()
        if img.isNull():
            return None, dur
        img = img.scaled(*THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        img.save(str(c), "JPG", 85)
        return img, dur


_live = set()  # keeps a running OCR thread alive even if its viewer window gets closed


class OcrWorker(QThread):
    done = Signal(list)
    failed = Signal(str)

    def __init__(self, st, path):
        super().__init__()
        self.st, self.path = st, path

    def run(self):
        try:
            words = ocr.ocr_words(self.st, self.path)
            ocr.store(self.st, self.path, ocr.join_words(words))  # also makes it searchable in the library
            self.done.emit(words)
        except Exception as e:
            lines = str(e).strip().splitlines()
            self.failed.emit((lines[0] if lines else type(e).__name__)[:240])


class TextImageView(QWidget):
    """Image scaled to fit. In text mode it outlines the OCR words and lets you drag a box to select them."""
    changed = Signal()

    def __init__(self, pix):
        super().__init__()
        self.pix, self.words, self.sel, self.mode = pix, [], set(), False
        self.p0 = self.p1 = None
        self.setMinimumSize(1, 1)

    def set_mode(self, on):
        self.mode, self.sel = on, set()
        self.setCursor(Qt.IBeamCursor if on else Qt.ArrowCursor)
        self.update()
        self.changed.emit()

    def _geo(self):
        s = min(self.width() / self.pix.width(), self.height() / self.pix.height())
        w, h = self.pix.width() * s, self.pix.height() * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h), s

    @staticmethod
    def _wr(w, t, s):
        return QRectF(t.x() + w[1] * s, t.y() + w[2] * s, w[3] * s, w[4] * s)

    def paintEvent(self, _):
        if self.pix.isNull():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        t, s = self._geo()
        p.drawPixmap(t, self.pix, QRectF(self.pix.rect()))
        if not self.mode:
            return
        for i, w in enumerate(self.words):
            r = self._wr(w, t, s)
            if i in self.sel:
                p.fillRect(r, QColor(61, 139, 253, 120))
            else:
                p.setPen(QPen(QColor(255, 200, 0, 170), 1))
                p.setBrush(QColor(255, 220, 0, 40))
                p.drawRect(r)
        if self.p0 is not None:
            p.setPen(QPen(QColor("#3d8bfd"), 1, Qt.DashLine))
            p.setBrush(QColor(61, 139, 253, 30))
            p.drawRect(QRectF(self.p0, self.p1).normalized())

    def _select(self):
        t, s = self._geo()
        band = QRectF(self.p0, self.p1).normalized()
        if band.width() < 4 and band.height() < 4:  # a plain click picks the word under the cursor
            band = band.adjusted(-2, -2, 2, 2)
        self.sel = {i for i, w in enumerate(self.words) if band.intersects(self._wr(w, t, s))}

    def mousePressEvent(self, e):
        if self.mode and e.button() == Qt.LeftButton:
            self.p0 = self.p1 = e.position()
            self._select()
            self.update()

    def mouseMoveEvent(self, e):
        if self.p0 is not None:
            self.p1 = e.position()
            self._select()
            self.update()

    def mouseReleaseEvent(self, e):
        if self.p0 is not None:
            self.p1 = e.position()
            self._select()
            self.p0 = self.p1 = None
            self.update()

    def has_selection(self):
        return bool(self.sel)

    def selected_text(self):
        return ocr.join_words([self.words[i] for i in sorted(self.sel)])

    def all_text(self):
        return ocr.join_words(self.words)

    def select_all(self):
        self.sel = set(range(len(self.words)))
        self.update()


class Viewer(QWidget):
    """Built-in viewer for images and videos, with buttons and a right-click menu."""
    closed = Signal(object)

    def __init__(self, path, st):
        super().__init__()
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.path, self.st = path, st
        self.is_video = Path(path).suffix.lower() in VID
        self.setWindowTitle(Path(path).name)
        self.setWindowIcon(make_icon())
        self.resize(1000, 720)
        self.player = self.worker = self.btn_text = None
        self.words_ready = self.copy_pending = False
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setContentsMargins(2, 0, 2, 0)
        self.note_timer = QTimer(self, singleShot=True)
        self.note_timer.timeout.connect(lambda: self.note.setText(""))
        self.note.setObjectName("note")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 8)
        lay.setSpacing(8)
        panel = QFrame()
        panel.setObjectName("panel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        lay.addWidget(panel, 1)

        if self.is_video:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer  # loaded only when a video is opened
            from PySide6.QtMultimediaWidgets import QVideoWidget
            target = QVideoWidget()
            pl.addWidget(target, 1)
            self.player = QMediaPlayer(self)
            self.audio = QAudioOutput(self)
            self.player.setAudioOutput(self.audio)
            self.player.setVideoOutput(target)
            self.player.setSource(QUrl.fromLocalFile(path))
            ctl = QHBoxLayout()
            ctl.setContentsMargins(12, 8, 12, 10)
            self.btn = QPushButton("Pause")
            self.sl = QSlider(Qt.Horizontal)
            ctl.addWidget(self.btn)
            ctl.addWidget(self.sl, 1)
            pl.addLayout(ctl)
            self.btn.clicked.connect(self._toggle)
            self.sl.sliderMoved.connect(self.player.setPosition)
            self.player.durationChanged.connect(lambda d: self.sl.setRange(0, d))
            self.player.positionChanged.connect(lambda v: None if self.sl.isSliderDown() else self.sl.setValue(v))
            self.player.play()
        else:
            self.pix = QPixmap(path)
            target = self.view = TextImageView(self.pix)
            self.view.changed.connect(self._sync_text_btn)
            pl.addWidget(self.view, 1)

        for w in (self, target):  # right-click anywhere in the viewer
            w.setContextMenuPolicy(Qt.CustomContextMenu)
            w.customContextMenuRequested.connect(lambda p, w=w: self._menu(w.mapToGlobal(p)))

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        for text, fn in self._actions():
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: self._run(f))
            if text.startswith("Select text"):
                b.setCheckable(True)
                self.btn_text = b
            bar.addWidget(b)
        bar.addStretch()
        lay.addLayout(bar)
        lay.addWidget(self.note)
        QShortcut(QKeySequence.Copy, self, activated=lambda: self._run(self._copy_primary))
        QShortcut(QKeySequence.SelectAll, self, activated=lambda: self._run(self._select_all))

    # ---------- actions ----------
    def _actions(self):
        p = self.path
        acts = [("Show in folder", lambda: show_in_folder(p)),
                ("Open with default app", lambda: open_default(p)),
                ("Open with…", lambda: open_with(p, int(self.winId())))]
        if self.is_video:
            acts.append(("Copy frame", self.copy_frame))
        else:
            acts += [("Copy image", self.copy_image), ("Select text (OCR)", self.toggle_text),
                     ("Copy text", self.copy_text)]
        return acts

    def _run(self, fn):
        try:
            fn()
        except Exception as e:
            self._say(f"Failed: {e}")

    def _menu(self, gpos):
        m = QMenu(self)
        for text, fn in self._actions():
            m.addAction(text).triggered.connect(lambda _=False, f=fn: self._run(f))
        m.exec(gpos)

    def _say(self, text, ms=2500):
        self.note.setText(text)
        self.note_timer.start(ms)

    def _copy_primary(self):  # Ctrl+C
        if self.is_video:
            self.copy_frame()
        elif self.view.mode and self.view.has_selection():
            self.copy_text()
        else:
            self.copy_image()

    def _select_all(self):  # Ctrl+A
        if not self.is_video and self.view.mode:
            self.view.select_all()

    def copy_image(self):
        if self.pix.isNull():
            return self._say("Couldn't read this image")
        QGuiApplication.clipboard().setPixmap(self.pix)
        self._say("Image copied to clipboard")

    def copy_frame(self):
        """Copies the frame at the current playback position, at the video's full resolution."""
        cap = cv2.VideoCapture(self.path)
        cap.set(cv2.CAP_PROP_POS_MSEC, self.player.position())
        ok, f = cap.read()
        cap.release()
        if not ok:
            return self._say("Couldn't read that frame")
        f = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
        h, w = f.shape[:2]
        QGuiApplication.clipboard().setImage(QImage(f.data, w, h, 3 * w, QImage.Format_RGB888).copy())
        self._say("Frame copied to clipboard")

    # ---------- OCR text selection ----------
    def _sync_text_btn(self):
        if self.btn_text:
            self.btn_text.setChecked(self.view.mode)

    def toggle_text(self):
        if self.view.mode:
            return self.view.set_mode(False)
        if self.words_ready:
            self.view.set_mode(True)
            return self._say("Drag over text to select it, then press Ctrl+C or use Copy text.", 5000)
        if self.worker is not None:
            return
        self._sync_text_btn()
        self._say("Reading text…", 120000)
        w = self.worker = OcrWorker(self.st, self.path)
        _live.add(w)
        w.finished.connect(lambda w=w: _live.discard(w))
        w.done.connect(self._ocr_done)
        w.failed.connect(self._ocr_failed)
        w.start()

    def _ocr_done(self, words):
        self.worker, self.words_ready = None, True
        self.view.words = words
        if not words:
            self.copy_pending = False
            return self._say("No text found in this image.", 5000)
        self.view.set_mode(True)
        if self.copy_pending:
            self.copy_pending = False
            self.copy_text()
        else:
            self._say(f"Found {len(words)} words — drag over text to select it, then press Ctrl+C.", 6000)

    def _ocr_failed(self, msg):
        self.worker, self.copy_pending = None, False
        self._sync_text_btn()
        self._say(msg, 10000)

    def copy_text(self):
        """Copies the selected words, or all recognised text if nothing is selected."""
        if not self.words_ready:
            self.copy_pending = True
            return self.toggle_text()
        sel = self.view.has_selection()
        txt = self.view.selected_text() if sel else self.view.all_text()
        if not txt:
            return self._say("No text to copy.")
        QGuiApplication.clipboard().setText(txt)
        self._say("Copied selected text" if sel else "Copied all recognised text")

    def showEvent(self, e):
        super().showEvent(e)
        theme.style_titlebar(self)

    # ---------- playback ----------
    def _toggle(self):
        from PySide6.QtMultimedia import QMediaPlayer
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.btn.setText("Play")
        else:
            self.player.play()
            self.btn.setText("Pause")

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
        elif e.key() == Qt.Key_Space and self.is_video:
            self._toggle()

    def closeEvent(self, e):
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())  # release the file lock
        self.closed.emit(self)
        super().closeEvent(e)


def fmt_size(n):
    if n < 1024 ** 2:
        return f"{max(1, round(n / 1024))} KB"
    return f"{n / 1024 ** 2:.1f} MB" if n < 1024 ** 3 else f"{n / 1024 ** 3:.2f} GB"


def fmt_dur(s):
    m, s = divmod(int(round(s)), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fmt_when(ts):
    """'Oct 26 · 6:44 PM' (the year is added only for captures from earlier years)."""
    dt = datetime.fromtimestamp(ts)
    day = f"{dt:%b} {dt.day}" + ("" if dt.year == datetime.now().year else f", {dt.year}")
    return f"{day} · {dt.strftime('%I:%M %p').lstrip('0')}"


R_PATH = Qt.UserRole
R_KEY, R_PIX, R_DUR, R_META, R_VID = (Qt.UserRole + i for i in range(1, 6))


class CardDelegate(QStyledItemDelegate):
    """Paints one media card: uniform preview well, title underneath, time/size and a type icon."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cell, self.prev_h = QSize(300, 280), 180

    def sizeHint(self, opt, idx):
        return self.cell

    def paint(self, p, opt, idx):
        P = PAL
        r = QRectF(opt.rect.adjusted(0, 0, -GAP, -GAP))
        sel, hov = bool(opt.state & QStyle.State_Selected), bool(opt.state & QStyle.State_MouseOver)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        card = QPainterPath()
        card.addRoundedRect(r.adjusted(0.75, 0.75, -0.75, -0.75), 14, 14)
        p.fillPath(card, QColor(P["card_hover"] if hov and not sel else P["card"]))
        p.setPen(QPen(QColor(P["accent"] if sel else P["card_line"]), 1.5 if sel else 1))
        p.drawPath(card)

        prev = QRectF(r.x() + PAD, r.y() + PAD, r.width() - 2 * PAD, self.prev_h)
        pix = idx.data(R_PIX)
        if isinstance(pix, QPixmap) and not pix.isNull():
            s = min(prev.width() / pix.width(), prev.height() / pix.height(), 2.0)
            w, h = pix.width() * s, pix.height() * s
            t = QRectF(prev.x() + (prev.width() - w) / 2, prev.y() + (prev.height() - h) / 2, w, h)
            clip = QPainterPath()
            clip.addRoundedRect(t, 10, 10)
            p.save()
            p.setClipPath(clip)
            p.drawPixmap(t, pix, QRectF(pix.rect()))
            p.restore()
            p.setPen(QPen(QColor(P["card_line"]), 1))
            p.setBrush(Qt.NoBrush)
            p.drawPath(clip)
        else:
            ph = QPainterPath()
            ph.addRoundedRect(prev, 10, 10)
            p.fillPath(ph, QColor(P["thumb_ph"]))

        vid = bool(idx.data(R_VID))
        if vid:  # play badge with the video length
            dur = idx.data(R_DUR) or ""
            f = QFont(opt.font)
            f.setPixelSize(12)
            f.setWeight(QFont.Medium)
            tw = QFontMetrics(f).horizontalAdvance(dur) if dur else 0
            bw, bh = (tw + 34) if dur else 30, 24
            b = QRectF(prev.right() - 8 - bw, prev.bottom() - 8 - bh, bw, bh)
            bp = QPainterPath()
            bp.addRoundedRect(b, 8, 8)
            p.fillPath(bp, QColor(8, 10, 18, 205))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#FFFFFF"))
            p.drawPolygon(QPolygonF([QPointF(b.x() + 10, b.y() + 7), QPointF(b.x() + 10, b.y() + 17),
                                     QPointF(b.x() + 18, b.y() + 12)]))
            if dur:
                p.setFont(f)
                p.setPen(QColor("#FFFFFF"))
                p.drawText(QRectF(b.x() + 24, b.y(), tw + 8, bh), Qt.AlignVCenter | Qt.AlignLeft, dur)

        tx, ty, tw_ = r.x() + 14, prev.bottom() + 10, r.width() - 28
        f = QFont(opt.font)
        f.setPixelSize(13)
        f.setWeight(QFont.Medium)
        p.setFont(f)
        p.setPen(QColor(P["text"]))
        name = QFontMetrics(f).elidedText(idx.data(Qt.DisplayRole) or "", Qt.ElideRight, int(tw_))
        p.drawText(QRectF(tx, ty, tw_, 20), Qt.AlignVCenter | Qt.AlignLeft, name)
        f2 = QFont(opt.font)
        f2.setPixelSize(12)
        p.setFont(f2)
        p.setPen(QColor(P["muted"]))
        meta = QFontMetrics(f2).elidedText(idx.data(R_META) or "", Qt.ElideRight, int(tw_ - 24))
        p.drawText(QRectF(tx, ty + 24, tw_ - 24, 18), Qt.AlignVCenter | Qt.AlignLeft, meta)
        p.drawPixmap(int(r.right() - 14 - 16), int(ty + 25), theme.pixmap("video" if vid else "image", P["muted"], 16))
        p.restore()


class GridList(QListWidget):
    resized = Signal()
    empty_text = ""

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.resized.emit()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.count() == 0 and self.empty_text:
            p = QPainter(self.viewport())
            p.setPen(QColor(PAL["dim"]))
            p.drawText(self.viewport().rect(), Qt.AlignCenter, self.empty_text)


class ActionButton(QPushButton):
    """Large rounded button: icon, bold label, and the shortcut in small text underneath."""

    def __init__(self, icon_name, title):
        super().__init__()
        self.setObjectName("actionBtn")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(44)
        self.icon_name = icon_name
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 18, 0)
        lay.setSpacing(10)
        self.ico = QLabel()
        self.ico.setFixedSize(20, 20)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.title, self.hint = QLabel(title), QLabel()
        self.title.setObjectName("actionTitle")
        self.hint.setObjectName("actionHint")
        col.addWidget(self.title)
        col.addWidget(self.hint)
        lay.addWidget(self.ico)
        lay.addLayout(col)
        for w in (self.ico, self.title, self.hint):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.retheme()

    def sizeHint(self):
        return self.layout().sizeHint()

    def set_hint(self, text):
        self.hint.setText(text)
        self.hint.setVisible(bool(text))

    def retheme(self):
        self.ico.setPixmap(theme.pixmap(self.icon_name, PAL["text"], 20))


class IconButton(QPushButton):
    def __init__(self, icon_name, tip):
        super().__init__()
        self.setObjectName("iconBtn")
        self.setFixedSize(44, 44)
        self.setIconSize(QSize(20, 20))
        self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor)
        self.icon_name = icon_name
        self.retheme()

    def retheme(self):
        self.setIcon(QIcon(theme.pixmap(self.icon_name, PAL["icon"], 20)))


class ClickLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, e):
        self.clicked.emit()


class Library(QMainWindow):
    def __init__(self, app):
        super().__init__()
        self.app, self.st = app, app.st
        self.workers, self.viewers, self.items, self.icons = [], [], {}, {}
        self.dirty = True
        self.setWindowTitle(APP)
        self.setWindowIcon(make_icon())
        self.setMinimumSize(980, 560)
        self.resize(1180, 760)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- top bar: capture / record / save replay, search, tools ---
        bar = QHBoxLayout()
        bar.setContentsMargins(14, 8, 14, 12)
        bar.setSpacing(10)
        self.b_cap, self.b_rec, self.b_rep = (ActionButton("capture", "Capture"), ActionButton("record", "Record"),
                                              ActionButton("replay", "Save replay"))
        self.b_cap.clicked.connect(lambda: self._cap("image"))
        self.b_rec.clicked.connect(lambda: self._cap("video"))
        self.b_rep.clicked.connect(self.app.save_replay)
        for b in (self.b_cap, self.b_rec, self.b_rep):
            bar.addWidget(b)
        bar.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search names and text in screenshots")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedSize(300, 44)
        self.search_act = self.search.addAction(QIcon(theme.pixmap("search", PAL["dim"], 18)), QLineEdit.LeadingPosition)
        bar.addWidget(self.search)
        self.icon_btns = []
        for name, tip, fn in (("refresh", "Refresh", self.hard_refresh),
                              ("folder", "Open media folder", lambda: os.startfile(self.st.storage())),
                              ("settings", "Settings", app.open_settings)):
            b = IconButton(name, tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            bar.addWidget(b)
            self.icon_btns.append(b)
        root.addLayout(bar)

        # --- main panel: filter tabs + sort, then the card grid ---
        self.panel = QFrame()
        self.panel.setObjectName("panel")
        pl = QVBoxLayout(self.panel)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        hdr = QHBoxLayout()
        hdr.setContentsMargins(24, 18, 24, 0)
        hdr.setSpacing(6)
        self.tabs, self.tab_btns = QButtonGroup(self), []
        for i in range(3):
            b = QPushButton()
            b.setObjectName("tab")
            b.setCheckable(True)
            b.setFixedHeight(36)
            b.setCursor(Qt.PointingHandCursor)
            self.tabs.addButton(b, i)
            hdr.addWidget(b)
            self.tab_btns.append(b)
        self.tab_btns[0].setChecked(True)
        hdr.addStretch(1)
        self.sort_btn = QPushButton("Date created")
        self.sort_btn.setObjectName("sortBtn")
        self.sort_btn.setFixedHeight(36)
        self.sort_btn.setCursor(Qt.PointingHandCursor)
        self.sort_btn.clicked.connect(self._flip)
        hdr.addWidget(self.sort_btn)
        pl.addLayout(hdr)

        self.lst = GridList()
        self.lst.setObjectName("grid")
        self.delegate = CardDelegate(self.lst)
        self.lst.setItemDelegate(self.delegate)
        self.lst.setViewMode(QListView.IconMode)
        self.lst.setResizeMode(QListView.Adjust)
        self.lst.setMovement(QListView.Static)
        self.lst.setSpacing(0)
        self.lst.setSelectionMode(QListWidget.ExtendedSelection)
        self.lst.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.lst.setMouseTracking(True)
        self.lst.setFrameShape(QFrame.NoFrame)
        self.lst.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lst.customContextMenuRequested.connect(self._menu)
        self.lst.itemDoubleClicked.connect(lambda it: self.open_path(it.data(R_PATH)))
        self.lst.resized.connect(self._relayout)
        QShortcut(QKeySequence(Qt.Key_Delete), self.lst, activated=lambda: self.delete(self._sel()))
        wrap = QHBoxLayout()
        wrap.setContentsMargins(24, 14, 4, 0)  # right margin is smaller: each card carries a trailing gap
        wrap.addWidget(self.lst)
        pl.addLayout(wrap, 1)
        pw = QHBoxLayout()
        pw.setContentsMargins(12, 0, 12, 0)
        pw.addWidget(self.panel)
        root.addLayout(pw, 1)

        # --- bottom bar: item count, folder size, replay buffer status ---
        sb = QHBoxLayout()
        sb.setContentsMargins(20, 0, 20, 0)
        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.replay_lbl = ClickLabel()
        self.replay_lbl.setObjectName("status")
        self.replay_lbl.setCursor(Qt.PointingHandCursor)
        self.replay_lbl.setToolTip("Click to start or stop the replay buffer")
        self.replay_lbl.clicked.connect(self._toggle_replay)
        sb.addWidget(self.status, 1)
        sb.addWidget(self.replay_lbl)
        status_row = QWidget()
        status_row.setFixedHeight(34)
        status_row.setLayout(sb)
        root.addWidget(status_row)

        # every refresh request funnels through this one debounced timer, so overlapping triggers
        # (capture finished + folder watcher + search typing) collapse into a single rebuild
        self.debounce = QTimer(self, singleShot=True, interval=200)
        self.debounce.timeout.connect(self._do_refresh)
        self.search.textChanged.connect(lambda _: self.debounce.start())
        self.tabs.idClicked.connect(lambda _: self.debounce.start())
        self.rtimer = QTimer(self, interval=1500)  # only runs while the window is visible
        self.rtimer.timeout.connect(self._replay_status)
        self._sig = None  # what the grid currently shows; identical rebuild requests are skipped
        self.fsw = QFileSystemWatcher(self)
        self.fsw.directoryChanged.connect(lambda _: self.debounce.start())
        app.theme.changed.connect(self.retheme)
        self.refresh_hints()
        self._sort_icon()
        self._replay_status()
        self.set_folder()

    # ---------- look ----------
    def retheme(self):
        for b in (self.b_cap, self.b_rec, self.b_rep, *self.icon_btns):
            b.retheme()
        self.search_act.setIcon(QIcon(theme.pixmap("search", PAL["dim"], 18)))
        self._sort_icon()
        self._replay_status()
        self.lst.viewport().update()

    def refresh_hints(self):
        """Shows the current shortcuts on the three big buttons."""
        self.b_cap.set_hint(self.st["hk_image"])
        self.b_rec.set_hint(self.st["hk_video"])
        self.b_rep.set_hint(self.st["hk_replay"])

    def _sort_icon(self):
        desc = bool(self.st["sort_desc"])
        self.sort_btn.setIcon(QIcon(theme.pixmap("sort_down" if desc else "sort_up", PAL["sort_text"], 16)))
        self.sort_btn.setToolTip("Newest first (click to reverse)" if desc else "Oldest first (click to reverse)")

    def _flip(self):
        self.st["sort_desc"] = not self.st["sort_desc"]
        self.st.save()
        self._sort_icon()
        self.refresh()

    def _replay_status(self):
        on = self.app.replay.running
        col = PAL["good"] if on else PAL["dim"]
        txt = (f"Replay buffer on · last {self.st['replay_seconds']} s" if on
               else "Replay buffer off · click to start")
        self.replay_lbl.setText(f"<span style='color:{col}'>●</span>&nbsp;&nbsp;{txt}")

    def _toggle_replay(self):
        self.app.toggle_replay()
        self._replay_status()

    def _relayout(self):
        """Sizes the cards so each row fills the width evenly (about four across on a normal window)."""
        # Qt lays icons out inside the viewer width minus the scroll bar's width, whether or not it is showing
        w = (self.lst.maximumViewportSize().width()
             - self.lst.style().pixelMetric(QStyle.PM_ScrollBarExtent, None, self.lst.verticalScrollBar()))
        w -= 4  # a few px of slack: Qt wraps a row if it fits to the pixel
        if w < 100:
            return
        cell_w = w // max(1, w // MIN_CELL)
        prev_h = int((cell_w - GAP - 2 * PAD) * RATIO)
        cell = QSize(cell_w, PAD + prev_h + INFO_H + GAP)
        if cell != self.delegate.cell:
            self.delegate.cell, self.delegate.prev_h = cell, prev_h
            self.lst.setGridSize(cell)
            self.lst.viewport().update()

    # ---------- refresh ----------
    def refresh(self):
        self.debounce.start()

    def hard_refresh(self):
        self.icons.clear()
        self._sig = None
        self.refresh()

    def set_folder(self):
        if self.fsw.directories():
            self.fsw.removePaths(self.fsw.directories())
        self.fsw.addPath(str(self.st.storage()))
        self._sig = None
        self.refresh()

    def showEvent(self, e):
        super().showEvent(e)
        self.app.theme.sync()  # pick up a Windows light/dark change made while we were hidden
        theme.style_titlebar(self)
        self._replay_status()
        self.rtimer.start()
        self._relayout()
        if self.dirty:  # changes that arrived while the window was hidden
            self.debounce.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.rtimer.stop()

    def _do_refresh(self):
        if not self.isVisible():
            self.dirty = True
            return
        self.dirty = False
        d = self.st.storage()
        q = self.search.text().lower().strip()
        k = self.tabs.checkedId()
        idx = ocr.load_index(self.st) if q else {}
        files = []
        for p in d.iterdir():
            try:
                if p.is_file() and p.suffix.lower() in IMG | VID:
                    stt = p.stat()
                    created = stt.st_birthtime if hasattr(stt, "st_birthtime") else stt.st_ctime
                    files.append((p, stt.st_mtime, created, stt.st_size))
            except OSError:
                pass
        files.sort(key=lambda t: t[2], reverse=bool(self.st["sort_desc"]))  # date created
        sig = (q, k, bool(self.st["sort_desc"]), len(idx), tuple((str(p), mt) for p, mt, _c, _s in files))
        if sig == self._sig:  # nothing visible changed (e.g. a folder-watcher ping): don't rebuild the grid
            return
        self._sig = sig
        log(f"library rebuilt ({len(files)} files)")

        counts, shown = [0, 0, 0], []  # all / images / videos that match the search
        for p, mt, created, size in files:
            vid = p.suffix.lower() in VID
            if q and q not in p.name.lower() and q not in idx.get(p.name, "").lower():
                continue
            counts[0] += 1
            counts[2 if vid else 1] += 1
            if (k == 1 and vid) or (k == 2 and not vid):
                continue
            shown.append((p, mt, created, size, vid))
        for b, name, n in zip(self.tab_btns, ("All captures", "Images", "Videos"), counts):
            b.setText(f"{name}  {n}")

        self.lst.setUpdatesEnabled(False)
        try:
            self.lst.clear()
            self.items, todo = {}, []
            for p, mt, created, size, vid in shown:
                key = f"{p}|{int(mt)}"
                it = QListWidgetItem(p.name)
                it.setData(R_PATH, str(p))
                it.setData(R_KEY, key)
                it.setData(R_VID, vid)
                it.setData(R_META, f"{fmt_when(created)} · {fmt_size(size)}")
                it.setToolTip(str(p))
                cached = self.icons.get(key)
                if cached:
                    it.setData(R_PIX, cached[0])
                    it.setData(R_DUR, cached[1])
                else:
                    todo.append(str(p))
                self.lst.addItem(it)
                self.items[str(p)] = it
        finally:
            self.lst.setUpdatesEnabled(True)
        self.lst.empty_text = "No matches" if q else "No captures yet."
        self._relayout()
        self.lst.viewport().update()

        for w in self.workers:
            w.stop()
        self.workers = [w for w in self.workers if w.isRunning()]
        if todo:
            w = ThumbWorker(todo, self.st.meta_dir() / "thumbs")
            w.ready.connect(self._thumb)
            self.workers.append(w)
            w.start()
        total = fmt_size(sum(s for _p, _m, _c, s in files))
        shown_txt = f"{len(shown)} items" if counts[0] == len(files) and k == 0 else f"{len(shown)} of {len(files)} items"
        self.status.setText(f"{shown_txt} · {total} — {d}")

    def _thumb(self, path, img, dur):
        it = self.items.get(path)
        if not it:
            return
        pm, d = QPixmap.fromImage(img), (fmt_dur(dur) if dur > 0 else "")
        self.icons[it.data(R_KEY)] = (pm, d)
        it.setData(R_PIX, pm)
        it.setData(R_DUR, d)

    # ---------- window / actions ----------
    def _cap(self, base):
        self.hide()
        self.app.later(lambda: self.app.act(base, False))

    def show_front(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def show_item(self, path):
        self.show_front()
        self._do_refresh()
        self.open_path(path)

    def _sel(self):
        return [i.data(R_PATH) for i in self.lst.selectedItems()]

    def _menu(self, pos):
        paths = self._sel()
        if not paths:
            return
        p = paths[0]
        m = QMenu(self)
        m.addAction("Open").triggered.connect(lambda: self.open_path(p))
        m.addAction("Open with default app").triggered.connect(lambda: open_default(p))
        m.addAction("Open with…").triggered.connect(lambda: open_with(p, int(self.winId())))
        m.addAction("Show in folder").triggered.connect(lambda: show_in_folder(p))
        m.addSeparator()
        m.addAction("Copy").triggered.connect(lambda: self.app.copy_path(p, "image"))
        m.addAction("Copy file path").triggered.connect(lambda: self.app.copy_path(p, "path"))
        m.addAction("Rename…").triggered.connect(lambda: self.rename(p))
        m.addSeparator()
        m.addAction("Delete").triggered.connect(lambda: self.delete(paths))
        m.exec(self.lst.mapToGlobal(pos))

    def open_path(self, path):
        v = Viewer(path, self.st)
        v.closed.connect(lambda vv: self.viewers.remove(vv) if vv in self.viewers else None)
        self.viewers.append(v)
        v.show()
        v.raise_()
        v.activateWindow()

    def rename(self, path):
        p = Path(path)
        name, ok = QInputDialog.getText(self, "Rename", "New name:", text=p.stem)
        if ok and name.strip():
            try:
                p.rename(p.with_name(name.strip() + p.suffix))
            except OSError as e:
                QMessageBox.warning(self, "Rename", str(e))
            self.refresh()

    def delete(self, paths):
        if not paths:
            return
        if QMessageBox.question(self, "Delete", f"Move {len(paths)} item(s) to the Recycle Bin?") != QMessageBox.Yes:
            return
        for v in list(self.viewers):
            if v.path in paths:
                v.close()
        for p in paths:
            try:
                (send2trash or os.remove)(str(Path(p)))
            except Exception as e:
                QMessageBox.warning(self, "Delete", str(e))
        self.refresh()

    def closeEvent(self, e):
        if self.st["keep_in_tray"]:
            e.ignore()
            self.hide()
            self.app.trim_later()
        else:
            self.app.quit()
            e.accept()
