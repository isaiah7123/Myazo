import ctypes
import os
import sys
import winreg
import winsound
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import QMimeData, QObject, QRect, QTimer, QUrl, Signal
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from capture import RegionPicker, active_window_rect, grab, screen_under_cursor, to_physical
from config import APP, CFG_DIR, HOTKEYS, Settings
from hotkeys import HotkeyManager
from hud import RecordHUD
from icon import make_icon, make_pixmap
from library import IMG, VID, Library, open_default
from ocr import ocr_async
from recorder import Recorder, ReplayBuffer
from settings_dialog import SettingsDialog
from log import LOG, install_excepthooks, log
from toast import register as register_integration, show_saved

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def set_startup(on):
    if getattr(sys, "frozen", False):
        cmd = f'"{sys.executable}" --tray'
    else:
        cmd = f'"{sys.executable.replace("python.exe", "pythonw.exe")}" "{Path(__file__).resolve()}" --tray'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        try:
            winreg.DeleteValue(k, "Snapkeep")
        except FileNotFoundError:
            pass
        if on:
            winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(k, APP)
            except FileNotFoundError:
                pass


class SnapApp(QObject):
    toast_failed = Signal(str)

    def __init__(self, qapp):
        super().__init__()
        self.qapp = qapp
        self.st = Settings()
        self.picker = RegionPicker()
        self.rec = self.hud = self._cb = None
        self.rec_open = False
        self.replay = ReplayBuffer(self.st)
        self.replay.saved.connect(lambda p: self.finish(p, False))
        self.replay.failed.connect(lambda m: self.notify(m))
        self.lib = Library(self)
        self.picker.picked.connect(lambda s, r, p: self._cb and self._cb(s, r, p))
        self.picker.cancelled.connect(lambda: setattr(self, "_cb", None))

        self.tray = QSystemTrayIcon(make_icon())
        self.tray.setToolTip(APP)
        self.tray.activated.connect(lambda r: self.lib.show_front()
                                    if r in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
        self.tray.show()
        self.toast_failed.connect(self.notify)  # fallback if a Windows toast can't be shown

        log(f"Myazo started (frozen={getattr(sys, 'frozen', False)}, python {sys.version.split()[0]})")
        log("screens: " + ", ".join(f"{s.name()} {s.geometry().width()}x{s.geometry().height()}"
                                    f"@{s.devicePixelRatio()}" for s in QGuiApplication.screens()))
        CFG_DIR.mkdir(parents=True, exist_ok=True)
        icon_png = CFG_DIR / "icon.png"
        if not icon_png.exists():
            make_pixmap().save(str(icon_png))
        register_integration(icon_png)  # notification identity + myazo:// link used by the toast buttons

        self.hk = HotkeyManager()
        self.hk.triggered.connect(self.on_hotkey)
        self.hk.failed.connect(lambda n: self.notify(f"Couldn't claim the shortcut for “{n}” — another app is using it. Pick a different combination in Settings."))
        self.apply_settings(first=True)

    # ---------- plumbing ----------
    def later(self, fn, ms=250):
        QTimer.singleShot(ms, fn)

    def notify(self, msg):
        self.tray.showMessage(APP, msg, QSystemTrayIcon.Information, 3000)

    def quit(self):
        self.hk.stop()
        self.replay.stop()
        if self.rec:
            self.rec.stop()
        self.tray.hide()
        self.qapp.quit()

    def apply_settings(self, first=False):
        binds = {}
        for k, _l, _a, b in HOTKEYS:
            binds[k] = self.st["hk_" + k]
            if b is not None:
                binds[k + "_open"] = self.st["hk_" + k + "_open"]
        if self.st["printscreen"]:
            binds["printscreen"] = "Print"
        self.hk.set_bindings(binds)
        try:
            set_startup(self.st["start_with_windows"])
        except OSError:
            pass
        self.lib.set_folder()
        if self.replay.running:
            self.replay.stop()
            self.replay.start()
        elif first and self.st["replay_autostart"]:
            self.replay.start()
        self.build_menu()

    def open_settings(self):
        self.hk.stop()  # so the shortcut editors can record keys already registered globally
        SettingsDialog(self.st, self.lib if self.lib.isVisible() else None).exec()
        self.apply_settings()

    def build_menu(self):
        st, o = self.st, self.st["open_after_capture"]
        m = QMenu()

        def add(text, hk, fn):
            label = f"{text}\t{st[hk]}" if hk and st[hk] else text
            m.addAction(label).triggered.connect(lambda _=False: self.later(fn))

        m.addAction("Open library").triggered.connect(lambda _=False: self.lib.show_front())
        m.addSeparator()
        add("Capture image", "hk_image", lambda: self.act("image", o))
        add("Capture active window", "hk_window", lambda: self.act("window", o))
        add("Capture fullscreen", "hk_full", lambda: self.act("full", o))
        add("Record video", "hk_video", lambda: self.act("video", o))
        add("Record fullscreen video", "hk_fullvideo", lambda: self.act("fullvideo", o))
        m.addSeparator()
        add("Stop replay buffer" if self.replay.running else "Start replay buffer", None, self.toggle_replay)
        add("Save replay", "hk_replay", self.save_replay)
        m.addSeparator()
        add("Settings…", None, self.open_settings)
        m.addAction("Open diagnostics log").triggered.connect(
            lambda _=False: os.startfile(LOG) if LOG.exists() else self.notify("No log yet."))
        m.addAction("Open storage folder").triggered.connect(lambda _=False: __import__("os").startfile(st.storage()))
        m.addAction("Quit").triggered.connect(lambda _=False: self.quit())
        self.menu = m
        self.tray.setContextMenu(m)

    # ---------- actions ----------
    def on_hotkey(self, name):
        log(f"shortcut fired: {name}")
        if name == "printscreen":
            return self.act("image", self.st["open_after_capture"])
        self.act(name.removesuffix("_open"), name.endswith("_open"))

    def act(self, base, open_after=False):
        {"image": self.cap_image, "window": self.cap_window, "full": self.cap_full,
         "video": self.rec_video, "fullvideo": self.rec_full, "replay": lambda o: self.replay_key()}[base](open_after)

    def new_path(self, prefix, ext):
        d, stamp = self.st.storage(), datetime.now().strftime("%Y-%m-%d %H-%M-%S")
        p, n = d / f"{prefix} {stamp}.{ext}", 1
        while p.exists():
            n += 1
            p = d / f"{prefix} {stamp} ({n}).{ext}"
        return p

    def save_image(self, img, open_after):
        ext = self.st["image_format"]
        p = self.new_path("Screenshot", ext)
        if not img.save(str(p), ext.upper(), 92 if ext == "jpg" else -1):
            return self.notify("Could not save the screenshot.")
        self.finish(str(p), open_after)

    def cap_image(self, open_after):
        if self.picker.active:
            return

        def cb(scr, r, pix):
            d = scr.devicePixelRatio()
            self.save_image(pix.copy(QRect(round(r.x() * d), round(r.y() * d),
                                           round(r.width() * d), round(r.height() * d))), open_after)

        self._cb = cb
        self.picker.start()

    def cap_window(self, open_after):
        r = active_window_rect()
        if r:
            self.save_image(grab(r), open_after)

    def cap_full(self, open_after):
        self.save_image(grab(to_physical(screen_under_cursor())), open_after)

    def rec_video(self, open_after):
        if self.rec:
            return self.rec.stop() or self._saving()
        if self.picker.active:
            return
        self._cb = lambda scr, r, pix: self.start_recording(to_physical(scr, r), scr, r, open_after)
        self.picker.start()

    def rec_full(self, open_after):
        if self.rec:
            return self.rec.stop() or self._saving()
        scr = screen_under_cursor()
        self.start_recording(to_physical(scr), scr, None, open_after)

    def start_recording(self, mon, scr, rect, open_after):
        self.rec_open = open_after
        self.rec = Recorder(self.st, mon, self.new_path("Recording", "mp4"))
        self.rec.finished.connect(self.on_rec_done)
        self.rec.failed.connect(self.on_rec_fail)
        self.hud = RecordHUD(scr, rect, self.st["exclude_bar"], lambda: self.rec_video(False))

        def go():  # short delay so the selection overlay is gone from the first frames
            self.rec.start()
            self.hud.present()

        self.later(go)

    def _saving(self):
        if self.hud:
            self.hud.saving()

    def _end_rec(self):
        if self.hud:
            self.hud.close_all()
        self.rec = self.hud = None

    def on_rec_done(self, path):
        self._end_rec()
        self.finish(path, self.rec_open)

    def on_rec_fail(self, msg):
        self._end_rec()
        self.notify(f"Recording failed: {msg}")

    def toggle_replay(self):
        if self.replay.running:
            self.replay.stop()
            self.notify("Replay buffer stopped.")
        else:
            self.replay.start()
            self.notify("Replay buffer running — press the replay shortcut to save the last "
                        f"{self.st['replay_seconds']} seconds.")
        self.build_menu()

    def save_replay(self):
        if not self.replay.running:
            return self.notify("Replay buffer isn't running. Start it from the tray menu.")
        self.replay.save(self.new_path("Replay", "mp4"))

    def replay_key(self):
        self.save_replay() if self.replay.running else self.toggle_replay()

    # ---------- after capture ----------
    def copy_path(self, path, fmt):
        cb, p = QGuiApplication.clipboard(), Path(path)
        if fmt == "image" and p.suffix.lower() in IMG:
            cb.setPixmap(QPixmap(str(p)))
        elif fmt == "path":
            cb.setText(str(p))
        else:
            md = QMimeData()
            md.setUrls([QUrl.fromLocalFile(str(p))])
            cb.setMimeData(md)

    def finish(self, path, open_after):
        if self.st["play_sound"]:
            winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
        if self.st["copy_after_capture"]:
            self.copy_path(path, self.st["clip_format"])
        if self.st["ocr"] and Path(path).suffix.lower() in IMG:
            ocr_async(self.st, path)
        if self.st["notify_capture"] and not open_after:  # (if it opens in the app anyway, no toast is needed)
            p, is_img = Path(path), Path(path).suffix.lower() in IMG
            title = "Screenshot saved" if is_img else ("Replay saved" if p.name.startswith("Replay") else "Recording saved")
            show_saved(path, title, is_img, lambda: self.toast_failed.emit(f"{title}: {p.name}"))
        self.lib.refresh()
        if open_after:
            self.lib.show_item(path)

    def handle_message(self, msg):
        """Messages from a second launch or from a notification button (myazo://open?file=...&with=app|default|copy)."""
        if not msg.lower().startswith("myazo:"):
            return self.lib.show_front()
        q = parse_qs(urlparse(msg).query)
        try:
            f = Path(q["file"][0]).resolve()
            f.relative_to(self.st.storage().resolve())  # only ever act on files inside the media folder
        except (KeyError, ValueError, OSError):
            return log(f"ignored link: {msg}")
        if f.suffix.lower() not in IMG | VID or not f.is_file():
            return
        mode = q.get("with", ["app"])[0]
        if mode == "copy":  # toast button: copy the screenshot itself, without opening any window
            if f.suffix.lower() in IMG:
                self.copy_path(str(f), "image")
                self.notify("Screenshot copied to clipboard")
            return
        if mode == "default":
            open_default(str(f))
        else:
            self.lib.show_item(str(f))


def main():
    install_excepthooks()
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Myazo.App")
    qa = QApplication(sys.argv)
    qa.setApplicationName(APP)
    qa.setQuitOnLastWindowClosed(False)
    qa.setWindowIcon(make_icon())
    name = "Myazo-single-instance"
    url = next((a for a in sys.argv[1:] if a.lower().startswith("myazo:")), "")
    s = QLocalSocket()
    s.connectToServer(name)
    if s.waitForConnected(300):  # already running: hand over to it (also how notification buttons arrive)
        s.write((url or "show").encode("utf-8"))
        s.flush()
        s.waitForBytesWritten(500)
        return 0
    QLocalServer.removeServer(name)
    srv = QLocalServer()
    srv.listen(name)
    app = SnapApp(qa)

    def on_conn():
        c = srv.nextPendingConnection()

        def read():
            data = bytes(c.readAll()).decode("utf-8", "ignore").strip()
            if data:
                app.handle_message(data)
                c.disconnectFromServer()

        c.readyRead.connect(read)
        if c.bytesAvailable():
            read()

    srv.newConnection.connect(on_conn)
    if url:
        app.handle_message(url)
    elif "--tray" not in sys.argv:
        app.lib.show_front()
    return qa.exec()


if __name__ == "__main__":
    sys.exit(main())
