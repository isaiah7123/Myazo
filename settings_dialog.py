from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout,
                               QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                               QSpinBox, QTabWidget, QVBoxLayout, QWidget)

import theme
from config import APP, HOTKEYS


class HotkeyEdit(QLineEdit):
    """Click, then press the combination you want (e.g. Ctrl+Shift+C). Backspace clears."""
    MODS = {int(Qt.Key_Control), int(Qt.Key_Shift), int(Qt.Key_Alt), int(Qt.Key_Meta), int(Qt.Key_AltGr)}

    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setPlaceholderText("Click, then press keys")
        self._val = ""

    def value(self):
        return self._val

    def setValue(self, v):
        self._val = v
        self.setText(v)

    def event(self, e):
        if e.type() == QEvent.ShortcutOverride:  # let us receive Tab/Esc/etc. instead of the dialog
            e.accept()
            return True
        return super().event(e)

    def focusNextPrevChild(self, nxt):
        return False

    def keyPressEvent(self, e):
        k, m = int(e.key()), e.modifiers()
        parts = [n for f, n in ((Qt.ControlModifier, "Ctrl"), (Qt.AltModifier, "Alt"),
                                (Qt.ShiftModifier, "Shift"), (Qt.MetaModifier, "Meta")) if m & f]
        if k in self.MODS or k == int(Qt.Key_unknown):
            self.setText("+".join(parts + [""]) if parts else "")  # live preview while modifiers are held
            return
        if not parts and k in (int(Qt.Key_Backspace), int(Qt.Key_Delete)):
            self.setValue("")
            return
        self.setValue("+".join(parts + [QKeySequence(k).toString()]))

    def keyReleaseEvent(self, e):
        self.setText(self._val)

    def focusOutEvent(self, e):
        self.setText(self._val)
        super().focusOutEvent(e)


class SettingsDialog(QDialog):
    def __init__(self, st, parent=None):
        super().__init__(parent)
        self.st, self.w = st, {}
        self.setWindowTitle(f"{APP} Settings")
        self.setMinimumSize(720, 560)
        self.resize(760, 680)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(12)
        tabs = QTabWidget()
        lay.addWidget(tabs)
        tabs.addTab(self._general(), "General")
        tabs.addTab(self._keys(), "Shortcut keys")
        tabs.addTab(self._more(), "More options")
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setObjectName("primary")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._load()

    # --- widget helpers (each registers itself under its settings key) ---
    def _reg(self, key, widget):
        self.w[key] = widget
        return widget

    def _chk(self, key, text):
        return self._reg(key, QCheckBox(text))

    def _combo(self, key, items):
        c = QComboBox()
        for label, data in items:
            c.addItem(label, data)
        return self._reg(key, c)

    def _spin(self, key, lo, hi, suffix=""):
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setSuffix(suffix)
        return self._reg(key, s)

    def _general(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(10)
        row = QHBoxLayout()
        row.addWidget(QLabel("Theme"))
        row.addWidget(self._combo("theme", [("Auto (match Windows)", "auto"), ("Light", "light"), ("Dark", "dark")]))
        row.addStretch()
        v.addLayout(row)
        v.addWidget(self._chk("keep_in_tray", "Keep Myazo running in the system tray when the window is closed"))
        v.addWidget(self._chk("start_with_windows", "Launch Myazo when Windows starts"))
        v.addWidget(self._chk("open_after_capture", "Open in app after capture (tray menu and PrintScreen captures)"))
        v.addWidget(self._chk("copy_after_capture", "Copy to clipboard after capture"))
        v.addWidget(self._chk("notify_capture", "Show a Windows notification when media is saved (with Open buttons)"))
        row = QHBoxLayout()
        row.addSpacing(24)
        row.addWidget(QLabel("Copy as"))
        row.addWidget(self._combo("clip_format", [("Image (videos copy as file)", "image"),
                                                  ("File", "file"), ("File path", "path")]))
        row.addStretch()
        v.addLayout(row)
        v.addWidget(self._chk("play_sound", "Play sound on capture"))
        v.addStretch()
        return w

    def _keys(self):
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(20, 20, 20, 20)
        g.setVerticalSpacing(10)
        g.addWidget(QLabel("<b>Capture in background</b>"), 0, 1)
        g.addWidget(QLabel("<b>Capture, then open in app</b>"), 0, 2)
        for r, (k, label, _a, b) in enumerate(HOTKEYS, 1):
            g.addWidget(QLabel(label), r, 0)
            for c, key in ((1, "hk_" + k), (2, "hk_" + k + "_open")):
                if c == 2 and b is None:
                    continue
                cell = QWidget()
                h = QHBoxLayout(cell)
                h.setContentsMargins(0, 0, 0, 0)
                e = HotkeyEdit()
                x = QPushButton("✕")
                x.setFixedWidth(30)
                x.setObjectName("clearBtn")
                x.clicked.connect(e.clear)
                h.addWidget(e)
                h.addWidget(x)
                self._reg(key, e)
                g.addWidget(cell, r, c)
        g.addWidget(self._chk("printscreen", "Start image capture with the PrintScreen key"), len(HOTKEYS) + 1, 0, 1, 3)
        g.setRowStretch(len(HOTKEYS) + 2, 1)
        return w

    def _more(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(16, 6, 16, 16)

        box = QGroupBox("Library")
        f = QFormLayout(box)
        row = QHBoxLayout()
        d = self._reg("storage_dir", QLineEdit())
        br = QPushButton("Browse…")
        br.clicked.connect(self._browse)
        row.addWidget(d)
        row.addWidget(br)
        f.addRow("Media storage location", row)
        f.addRow("Screenshot format", self._combo("image_format", [("PNG", "png"), ("JPEG", "jpg")]))
        f.addRow(self._chk("ocr", "Index new screenshots for text search (OCR, requires Tesseract)"))
        f.addRow("Tesseract path (blank = auto-detect)", self._reg("tesseract_path", QLineEdit()))
        f.addRow("OCR language(s), e.g. eng or eng+spa", self._reg("ocr_lang", QLineEdit()))
        v.addWidget(box)

        box = QGroupBox("Video")
        f = QFormLayout(box)
        f.addRow("Maximum final video resolution", self._combo("max_res", [
            ("1280 x 720", "1280 x 720"), ("1920 x 1080", "1920 x 1080"),
            ("2560 x 1440", "2560 x 1440"), ("3840 x 2160", "3840 x 2160"), ("Original", "original")]))
        f.addRow("Frame rate", self._combo("fps", [("15 FPS", 15), ("30 FPS", 30), ("60 FPS", 60)]))
        f.addRow(self._chk("rec_system", "Record system audio"))
        f.addRow(self._chk("rec_mic", "Record mic audio"))
        f.addRow(self._chk("rec_normalize", "Enable volume normalization"))
        f.addRow(self._chk("exclude_bar", "Exclude control bar from recording"))
        f.addRow("Recording duration limit (0 = unlimited)", self._spin("max_seconds", 0, 86400, " sec"))
        v.addWidget(box)

        box = QGroupBox("Replay")
        f = QFormLayout(box)
        f.addRow("Replay length", self._spin("replay_seconds", 5, 300, " sec"))
        f.addRow(self._chk("replay_system", "Record system audio"))
        f.addRow(self._chk("replay_mic", "Record mic audio"))
        f.addRow(self._chk("replay_normalize", "Enable volume normalization"))
        f.addRow(self._chk("replay_autostart", "Start the replay buffer when Myazo launches"))
        v.addWidget(box)
        sa = QScrollArea()  # this page is tall: let it scroll instead of stretching the dialog
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setWidget(w)
        return sa

    def showEvent(self, e):
        super().showEvent(e)
        theme.style_titlebar(self)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Choose media storage location", self.w["storage_dir"].text())
        if d:
            self.w["storage_dir"].setText(d)

    def _load(self):
        for k, w in self.w.items():
            v = self.st[k]
            if isinstance(w, HotkeyEdit):
                w.setValue(str(v))
            elif isinstance(w, QCheckBox):
                w.setChecked(bool(v))
            elif isinstance(w, QComboBox):
                w.setCurrentIndex(max(0, w.findData(v)))
            elif isinstance(w, QSpinBox):
                w.setValue(int(v))
            elif isinstance(w, QLineEdit):
                w.setText(str(v))

    def accept(self):
        for k, w in self.w.items():
            if isinstance(w, HotkeyEdit):
                self.st[k] = w.value()
            elif isinstance(w, QCheckBox):
                self.st[k] = w.isChecked()
            elif isinstance(w, QComboBox):
                self.st[k] = w.currentData()
            elif isinstance(w, QSpinBox):
                self.st[k] = w.value()
            elif isinstance(w, QLineEdit):
                self.st[k] = w.text().strip()
        self.st.save()
        super().accept()
