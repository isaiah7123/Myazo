@echo off
rem Builds dist\Myazo-Setup.exe. Usage: build_installer.bat [version]    e.g. build_installer.bat 1.0.1
cd /d "%~dp0"
set VER=%~1
if "%VER%"=="" set VER=1.2.0

if not exist dist\Myazo\Myazo.exe call build.bat
if not exist dist\Myazo\Myazo.exe goto :err

set MAKENSIS=makensis
where makensis >nul 2>nul || set MAKENSIS="%ProgramFiles(x86)%\NSIS\makensis.exe"
if not exist %MAKENSIS% (
  where makensis >nul 2>nul || (
    echo NSIS is needed to build the installer. It's free: install it with
    echo     winget install NSIS.NSIS
    echo or download it from https://nsis.sourceforge.io/Download and run this script again.
    goto :err
  )
)

%MAKENSIS% /DVERSION=%VER% installer\Myazo.nsi || goto :err
echo.
echo Built: dist\Myazo-Setup.exe
goto :eof
:err
echo Installer build failed.
exit /b 1
