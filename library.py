import ctypes
import os
import subprocess
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QPoint, QRectF, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (QColor, QGuiApplication, QIcon, QImage, QImageReader, QKeySequence, QPainter, QPen,
                           QPixmap, QPolygon, QShortcut)
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListView, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton, QSlider, QToolBar,
                               QVBoxLayout, QWidget)

from config import APP, IMG, VID
from icon import make_icon
import ocr
from lazy import lazy
from log import log

try:
    from send2trash import send2trash
except Exception:  # pragma: no cover
    send2trash = None

cv2 = lazy("cv2")  # only loaded when a video thumbnail or frame is actually needed
TW, TH = 220, 140


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
    ready = Signal(str, QImage)

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
                img = self.make(Path(p))
            except Exception:
                img = None
            if img is not None and not img.isNull():
                self.ready.emit(p, img)

    def make(self, p):
        c = self.cache / f"{p.name}_{int(p.stat().st_mtime)}.jpg"
        if c.exists():
            return QImage(str(c))
        if p.suffix.lower() in VID:
            cap = cv2.VideoCapture(str(p))
            cap.set(cv2.CAP_PROP_POS_MSEC, 500)
            ok, f = cap.read()
            if not ok:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, f = cap.read()
            cap.release()
            if not ok:
                return None
            f = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
            h, w = f.shape[:2]
            img = QImage(f.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        else:
            r = QImageReader(str(p))
            r.setAutoTransform(True)
            sz = r.size()
            if sz.isValid():
                r.setScaledSize(sz.scaled(TW * 2, TH * 2, Qt.KeepAspectRatio))
            img = r.read()
        if img.isNull():
            return None
        img = img.scaled(TW * 2, TH * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        img.save(str(c), "JPG", 85)
        return img


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
        self.note.setContentsMargins(10, 0, 10, 6)
        self.note_timer = QTimer(self, singleShot=True)
        self.note_timer.timeout.connect(lambda: self.note.setText(""))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        if self.is_video:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer  # loaded only when a video is opened
            from PySide6.QtMultimediaWidgets import QVideoWidget
            target = QVideoWidget()
            lay.addWidget(target, 1)
            self.player = QMediaPlayer(self)
            self.audio = QAudioOutput(self)
            self.player.setAudioOutput(self.audio)
            self.player.setVideoOutput(target)
            self.player.setSource(QUrl.fromLocalFile(path))
            ctl = QHBoxLayout()
            ctl.setContentsMargins(8, 4, 8, 0)
            self.btn = QPushButton("Pause")
            self.sl = QSlider(Qt.Horizontal)
            ctl.addWidget(self.btn)
            ctl.addWidget(self.sl, 1)
            lay.addLayout(ctl)
            self.btn.clicked.connect(self._toggle)
            self.sl.sliderMoved.connect(self.player.setPosition)
            self.player.durationChanged.connect(lambda d: self.sl.setRange(0, d))
            self.player.positionChanged.connect(lambda v: None if self.sl.isSliderDown() else self.sl.setValue(v))
            self.player.play()
        else:
            self.pix = QPixmap(path)
            target = self.view = TextImageView(self.pix)
            self.view.changed.connect(self._sync_text_btn)
            lay.addWidget(self.view, 1)

        for w in (self, target):  # right-click anywhere in the viewer
            w.setContextMenuPolicy(Qt.CustomContextMenu)
            w.customContextMenuRequested.connect(lambda p, w=w: self._menu(w.mapToGlobal(p)))

        bar = QHBoxLayout()
        bar.setContentsMargins(8, 6, 8, 2)
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


class Library(QMainWindow):
    def __init__(self, app):
        super().__init__()
        self.app, self.st = app, app.st
        self.workers, self.viewers, self.items, self.icons = [], [], {}, {}
        self.dirty = True
        self.setWindowTitle(f"{APP} — Library")
        self.setWindowIcon(make_icon())
        self.resize(1100, 720)

        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)

        def tool(text, fn):
            tb.addAction(text).triggered.connect(lambda _=False: fn())

        tool("📷 Capture", lambda: self._cap("image"))
        tool("🎬 Record", lambda: self._cap("video"))
        tb.addSeparator()
        self.search = QLineEdit(placeholderText="Search file names and text in screenshots…")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(300)
        self.kind = QComboBox()
        self.kind.addItems(["All", "Images", "Videos"])
        tb.addWidget(self.search)
        tb.addWidget(self.kind)
        self.sort = QComboBox()
        for label, data in (("Date created", "date"), ("Name", "name"), ("File type", "type")):
            self.sort.addItem(label, data)
        self.sort.setCurrentIndex(max(0, self.sort.findData(self.st["sort_key"])))
        self.dir_btn = QPushButton()
        self.dir_btn.setToolTip("Reverse the sort order")
        self._dir_text()
        tb.addWidget(QLabel("  Sort: "))
        tb.addWidget(self.sort)
        tb.addWidget(self.dir_btn)
        self.sort.currentIndexChanged.connect(self._sort_changed)
        self.dir_btn.clicked.connect(self._flip)
        tb.addSeparator()
        tool("Refresh", self.hard_refresh)
        tool("Open folder", lambda: os.startfile(self.st.storage()))
        tool("⚙ Settings", app.open_settings)

        self.lst = QListWidget()
        self.lst.setViewMode(QListView.IconMode)
        self.lst.setIconSize(QSize(TW, TH))
        self.lst.setGridSize(QSize(TW + 24, TH + 48))
        self.lst.setUniformItemSizes(True)
        self.lst.setResizeMode(QListView.Adjust)
        self.lst.setMovement(QListView.Static)
        self.lst.setSelectionMode(QListWidget.ExtendedSelection)
        self.lst.setWordWrap(True)
        self.lst.setTextElideMode(Qt.ElideMiddle)
        self.lst.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lst.customContextMenuRequested.connect(self._menu)
        self.lst.itemDoubleClicked.connect(lambda it: self.open_path(it.data(Qt.UserRole)))
        QShortcut(QKeySequence(Qt.Key_Delete), self.lst, activated=lambda: self.delete(self._sel()))
        self.setCentralWidget(self.lst)
        self.status = QLabel()
        self.statusBar().addWidget(self.status)

        ph = QPixmap(TW, TH)
        ph.fill(QColor("#d8d8d8"))
        self.ph_icon = QIcon(ph)
        # every refresh request funnels through this one debounced timer, so overlapping triggers
        # (capture finished + folder watcher + search typing) collapse into a single rebuild
        self.debounce = QTimer(self, singleShot=True, interval=200)
        self.debounce.timeout.connect(self._do_refresh)
        self.search.textChanged.connect(lambda _: self.debounce.start())
        self.kind.currentIndexChanged.connect(lambda _: self.debounce.start())
        self._sig = None  # what the grid currently shows; identical rebuild requests are skipped
        self.fsw = QFileSystemWatcher(self)
        self.fsw.directoryChanged.connect(lambda _: self.debounce.start())
        self.set_folder()

    # ---------- sorting ----------
    def _dir_text(self):
        d, k = self.st["sort_desc"], self.sort.currentData()
        self.dir_btn.setText(("Newest first" if d else "Oldest first") if k == "date"
                             else ("Z → A" if d else "A → Z"))

    def _sort_changed(self):
        k = self.sort.currentData()
        self.st["sort_key"], self.st["sort_desc"] = k, (k == "date")  # sensible default direction per key
        self.st.save()
        self._dir_text()
        self.refresh()

    def _flip(self):
        self.st["sort_desc"] = not self.st["sort_desc"]
        self.st.save()
        self._dir_text()
        self.refresh()

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
        if self.dirty:  # changes that arrived while the window was hidden
            self.debounce.start()

    def _do_refresh(self):
        if not self.isVisible():
            self.dirty = True
            return
        self.dirty = False
        d = self.st.storage()
        q = self.search.text().lower().strip()
        k = self.kind.currentIndex()
        idx = ocr.load_index(self.st) if q else {}
        files = []
        for p in d.iterdir():
            try:
                if p.is_file() and p.suffix.lower() in IMG | VID:
                    stt = p.stat()
                    created = stt.st_birthtime if hasattr(stt, "st_birthtime") else stt.st_ctime
                    files.append((p, stt.st_mtime, created))
            except OSError:
                pass
        keyf = {"date": lambda t: t[2], "name": lambda t: t[0].name.lower(),
                "type": lambda t: (t[0].suffix.lower(), t[0].name.lower())}[self.sort.currentData()]
        files.sort(key=keyf, reverse=bool(self.st["sort_desc"]))
        sig = (q, k, self.sort.currentData(), bool(self.st["sort_desc"]), len(idx),
               tuple((str(p), mt) for p, mt, _c in files))
        if sig == self._sig:  # nothing visible changed (e.g. a folder-watcher ping): don't rebuild the grid
            return
        self._sig = sig
        log(f"library rebuilt ({len(files)} files)")

        self.lst.setUpdatesEnabled(False)
        try:
            self.lst.clear()
            self.items, todo = {}, []
            for p, mt, _created in files:
                vid = p.suffix.lower() in VID
                if (k == 1 and vid) or (k == 2 and not vid):
                    continue
                if q and q not in p.name.lower() and q not in idx.get(p.name, "").lower():
                    continue
                key = f"{p}|{int(mt)}"
                icon = self.icons.get(key)
                it = QListWidgetItem(icon or self.ph_icon, p.name)
                it.setData(Qt.UserRole, str(p))
                it.setData(Qt.UserRole + 1, key)
                it.setToolTip(str(p))
                self.lst.addItem(it)
                self.items[str(p)] = it
                if icon is None:
                    todo.append(str(p))
            count = self.lst.count()
        finally:
            self.lst.setUpdatesEnabled(True)
        self.lst.viewport().update()

        for w in self.workers:
            w.stop()
        self.workers = [w for w in self.workers if w.isRunning()]
        if todo:
            w = ThumbWorker(todo, self.st.meta_dir() / "thumbs")
            w.ready.connect(self._thumb)
            self.workers.append(w)
            w.start()
        self.status.setText(f"{count} items — {d}")

    def _thumb(self, path, img):
        it = self.items.get(path)
        if not it:
            return
        pm = QPixmap.fromImage(img).scaled(TW, TH, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if Path(path).suffix.lower() in VID:
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            p.setBrush(QColor(0, 0, 0, 160))
            p.setPen(Qt.NoPen)
            c = pm.rect().center()
            p.drawEllipse(c, 22, 22)
            p.setBrush(Qt.white)
            p.drawPolygon(QPolygon([QPoint(c.x() - 7, c.y() - 12), QPoint(c.x() - 7, c.y() + 12),
                                    QPoint(c.x() + 13, c.y())]))
            p.end()
        icon = QIcon(pm)
        self.icons[it.data(Qt.UserRole + 1)] = icon
        it.setIcon(icon)

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
        return [i.data(Qt.UserRole) for i in self.lst.selectedItems()]

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
