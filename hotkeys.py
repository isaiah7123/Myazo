import ctypes
import threading
import time
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal

from log import log

u32 = ctypes.windll.user32
u32e = ctypes.WinDLL("user32", use_last_error=True)  # only used to read RegisterHotKey's error code
k32 = ctypes.windll.kernel32
HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
u32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HMODULE, wintypes.DWORD]
u32.SetWindowsHookExW.restype = wintypes.HANDLE
u32.CallNextHookEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
u32.CallNextHookEx.restype = ctypes.c_ssize_t
u32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
k32.GetModuleHandleW.restype = wintypes.HMODULE


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


def mods_down():
    down = lambda vk: u32.GetAsyncKeyState(vk) & 0x8000
    m = 0
    if down(0x11):
        m |= 2
    if down(0x12):
        m |= 1
    if down(0x10):
        m |= 4
    if down(0x5B) or down(0x5C):
        m |= 8
    return m


MODS = {"ctrl": 2, "alt": 1, "shift": 4, "meta": 8, "win": 8}
NAMED = {
    "print": 0x2C, "printscreen": 0x2C, "space": 0x20, "esc": 0x1B, "tab": 9, "return": 0x0D,
    "enter": 0x0D, "backspace": 8, "ins": 0x2D, "del": 0x2E, "home": 0x24, "end": 0x23,
    "pgup": 0x21, "pgdown": 0x22, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
}


def parse(s):
    """'Ctrl+Shift+F11' -> (modifier_flags, virtual_key) or None."""
    if not s:
        return None
    mod, vk = 0, None
    for t in (x.strip() for x in s.split("+")):
        tl = t.lower()
        if tl in MODS:
            mod |= MODS[tl]
        elif len(t) == 1 and t.isalnum():
            vk = ord(t.upper())
        elif tl.startswith("f") and tl[1:].isdigit():
            vk = 0x6F + int(tl[1:])
        else:
            vk = NAMED.get(tl)
    return (mod, vk) if vk else None


class HotkeyManager(QObject):
    """Every shortcut is claimed two independent ways at once:
    1) a low-level keyboard hook, which sees keys before other apps do and so still works when another
       program has registered (or is swallowing) the same combination, and
    2) RegisterHotKey, the standard method, as a backup in case Windows drops the hook.
    A short de-duplication window stops a single key press from firing twice."""
    triggered = Signal(str)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self._t = None
        self._tid = 0

    def set_bindings(self, bindings: dict):
        self.stop()
        items = [(n, parse(s)) for n, s in bindings.items()]
        items = [(n, p) for n, p in items if p]
        log("shortcuts: " + ", ".join(f"{n}={bindings[n]}" for n, _ in items))
        ready = threading.Event()

        def run():
            self._tid = k32.GetCurrentThreadId()
            msg = wintypes.MSG()
            u32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # force message queue creation
            ids, last, pressed, by_key, reg_failed = {}, {}, set(), {}, []
            for name, (mod, vk) in items:
                by_key.setdefault(vk, []).append((name, mod))

            def fire(name):
                now = time.monotonic()
                if now - last.get(name, 0) > 0.35:
                    last[name] = now
                    self.triggered.emit(name)

            for i, (name, (mod, vk)) in enumerate(items, 1):
                if u32e.RegisterHotKey(None, i, mod | 0x4000, vk):  # MOD_NOREPEAT
                    ids[i] = name
                else:
                    reg_failed.append(name)
                    log(f"shortcut {name}: RegisterHotKey failed (Windows error {ctypes.get_last_error()}; "
                        "1409 = another app owns it) - the keyboard hook will handle it")

            def proc(code, wparam, lparam):  # keep this fast: Windows removes slow hooks
                try:
                    if code >= 0:
                        vk = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents.vkCode
                        cands = by_key.get(vk)
                        if cands:
                            if wparam in (0x101, 0x105):  # key up
                                pressed.discard(vk)
                            elif wparam in (0x100, 0x104):  # key down
                                mods = mods_down()
                                for name, m in cands:
                                    if m == mods:
                                        if vk not in pressed:  # ignore auto-repeat
                                            pressed.add(vk)
                                            fire(name)
                                        return 1  # swallow so the other app doesn't also get it
                except Exception:
                    pass
                return u32.CallNextHookEx(None, code, wparam, lparam)

            cb = HOOKPROC(proc)  # keep a reference alive for the lifetime of the loop
            hook = None
            if items:
                hook = u32.SetWindowsHookExW(13, cb, k32.GetModuleHandleW(None), 0)  # WH_KEYBOARD_LL
                log(f"keyboard hook: {'installed' if hook else 'FAILED'}; "
                    f"RegisterHotKey ok for {len(ids)}/{len(items)}")
                if not hook:
                    for name in reg_failed:
                        self.failed.emit(name)
            ready.set()
            while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0312 and msg.wParam in ids:  # WM_HOTKEY
                    fire(ids[msg.wParam])
            if hook:
                u32.UnhookWindowsHookEx(hook)
            for i in ids:
                u32.UnregisterHotKey(None, i)

        self._t = threading.Thread(target=run, daemon=True)
        self._t.start()
        ready.wait(2)

    def stop(self):
        if self._t:
            u32.PostThreadMessageW(self._tid, 0x0012, 0, 0)  # WM_QUIT
            self._t.join(2)
            self._t = None
