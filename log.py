import sys
import threading
import time
import traceback

from config import CFG_DIR

LOG = CFG_DIR / "myazo.log"


def log(msg):
    """Tiny diagnostics log (the windowed exe has no console, so errors would otherwise vanish)."""
    try:
        CFG_DIR.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > 300_000:
            LOG.write_text("", "utf-8")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def install_excepthooks():
    def hook(t, v, tb):
        log("".join(traceback.format_exception(t, v, tb)))

    sys.excepthook = hook
    threading.excepthook = lambda a: hook(a.exc_type, a.exc_value, a.exc_traceback)
