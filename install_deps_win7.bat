@echo off
setlocal
cd /d "%~dp0"
echo Checking the activated Windows x64 Python 3.8.10 Conda environment...
python check_build_env.py --runtime-only
if errorlevel 1 goto failed

echo Verifying the bundled wheel files and pinned SHA256 hashes...
python verify_wheels.py
if errorlevel 1 goto failed

echo Installing from LOCAL FILES ONLY. No PyPI connection is needed.
python -m pip --isolated --disable-pip-version-check install ^
    --no-index --find-links="%~dp0wheelhouse_win7_x64" ^
    --only-binary=:all: --require-hashes --no-cache-dir ^
    -r "%~dp0requirements-offline-win7.txt"
if errorlevel 1 goto failed
python -m pip check
if errorlevel 1 goto failed
python check_build_env.py
if errorlevel 1 goto failed

echo.
echo Offline dependency installation succeeded.
echo Next: build_win7.bat debug
exit /b 0

:failed
echo.
echo Installation stopped. Fix the error above before building.
echo If wheels are missing, download and extract the latest complete repository ZIP.
exit /b 1
