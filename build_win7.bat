@echo off
setlocal
cd /d "%~dp0"
set "M2507_LAYOUT=--onedir"
set "M2507_UI=--windowed"
set "M2507_MODE=onedir"
if "%~1"=="" goto args_ok
if /I "%~1"=="debug" (
    set "M2507_UI=--console"
    set "M2507_MODE=debug"
    goto args_ok
)
if /I "%~1"=="onefile" (
    set "M2507_LAYOUT=--onefile"
    set "M2507_MODE=onefile"
    goto args_ok
)
echo Usage: build_win7.bat [debug^|onefile]
exit /b 2

:args_ok
python check_build_env.py
if errorlevel 1 goto failed
python -m pip check
if errorlevel 1 goto failed
python -m unittest discover -s tests -v
if errorlevel 1 goto failed
set "M2507_BITS="
for /f %%B in ('python -c "import struct; print(struct.calcsize('P') * 8)"') do set "M2507_BITS=%%B"
if not defined M2507_BITS goto failed

python -m PyInstaller --noconfirm --clean --noupx ^
    %M2507_LAYOUT% %M2507_UI% ^
    --name M2507_OTA ^
    --distpath "dist\win%M2507_BITS%\%M2507_MODE%" ^
    --workpath "build\win%M2507_BITS%\%M2507_MODE%\work" ^
    --specpath "build\win%M2507_BITS%\%M2507_MODE%" ^
    --hidden-import serial.tools.list_ports_windows ^
    M2507_dual_core_ota_scrollable.py
if errorlevel 1 goto failed
echo.
echo Build succeeded: dist\win%M2507_BITS%\%M2507_MODE%
echo For onedir/debug, copy the WHOLE M2507_OTA directory to the target computer.
echo The target needs no Conda or Python installation. Verify on Win7 SP1 before release.
exit /b 0

:failed
echo.
echo Build failed. Fix the error above; do not distribute stale dist output.
exit /b 1
