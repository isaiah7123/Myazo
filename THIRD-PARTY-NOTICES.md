# Third-party notices

Myazo's own source code is released under the MIT License (see [LICENSE](LICENSE)).

The released `Myazo.exe` is built with PyInstaller and bundles the third-party components below. Each is the property
of its respective authors and is used under its own license. Nothing here changes those licenses.

## Components bundled in Myazo.exe

| Component | Used for | License |
|---|---|---|
| [Python](https://www.python.org/) | Runtime | PSF License |
| [PySide6 / Qt 6](https://doc.qt.io/qtforpython-6/) | User interface | LGPL-3.0 (see note 1) |
| [mss](https://github.com/BoboTiG/python-mss) | Screen capture | MIT |
| [NumPy](https://numpy.org/) | Image and array handling | BSD-3-Clause |
| [opencv-python-headless](https://github.com/opencv/opencv-python) | Video writing and image processing | Apache-2.0 (wheel also contains LGPL-2.1 FFmpeg libraries and other third-party libraries; see note 2) |
| [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) | Wrapper that ships an `ffmpeg` executable | BSD-2-Clause (the bundled `ffmpeg` binary has its own license; see note 3) |
| [FFmpeg](https://ffmpeg.org/) | Video encoding and muxing | GPL-2.0-or-later or LGPL-2.1-or-later, depending on the build (see note 3) |
| [SoundCard](https://github.com/bastibe/SoundCard) | System and microphone audio capture | BSD-3-Clause |
| [Pillow](https://python-pillow.org/) | Image handling | MIT-CMU (HPND) |
| [pytesseract](https://github.com/madmaze/pytesseract) | Python interface to Tesseract | Apache-2.0 |
| [Send2Trash](https://github.com/arsenetar/send2trash) | Moving files to the Recycle Bin | BSD-3-Clause |
| [PyInstaller](https://pyinstaller.org/) | Packaging into a single exe | GPL-2.0 with a special exception that allows bundled apps to use any license |

## Not bundled

- **[Tesseract OCR](https://github.com/tesseract-ocr/tesseract)** (Apache-2.0) is optional. You install it separately,
  and Myazo only calls it if it is present. It is not part of Myazo.exe.

## Notes

1. **Qt / PySide6 (LGPL-3.0).** Myazo uses PySide6 as an unmodified library. You can obtain the Qt for Python source
   from <https://code.qt.io/cgit/pyside/pyside-setup.git/> and the LGPL-3.0 text from
   <https://www.gnu.org/licenses/lgpl-3.0.html>. Myazo's complete source code and build script are in this repository,
   so you can rebuild `Myazo.exe` with a different version of PySide6 by changing `requirements.txt` and running
   `build.bat`.
2. **OpenCV wheels.** The `opencv-python-headless` package bundles some third-party libraries, including FFmpeg
   libraries under the LGPL-2.1. Their license texts ship inside the package and are listed in the project's
   [LICENSE-3RD-PARTY.txt](https://github.com/opencv/opencv-python/blob/4.x/LICENSE-3RD-PARTY.txt).
3. **FFmpeg binary.** The `ffmpeg` executable that `imageio-ffmpeg` provides is typically a GPL build that includes
   the x264 encoder. Myazo runs it as a separate program and does not link against it. FFmpeg's license terms are at
   <https://ffmpeg.org/legal.html>, and its source code is available from <https://ffmpeg.org/download.html>.
   If you redistribute a build of Myazo that includes this binary, you are responsible for meeting the license
   conditions for it, including making the corresponding source available. H.264 encoding may also be covered by
   patent licenses in some jurisdictions.

## Trademarks

"Gyazo" is a trademark of its owner. Myazo is an independent project and is not affiliated with or endorsed by
Gyazo or Nota Inc. "Windows" is a trademark of Microsoft Corporation. "Qt" is a trademark of The Qt Company Ltd.
