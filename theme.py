"""Myazo's look: dark / light palettes, one app-wide Qt stylesheet, SVG icons, and Windows title-bar colours.
The theme can follow Windows ("auto"), or be forced to light or dark in Settings."""
import re
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QWidget

from config import CFG_DIR

DARK = dict(
    name="dark", outer="#121214", outer_line="#26272C", panel="#1E1F24", card="#292A31", card_hover="#30313A",
    card_line="#292A31", text="#F1F3F8", muted="#A3A7B3", dim="#9196A3", btn="#1E1F24", btn_hover="#25262C",
    btn_line="#2B2C33", input="#16171B", input_line="#2B2C33", tab_on="#262F4A", tab_on_text="#FFFFFF",
    tab_off="#A3ABC4", sort_bg="#23242A", sort_line="#32333B", sort_text="#E3E7F4", accent="#7F9CCB",
    primary="#26345C", primary_hover="#2E3F70", icon="#B4B8C6", good="#3FCF8E", handle="#34353D",
    thumb_ph="#30313A")
LIGHT = dict(
    name="light", outer="#E3E6ED", outer_line="#CDD2DD", panel="#F3F4F7", card="#FFFFFF", card_hover="#FAFAFC",
    card_line="#DDE1E9", text="#14161C", muted="#5D6372", dim="#5D6372", btn="#F3F4F7", btn_hover="#E9EBF0",
    btn_line="#CDD2DD", input="#F3F4F7", input_line="#CDD2DD", tab_on="#DDE3F2", tab_on_text="#1B2747",
    tab_off="#4A5060", sort_bg="#FFFFFF", sort_line="#CDD2DD", sort_text="#232734", accent="#5E7BB5",
    primary="#26345C", primary_hover="#31447A", icon="#4A5060", good="#1E9E62", handle="#C3C8D4",
    thumb_ph="#E6E8EE")

PAL = dict(DARK)  # the live palette; updated in place, so `from theme import PAL` always sees the current one

QSS = """
QWidget { color: $text; font-size: 13px; }
QMainWindow, QDialog, QMessageBox, QInputDialog { background: $outer; }
QLabel { background: transparent; }
QToolTip { background: $card; color: $text; border: 1px solid $btn_line; padding: 4px 8px; }
QMenu { background: $card; color: $text; border: 1px solid $btn_line; padding: 6px; }
QMenu::item { padding: 7px 26px 7px 14px; border-radius: 6px; }
QMenu::item:selected { background: $tab_on; color: $tab_on_text; }
QMenu::separator { height: 1px; background: $btn_line; margin: 5px 8px; }

QPushButton { background: $btn; color: $text; border: 1px solid $btn_line; border-radius: 10px; padding: 7px 16px; }
QPushButton:hover { background: $btn_hover; }
QPushButton:pressed { background: $btn_line; }
QPushButton:checked { background: $tab_on; color: $tab_on_text; border-color: $tab_on; }
QPushButton:disabled { color: $dim; }
QPushButton#primary { background: $primary; color: #FFFFFF; border: 1px solid $primary; }
QPushButton#primary:hover { background: $primary_hover; }
QPushButton#actionBtn { border-radius: 12px; padding: 0; }
QLabel#actionTitle { font-size: 14px; font-weight: 600; color: $text; }
QLabel#actionHint { font-size: 11px; color: $muted; }
QPushButton#tab { background: transparent; border: none; padding: 0 14px; color: $tab_off; font-weight: 500; }
QPushButton#tab:hover { background: $btn_hover; }
QPushButton#tab:checked { background: $tab_on; color: $tab_on_text; }
QPushButton#sortBtn { background: $sort_bg; border: 1px solid $sort_line; color: $sort_text; padding: 0 14px; }
QPushButton#sortBtn:hover { background: $btn_hover; }
QPushButton#clearBtn { padding: 0; border-radius: 8px; }
QPushButton#iconBtn { background: transparent; border: none; border-radius: 12px; padding: 0; }
QPushButton#iconBtn:hover { background: $btn; }

QFrame#panel { background: $panel; border-radius: 14px; }
QLabel#status { color: $dim; font-size: 12px; }
QLabel#note { color: $muted; }
QListWidget#grid { background: transparent; border: none; outline: none; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }

QLineEdit, QSpinBox, QComboBox { background: $input; color: $text; border: 1px solid $input_line; border-radius: 10px;
    padding: 6px 10px; selection-background-color: $accent; selection-color: #FFFFFF; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: $accent; }
QLineEdit:disabled { color: $dim; }
QComboBox { min-height: 20px; padding-right: 28px; }
QComboBox::drop-down { border: none; width: 28px; subcontrol-origin: padding; subcontrol-position: center right; }
QComboBox::down-arrow { image: url("$arrow_down"); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: $card; color: $text; border: 1px solid $btn_line; outline: none; padding: 4px;
    selection-background-color: $tab_on; selection-color: $tab_on_text; }
QSpinBox::up-button, QSpinBox::down-button { width: 20px; border: none; background: transparent; }
QSpinBox::up-arrow { image: url("$arrow_up"); width: 9px; height: 9px; }
QSpinBox::down-arrow { image: url("$arrow_down"); width: 9px; height: 9px; }

QCheckBox { spacing: 9px; background: transparent; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 5px; border: 1px solid $btn_line; background: $input; }
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked { background: $primary; border-color: $primary; image: url("$check"); }

QTabWidget::pane { background: $panel; border: none; border-radius: 14px; top: 8px; }
QTabBar { background: transparent; }
QTabBar::tab { background: transparent; color: $tab_off; padding: 8px 16px; border-radius: 10px; margin-right: 6px; font-weight: 500; }
QTabBar::tab:hover { background: $btn_hover; }
QTabBar::tab:selected { background: $panel; color: $text; }
QGroupBox { background: $card; border: 1px solid $card_line; border-radius: 12px; margin-top: 22px; padding: 18px 14px 12px 14px; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 14px; padding: 0 6px; color: $muted; font-weight: 600; }

QScrollBar:vertical { background: transparent; width: 12px; margin: 4px 2px; }
QScrollBar::handle:vertical { background: $handle; border-radius: 4px; min-height: 36px; }
QScrollBar::handle:vertical:hover { background: $dim; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px 4px; }
QScrollBar::handle:horizontal { background: $handle; border-radius: 4px; min-width: 36px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QSlider::groove:horizontal { height: 4px; background: $btn_line; border-radius: 2px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 2px; }
QSlider::handle:horizontal { background: $text; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }
"""

ICONS = {
    "capture": '<path d="M4 8V6a2 2 0 0 1 2-2h2M16 4h2a2 2 0 0 1 2 2v2M20 16v2a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-2"/><circle cx="12" cy="12" r="2.5"/>',
    "record": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4.5" fill="COLOR" stroke="none"/>',
    "replay": '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1"/><path d="M3.5 4.5v4.5H8"/><path d="M12 8v4.5l3 1.8"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "settings": '<path d="M4 7h8M18 7h2M4 17h2M12 17h8"/><circle cx="15" cy="7" r="2.5"/><circle cx="9" cy="17" r="2.5"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
    "sort_down": '<path d="M4 7h9M4 12h6M4 17h3"/><path d="M17 6v12m0 0-3-3m3 3 3-3"/>',
    "sort_up": '<path d="M4 7h3M4 12h6M4 17h9"/><path d="M17 18V6m0 0-3 3m3-3 3 3"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="9" cy="10" r="1.8"/><path d="M4 18l5-5 4 4 3-3 4 4"/>',
    "video": '<rect x="3" y="6" width="12" height="12" rx="2"/><path d="M15 10l6-3v10l-6-3"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5" stroke-width="2.6"/>',
    "arrow_down": '<path d="M6 9l6 6 6-6" stroke-width="2.4"/>',
    "arrow_up": '<path d="M6 15l6-6 6 6" stroke-width="2.4"/>',
}
_cache = {}


def _svg(name, color):
    body = ICONS[name].replace("COLOR", color)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="%s" stroke-width="1.8" '
            'stroke-linecap="round" stroke-linejoin="round">%s</svg>' % (color, body)).encode()


def pixmap(name, color, size=20):
    """A crisp pixmap of one of the icons above, in the given colour."""
    from PySide6.QtSvg import QSvgRenderer  # imported on first use to keep start-up light
    scr = QGuiApplication.primaryScreen()
    dpr = scr.devicePixelRatio() if scr else 1.0
    key = (name, color, size, dpr)
    pm = _cache.get(key)
    if pm is None:
        px = max(1, int(size * dpr))
        pm = QPixmap(px, px)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        QSvgRenderer(QByteArray(_svg(name, color))).render(p)
        p.end()
        pm.setDevicePixelRatio(dpr)
        _cache[key] = pm
    return pm


def system_dark():
    """True when Windows is set to dark app mode."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except Exception:
        return True


def _bgr(hexcol):
    c = QColor(hexcol)
    return c.blue() << 16 | c.green() << 8 | c.red()


def style_titlebar(w: QWidget):
    """Colours the native Windows title bar to match the theme (Windows 11; harmlessly ignored on older builds)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = wintypes.HWND(int(w.winId()))
        dwm = ctypes.windll.dwmapi

        def put(attr, val):
            v = ctypes.c_int(val)
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), 4)

        dark = PAL["name"] == "dark"
        put(19, int(dark))
        put(20, int(dark))  # dark-mode caption buttons
        put(35, _bgr(PAL["outer"]))  # caption colour
        put(36, _bgr(PAL["text"]))  # caption text
        put(34, _bgr(PAL["outer_line"]))  # window border
    except Exception:
        pass


def _assets():
    """Small PNGs the stylesheet needs (check mark, combo/spin arrows), drawn in the current colours."""
    d = CFG_DIR / "theme"
    d.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, color in (("check", "#FFFFFF"), ("arrow_down", PAL["muted"]), ("arrow_up", PAL["muted"])):
        f = d / f"{name}_{PAL['name']}.png"
        if not f.exists():
            pm = pixmap(name, color, 14)
            pm.setDevicePixelRatio(1.0)
            pm.save(str(f))
        out[name] = Path(f).as_posix()
    return out


def build_qss():
    assets = _assets()
    return re.sub(r"\$(\w+)", lambda m: assets.get(m.group(1)) or PAL[m.group(1)], QSS)


def build_palette():
    pal = QPalette()
    for role, key in ((QPalette.Window, "outer"), (QPalette.WindowText, "text"), (QPalette.Base, "input"),
                      (QPalette.AlternateBase, "panel"), (QPalette.Text, "text"), (QPalette.Button, "btn"),
                      (QPalette.ButtonText, "text"), (QPalette.ToolTipBase, "card"), (QPalette.ToolTipText, "text"),
                      (QPalette.PlaceholderText, "dim"), (QPalette.Highlight, "accent"), (QPalette.Link, "accent")):
        pal.setColor(role, QColor(PAL[key]))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        pal.setColor(QPalette.Disabled, role, QColor(PAL["dim"]))
    return pal


class ThemeManager(QObject):
    """Owns the current theme. mode: 'auto' (follow Windows), 'light' or 'dark' (setting `theme`)."""
    changed = Signal()

    def __init__(self, qapp, st):
        super().__init__()
        self.qapp, self.st, self._applied = qapp, st, False
        try:  # Qt 6.5+ tells us the moment Windows switches between light and dark
            qapp.styleHints().colorSchemeChanged.connect(lambda *_: self.sync())
        except Exception:
            pass

    def effective(self):
        m = self.st["theme"]
        return m if m in ("light", "dark") else ("dark" if system_dark() else "light")

    def apply(self):
        name = self.effective()
        if self._applied and name == PAL["name"]:
            return
        PAL.clear()
        PAL.update(DARK if name == "dark" else LIGHT)
        self.qapp.setPalette(build_palette())
        self.qapp.setStyleSheet(build_qss())
        for w in self.qapp.topLevelWidgets():
            if w.isVisible():
                style_titlebar(w)
        self._applied = True
        self.changed.emit()

    def sync(self):
        """Re-check Windows' setting (only matters in auto mode). Also called whenever the library is shown."""
        if self.st["theme"] == "auto":
            self.apply()
