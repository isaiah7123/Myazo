import base64
import subprocess
import sys
import threading
import winreg
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape, quoteattr

from config import APP
from log import log

AUMID = f"{APP}.App"
SCHEME = APP.lower()
HKCU = winreg.HKEY_CURRENT_USER


def _launch_cmd():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable.replace("python.exe", "pythonw.exe")}" "{Path(sys.argv[0]).resolve()}"'


def register(icon_png):
    """Per-user setup: the notification identity (name + icon) and the myazo:// link the buttons use."""
    try:
        with winreg.CreateKey(HKCU, rf"Software\Classes\AppUserModelId\{AUMID}") as k:
            winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, APP)
            winreg.SetValueEx(k, "IconUri", 0, winreg.REG_SZ, str(icon_png))
        with winreg.CreateKey(HKCU, rf"Software\Classes\{SCHEME}") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f"URL:{APP}")
            winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(HKCU, rf"Software\Classes\{SCHEME}\shell\open\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, _launch_cmd() + ' "%1"')
    except OSError as e:
        log(f"toast registration failed: {e}")


def show_saved(path, title, with_image, on_fail):
    """Shows a Windows toast with 'Open in Myazo' / 'Open in default app' buttons (runs in the background)."""
    p = Path(path)

    def uri(mode):
        return f"{SCHEME}://open?file={quote(str(p), safe='')}&with={mode}"

    img = (f'<image placement="appLogoOverride" src={quoteattr(p.as_uri())}/>' if with_image else "")
    xml = (f'<toast launch={quoteattr(uri("app"))} activationType="protocol">'
           f'<visual><binding template="ToastGeneric"><text>{escape(title)}</text><text>{escape(p.name)}</text>'
           f'{img}</binding></visual><actions>'
           f'<action content="Open in {APP}" arguments={quoteattr(uri("app"))} activationType="protocol"/>'
           f'<action content="Open in default app" arguments={quoteattr(uri("default"))} activationType="protocol"/>'
           f'</actions><audio silent="true"/></toast>')
    ps = ("$ErrorActionPreference = 'Stop'\n"
          "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null\n"
          "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null\n"
          "$x = New-Object Windows.Data.Xml.Dom.XmlDocument\n"
          "$x.LoadXml(@'\n" + xml + "\n'@)\n"
          "$t = [Windows.UI.Notifications.ToastNotification]::new($x)\n"
          f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{AUMID}').Show($t)\n")
    enc = base64.b64encode(ps.encode("utf-16-le")).decode()

    def work():
        try:
            r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
                               creationflags=0x08000000, capture_output=True, text=True, timeout=30)
            if r.returncode:
                raise RuntimeError((r.stderr or r.stdout or "unknown error").strip()[:300])
        except Exception as e:
            log(f"toast failed: {e}")
            on_fail()

    threading.Thread(target=work, daemon=True).start()
