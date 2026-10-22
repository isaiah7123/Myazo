@echo off
cd /d "%~dp0"
if not exist .venv py -3 -m venv .venv
call .venv\Scripts\activate
pip install -r requirements.txt pyinstaller || goto :err
python icon.py
pyinstaller --noconfirm --noconsole --onefile --name Myazo --icon app.ico --collect-all imageio_ffmpeg --collect-all soundcard main.py || goto :err
echo.
echo Built: dist\Myazo.exe  (a single file - copy it anywhere)
goto :eof
:err
echo Build failed.
