@echo off
cd /d "%~dp0"
if not exist .venv py -3 -m venv .venv
call .venv\Scripts\activate
pip install -r requirements.txt pyinstaller || goto :err
python icon.py
rem onedir (not onefile): starts instantly and doesn't unpack to a temp folder on every launch
pyinstaller --noconfirm --noconsole --onedir --contents-directory _internal --name Myazo --icon app.ico ^
  --collect-all imageio_ffmpeg --collect-all soundcard ^
  --hidden-import cv2 --hidden-import numpy ^
  --exclude-module tkinter --exclude-module matplotlib --exclude-module scipy --exclude-module pytest --exclude-module IPython ^
  --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQuickWidgets ^
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtPdf ^
  --exclude-module PySide6.QtSql --exclude-module PySide6.QtCharts --exclude-module PySide6.QtDesigner ^
  --exclude-module PySide6.Qt3DCore --exclude-module PySide6.QtBluetooth --exclude-module PySide6.QtSensors ^
  main.py || goto :err
echo.
echo Built: dist\Myazo\Myazo.exe  (keep the whole Myazo folder together, or run build_installer.bat to make Myazo-Setup.exe)
goto :eof
:err
echo Build failed.
