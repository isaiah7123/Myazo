import json
import os
import shutil
from pathlib import Path

APP = "Myazo"
CFG_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / APP
CFG_FILE = CFG_DIR / "settings.json"
OLD_CFG = Path(os.environ.get("APPDATA", str(Path.home()))) / "Snapkeep" / "settings.json"

IMG = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
VID = {".mp4", ".mkv", ".webm", ".mov"}

# (id, label, default "capture in background", default "open in app")
HOTKEYS = [
    ("image", "Capture image", "Ctrl+Shift+C", "Ctrl+Alt+Shift+C"),
    ("window", "Capture active window", "", ""),
    ("full", "Capture fullscreen", "Ctrl+Shift+F11", "Ctrl+Alt+Shift+F11"),
    ("video", "Record video", "Ctrl+Shift+G", "Ctrl+Alt+Shift+G"),
    ("fullvideo", "Record fullscreen video", "Ctrl+Shift+F12", "Ctrl+Alt+Shift+F12"),
    ("replay", "Record replay", "Ctrl+Shift+F", None),
]

DEFAULTS = {
    "storage_dir": str(Path.home() / "Pictures" / APP),
    "keep_in_tray": True,
    "start_with_windows": False,
    "open_after_capture": False,
    "copy_after_capture": True,
    "clip_format": "image",
    "play_sound": False,
    "printscreen": False,
    "image_format": "png",
    "ocr": False,
    "ocr_lang": "eng",
    "notify_capture": True,
    "sort_key": "date",
    "sort_desc": True,
    "tesseract_path": "",
    "max_res": "1920 x 1080",
    "fps": 30,
    "rec_system": True,
    "rec_mic": False,
    "rec_normalize": True,
    "exclude_bar": True,
    "max_seconds": 0,
    "replay_seconds": 30,
    "replay_system": False,
    "replay_mic": False,
    "replay_normalize": True,
    "replay_autostart": False,
}
for _k, _l, _a, _b in HOTKEYS:
    DEFAULTS["hk_" + _k] = _a
    if _b is not None:
        DEFAULTS["hk_" + _k + "_open"] = _b


class Settings:
    def __init__(self):
        self.d = dict(DEFAULTS)
        if not CFG_FILE.exists() and OLD_CFG.exists():  # carry settings over from the Snapkeep name
            try:
                CFG_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copy2(OLD_CFG, CFG_FILE)
            except OSError:
                pass
        if not CFG_FILE.exists():  # first run after the installer: adopt the folders/options chosen there
            self._seed_from_installer()
        try:
            self.d.update(json.loads(CFG_FILE.read_text("utf-8")))
        except Exception:
            pass

    def _seed_from_installer(self):
        import sys
        try:
            f = Path(sys.executable).parent / "install-config.json"
            if getattr(sys, "frozen", False) and f.exists():
                raw = f.read_bytes()  # the installer writes UTF-16 (with BOM) so non-English folder names survive
                text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")
                seed = {k: v for k, v in json.loads(text).items() if k in DEFAULTS}
                if seed:
                    CFG_DIR.mkdir(parents=True, exist_ok=True)
                    CFG_FILE.write_text(json.dumps({**DEFAULTS, **seed}, indent=2), "utf-8")
        except Exception:
            pass

    def __getitem__(self, k):
        return self.d[k]

    def __setitem__(self, k, v):
        self.d[k] = v

    def save(self):
        CFG_DIR.mkdir(parents=True, exist_ok=True)
        CFG_FILE.write_text(json.dumps(self.d, indent=2), "utf-8")

    def storage(self) -> Path:
        p = Path(self["storage_dir"])
        p.mkdir(parents=True, exist_ok=True)
        return p

    def meta_dir(self) -> Path:
        """Hidden folder inside the media folder holding thumbnails and the OCR index."""
        d, old = self.storage() / ".myazo", self.storage() / ".snapkeep"
        if old.exists() and not d.exists():
            try:
                old.rename(d)
            except OSError:
                pass
        d.mkdir(exist_ok=True)
        return d
