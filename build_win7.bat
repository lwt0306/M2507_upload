@echo off
setlocal
cd /d "%~dp0"
set "M2507_MODE=onedir"
if "%~1"=="" goto args_ok
if /I "%~1"=="debug" (
    set "M2507_MODE=debug"
    goto args_ok
)
if /I "%~1"=="onefile" (
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
python package_win7.py --mode "%M2507_MODE%"
if errorlevel 1 goto failed
echo.
echo Build and isolated GUI startup check succeeded: dist\win64\%M2507_MODE%
echo For onedir/debug, copy the WHOLE M2507_OTA directory to the target computer.
echo Use run_diagnostics.bat next to the EXE if the target computer cannot start it.
echo Test again on the actual Win7 SP1 target before release.
exit /b 0

:failed
echo.
echo Build failed. Fix the error above; do not distribute stale dist output.
exit /b 1
