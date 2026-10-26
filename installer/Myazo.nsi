; Myazo installer (NSIS 3). Build with build_installer.bat after build.bat.
;   makensis [/DVERSION=1.2.0] installer\Myazo.nsi
Unicode true
ManifestDPIAware true
SetCompressor /SOLID lzma

!define APP "Myazo"
!define EXE "Myazo.exe"
!define UNINST "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}"
!ifndef VERSION
  !define VERSION "1.2.0"
!endif
!ifndef SRC
  !define SRC "..\dist\Myazo"            ; PyInstaller onedir output
!endif
!ifndef OUT
  !define OUT "..\dist\Myazo-Setup.exe"
!endif

Name "${APP} ${VERSION}"
OutFile "${OUT}"
InstallDir "$PROGRAMFILES64\${APP}"
InstallDirRegKey HKLM "Software\${APP}" "InstallDir"
RequestExecutionLevel admin
BrandingText "${APP} ${VERSION}"

!include "MUI2.nsh"
!include "nsDialogs.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!insertmacro GetParameters
!insertmacro GetOptions
!insertmacro GetSize

!if /FileExists "..\app.ico"
  !define MUI_ICON "..\app.ico"
  !define MUI_UNICON "..\app.ico"
!endif
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Start ${APP} now"
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchApp

Var Dlg
Var rbInstDef
Var rbInstCus
Var edInst
Var btInst
Var rbMedDef
Var rbMedCus
Var edMed
Var btMed
Var StartupChk
Var DesktopChk
Var InstDefault
Var MediaDefault
Var MediaDir
Var HasSettings
Var StartupOpt
Var DesktopOpt

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\LICENSE"
Page custom LocationsPage LocationsLeave
Page custom OptionsPage OptionsLeave
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; ------------------------------------------------------------------ start-up
Function .onInit
  SetRegView 64
  StrCpy $InstDefault $INSTDIR              ; Program Files, or the folder of an existing install
  StrCpy $MediaDefault "$PICTURES\${APP}"
  StrCpy $MediaDir $MediaDefault
  StrCpy $StartupOpt 1
  StrCpy $DesktopOpt 0
  StrCpy $HasSettings 0
  ${If} ${FileExists} "$APPDATA\${APP}\settings.json"
    StrCpy $HasSettings 1                   ; upgrade: keep the user's existing folders and options
  ${EndIf}
  ${GetParameters} $0
  ClearErrors
  ${GetOptions} $0 "/MEDIADIR=" $1          ; silent installs: Myazo-Setup.exe /S /MEDIADIR="D:\Shots" /D=D:\Apps\Myazo
  ${IfNot} ${Errors}
    StrCpy $MediaDir $1
  ${EndIf}
  ClearErrors
FunctionEnd

; ------------------------------------------------------------------ locations page
Function LocationsPage
  !insertmacro MUI_HEADER_TEXT "Choose locations" "Pick the default folders, or choose your own."
  nsDialogs::Create 1018
  Pop $Dlg
  ${If} $Dlg == error
    Abort
  ${EndIf}

  ${NSD_CreateLabel} 0 0 100% 10u "Where should ${APP} be installed?"
  Pop $0
  ${NSD_CreateFirstRadioButton} 6u 12u 95% 10u "Default: $InstDefault"
  Pop $rbInstDef
  ${NSD_CreateAdditionalRadioButton} 6u 24u 95% 10u "A different folder (a ${APP} subfolder is added):"
  Pop $rbInstCus
  ${NSD_CreateText} 18u 36u 205u 12u "$InstDefault"
  Pop $edInst
  ${NSD_CreateBrowseButton} 228u 35u 40u 14u "Browse..."
  Pop $btInst
  ${NSD_OnClick} $rbInstDef OnInstRadio
  ${NSD_OnClick} $rbInstCus OnInstRadio
  ${NSD_OnClick} $btInst OnInstBrowse
  ${NSD_Check} $rbInstDef
  EnableWindow $edInst 0
  EnableWindow $btInst 0

  ${If} $HasSettings == 1
    ${NSD_CreateLabel} 0 66u 100% 30u "Existing ${APP} settings were found, so your media folder stays as it is. You can change it any time in Settings (tray icon > Settings)."
    Pop $0
  ${Else}
    ${NSD_CreateLabel} 0 62u 100% 10u "Where should screenshots and videos be saved?"
    Pop $0
    ${NSD_CreateFirstRadioButton} 6u 74u 95% 10u "Default: $MediaDefault"
    Pop $rbMedDef
    ${NSD_CreateAdditionalRadioButton} 6u 86u 95% 10u "A different folder:"
    Pop $rbMedCus
    ${NSD_CreateText} 18u 98u 205u 12u "$MediaDir"
    Pop $edMed
    ${NSD_CreateBrowseButton} 228u 97u 40u 14u "Browse..."
    Pop $btMed
    ${NSD_OnClick} $rbMedDef OnMedRadio
    ${NSD_OnClick} $rbMedCus OnMedRadio
    ${NSD_OnClick} $btMed OnMedBrowse
    ${If} $MediaDir == $MediaDefault
      ${NSD_Check} $rbMedDef
      EnableWindow $edMed 0
      EnableWindow $btMed 0
    ${Else}
      ${NSD_Check} $rbMedCus
    ${EndIf}
  ${EndIf}
  nsDialogs::Show
FunctionEnd

Function OnInstRadio
  ${NSD_GetState} $rbInstCus $0
  ${If} $0 == ${BST_CHECKED}
    EnableWindow $edInst 1
    EnableWindow $btInst 1
  ${Else}
    EnableWindow $edInst 0
    EnableWindow $btInst 0
  ${EndIf}
FunctionEnd

Function OnMedRadio
  ${NSD_GetState} $rbMedCus $0
  ${If} $0 == ${BST_CHECKED}
    EnableWindow $edMed 1
    EnableWindow $btMed 1
  ${Else}
    EnableWindow $edMed 0
    EnableWindow $btMed 0
  ${EndIf}
FunctionEnd

Function OnInstBrowse
  ${NSD_GetText} $edInst $0
  nsDialogs::SelectFolderDialog "Choose the install folder" "$0"
  Pop $0
  ${If} $0 != error
    ${NSD_SetText} $edInst $0
  ${EndIf}
FunctionEnd

Function OnMedBrowse
  ${NSD_GetText} $edMed $0
  nsDialogs::SelectFolderDialog "Choose the folder for screenshots and videos" "$0"
  Pop $0
  ${If} $0 != error
    ${NSD_SetText} $edMed $0
  ${EndIf}
FunctionEnd

Function LocationsLeave
  ; --- install folder
  ${NSD_GetState} $rbInstCus $0
  ${If} $0 == ${BST_CHECKED}
    ${NSD_GetText} $edInst $1
    ${If} $1 == ""
      MessageBox MB_ICONEXCLAMATION "Please enter an install folder, or choose the default."
      Abort
    ${EndIf}
    StrCpy $2 $1 1 -1                       ; drop a trailing backslash
    ${If} $2 == "\"
      StrCpy $1 $1 -1
    ${EndIf}
    StrCpy $2 $1 6 -6
    ${If} $2 != "\${APP}"                   ; keep the app in its own folder so uninstall can never touch other files
      StrCpy $1 "$1\${APP}"
    ${EndIf}
    StrCpy $INSTDIR $1
  ${Else}
    StrCpy $INSTDIR $InstDefault
  ${EndIf}

  ; --- media folder (new installs only)
  ${If} $HasSettings != 1
    ${NSD_GetState} $rbMedCus $0
    ${If} $0 == ${BST_CHECKED}
      ${NSD_GetText} $edMed $1
      ${If} $1 == ""
        MessageBox MB_ICONEXCLAMATION "Please enter a media folder, or choose the default."
        Abort
      ${EndIf}
      StrCpy $2 $1 1 -1
      ${If} $2 == "\"
        StrCpy $1 $1 -1
      ${EndIf}
      StrCpy $MediaDir $1
    ${Else}
      StrCpy $MediaDir $MediaDefault
    ${EndIf}
  ${EndIf}
FunctionEnd

; ------------------------------------------------------------------ options page
Function OptionsPage
  !insertmacro MUI_HEADER_TEXT "Options" "A few choices about how ${APP} starts."
  nsDialogs::Create 1018
  Pop $Dlg
  ${If} $Dlg == error
    Abort
  ${EndIf}
  ${If} $HasSettings != 1
    ${NSD_CreateCheckbox} 0 0 100% 12u "Start ${APP} when Windows starts"
    Pop $StartupChk
    ${NSD_Check} $StartupChk
  ${EndIf}
  ${NSD_CreateCheckbox} 0 16u 100% 12u "Create a desktop shortcut"
  Pop $DesktopChk
  ${NSD_CreateLabel} 0 44u 100% 40u "${APP} runs quietly in the system tray (bottom right of the taskbar). Right-click its icon for the library and settings. A Start menu shortcut is always created."
  Pop $0
  nsDialogs::Show
FunctionEnd

Function OptionsLeave
  ${If} $HasSettings != 1
    ${NSD_GetState} $StartupChk $StartupOpt
  ${EndIf}
  ${NSD_GetState} $DesktopChk $DesktopOpt
FunctionEnd

; ------------------------------------------------------------------ helpers
; Turns a path into a JSON string body: \ -> \\ and " -> \"
Function EscapeJson
  Exch $0
  Push $1
  Push $2
  Push $3
  StrCpy $1 ""
  StrCpy $2 0
  loop:
    StrCpy $3 $0 1 $2
    ${If} $3 == ""
      Goto done
    ${EndIf}
    ${If} $3 == "\"
      StrCpy $1 "$1\\"
    ${ElseIf} $3 == '"'
      StrCpy $1 '$1\"'
    ${Else}
      StrCpy $1 "$1$3"
    ${EndIf}
    IntOp $2 $2 + 1
    Goto loop
  done:
  StrCpy $0 $1
  Pop $3
  Pop $2
  Pop $1
  Exch $0
FunctionEnd

; Written next to the exe; Myazo adopts it the first time it runs (see config.py). UTF-16 so any folder name works.
Function WriteInstallConfig
  Push $MediaDir
  Call EscapeJson
  Pop $0
  FileOpen $1 "$INSTDIR\install-config.json" w
  FileWriteUTF16LE /BOM $1 '{"storage_dir": "$0", "start_with_windows": '
  ${If} $StartupOpt == 1
    FileWriteUTF16LE $1 "true}"
  ${Else}
    FileWriteUTF16LE $1 "false}"
  ${EndIf}
  FileClose $1
FunctionEnd

Function LaunchApp
  Exec '"$WINDIR\explorer.exe" "$INSTDIR\${EXE}"'   ; via Explorer so it runs as you, not elevated
FunctionEnd

; ------------------------------------------------------------------ install
Section "Install"
  SetRegView 64
  SetShellVarContext current

  nsExec::Exec 'taskkill /F /IM ${EXE}'      ; close a running copy so files can be replaced
  Pop $0
  Sleep 500

  SetOutPath "$INSTDIR"
  RMDir /r "$INSTDIR\_internal"              ; clear old libraries on upgrade
  File /r "${SRC}\*.*"
  File "..\LICENSE"
  File "..\THIRD-PARTY-NOTICES.md"

  ${If} $HasSettings != 1
    ClearErrors
    CreateDirectory "$MediaDir"
    ${If} ${Errors}
      MessageBox MB_ICONINFORMATION|MB_OK "Couldn't create the media folder:$\r$\n$MediaDir$\r$\n$\r$\n${APP} will try again when it starts. You can change the folder in Settings."
      ClearErrors
    ${EndIf}
    Call WriteInstallConfig
    ${If} $StartupOpt == 1
      WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "${APP}" '"$INSTDIR\${EXE}" --tray'
    ${EndIf}
  ${EndIf}

  WriteUninstaller "$INSTDIR\uninstall.exe"
  WriteRegStr HKLM "Software\${APP}" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "${UNINST}" "DisplayName" "${APP}"
  WriteRegStr HKLM "${UNINST}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "${UNINST}" "Publisher" "${APP}"
  WriteRegStr HKLM "${UNINST}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINST}" "DisplayIcon" "$INSTDIR\${EXE}"
  WriteRegStr HKLM "${UNINST}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr HKLM "${UNINST}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
  WriteRegDWORD HKLM "${UNINST}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINST}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKLM "${UNINST}" "EstimatedSize" "$0"

  SetShellVarContext all
  CreateShortcut "$SMPROGRAMS\${APP}.lnk" "$INSTDIR\${EXE}"
  ${If} $DesktopOpt == 1
    CreateShortcut "$DESKTOP\${APP}.lnk" "$INSTDIR\${EXE}"
  ${EndIf}
  SetShellVarContext current
SectionEnd

; ------------------------------------------------------------------ uninstall
Section "Uninstall"
  SetRegView 64
  nsExec::Exec 'taskkill /F /IM ${EXE}'
  Pop $0
  Sleep 500

  SetShellVarContext all
  Delete "$SMPROGRAMS\${APP}.lnk"
  Delete "$DESKTOP\${APP}.lnk"
  SetShellVarContext current
  Delete "$SMPROGRAMS\${APP}.lnk"
  Delete "$DESKTOP\${APP}.lnk"

  ; only files the installer put there are removed, never the whole folder blindly
  RMDir /r "$INSTDIR\_internal"
  Delete "$INSTDIR\${EXE}"
  Delete "$INSTDIR\install-config.json"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\THIRD-PARTY-NOTICES.md"
  Delete "$INSTDIR\uninstall.exe"
  RMDir "$INSTDIR"

  DeleteRegKey HKLM "${UNINST}"
  DeleteRegKey HKLM "Software\${APP}"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "${APP}"
  DeleteRegKey HKCU "Software\Classes\myazo"
  DeleteRegKey HKCU "Software\Classes\AppUserModelId\${APP}.App"

  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 "Also remove your ${APP} settings and log file?$\r$\n$\r$\nYour screenshots and videos are never deleted." /SD IDNO IDNO keepsettings
    RMDir /r "$APPDATA\${APP}"
  keepsettings:
SectionEnd
