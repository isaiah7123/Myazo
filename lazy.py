import importlib


# NOTE: PyInstaller can't see modules imported by name at runtime, so every module used through lazy() must also
# be listed with --hidden-import in build.bat and .github/workflows/release.yml (currently: cv2, numpy).
class lazy:
    """Stand-in for a heavy module (cv2, numpy...) that is only really imported the first time it is used.
    Keeps start-up time and idle memory low: Myazo sits in the tray for days and rarely needs them."""

    def __init__(self, name):
        self._name, self._mod = name, None

    def __getattr__(self, attr):
        if self._mod is None:
            self._mod = importlib.import_module(self._name)
        return getattr(self._mod, attr)
