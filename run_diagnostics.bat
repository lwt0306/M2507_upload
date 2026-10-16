@echo off
setlocal
cd /d "%~dp0"
set "M2507_EXE=%~1"
if defined M2507_EXE goto check_exe
if exist "%~dp0M2507_OTA.exe" set "M2507_EXE=%~dp0M2507_OTA.exe"
if defined M2507_EXE goto check_exe
if exist "%~dp0dist\win64\debug\M2507_OTA\M2507_OTA.exe" set "M2507_EXE=%~dp0dist\win64\debug\M2507_OTA\M2507_OTA.exe"
if defined M2507_EXE goto check_exe
if exist "%~dp0dist\win64\onedir\M2507_OTA\M2507_OTA.exe" set "M2507_EXE=%~dp0dist\win64\onedir\M2507_OTA\M2507_OTA.exe"
if defined M2507_EXE goto check_exe
if exist "%~dp0dist\win64\onefile\M2507_OTA.exe" set "M2507_EXE=%~dp0dist\win64\onefile\M2507_OTA.exe"

:check_exe
if not defined M2507_EXE goto missing_exe
if not exist "%M2507_EXE%" goto missing_exe
set "M2507_LOG_DIR=%TEMP%\M2507OTA"
if not exist "%M2507_LOG_DIR%" mkdir "%M2507_LOG_DIR%"
set "M2507_CAPTURE=%M2507_LOG_DIR%\launch-console.log"
echo Starting: "%M2507_EXE%"
echo If the GUI opens, close it to finish this diagnostic run.
echo Capturing console output to: "%M2507_CAPTURE%"
"%M2507_EXE%" > "%M2507_CAPTURE%" 2>&1
set "M2507_EXIT=%ERRORLEVEL%"
echo.
type "%M2507_CAPTURE%"
echo.
echo Exit code: %M2507_EXIT%
echo Exit code: %M2507_EXIT%>> "%M2507_CAPTURE%"
echo.
echo Console log: "%M2507_CAPTURE%"
echo Python startup log: "%LOCALAPPDATA%\M2507OTA\startup.log"
echo Application log: "%LOCALAPPDATA%\M2507OTA\error.log"
echo If LOCALAPPDATA was not writable, also check "%TEMP%\M2507OTA".
echo Please copy the error text and exit code when reporting startup failures.
pause
exit /b %M2507_EXIT%

:missing_exe
echo M2507_OTA.exe was not found.
echo Put this BAT next to the EXE, or run: run_diagnostics.bat "C:\path\M2507_OTA.exe"
pause
exit /b 2
