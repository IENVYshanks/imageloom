; ImageLoom: per-user Windows installer (NSIS 3, Modern UI 2, English + Russian).
; Built on macOS by windows/build_windows.sh:
;   makensis -DVERSION=1.0.0 -DVERSION_NUM=1.0.0.0 -DSTAGE=<abs staging dir> -DOUTFILE=<abs .exe> -DINSTALLED_KB=<n> windows/installer.nsi
; STAGE contains python\ app\ engine\ (app\app.ico is the icon). This file is UTF-8 WITH BOM on purpose (Cyrillic strings).
; Languages: English is the default and the fallback; Russian is used when the user's Windows UI language is Russian (NSIS picks the
; language from the system UI language by itself, so there is no extra language dialog: this is a one-click per-user install).
; To add a language: one more !insertmacro MUI_LANGUAGE line plus one LangString line per T_* text below.
; Nothing here has ever been executed on Windows.
Unicode true

!ifndef VERSION
  !define VERSION "1.0.0"
!endif
!ifndef VERSION_NUM
  !define VERSION_NUM "1.0.0.0"
!endif
!ifndef INSTALLED_KB
  !define INSTALLED_KB 0
!endif
!ifndef STAGE
  !error "pass -DSTAGE=<staging dir>"
!endif
!ifndef OUTFILE
  !define OUTFILE "ImageLoom-${VERSION}-Windows-x64-Setup.exe"
!endif

!define APPNAME "ImageLoom"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}"
!define WV2_KEY "Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
!define WV2_URL "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
!define VC_URL "https://aka.ms/vs/17/release/vc_redist.x64.exe"

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!include "WinVer.nsh"
!include "FileFunc.nsh"
!insertmacro GetFileName

Name "${APPNAME}"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\${APPNAME}"
InstallDirRegKey HKCU "Software\${APPNAME}" "InstallDir"
RequestExecutionLevel user          ; per-user install: no administrator rights needed
SetCompressor /SOLID lzma
SetCompressorDictSize 64
ManifestDPIAware true
BrandingText "${APPNAME} ${VERSION}"

!define MUI_ICON "${STAGE}/app/app.ico"
!define MUI_UNICON "${STAGE}/app/app.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchApp
!define MUI_FINISHPAGE_RUN_TEXT "$(T_RUN)"

!insertmacro MUI_PAGE_WELCOME
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE DirLeave   ; applies to the next page only
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

; first language = default and fallback; NSIS picks the user's UI language when it is one of these
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "Russian"

LangString T_RUN ${LANG_ENGLISH} "Run ${APPNAME}"
LangString T_RUN ${LANG_RUSSIAN} "Запустить ${APPNAME}"
LangString T_OS ${LANG_ENGLISH} "A 64-bit Windows 10 or 11 is required."
LangString T_OS ${LANG_RUSSIAN} "Нужна 64-разрядная Windows 10 или 11."
LangString T_RUNNING ${LANG_ENGLISH} "${APPNAME} is running. Close it (the window, or the Quit ImageLoom button in the help dialog) and press Retry."
LangString T_RUNNING ${LANG_RUSSIAN} "${APPNAME} сейчас запущен. Закройте программу (окно или кнопку «Завершить программу») и нажмите «Повтор»."
LangString T_WV2_ASK ${LANG_ENGLISH} "Microsoft Edge WebView2 Runtime was not found. Without it the app opens in a Microsoft Edge app-mode window instead, which also works.$\r$\n$\r$\nDownload and install WebView2 now? (about 2 MB, needs internet)"
LangString T_WV2_ASK ${LANG_RUSSIAN} "Не найден Microsoft Edge WebView2 Runtime. Без него программа откроется в окне браузера Microsoft Edge (режим приложения), это тоже работает.$\r$\n$\r$\nСкачать и установить WebView2 сейчас? (около 2 МБ, нужен интернет)"
LangString T_WV2_DL ${LANG_ENGLISH} "Downloading Microsoft Edge WebView2..."
LangString T_WV2_DL ${LANG_RUSSIAN} "Загрузка Microsoft Edge WebView2…"
LangString T_WV2_FAIL ${LANG_ENGLISH} "WebView2 could not be installed. That is fine: the app will open in Microsoft Edge."
LangString T_WV2_FAIL ${LANG_RUSSIAN} "WebView2 установить не удалось. Это не страшно: программа откроется в Microsoft Edge."
LangString T_VC_ASK ${LANG_ENGLISH} "The engine needs Microsoft Visual C++ Redistributable 2015-2022 (x64), version 14.40 or newer. It was not found.$\r$\n$\r$\nDownload and install it now? (about 18 MB, needs internet; Windows will ask for administrator approval)"
LangString T_VC_ASK ${LANG_RUSSIAN} "Для движка нужен Microsoft Visual C++ Redistributable 2015-2022 (x64), версия 14.40 или новее. Он не найден.$\r$\n$\r$\nСкачать и установить его сейчас? (около 18 МБ, нужен интернет; Windows запросит подтверждение администратора)"
LangString T_VC_DL ${LANG_ENGLISH} "Downloading Visual C++ Redistributable..."
LangString T_VC_DL ${LANG_RUSSIAN} "Загрузка Visual C++ Redistributable…"
LangString T_VC_FAIL ${LANG_ENGLISH} "Visual C++ Redistributable was not installed. Image generation will not start without it. Download it manually: ${VC_URL}"
LangString T_VC_FAIL ${LANG_RUSSIAN} "Visual C++ Redistributable не установлен. Без него генерация не запустится. Скачайте его вручную: ${VC_URL}"
LangString T_UN_DATA ${LANG_ENGLISH} "Also delete the app data in $LOCALAPPDATA\${APPNAME}?$\r$\n(models ~18 GB, history, thumbnails, logs, window settings)$\r$\n$\r$\nFinished images in Pictures\ImageLoom are NOT deleted. By default the data is kept."
LangString T_UN_DATA ${LANG_RUSSIAN} "Удалить также данные программы в $LOCALAPPDATA\${APPNAME}?$\r$\n(модели ~18 ГБ, история, миниатюры, журналы, настройки окна)$\r$\n$\r$\nГотовые картинки в папке «Изображения\ImageLoom» НЕ удаляются. По умолчанию данные сохраняются."

VIProductVersion "${VERSION_NUM}"
!macro VERSIONINFO LANGID
  VIAddVersionKey /LANG=${LANGID} "ProductName" "${APPNAME}"
  VIAddVersionKey /LANG=${LANGID} "FileDescription" "${APPNAME} Setup"
  VIAddVersionKey /LANG=${LANGID} "FileVersion" "${VERSION}"
  VIAddVersionKey /LANG=${LANGID} "ProductVersion" "${VERSION}"
  VIAddVersionKey /LANG=${LANGID} "LegalCopyright" "Local AI image studio. Model weights are downloaded separately under their own licenses."
!macroend
!insertmacro VERSIONINFO ${LANG_ENGLISH}
!insertmacro VERSIONINFO ${LANG_RUSSIAN}

; ---------------------------------------------------------------------------------------------------- helpers
Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP|MB_OK "$(T_OS)"
    Abort
  ${EndIf}
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_ICONSTOP|MB_OK "$(T_OS)"
    Abort
  ${EndIf}
FunctionEnd

; always install into a folder called "ImageLoom", so the uninstaller never touches a shared directory
Function DirLeave
  ${GetFileName} "$INSTDIR" $0
  ${IfThen} $0 != "${APPNAME}" ${|} StrCpy $INSTDIR "$INSTDIR\${APPNAME}" ${|}
FunctionEnd

Function LaunchApp
  SetOutPath "$INSTDIR"
  Exec '"$INSTDIR\python\pythonw.exe" "$INSTDIR\app\app.py"'
FunctionEnd

; $0 = URL, $1 = target file; leaves $2 = 0 on success. curl.exe ships with Windows 10 1803+, PowerShell is the fallback.
Function DownloadFile
  Delete "$1"
  nsExec::ExecToLog 'curl.exe -L --fail --silent --show-error -o "$1" "$0"'
  Pop $2
  ${If} $2 != 0
    nsExec::ExecToLog `powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '$0' -OutFile '$1'"`
    Pop $2
  ${EndIf}
  ${IfNot} ${FileExists} "$1"
    StrCpy $2 1
  ${EndIf}
FunctionEnd

; the app falls back to Microsoft Edge in app mode when WebView2 is absent, so every failure here is tolerated
Function CheckWebView2
  SetRegView 64
  ReadRegStr $0 HKLM "SOFTWARE\WOW6432Node\${WV2_KEY}" "pv"
  ${If} $0 == ""
    ReadRegStr $0 HKLM "SOFTWARE\${WV2_KEY}" "pv"
  ${EndIf}
  ${If} $0 == ""
    ReadRegStr $0 HKCU "Software\${WV2_KEY}" "pv"
  ${EndIf}
  ${If} $0 == ""
    ReadRegStr $0 HKCU "Software\WOW6432Node\${WV2_KEY}" "pv"
  ${EndIf}
  SetRegView 32
  ${If} $0 != ""
  ${AndIf} $0 != "0.0.0.0"
    Return
  ${EndIf}
  MessageBox MB_YESNO|MB_ICONQUESTION "$(T_WV2_ASK)" /SD IDNO IDNO done
  DetailPrint "$(T_WV2_DL)"
  StrCpy $0 "${WV2_URL}"
  StrCpy $1 "$TEMP\MicrosoftEdgeWebview2Setup.exe"
  Call DownloadFile
  ${If} $2 == 0
    ExecShellWait "open" "$1" "/silent /install" SW_HIDE
    Delete "$1"
  ${Else}
    DetailPrint "$(T_WV2_FAIL)"
    MessageBox MB_OK|MB_ICONINFORMATION "$(T_WV2_FAIL)" /SD IDOK
  ${EndIf}
  done:
FunctionEnd

; sd-cli.exe / stable-diffusion.dll / ggml-*.dll are MSVC builds (MSVCP140, VCRUNTIME140_1, VCOMP140). Binaries built with
; toolset 14.40+ crash on older redistributables, hence the Minor >= 40 test.
Function CheckVCRuntime
  SetRegView 64
  ReadRegDWORD $0 HKLM "SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" "Installed"
  ReadRegDWORD $1 HKLM "SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" "Minor"
  SetRegView 32
  ${If} $0 == 1
  ${AndIf} $1 >= 40
    Return
  ${EndIf}
  MessageBox MB_YESNO|MB_ICONEXCLAMATION "$(T_VC_ASK)" /SD IDNO IDNO skip
  DetailPrint "$(T_VC_DL)"
  StrCpy $0 "${VC_URL}"
  StrCpy $1 "$TEMP\vc_redist.x64.exe"
  Call DownloadFile
  ${If} $2 == 0
    ExecShellWait "open" "$1" "/install /quiet /norestart" SW_HIDE
    Delete "$1"
    Return
  ${EndIf}
  skip:
  DetailPrint "$(T_VC_FAIL)"
  MessageBox MB_OK|MB_ICONEXCLAMATION "$(T_VC_FAIL)" /SD IDOK
FunctionEnd

; ---------------------------------------------------------------------------------------------------- install
Section "-Install"
  SetOutPath "$INSTDIR"

  ; upgrade in place: only when a previous install of ours is there (its Uninstall.exe is the marker)
  ${If} ${FileExists} "$INSTDIR\Uninstall.exe"
    retry:
    ClearErrors
    Delete "$INSTDIR\python\pythonw.exe"       ; cannot be deleted while the app is running
    ${If} ${Errors}
      MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "$(T_RUNNING)" /SD IDCANCEL IDRETRY retry
      Abort
    ${EndIf}
    RMDir /r "$INSTDIR\python"
    RMDir /r "$INSTDIR\app"
    RMDir /r "$INSTDIR\engine"
  ${EndIf}

  ; NOTE: `File /r "<dir>"` (without /*) searches the PARENT folder recursively for anything named like <dir> and would also
  ; pick up copies elsewhere under STAGE; `<dir>/*` + an explicit SetOutPath copies exactly that folder.
  SetOutPath "$INSTDIR\python"
  File /r "${STAGE}/python/*"
  SetOutPath "$INSTDIR\app"
  File /r "${STAGE}/app/*"
  SetOutPath "$INSTDIR\engine"
  File /r "${STAGE}/engine/*"
  SetOutPath "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ; shortcuts: pythonw.exe "<install>\app\app.py", working directory = install dir (the current OutPath)
  CreateShortCut "$SMPROGRAMS\${APPNAME}.lnk" "$INSTDIR\python\pythonw.exe" '"$INSTDIR\app\app.py"' "$INSTDIR\app\app.ico" 0 SW_SHOWNORMAL "" "${APPNAME}"
  CreateShortCut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\python\pythonw.exe" '"$INSTDIR\app\app.py"' "$INSTDIR\app\app.ico" 0 SW_SHOWNORMAL "" "${APPNAME}"

  ; "Apps & features" entry (current user)
  WriteRegStr HKCU "Software\${APPNAME}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "ImageLoom"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\app\app.ico"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" ${INSTALLED_KB}
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1

  Call CheckVCRuntime
  Call CheckWebView2
SectionEnd

; ---------------------------------------------------------------------------------------------------- uninstall
Section "Uninstall"
  Delete "$SMPROGRAMS\${APPNAME}.lnk"
  Delete "$DESKTOP\${APPNAME}.lnk"
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\engine"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"                               ; only if empty: never recursive on the install root
  DeleteRegKey HKCU "${UNINST_KEY}"
  DeleteRegKey HKCU "Software\${APPNAME}"

  ; user data (models, history, logs) survives unless the user explicitly agrees; default button = No, silent = keep
  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 "$(T_UN_DATA)" /SD IDNO IDNO keepdata
  RMDir /r "$LOCALAPPDATA\${APPNAME}"
  keepdata:
SectionEnd
